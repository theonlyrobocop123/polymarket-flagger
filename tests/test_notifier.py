from polymarket_flagger.models import (
    QualifyingItem, FLAG_MISPRICING, FLAG_UFC_LONGSHOT, FLAG_SPORTS_LONGSHOT,
)
from polymarket_flagger.telegram_notifier import format_message


def _item(**kw):
    base = dict(market_id="m", title="A vs. B", flagged_outcome="B", price=0.08,
                volume=18000.0, liquidity=18000.0, event_slug="a-vs-b",
                sport="ufc", is_ufc=True, flags=[FLAG_UFC_LONGSHOT], record_detail="")
    base.update(kw)
    return QualifyingItem(**base)


def test_format_has_new_and_still_sections():
    new = [_item(flags=[FLAG_UFC_LONGSHOT, FLAG_SPORTS_LONGSHOT])]
    still = [(_item(market_id="m2", flagged_outcome="Draw", price=0.06, sport="soccer",
                    is_ufc=False, flags=[FLAG_SPORTS_LONGSHOT]), 0.08)]
    msg = format_message("2026-07-21 14:15 UTC", new, still)
    assert "NEW (1)" in msg
    assert "STILL QUALIFYING (1)" in msg
    assert "8%" in msg            # new item price
    assert "was 8%" in msg        # still item shows previous price
    assert "6%" in msg            # still item current price
    assert "polymarket.com/event/a-vs-b" in msg


def test_mispricing_shows_record_detail():
    item = _item(flags=[FLAG_MISPRICING], record_detail="A 27-1 (96%) vs B 20-4 (83%), 13-pt gap")
    msg = format_message("t", [item], [])
    assert "13-pt gap" in msg
    assert "UFC mispricing" in msg


def test_empty_still_section_omitted():
    msg = format_message("t", [_item()], [])
    assert "STILL QUALIFYING" not in msg
