from datetime import datetime, timezone

from .models import (
    Market, QualifyingItem, parse_game_start,
    FLAG_MISPRICING, FLAG_UFC_LONGSHOT, FLAG_SPORTS_LONGSHOT,
)


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
    if market.prices[dog] >= cfg.flag1_underdog_max:
        return None
    return dog, ra, rb


def _fighter_str(outcome_name, rec):
    if rec is None:
        return f"{outcome_name} record unknown"
    return f"{rec.name} {rec.wins}-{rec.losses} ({round(rec.win_pct)}%)"


def _records_detail(market, store, gap=None):
    """W-L and win rate for both fighters, in outcome order. "" if neither is known."""
    ra = store.lookup(market.outcomes[0])
    rb = store.lookup(market.outcomes[1])
    if ra is None and rb is None:
        return ""
    detail = (f"{_fighter_str(market.outcomes[0], ra)} vs "
              f"{_fighter_str(market.outcomes[1], rb)}")
    if gap is not None:
        detail += f", {gap}-pt gap"
    return detail


def evaluate(markets, store, cfg, now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    items = []
    for market in markets:
        # Odds are only actionable before the event begins. A market with no
        # parseable start time is kept (fail open) rather than silently dropped.
        start = parse_game_start(market.game_start_time)
        if start is not None and now >= start:
            continue
        flags_by_index = {}

        for i, price in enumerate(market.prices):
            hits = []
            if price < cfg.flag3_sports_threshold and market.liquidity >= cfg.flag3_min_liquidity:
                hits.append(FLAG_SPORTS_LONGSHOT)
            if market.is_ufc and price < cfg.flag2_ufc_threshold:
                hits.append(FLAG_UFC_LONGSHOT)
            if hits:
                flags_by_index.setdefault(i, []).extend(hits)

        mis = _mispricing_index(market, store, cfg)
        if mis is not None:
            dog, ra, rb = mis
            flags_by_index.setdefault(dog, []).append(FLAG_MISPRICING)

        # Fighter records are shown on every UFC flag, not only mispricing.
        detail = ""
        if flags_by_index and market.is_ufc and len(market.outcomes) == 2:
            gap = round(abs(mis[1].win_pct - mis[2].win_pct)) if mis is not None else None
            detail = _records_detail(market, store, gap)

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
                record_detail=detail,
            ))
    return items
