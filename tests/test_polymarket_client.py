import json
from pathlib import Path

from polymarket_flagger.polymarket_client import parse_events

FIXTURE = Path(__file__).parent / "fixtures" / "gamma_events.json"


def test_parse_returns_all_match_outcome_markets_and_drops_props():
    events = json.loads(FIXTURE.read_text())
    markets = parse_events(events, sport="ufc", ufc_tag_slugs=("ufc", "mma"))
    # Event 1 yields the 2-fighter moneyline + the 3-way method market; the Yes/No
    # and Over/Under props are dropped. Event 2 is all Yes/No props -> nothing.
    by_id = {m.id: m for m in markets}
    assert set(by_id) == {"2885100", "2885103"}

    moneyline = by_id["2885100"]
    assert moneyline.outcomes == ["Mike Davis", "Nurullo Aliev"]
    assert moneyline.prices == [0.92, 0.08]
    assert moneyline.is_ufc is True
    assert moneyline.event_slug == "ufc-dav-ali-2026-07-25"
    assert moneyline.liquidity == 18000.0

    three_way = by_id["2885103"]
    assert three_way.outcomes == ["KO/TKO", "Decision", "Submission"]


def test_parse_pure_prop_event_returns_empty():
    events = [
        {
            "slug": "who-will-x-fight-next",
            "tags": [{"slug": "ufc"}],
            "markets": [
                {"id": "1", "question": "Will X fight A next?",
                 "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.3\", \"0.7\"]",
                 "volumeNum": 1.0, "liquidityNum": 1.0, "active": True, "closed": False},
                {"id": "2", "question": "Will X fight B next?",
                 "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.2\", \"0.8\"]",
                 "volumeNum": 1.0, "liquidityNum": 1.0, "active": True, "closed": False},
            ],
        }
    ]
    assert parse_events(events, sport="ufc", ufc_tag_slugs=("ufc",)) == []


def test_parse_excludes_over_under_props():
    events = [
        {"slug": "e", "tags": [{"slug": "ufc"}], "markets": [
            {"id": "ou", "question": "O/U 2.5 Rounds",
             "outcomes": "[\"Over\", \"Under\"]", "outcomePrices": "[\"0.6\", \"0.4\"]",
             "volumeNum": 1.0, "liquidityNum": 1.0, "active": True, "closed": False},
        ]},
    ]
    assert parse_events(events, sport="ufc", ufc_tag_slugs=("ufc",)) == []


def test_parse_captures_game_start_time():
    events = [
        {"slug": "e", "tags": [{"slug": "ufc"}], "markets": [
            {"id": "m", "question": "A vs. B",
             "outcomes": "[\"A\", \"B\"]", "outcomePrices": "[\"0.5\", \"0.5\"]",
             "volumeNum": 1.0, "liquidityNum": 1.0, "active": True, "closed": False,
             "gameStartTime": "2026-08-22 21:00:00+00"},
        ]},
    ]
    markets = parse_events(events, sport="ufc", ufc_tag_slugs=("ufc",))
    assert markets[0].game_start_time == "2026-08-22 21:00:00+00"


def test_parse_missing_game_start_time_is_empty_string():
    events = [
        {"slug": "e", "tags": [{"slug": "ufc"}], "markets": [
            {"id": "m", "question": "A vs. B",
             "outcomes": "[\"A\", \"B\"]", "outcomePrices": "[\"0.5\", \"0.5\"]",
             "volumeNum": 1.0, "liquidityNum": 1.0, "active": True, "closed": False},
        ]},
    ]
    markets = parse_events(events, sport="ufc", ufc_tag_slugs=("ufc",))
    assert markets[0].game_start_time == ""


def test_parse_missing_active_treated_as_truthy():
    # /events already filters active=true; a market lacking the field must be kept.
    events = [
        {"slug": "e", "tags": [{"slug": "ufc"}], "markets": [
            {"id": "m", "question": "A vs. B",
             "outcomes": "[\"A\", \"B\"]", "outcomePrices": "[\"0.5\", \"0.5\"]",
             "volumeNum": 1.0, "liquidityNum": 1.0, "closed": False},
        ]},
    ]
    markets = parse_events(events, sport="ufc", ufc_tag_slugs=("ufc",))
    assert len(markets) == 1 and markets[0].id == "m"


def test_parse_skips_closed_and_empty():
    events = [
        {"slug": "x", "tags": [], "markets": []},
        {"slug": "y", "tags": [], "markets": [
            {"id": "1", "question": "q", "outcomes": "[\"A\",\"B\"]",
             "outcomePrices": "[\"0.5\",\"0.5\"]", "volumeNum": 1.0,
             "liquidityNum": 1.0, "endDate": "", "active": False, "closed": True}
        ]},
    ]
    assert parse_events(events, sport="nba", ufc_tag_slugs=("ufc",)) == []
