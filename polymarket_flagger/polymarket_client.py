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


# Generic prop-market outcome patterns. A market whose outcome set is a subset of
# any of these is a proposition bet (not a match outcome) and is excluded. Verified
# against live Gamma UFC events: real fighter moneylines carry the two fighter names,
# while props are Yes/No (fight-next, become-champion, method-of-victory) or
# Over/Under (round totals).
_PROP_OUTCOME_SETS = ({"yes", "no"}, {"over", "under"})


def _is_prop_market(outcomes) -> bool:
    norm = {str(o).lower().strip() for o in outcomes}
    return any(norm <= prop_set for prop_set in _PROP_OUTCOME_SETS)


def parse_events(events, sport, ufc_tag_slugs):
    """Emit a Market for EVERY match-outcome market on each event.

    A "match-outcome" market is one whose outcomes are the participants/draw, e.g.
    ["Mike Davis", "Nurullo Aliev"]. Generic Yes/No and Over/Under proposition
    markets are excluded so we never alert on props (e.g. "Who will X fight next?").
    """
    markets = []
    for ev in events:
        tag_slugs = {t.get("slug", "") for t in ev.get("tags", [])}
        is_ufc = bool(tag_slugs & set(ufc_tag_slugs))
        for mk in ev.get("markets", []):
            # The /events query already filters active=true&closed=false, so a
            # missing per-market `active` is treated as truthy; only an explicit
            # active:false or closed:true excludes a market.
            if not mk.get("active", True) or mk.get("closed", False):
                continue
            outcomes = _parse_json_field(mk.get("outcomes"), [])
            prices_raw = _parse_json_field(mk.get("outcomePrices"), [])
            if len(outcomes) < 2 or len(outcomes) != len(prices_raw):
                continue
            try:
                prices = [float(p) for p in prices_raw]
            except (ValueError, TypeError):
                continue
            if _is_prop_market(outcomes):
                continue
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
            # First tag wins. is_ufc is derived from the event's own tags, so the
            # same market id yields the same is_ufc under any tag_slug it surfaces
            # for; a later duplicate can never carry more info than the first.
            by_id.setdefault(m.id, m)
    return list(by_id.values())
