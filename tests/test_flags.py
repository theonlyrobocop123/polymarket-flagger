from datetime import datetime, timezone

from polymarket_flagger.config import Config
from polymarket_flagger.models import (
    Market, FighterRecord, parse_game_start,
    FLAG_MISPRICING, FLAG_UFC_LONGSHOT, FLAG_SPORTS_LONGSHOT,
)
from polymarket_flagger.flags import evaluate


class FakeStore:
    def __init__(self, mapping):
        self.mapping = mapping

    def lookup(self, name):
        return self.mapping.get(name)


def _ufc_market(prices, liq=20000.0, outcomes=("A", "B")):
    return Market(id="m1", title="A vs. B", outcomes=list(outcomes), prices=list(prices),
                  volume=1000.0, liquidity=liq, event_slug="a-vs-b", end_date="",
                  is_ufc=True, sport="ufc")


def test_flag3_sports_longshot_respects_liquidity_floor():
    cfg = Config()
    m = Market(id="s1", title="X vs Y - Draw", outcomes=["X", "Draw", "Y"],
               prices=[0.5, 0.06, 0.44], volume=1.0, liquidity=6000.0,
               event_slug="x-y", end_date="", is_ufc=False, sport="soccer")
    items = evaluate([m], FakeStore({}), cfg)
    assert len(items) == 1 and items[0].flagged_outcome == "Draw"
    assert FLAG_SPORTS_LONGSHOT in items[0].flags

    m.liquidity = 100.0  # below floor
    assert evaluate([m], FakeStore({}), cfg) == []


def test_flag2_ufc_longshot():
    cfg = Config()
    items = evaluate([_ufc_market([0.92, 0.08])], FakeStore({}), cfg)
    assert FLAG_UFC_LONGSHOT in items[0].flags
    assert items[0].flagged_outcome == "B"


def test_flag2_boundary_not_below_threshold():
    cfg = Config()
    # exactly 0.15 is NOT below 0.15
    items = evaluate([_ufc_market([0.85, 0.15])], FakeStore({}), cfg)
    assert items == []


def test_flag2_fires_between_10_and_15_pct():
    cfg = Config()
    items = evaluate([_ufc_market([0.88, 0.12])], FakeStore({}), cfg)
    assert len(items) == 1
    assert items[0].flags == [FLAG_UFC_LONGSHOT]  # above the 10% sports-longshot cutoff


def test_flag1_mispricing_similar_records():
    cfg = Config()
    store = FakeStore({
        "A": FighterRecord("A", "", 20, 4, 0),   # 83.3%
        "B": FighterRecord("B", "", 18, 5, 0),   # 78.3%  -> 5pt gap
    })
    items = evaluate([_ufc_market([0.82, 0.18])], store, cfg)
    assert FLAG_MISPRICING in items[0].flags
    assert items[0].flagged_outcome == "B"
    assert "gap" in items[0].record_detail


def test_flag1_skipped_when_records_differ():
    cfg = Config()
    store = FakeStore({
        "A": FighterRecord("A", "", 25, 1, 0),   # 96%
        "B": FighterRecord("B", "", 5, 10, 0),   # 33%  -> big gap
    })
    items = evaluate([_ufc_market([0.82, 0.18])], store, cfg)
    assert items == []  # not a longshot (<15%) and not mispricing


def test_flag1_skipped_when_fighter_unmatched():
    cfg = Config()
    store = FakeStore({"A": FighterRecord("A", "", 20, 4, 0)})  # B missing
    items = evaluate([_ufc_market([0.82, 0.18])], store, cfg)
    assert items == []


def test_flag1_cheap_side_boundary_not_below_020():
    cfg = Config()
    # 3-1 vs 3-1: identical 75% records, 0 pt gap, both 4 fights
    store = FakeStore({
        "A": FighterRecord("A", "", 3, 1, 0),
        "B": FighterRecord("B", "", 3, 1, 0),
    })
    # cheap side exactly 0.20 -> not < 0.20, so mispricing must not fire
    items = evaluate([_ufc_market([0.80, 0.20])], store, cfg)
    assert items == []


def test_flag1_underdog_max_is_configurable():
    # M1: the underdog cap comes from Config, not a literal 0.20.
    cfg = Config(flag1_underdog_max=0.10)
    store = FakeStore({
        "A": FighterRecord("A", "", 3, 1, 0),
        "B": FighterRecord("B", "", 3, 1, 0),
    })
    # cheap side 0.18 is below the default 0.20 but not below the tightened 0.10.
    assert evaluate([_ufc_market([0.82, 0.18])], store, cfg) == []
    # With the default cap it fires.
    assert FLAG_MISPRICING in evaluate([_ufc_market([0.82, 0.18])], store, Config())[0].flags


