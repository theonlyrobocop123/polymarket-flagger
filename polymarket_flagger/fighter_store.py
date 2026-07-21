import hashlib
import json
import logging
import re
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process
from unidecode import unidecode

from .models import FighterRecord

log = logging.getLogger(__name__)

ROSTER_URL = "http://ufcstats.com/statistics/fighters?char={char}&page=all"
CHALLENGE_POST_URL = "http://ufcstats.com/__c"

# The real fighter table page contains this class; the anti-bot JS challenge
# does not and instead POSTs its proof-of-work to "/__c".
TABLE_MARKER = "b-statistics__table"
CHALLENGE_MARKER = "/__c"

# Extract the PoW parameters from the live challenge markup. The challenge embeds
#   var nonce="<hex>", target=new Array(<difficulty>+1).join('0');
# and brute-forces the smallest n whose sha256("<nonce>:<n>") hex digest starts
# with <difficulty> leading '0' hex chars.
_NONCE_RE = re.compile(r'nonce\s*=\s*"([0-9a-fA-F]+)"')
_DIFFICULTY_RE = re.compile(r"target\s*=\s*new Array\((\d+)\+1\)")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Sanity floor: a real full 26-letter scrape returns thousands of fighters. If we
# get far fewer than this, the scrape was blocked/broken and must NOT clobber a
# good cache or be treated as a valid roster.
MIN_ROSTER_FLOOR = 100

SEED_PATH = Path(__file__).parent / "data" / "fighters_seed.json"


def _norm(name: str) -> str:
    return unidecode(name or "").lower().strip()


def parse_roster_html(html: str) -> list[FighterRecord]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for row in soup.select("tr.b-statistics__table-row"):
        cols = [c.get_text(strip=True) for c in row.select("td.b-statistics__table-col")]
        if len(cols) < 3:
            continue
        first, last, nick = cols[0], cols[1], cols[2]
        full = f"{first} {last}".strip()
        if not full:
            continue
        # Real UFCStats layout: First, Last, Nickname, Ht., Wt., Reach, Stance,
        # W, L, D, Belt. W/L/D are the only all-digit columns among the trailing
        # stats (height/weight/reach carry units, belt is blank), so take the last
        # three all-digit columns. This survives added/reordered columns and never
        # misreads a units column as a record.
        digit_cols = [c for c in cols[3:] if c.isdigit()]
        if len(digit_cols) < 3:
            continue
        wins, losses, draws = digit_cols[-3:]
        records.append(FighterRecord(
            name=full, nickname=nick,
            wins=int(wins), losses=int(losses), draws=int(draws),
        ))
    return records


# --- Proof-of-work anti-bot challenge (pure, testable helpers) ----------------

def is_challenge(html: str) -> bool:
    """True if `html` is the JS proof-of-work challenge rather than the real
    fighter table. Detected by content, not HTTP status (the challenge is 200)."""
    return TABLE_MARKER not in html and CHALLENGE_MARKER in html


def parse_challenge(html: str) -> tuple[str, int]:
    """Extract (nonce, difficulty) from the challenge page.

    Raises ValueError if the expected markup is absent."""
    nonce_m = _NONCE_RE.search(html)
    diff_m = _DIFFICULTY_RE.search(html)
    if not nonce_m or not diff_m:
        raise ValueError("could not parse PoW challenge markup")
    return nonce_m.group(1), int(diff_m.group(1))


def solve_pow(nonce: str, difficulty: int) -> int:
    """Smallest non-negative integer n such that the hex sha256 digest of
    f"{nonce}:{n}" begins with `difficulty` leading '0' characters."""
    target = "0" * difficulty
    n = 0
    while not hashlib.sha256(f"{nonce}:{n}".encode()).hexdigest().startswith(target):
        n += 1
    return n


