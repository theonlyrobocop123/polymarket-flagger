import json
import logging

import requests

from .models import Market

log = logging.getLogger(__name__)


def _parse_json_field(raw, default):
    if isinstance(raw, list):
        return raw
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def parse_events(events, sport, ufc_tag_slugs):
    """Turn raw Gamma events into one Market each (highest-liquidity market)."""
    markets = []
    for ev in events:
        tag_slugs = {t.get("slug", "") for t in ev.get("tags", [])}
        is_ufc = bool(tag_slugs & set(ufc_tag_slugs))
        candidates = []
        for mk in ev.get("markets", []):
            if not mk.get("active", False) or mk.get("closed", False):
                continue
            outcomes = _parse_json_field(mk.get("outcomes"), [])
            prices_raw = _parse_json_field(mk.get("outcomePrices"), [])
            if len(outcomes) < 2 or len(outcomes) != len(prices_raw):
                continue
            try:
                prices = [float(p) for p in prices_raw]
            except (ValueError, TypeError):
                continue
            candidates.append((mk, outcomes, prices))
        if not candidates:
            continue
        # Primary market = highest liquidity (the moneyline/winner market)
        mk, outcomes, prices = max(
            candidates, key=lambda c: float(c[0].get("liquidityNum") or 0.0)
        )
        markets.append(Market(
            id=str(mk.get("id", "")),
            title=mk.get("question", ""),
            outcomes=outcomes,
            prices=prices,
            volume=float(mk.get("volumeNum") or 0.0),
            liquidity=float(mk.get("liquidityNum") or 0.0),
            event_slug=ev.get("slug", ""),
            end_date=mk.get("endDate", ""),
            is_ufc=is_ufc,
            sport=sport,
        ))
    return markets


def fetch_markets(cfg):
    """Fetch active markets for every configured sport tag. Deduped by market id."""
    session = requests.Session()
    by_id = {}
    for slug in cfg.sport_tag_slugs:
        try:
            resp = session.get(
                f"{cfg.gamma_base}/events",
                params={
                    "tag_slug": slug,
                    "active": "true",
                    "closed": "false",
                    "limit": cfg.events_per_tag,
                },
                timeout=30,
            )
            resp.raise_for_status()
            events = resp.json()
        except requests.RequestException as exc:
            log.warning("Gamma fetch failed for tag %s: %s", slug, exc)
            continue
        for m in parse_events(events, sport=slug, ufc_tag_slugs=cfg.ufc_tag_slugs):
            # First tag wins; but prefer a UFC-tagged view if any tag marks it UFC
            if m.id not in by_id or (m.is_ufc and not by_id[m.id].is_ufc):
                by_id[m.id] = m
    return list(by_id.values())