def test_flag1_min_fights_boundary_fires_at_exactly_4():
    cfg = Config()
    store = FakeStore({
        "A": FighterRecord("A", "", 3, 1, 0),   # 4 fights, 75%
        "B": FighterRecord("B", "", 3, 1, 0),   # 4 fights, 75%
    })
    items = evaluate([_ufc_market([0.81, 0.19])], store, cfg)
    assert FLAG_MISPRICING in items[0].flags
    assert items[0].flagged_outcome == "B"


def test_flag1_min_fights_boundary_below_4_does_not_fire():
    cfg = Config()
    store = FakeStore({
        "A": FighterRecord("A", "", 2, 1, 0),   # 3 fights -> below min
        "B": FighterRecord("B", "", 3, 1, 0),   # 4 fights, 75%
    })
    items = evaluate([_ufc_market([0.81, 0.19])], store, cfg)
    assert items == []


def test_flag1_gap_boundary_fires_at_exactly_15():
    cfg = Config()
    store = FakeStore({
        "A": FighterRecord("A", "", 3, 1, 0),   # 4 fights, 75%
        "B": FighterRecord("B", "", 3, 2, 0),   # 5 fights, 60%  -> 15pt gap
    })
    items = evaluate([_ufc_market([0.81, 0.19])], store, cfg)
    assert FLAG_MISPRICING in items[0].flags


def test_flag1_gap_boundary_16pts_does_not_fire():
    cfg = Config()
    store = FakeStore({
        "A": FighterRecord("A", "", 4, 1, 0),    # 5 fights, 80%
        "B": FighterRecord("B", "", 16, 9, 0),   # 25 fights, 64% -> 16pt gap
    })
    items = evaluate([_ufc_market([0.81, 0.19])], store, cfg)
    assert items == []


def test_flag3_liquidity_boundary_fires_at_exactly_5000():
    cfg = Config()
    m = Market(id="s1", title="X vs Y - Draw", outcomes=["X", "Draw", "Y"],
               prices=[0.5, 0.06, 0.44], volume=1.0, liquidity=5000.0,
               event_slug="x-y", end_date="", is_ufc=False, sport="soccer")
    items = evaluate([m], FakeStore({}), cfg)
    assert len(items) == 1 and items[0].flagged_outcome == "Draw"
    assert FLAG_SPORTS_LONGSHOT in items[0].flags


def test_flag3_liquidity_boundary_4999_does_not_fire():
    cfg = Config()
    m = Market(id="s1", title="X vs Y - Draw", outcomes=["X", "Draw", "Y"],
               prices=[0.5, 0.06, 0.44], volume=1.0, liquidity=4999.0,
               event_slug="x-y", end_date="", is_ufc=False, sport="soccer")
    items = evaluate([m], FakeStore({}), cfg)
    assert items == []


def test_flag3_price_boundary_not_below_010():
    cfg = Config()
    m = Market(id="s1", title="X vs Y - Draw", outcomes=["X", "Draw", "Y"],
               prices=[0.5, 0.10, 0.40], volume=1.0, liquidity=20000.0,
               event_slug="x-y", end_date="", is_ufc=False, sport="soccer")
    items = evaluate([m], FakeStore({}), cfg)
    assert items == []


def test_flag3_three_way_market_two_cheap_outcomes_yields_two_items():
    cfg = Config()
    m = Market(id="s2", title="X vs Y vs Z", outcomes=["X", "Draw", "Y"],
               prices=[0.05, 0.06, 0.89], volume=1.0, liquidity=20000.0,
               event_slug="x-y-z", end_date="", is_ufc=False, sport="soccer")
    items = evaluate([m], FakeStore({}), cfg)
    assert len(items) == 2
    outcomes = {it.flagged_outcome for it in items}
    assert outcomes == {"X", "Draw"}
    for it in items:
        assert FLAG_SPORTS_LONGSHOT in it.flags


def test_started_event_is_not_flagged():
    # Once the event has begun we no longer care about its odds.
    cfg = Config()
    m = _ufc_market([0.92, 0.08])
    m.game_start_time = "2026-08-22 21:00:00+00"
    now = datetime(2026, 8, 22, 21, 30, tzinfo=timezone.utc)  # 30 min after start
    assert evaluate([m], FakeStore({}), cfg, now=now) == []


