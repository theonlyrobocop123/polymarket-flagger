import json
import logging
import string

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process
from unidecode import unidecode

from .models import FighterRecord

log = logging.getLogger(__name__)

ROSTER_URL = "http://ufcstats.com/statistics/fighters?char={char}&page=all"


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

    def to_cache(self, path: str) -> None:
        payload = [r.__dict__ for r in self.records]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    @classmethod
    def from_cache(cls, path: str, threshold: int = 85):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            records = [FighterRecord(**d) for d in data]
        except (OSError, ValueError, TypeError, AttributeError):
            return None
        return cls(records, threshold) if records else None

    @classmethod
    def build_and_cache(cls, cfg):
        session = requests.Session()
        records = []
        for char in string.ascii_lowercase:
            try:
                resp = session.get(ROSTER_URL.format(char=char), timeout=30)
                resp.raise_for_status()
                records.extend(parse_roster_html(resp.text))
            except requests.RequestException as exc:
                log.warning("UFCStats fetch failed for '%s': %s", char, exc)
        store = cls(records, cfg.name_match_threshold)
        if records:
            store.to_cache(cfg.fighter_cache_path)
        return store
