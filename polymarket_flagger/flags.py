import logging

from .models import (
    Market, QualifyingItem,
    FLAG_MISPRICING, FLAG_UFC_LONGSHOT, FLAG_SPORTS_LONGSHOT,
)

log = logging.getLogger(__name__)


def _mispricing_index(market: Market, store, cfg):
    """Return the underdog outcome index if the mispricing flag applies, else None."""
    if not market.is_ufc or len(market.outcomes) != 2:
        return None
    ra = store.lookup(market.outcomes[0])
    rb = store.lookup(market.outcomes[1])
    if ra is None or rb is None:
        return None
    if ra.total_fights < cfg.flag1_min_fights or rb.total_fights < cfg.flag1_min_fights:
        return None
    if abs(ra.win_pct - rb.win_pct) > cfg.flag1_gap_pct:
        return None
    dog = 0 if market.prices[0] <= market.prices[1] else 1
    if market.prices[dog] >= 0.20:
        return None
    return dog, ra, rb


def _record_detail(market, dog, ra, rb):
    recs = [ra, rb]
    fav = recs[1 - dog]
    dogr = recs[dog]
    gap = round(abs(ra.win_pct - rb.win_pct))
    return (f"{fav.name} {fav.wins}-{fav.losses} ({round(fav.win_pct)}%) vs "
            f"{dogr.name} {dogr.wins}-{dogr.losses} ({round(dogr.win_pct)}%), {gap}-pt gap")


def evaluate(markets, store, cfg):
    items = []
    for market in markets:
        flags_by_index = {}

        for i, price in enumerate(market.prices):
            hits = []
            if price < cfg.flag3_sports_threshold and market.liquidity >= cfg.flag3_min_liquidity:
                hits.append(FLAG_SPORTS_LONGSHOT)
            if market.is_ufc and price < cfg.flag2_ufc_threshold:
                hits.append(FLAG_UFC_LONGSHOT)
            if hits:
                flags_by_index.setdefault(i, []).extend(hits)

        detail = ""
        mis = _mispricing_index(market, store, cfg)
        if mis is not None:
            dog, ra, rb = mis
            flags_by_index.setdefault(dog, []).append(FLAG_MISPRICING)
            detail_map = {dog: _record_detail(market, dog, ra, rb)}
        else:
            detail_map = {}

        for i, flags in flags_by_index.items():
            items.append(QualifyingItem(
                market_id=market.id,
                title=market.title,
                flagged_outcome=market.outcomes[i],
                price=market.prices[i],
                volume=market.volume,
                liquidity=market.liquidity,
                event_slug=market.event_slug,
                sport=market.sport,
                is_ufc=market.is_ufc,
                flags=flags,
                record_detail=detail_map.get(i, ""),
            ))
    return items