def fetch_with_pow(session: requests.Session, url: str,
                   timeout: int = 30, max_attempts: int = 3) -> str:
    """GET `url`; if the anti-bot challenge is returned, solve the PoW, POST the
    solution to obtain the `_fmc` cookie, and re-fetch. Returns the final HTML
    (which may still be a challenge if solving repeatedly failed - callers check)."""
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    html = resp.text
    attempts = 0
    while is_challenge(html) and attempts < max_attempts:
        attempts += 1
        nonce, difficulty = parse_challenge(html)
        n = solve_pow(nonce, difficulty)
        log.info("Solved UFCStats PoW (difficulty %d) for %s -> n=%d", difficulty, url, n)
        post = session.post(CHALLENGE_POST_URL, data={"nonce": nonce, "n": n}, timeout=timeout)
        post.raise_for_status()
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        html = resp.text
    return html


# --- Cache (de)serialization -------------------------------------------------

def _read_cache(path: str) -> tuple[list[FighterRecord], str | None]:
    """Read a cache/seed file. Returns (records, fetched_at).

    Supports the timestamped object format {"fetched_at": ..., "fighters": [...]}
    and the legacy bare-list format (returned with fetched_at=None -> treated as
    stale). Raises on missing/corrupt files."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        raw = data.get("fighters", [])
        fetched_at = data.get("fetched_at")
    else:
        raw = data
        fetched_at = None
    records = [FighterRecord(**d) for d in raw]
    return records, fetched_at


def _try_read_cache(path: str) -> tuple[list[FighterRecord], str | None] | None:
    try:
        return _read_cache(path)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _is_fresh(fetched_at: str | None, max_age_days: int) -> bool:
    """True if `fetched_at` (ISO-8601) is within `max_age_days` of now. Unknown
    or unparseable timestamps (e.g. legacy bare-list caches) are treated as stale."""
    if not fetched_at:
        return False
    try:
        ts = datetime.fromisoformat(fetched_at)
    except (ValueError, TypeError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ts <= timedelta(days=max_age_days)


class FighterStore:
    def __init__(self, records: list[FighterRecord], threshold: int = 85):
        self.records = records
        self.threshold = threshold
        # Map normalized "name"/"nickname" -> record for fuzzy matching.
        # Never-guess safety: if two DIFFERENT records share a normalized full name
        # (UFC has multiple e.g. "Bruno Silva") that name is ambiguous and must not
        # resolve at all - lookup returns None rather than confidently returning the
        # wrong person. Same rule for shared nicknames.
        ambiguous_names = self._collisions(records, lambda r: r.name)
        ambiguous_nicks = self._collisions(records, lambda r: r.nickname)
        for key in ambiguous_names:
            log.warning("Ambiguous fighter name, skipping: %r", key)

        self._choices = {}
        for r in records:
            name_key = _norm(r.name)
            if name_key and name_key not in ambiguous_names:
                self._choices.setdefault(name_key, r)
        for r in records:
            if not r.nickname:
                continue
            nick_key = _norm(r.nickname)
            if nick_key and nick_key not in ambiguous_nicks:
                self._choices.setdefault(nick_key, r)

    @staticmethod
    def _collisions(records, keyfunc) -> set:
        """Normalized keys held by two or more DIFFERENT records.

        Two distinct people named "Bruno Silva" share the name STRING, so the
        comparison is between the records themselves: a genuinely identical
        duplicate record is not a collision, but two different records are.
        """
        first_seen = {}
        ambiguous = set()
        for r in records:
            key = _norm(keyfunc(r))
            if not key:
                continue
            if key in first_seen:
                # FighterRecord is an unfrozen dataclass (unhashable) but supports
                # equality via its fields.
                if first_seen[key] != r:
                    ambiguous.add(key)
            else:
                first_seen[key] = r
        return ambiguous

    def lookup(self, name: str):
        if not name or not self._choices:
            return None
        query = _norm(name)
        match = process.extractOne(
            query, self._choices.keys(), scorer=fuzz.token_sort_ratio
        )
        if match and match[1] >= self.threshold:
            return self._choices[match[0]]
        log.info("No confident fighter match for %r (best score %s)",
                 name, match[1] if match else None)
        return None

    def to_cache(self, path: str, fetched_at: str | None = None) -> None:
        if fetched_at is None:
            fetched_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "fetched_at": fetched_at,
            "fighters": [r.__dict__ for r in self.records],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    @classmethod
    def from_cache(cls, path: str, threshold: int = 85):
        result = _try_read_cache(path)
        if result is None:
            return None
        records, _ = result
        return cls(records, threshold) if records else None

    @classmethod
    def build_and_cache(cls, cfg):
        """PoW-aware full scrape of all 26 letter pages.

        Writes the runtime cache ONLY when the scrape meets the sanity floor, so a
        blocked/empty scrape can never clobber a previously-good cache."""
        session = requests.Session()
        session.headers.update({"User-Agent": _USER_AGENT})
        records = []
        for char in string.ascii_lowercase:
            try:
                html = fetch_with_pow(session, ROSTER_URL.format(char=char))
            except requests.RequestException as exc:
                log.warning("UFCStats fetch failed for '%s': %s", char, exc)
                continue
            if is_challenge(html):
                log.error("UFCStats still returned the anti-bot challenge for '%s' "
                          "after solving the PoW; skipping this page.", char)
                continue
            page = parse_roster_html(html)
            if not page:
                log.error("UFCStats returned no fighters for '%s' (unexpected).", char)
            records.extend(page)

        store = cls(records, cfg.name_match_threshold)
        if len(records) >= MIN_ROSTER_FLOOR:
            store.to_cache(cfg.fighter_cache_path)
            log.info("Cached %d fighters from live scrape.", len(records))
        else:
            log.error("UFCStats scrape yielded only %d records (< floor %d); NOT "
                      "overwriting cache and treating scrape as failed.",
                      len(records), MIN_ROSTER_FLOOR)
        return store

    @classmethod
    def load(cls, cfg, scrape_fn=None):
        """Resolve the fighter roster with graceful degradation.

        Order: fresh runtime cache -> live PoW scrape -> stale runtime cache ->
        committed seed roster. Never returns an empty store when the seed exists."""
        scrape_fn = scrape_fn or cls.build_and_cache
        threshold = cfg.name_match_threshold
        max_age = getattr(cfg, "cache_max_age_days", 7)

        cached = _try_read_cache(cfg.fighter_cache_path)
        if cached is not None and cached[0] and _is_fresh(cached[1], max_age):
            log.info("Using fresh fighter cache (%d records).", len(cached[0]))
            return cls(cached[0], threshold)

        log.info("Fighter cache missing or stale; attempting PoW scrape.")
        try:
            scraped = scrape_fn(cfg)
        except Exception as exc:  # scrape is best-effort; fall back below
            log.error("Fighter scrape raised: %s", exc)
            scraped = None
        if scraped is not None and len(scraped.records) >= MIN_ROSTER_FLOOR:
            return scraped

        if cached is not None and cached[0]:
            log.warning("Scrape failed/insufficient; using STALE runtime cache "
                        "(%d records). Records may be out of date.", len(cached[0]))
            return cls(cached[0], threshold)

        seed = cls._load_seed(threshold)
        if seed is not None:
            log.warning("Scrape failed and no runtime cache; using committed SEED "
                        "roster (%d records). Records may be out of date.",
                        len(seed.records))
            return seed

        log.error("No fighter data available from cache, scrape, or seed; "
                  "Flag 1 (UFC mispricing) will not fire.")
        return cls([], threshold)

    @classmethod
    def _load_seed(cls, threshold: int = 85):
        result = _try_read_cache(str(SEED_PATH))
        if result is None:
            return None
        records, _ = result
        return cls(records, threshold) if records else None