def test_event_flagged_right_up_to_start():
    cfg = Config()
    m = _ufc_market([0.92, 0.08])
    m.game_start_time = "2026-08-22 21:00:00+00"
    now = datetime(2026, 8, 22, 20, 59, tzinfo=timezone.utc)  # 1 min before start
    items = evaluate([m], FakeStore({}), cfg, now=now)
    assert len(items) == 1 and FLAG_UFC_LONGSHOT in items[0].flags


def test_event_at_exact_start_time_is_not_flagged():
    cfg = Config()
    m = _ufc_market([0.92, 0.08])
    m.game_start_time = "2026-08-22 21:00:00+00"
    now = datetime(2026, 8, 22, 21, 0, tzinfo=timezone.utc)
    assert evaluate([m], FakeStore({}), cfg, now=now) == []


def test_missing_or_bad_start_time_fails_open():
    # No start time (or unparseable) -> keep flagging as before.
    cfg = Config()
    now = datetime(2026, 8, 22, 21, 30, tzinfo=timezone.utc)
    m1 = _ufc_market([0.92, 0.08])                      # game_start_time defaults ""
    m2 = _ufc_market([0.92, 0.08])
    m2.game_start_time = "not-a-date"
    items = evaluate([m1, m2], FakeStore({}), cfg, now=now)
    assert len(items) == 2


def test_longshot_item_shows_both_fighter_records():
    # Records are shown on EVERY UFC flag, not just mispricing.
    cfg = Config()
    store = FakeStore({
        "A": FighterRecord("A", "", 25, 1, 0),   # 96% - big gap, so no mispricing
        "B": FighterRecord("B", "", 5, 10, 0),   # 33%
    })
    items = evaluate([_ufc_market([0.92, 0.08])], store, cfg)
    assert items[0].flags == [FLAG_SPORTS_LONGSHOT, FLAG_UFC_LONGSHOT]
    assert "A 25-1 (96%)" in items[0].record_detail
    assert "B 5-10 (33%)" in items[0].record_detail


def test_longshot_item_with_one_unknown_fighter_shows_partial_records():
    cfg = Config()
    store = FakeStore({"A": FighterRecord("A", "", 25, 1, 0)})  # B unknown
    items = evaluate([_ufc_market([0.92, 0.08])], store, cfg)
    assert "A 25-1 (96%)" in items[0].record_detail
    assert "B record unknown" in items[0].record_detail


def test_longshot_item_with_no_known_fighters_has_empty_detail():
    cfg = Config()
    items = evaluate([_ufc_market([0.92, 0.08])], FakeStore({}), cfg)
    assert items[0].record_detail == ""


def test_non_ufc_item_has_no_record_detail():
    cfg = Config()
    m = Market(id="s1", title="X vs Y - Draw", outcomes=["X", "Draw", "Y"],
               prices=[0.5, 0.06, 0.44], volume=1.0, liquidity=6000.0,
               event_slug="x-y", end_date="", is_ufc=False, sport="soccer")
    items = evaluate([m], FakeStore({}), cfg)
    assert items[0].record_detail == ""


def test_parse_game_start_gamma_formats():
    # Gamma sends "2026-08-22 21:00:00+00"; be liberal about ISO variants.
    dt = parse_game_start("2026-08-22 21:00:00+00")
    assert dt == datetime(2026, 8, 22, 21, 0, tzinfo=timezone.utc)
    dt = parse_game_start("2026-08-22T21:00:00Z")
    assert dt == datetime(2026, 8, 22, 21, 0, tzinfo=timezone.utc)
    assert parse_game_start("") is None
    assert parse_game_start(None) is None
    assert parse_game_start("garbage") is None
    # Naive timestamps are assumed UTC.
    dt = parse_game_start("2026-08-22 21:00:00")
    assert dt == datetime(2026, 8, 22, 21, 0, tzinfo=timezone.utc)


def test_dedupe_multiple_flags_one_item():
    cfg = Config()
    store = FakeStore({
        "A": FighterRecord("A", "", 20, 4, 0),
        "B": FighterRecord("B", "", 19, 5, 0),
    })
    # price 0.08 hits Flag1 (<20 + similar), Flag2 (<15), Flag3 (<10)
    items = evaluate([_ufc_market([0.92, 0.08])], store, cfg)
    assert len(items) == 1
    assert set(items[0].flags) == {FLAG_MISPRICING, FLAG_UFC_LONGSHOT, FLAG_SPORTS_LONGSHOT}
