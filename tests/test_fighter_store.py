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


def test_cache_round_trip(tmp_path):
    store = _store()
    cache_path = tmp_path / "fighters.json"
    store.to_cache(str(cache_path))

    loaded = FighterStore.from_cache(str(cache_path))

    assert loaded is not None
    jones = loaded.lookup("Jon Jones")
    assert jones is not None
    assert (jones.wins, jones.losses, jones.draws) == (27, 1, 0)
    assert jones.nickname == "Bones"


def test_from_cache_missing_file_returns_none(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"
    assert FighterStore.from_cache(str(missing_path)) is None


def test_from_cache_corrupt_schema_returns_none(tmp_path):
    cache_path = tmp_path / "corrupt.json"
    cache_path.write_text('{"not": "a list"}', encoding="utf-8")

    assert FighterStore.from_cache(str(cache_path)) is None
