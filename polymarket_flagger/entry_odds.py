"""Entry-odds advice: VWAP, trend, and a suggested entry for flagged outcomes.

This is an execution aid ("is now a good fill given recent trading"), never a
fair-value claim. Full methodology: docs/superpowers/specs/2026-08-20-entry-odds-design.md
"""
import logging
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

DAY = 86_400
WEEK = 7 * DAY
MIN_TRADES_24H = 5      # below this the VWAP is noise; skip the advice line
MIN_HISTORY_POINTS = 22  # EMA-21 needs a run-up; below this trend is meaningless
TREND_MOVE_PT = 0.01    # 24h net move needed (in price units) to call a trend
TRADES_PAGE = 500
TRADES_MAX_PAGES = 8    # hard cap so a runaway market cannot stall the cycle

DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


@dataclass
class EntryAdvice:
    now_price: float
    vwap24: float
    vwap7d: float
    low24: float
    range7d: tuple
    trend: str               # "rising" | "flat" | "falling"
    action: str              # "enter now" | "limit"
    limit_price: "float | None"


def normalize_trades(trades, flagged_outcome, other_outcome):
    """Reduce raw trades to (ts, price, size) in flagged-outcome terms.

    Both tokens of a binary market are the same economic instrument, so a trade
    on the other outcome at price p is a flagged-outcome trade at 1 - p.
    """
    norm = []
    for t in trades:
        try:
            ts, price, size = int(t["timestamp"]), float(t["price"]), float(t["size"])
        except (KeyError, TypeError, ValueError):
            continue
        outcome = t.get("outcome")
        if outcome == flagged_outcome:
            norm.append((ts, price, size))
        elif other_outcome and outcome == other_outcome:
            norm.append((ts, round(1.0 - price, 6), size))
    return norm


def _vwap(trades, since_ts):
    num = den = 0.0
    for ts, price, size in trades:
        if ts >= since_ts:
            num += price * size
            den += size
    return (num / den) if den else None


def _ema(values, span):
    alpha = 2.0 / (span + 1)
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


def compute_entry(trades, history, now_price, flagged_outcome, other_outcome, now_ts):
    """Pure computation. Returns EntryAdvice, or None when data is too thin."""
    norm = normalize_trades(trades, flagged_outcome, other_outcome)
    if len([t for t in norm if t[0] >= now_ts - DAY]) < MIN_TRADES_24H:
        return None

    points = sorted((int(h["t"]), float(h["p"])) for h in (history or []))
    points = [p for p in points if p[0] >= now_ts - WEEK]
    prices = [p for _, p in points]
    last24 = [p for ts, p in points if ts >= now_ts - DAY]
    if len(prices) < MIN_HISTORY_POINTS or len(last24) < 2:
        return None

    vwap24 = _vwap(norm, now_ts - DAY)
    vwap7d = _vwap(norm, now_ts - WEEK)
    change24 = prices[-1] - last24[0]
    low24 = min(last24)
    ema8, ema21 = _ema(prices, 8), _ema(prices, 21)

    if ema8 > ema21 and change24 >= TREND_MOVE_PT:
        trend = "rising"
    elif ema8 < ema21 and change24 <= -TREND_MOVE_PT:
        trend = "falling"
    else:
        trend = "flat"

    if trend == "rising":
        action, limit_price = "enter now", None
    elif trend == "flat":
        if now_price <= vwap24:
            action, limit_price = "enter now", None
        else:
            action, limit_price = "limit", vwap24
    else:  # falling: only get filled into continued weakness
        action, limit_price = "limit", low24

    return EntryAdvice(now_price, vwap24, vwap7d, low24,
                       (min(prices), max(prices)), trend, action, limit_price)


def _pct(p):
    return f"{round(p * 100, 1):g}%"


def format_entry(a):
    lo, hi = a.range7d
    arrow = {"rising": "↑", "flat": "↔", "falling": "↓"}[a.trend]
    tail = "enter now" if a.action == "enter now" else f"limit @ {_pct(a.limit_price)}"
    return (f"now {_pct(a.now_price)} · VWAP {_pct(a.vwap24)} (24h) / {_pct(a.vwap7d)} (7d) · "
            f"7d range {_pct(lo)[:-1]}-{_pct(hi)} · trend {arrow} → {tail}")


def fetch_trades(condition_id, since_ts):
    session = requests.Session()
    out = []
    for page in range(TRADES_MAX_PAGES):
        resp = session.get(f"{DATA_API}/trades",
                           params={"market": condition_id, "limit": TRADES_PAGE,
                                   "offset": page * TRADES_PAGE},
                           timeout=15)
        resp.raise_for_status()
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        # Trades come newest-first; stop once a page reaches past the window.
        if len(batch) < TRADES_PAGE or int(batch[-1].get("timestamp", 0)) < since_ts:
            break
    return out


def fetch_price_history(token_id):
    resp = requests.get(f"{CLOB_API}/prices-history",
                        params={"market": token_id, "interval": "1w", "fidelity": 60},
                        timeout=15)
    resp.raise_for_status()
    return resp.json().get("history", [])


def advise(cfg, item, now_ts=None):
    """Best-effort entry line for one qualifying item. "" on any failure."""
    if not item.condition_id or not item.clob_token_id:
        return ""
    if now_ts is None:
        now_ts = int(time.time())
    try:
        trades = fetch_trades(item.condition_id, now_ts - WEEK)
        history = fetch_price_history(item.clob_token_id)
        adv = compute_entry(trades, history, item.price, item.flagged_outcome,
                            item.other_outcome, now_ts)
    except (requests.RequestException, ValueError, KeyError) as exc:
        log.warning("Entry advice failed for %s: %s", item.key, exc)
        return ""
    return format_entry(adv) if adv else ""
