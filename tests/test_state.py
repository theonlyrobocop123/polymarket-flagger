import json

from polymarket_flagger.models import QualifyingItem, FLAG_SPORTS_LONGSHOT
from polymarket_flagger.state import load_state, save_state, diff


def _item(mid, outcome, price):
    return QualifyingItem(market_id=mid, title="t", flagged_outcome=outcome,
                          price=price, volume=1.0, liquidity=1.0, event_slug="s",
                          sport="soccer", is_ufc=False, flags=[FLAG_SPORTS_LONGSHOT])


def test_diff_classifies_new_and_still():
    prev = {"m1|A": {"price": 0.09, "flags": [FLAG_SPORTS_LONGSHOT]}}
    items = [_item("m1", "A", 0.06), _item("m2", "B", 0.04)]
    new, still = diff(items, prev)
    assert [i.market_id for i in new] == ["m2"]
    assert len(still) == 1
    still_item, prev_price = still[0]
    assert still_item.market_id == "m1" and prev_price == 0.09


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    save_state(str(path), [_item("m1", "A", 0.06)])
    loaded = load_state(str(path))
    assert loaded["m1|A"]["price"] == 0.06


def test_load_missing_returns_empty(tmp_path):
    assert load_state(str(tmp_path / "nope.json")) == {}
