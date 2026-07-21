from pathlib import Path

from polymarket_flagger.fighter_store import parse_roster_html, FighterStore

FIXTURE = Path(__file__).parent / "fixtures" / "ufcstats_page.html"


def _store():
    records = parse_roster_html(FIXTURE.read_text())
    return FighterStore(records, threshold=85)


def test_parse_roster():
    records = parse_roster_html(FIXTURE.read_text())
    jones = next(r for r in records if r.name == "Jon Jones")
    assert (jones.wins, jones.losses, jones.draws) == (27, 1, 0)
    assert jones.nickname == "Bones"
    assert round(jones.win_pct) == 96


def test_lookup_exact():
    assert _store().lookup("Jon Jones").wins == 27


def test_lookup_accent_and_suffix():
    # accents stripped, extra tokens tolerated by token_sort_ratio
    assert _store().lookup("Jon Jones Jr").name == "Jon Jones"


def test_lookup_below_threshold_returns_none():
    assert _store().lookup("Completely Different Person") is None
