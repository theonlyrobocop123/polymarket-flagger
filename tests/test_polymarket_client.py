import json
from pathlib import Path

from polymarket_flagger.polymarket_client import parse_events

FIXTURE = Path(__file__).parent / "fixtures" / "gamma_events.json"


def test_parse_picks_highest_liquidity_market():
    events = json.loads(FIXTURE.read_text())
    markets = parse_events(events, sport="ufc", ufc_tag_slugs=("ufc", "mma"))
    assert len(markets) == 1
    m = markets[0]
    # The moneyline market (higher liquidity), not the prop market
    assert m.outcomes == ["Mike Davis", "Nurullo Aliev"]
    assert m.prices == [0.92, 0.08]
    assert m.is_ufc is True
    assert m.event_slug == "ufc-dav-ali-2026-07-25"
    assert m.liquidity == 18000.0


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
