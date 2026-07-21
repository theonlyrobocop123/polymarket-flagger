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
        if len(cols) < 6:
            continue
        first, last, nick, wins, losses, draws = cols[0], cols[1], cols[2], cols[3], cols[4], cols[5]
        if not (wins.isdigit() and losses.isdigit() and draws.isdigit()):
            continue
        full = f"{first} {last}".strip()
        if not full:
            continue
        records.append(FighterRecord(
            name=full, nickname=nick,
            wins=int(wins), losses=int(losses), draws=int(draws),
        ))
    return records


class FighterStore:
    def __init__(self, records: list[FighterRecord], threshold: int = 85):
        self.records = records
        self.threshold = threshold
        # Map normalized "name"/"nickname" -> record for fuzzy matching
        self._choices = {}
        for r in records:
            self._choices[_norm(r.name)] = r
            if r.nickname:
                self._choices.setdefault(_norm(r.nickname), r)

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
