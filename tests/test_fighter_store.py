import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from polymarket_flagger.config import Config
from polymarket_flagger.models import FighterRecord
from polymarket_flagger.fighter_store import (
    parse_roster_html,
    FighterStore,
    is_challenge,
    parse_challenge,
    solve_pow,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ufcstats_page.html"
CHALLENGE_FIXTURE = Path(__file__).parent / "fixtures" / "ufcstats_challenge.html"


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

    # New format: object with a fetched_at timestamp and a fighters list.
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert "fetched_at" in raw and isinstance(raw["fighters"], list)

    loaded = FighterStore.from_cache(str(cache_path))

    assert loaded is not None
    abbasov = loaded.lookup("Nariman Abbasov")
    assert abbasov is not None
    assert (abbasov.wins, abbasov.losses, abbasov.draws) == (28, 4, 0)
    assert abbasov.nickname == "Bayraktar"


def test_from_cache_reads_legacy_bare_list(tmp_path):
    # Old cache format was a bare JSON list; from_cache must still load it.
    cache_path = tmp_path / "legacy.json"
    cache_path.write_text(
        json.dumps([FighterRecord("Jon Jones", "Bones", 28, 1, 0).__dict__]),
        encoding="utf-8",
    )
    loaded = FighterStore.from_cache(str(cache_path))
    assert loaded is not None
    assert loaded.lookup("Jon Jones").wins == 28


def test_from_cache_missing_file_returns_none(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"
    assert FighterStore.from_cache(str(missing_path)) is None


def test_from_cache_corrupt_schema_returns_none(tmp_path):
    cache_path = tmp_path / "corrupt.json"
    cache_path.write_text('{"not": "a list"}', encoding="utf-8")

    assert FighterStore.from_cache(str(cache_path)) is None


# --- Proof-of-work solver + challenge parsing --------------------------------

def test_solve_pow_returns_smallest_valid_n():
    nonce = "abc123"
    difficulty = 2
    n = solve_pow(nonce, difficulty)
    # The digest actually has the required leading zeros...
    digest = hashlib.sha256(f"{nonce}:{n}".encode()).hexdigest()
    assert digest.startswith("0" * difficulty)
    # ...and n is the SMALLEST such value (no earlier k qualifies).
    for k in range(n):
        assert not hashlib.sha256(f"{nonce}:{k}".encode()).hexdigest().startswith("00")


def test_solve_pow_matches_independently_computed_value():
    # Fixed nonce/difficulty -> deterministic expected n, computed here directly.
    nonce = "d5b9b0f5dd47fbbb"
    expected = 0
    while not hashlib.sha256(f"{nonce}:{expected}".encode()).hexdigest().startswith("0"):
        expected += 1
    assert solve_pow(nonce, 1) == expected


def test_is_challenge_detects_real_fixtures():
    assert is_challenge(CHALLENGE_FIXTURE.read_text(encoding="utf-8")) is True
    # The real fighter-table page is NOT a challenge.
    assert is_challenge(FIXTURE.read_text(encoding="utf-8")) is False


def test_parse_challenge_extracts_nonce_and_difficulty():
    nonce, difficulty = parse_challenge(CHALLENGE_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(nonce, str) and len(nonce) >= 8
    assert all(c in "0123456789abcdef" for c in nonce)
    assert difficulty == 2  # the captured live challenge used difficulty 2


def test_parse_challenge_raises_on_non_challenge():
    import pytest
    with pytest.raises(ValueError):
        parse_challenge("<html><body>no challenge here</body></html>")


# --- Fallback / staleness load logic (fake scrape, no network) ---------------

def _write_cache(path, records, fetched_at):
    payload = {"fetched_at": fetched_at, "fighters": [r.__dict__ for r in records]}
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def _rec(name, w=10, l=1):
    return FighterRecord(name, "", w, l, 0)


def _big_roster(prefix="F", n=150):
    return [_rec(f"{prefix} Fighter{i}") for i in range(n)]


def test_load_uses_fresh_cache_without_scraping(tmp_path):
    cache = tmp_path / "cache.json"
    _write_cache(cache, [_rec("Fresh Guy")], datetime.now(timezone.utc).isoformat())
    cfg = Config(fighter_cache_path=str(cache))

    def fail_scrape(cfg):
        raise AssertionError("scrape must not be called for a fresh cache")

    store = FighterStore.load(cfg, scrape_fn=fail_scrape)
    assert store.lookup("Fresh Guy").wins == 10


def test_load_stale_cache_triggers_scrape(tmp_path):
    cache = tmp_path / "cache.json"
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    _write_cache(cache, [_rec("Stale Guy")], old)
    cfg = Config(fighter_cache_path=str(cache))

    scraped = FighterStore(_big_roster("New"))
    store = FighterStore.load(cfg, scrape_fn=lambda cfg: scraped)
    assert store is scraped
    assert store.lookup("Stale Guy") is None  # replaced by scrape


def test_load_scrape_failure_falls_back_to_stale_cache(tmp_path):
    cache = tmp_path / "cache.json"
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    _write_cache(cache, [_rec("Stale Guy")], old)
    cfg = Config(fighter_cache_path=str(cache))

    # Scrape returns an insufficient (below-floor) roster -> treated as failure.
    store = FighterStore.load(cfg, scrape_fn=lambda cfg: FighterStore([_rec("Too Few")]))
    assert store.lookup("Stale Guy").wins == 10


def test_load_no_cache_scrape_failure_falls_back_to_seed(tmp_path):
    cfg = Config(fighter_cache_path=str(tmp_path / "absent.json"))
    store = FighterStore.load(cfg, scrape_fn=lambda cfg: FighterStore([]))
    # Committed seed roster is used; a well-known fighter resolves.
    assert store.lookup("Jon Jones") is not None
    assert len(store.records) > 100


def test_load_sanity_floor_prevents_caching_near_empty_scrape(tmp_path):
    cache = tmp_path / "cache.json"
    cfg = Config(fighter_cache_path=str(cache))

    def tiny_scrape(cfg):
        return FighterStore([_rec("Only One")])

    FighterStore.load(cfg, scrape_fn=tiny_scrape)
    # Near-empty scrape must not have written a cache file.
    assert not cache.exists()


def test_build_and_cache_floor_does_not_clobber(tmp_path, monkeypatch):
    # A blocked scrape (0 records) must not overwrite an existing good cache.
    import polymarket_flagger.fighter_store as fs
    cache = tmp_path / "cache.json"
    good = _big_roster("Good")
    _write_cache(cache, good, datetime.now(timezone.utc).isoformat())
    cfg = Config(fighter_cache_path=str(cache))

    class FakeSession:
        def __init__(self): self.headers = {}
        def get(self, *a, **k):
            raise fs.requests.RequestException("blocked")
    monkeypatch.setattr(fs.requests, "Session", lambda: FakeSession())

    store = FighterStore.build_and_cache(cfg)
    assert store.records == []  # scrape produced nothing
    # Existing good cache untouched.
    raw = json.loads(cache.read_text(encoding="utf-8"))
    assert len(raw["fighters"]) == len(good)
