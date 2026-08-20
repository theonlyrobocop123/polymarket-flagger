"""Entry-odds context: current price vs recent VWAPs and the 7d range.

Pure factual context to judge a fill against, never a recommendation or a
fair-value claim. Components that cannot be computed from the available data
render as "n/a" or are omitted; the line only disappears entirely when there
is no trade or price history at all.
Methodology: docs/superpowers/specs/2026-08-20-entry-odds-design.md
"""
import logging
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

DAY = 86_400
WEEK = 7 * DAY
TRADES_PAGE = 500
TRADES_MAX_PAGES = 8    # hard cap so a runaway market cannot stall the cycle

DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


@dataclass
class EntryAdvice:
    now_price: float
    vwap24: "float | None"
    vwap7d: "float | None"
    range7d: "tuple | None"


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


def compute_entry(trades, history, now_price, flagged_outcome, other_outcome, now_ts):
    """Pure computation. Returns EntryAdvice, or None when there is no data at all."""
    norm = normalize_trades(trades, flagged_outcome, other_outcome)
    vwap24 = _vwap(norm, now_ts - DAY)
    vwap7d = _vwap(norm, now_ts - WEEK)

    prices = [float(h["p"]) for h in (history or [])
              if int(h["t"]) >= now_ts - WEEK]
    range7d = (min(prices), max(prices)) if len(prices) >= 2 else None

    if vwap7d is None and range7d is None:
        return None
    return EntryAdvice(now_price, vwap24, vwap7d, range7d)


def _pct(p):
    return f"{round(p * 100, 1):g}%"


def format_entry(a):
    parts = [f"now {_pct(a.now_price)}"]
    v24 = _pct(a.vwap24) if a.vwap24 is not None else "n/a"
    v7d = _pct(a.vwap7d) if a.vwap7d is not None else "n/a"
    parts.append(f"VWAP {v24} (24h) / {v7d} (7d)")
    if a.range7d is not None:
        lo, hi = a.range7d
        parts.append(f"7d range {_pct(lo)[:-1]}-{_pct(hi)}")
    return " · ".join(parts)


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
