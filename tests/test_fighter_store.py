from pathlib import Path

from polymarket_flagger.models import FighterRecord
from polymarket_flagger.fighter_store import parse_roster_html, FighterStore

FIXTURE = Path(__file__).parent / "fixtures" / "ufcstats_page.html"


def _store():
    records = parse_roster_html(FIXTURE.read_text(encoding="utf-8"))
    return FighterStore(records, threshold=85)


def test_parse_roster_reads_real_columns():
    # Real ufcstats page: W/L/D live in trailing columns (indices 7,8,9), not 3,4,5.
    records = parse_roster_html(FIXTURE.read_text(encoding="utf-8"))
    assert records  # non-empty
    abbasov = next(r for r in records if r.name == "Nariman Abbasov")
    assert (abbasov.wins, abbasov.losses, abbasov.draws) == (28, 4, 0)
    assert abbasov.nickname == "Bayraktar"
    assert round(abbasov.win_pct) == 88


def test_parse_roster_handles_draws_and_missing_stats():
    records = parse_roster_html(FIXTURE.read_text(encoding="utf-8"))
    abe = next(r for r in records if r.name == "Hiroyuki Abe")
    assert (abe.wins, abe.losses, abe.draws) == (8, 15, 3)
    # Tom Aaron has no height/reach ("--") yet parses cleanly.
    aaron = next(r for r in records if r.name == "Tom Aaron")
    assert (aaron.wins, aaron.losses, aaron.draws) == (5, 3, 0)


def test_lookup_exact():
    assert _store().lookup("Nariman Abbasov").wins == 28


def test_lookup_accent_and_suffix():
    # accents stripped, extra tokens tolerated by token_sort_ratio
    assert _store().lookup("Nariman Abbasov Jr").name == "Nariman Abbasov"


def test_lookup_below_threshold_returns_none():
    assert _store().lookup("Completely Different Person") is None


def test_ambiguous_name_returns_none():
    # Two different fighters named "Bruno Silva" -> the name must NOT resolve.
    records = [
        FighterRecord("Bruno Silva", "", 23, 10, 0),
        FighterRecord("Bruno Silva", "", 12, 8, 0),
        FighterRecord("Nariman Abbasov", "", 28, 4, 0),
    ]
    store = FighterStore(records, threshold=85)
    assert store.lookup("Bruno Silva") is None
    # An unambiguous name in the same store still resolves.
    assert store.lookup("Nariman Abbasov").wins == 28


def test_ambiguous_nickname_returns_none():
    # Shared nickname "Tank" across two different fighters must not resolve.
    records = [
        FighterRecord("David Abbott", "Tank", 10, 15, 0),
        FighterRecord("Tahir Abdullayev", "Tank", 20, 3, 0),
    ]
    store = FighterStore(records, threshold=85)
    assert store.lookup("Tank") is None


def test_identical_duplicate_is_not_ambiguous():
    # A genuinely identical duplicate record is not a collision; the name resolves.
    rec = FighterRecord("Jon Jones", "Bones", 27, 1, 0)
    store = FighterStore([rec, FighterRecord("Jon Jones", "Bones", 27, 1, 0)], threshold=85)
    assert store.lookup("Jon Jones").wins == 27


def test_cache_round_trip(tmp_path):
    store = _store()
    cache_path = tmp_path / "fighters.json"
    store.to_cache(str(cache_path))

    loaded = FighterStore.from_cache(str(cache_path))

    assert loaded is not None
    abbasov = loaded.lookup("Nariman Abbasov")
    assert abbasov is not None
    assert (abbasov.wins, abbasov.losses, abbasov.draws) == (28, 4, 0)
    assert abbasov.nickname == "Bayraktar"


def test_from_cache_missing_file_returns_none(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"
    assert FighterStore.from_cache(str(missing_path)) is None


def test_from_cache_corrupt_schema_returns_none(tmp_path):
    cache_path = tmp_path / "corrupt.json"
    cache_path.write_text('{"not": "a list"}', encoding="utf-8")

    assert FighterStore.from_cache(str(cache_path)) is None
