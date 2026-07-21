# Polymarket Flagger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python service, run every 15 minutes by GitHub Actions, that flags underpriced Polymarket sports outcomes against three rules and alerts the user on Telegram only when a new one appears.

**Architecture:** One cycle = fetch active sports/UFC markets from the Polymarket Gamma API, look up UFC fighter career records from a cached UFCStats scrape, evaluate three flags, diff against saved state to find NEW vs STILL-QUALIFYING items, and send one Telegram message when there is at least one NEW item. State persists across runs in a JSON file committed to a dedicated `bot-state` branch.

**Tech Stack:** Python 3.12, `requests`, `beautifulsoup4`, `rapidfuzz`, `unidecode`, `python-dotenv`, `pytest`.

## Global Constraints

- Python 3.12.
- No API keys for Polymarket or UFCStats (public read / scrape).
- Telegram bot token and chat id come only from environment variables (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`), never committed.
- All thresholds live in one `Config` object; no magic numbers scattered in logic.
- Prices from Polymarket are floats in the range 0..1; display as whole-number percent.
- Never guess a fighter record: a name match below the confidence threshold means Flag 1 is skipped for that market.
- State only advances after a successful Telegram send, so a NEW item is never silently lost.
- Package name: `polymarket_flagger`. Entry point: `python -m polymarket_flagger.main`.

---

### Task 1: Project scaffold, models, and config

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `polymarket_flagger/__init__.py` (empty)
- Create: `polymarket_flagger/models.py`
- Create: `polymarket_flagger/config.py`
- Create: `tests/__init__.py` (empty)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Market`, `FighterRecord`, `QualifyingItem` dataclasses; flag constants `FLAG_MISPRICING`, `FLAG_UFC_LONGSHOT`, `FLAG_SPORTS_LONGSHOT`; `Config` dataclass with `Config.from_env()`.

- [ ] **Step 1: Create `requirements.txt`**

```
requests==2.32.3
beautifulsoup4==4.12.3
rapidfuzz==3.9.7
Unidecode==1.3.8
python-dotenv==1.0.1
pytest==8.3.3
```

- [ ] **Step 2: Create `.env.example`**

```
TELEGRAM_TOKEN=123456789:replace-with-botfather-token
TELEGRAM_CHAT_ID=123456789
```

- [ ] **Step 3: Create `polymarket_flagger/models.py`**

```python
from dataclasses import dataclass, field

# Flag identifiers (stored in state, so keep stable)
FLAG_MISPRICING = "ufc_mispricing"
FLAG_UFC_LONGSHOT = "ufc_longshot"
FLAG_SPORTS_LONGSHOT = "sports_longshot"


@dataclass
class Market:
    id: str
    title: str
    outcomes: list[str]        # e.g. ["Mike Davis", "Nurullo Aliev"]
    prices: list[float]        # same order as outcomes, each 0..1
    volume: float
    liquidity: float
    event_slug: str            # used to build the polymarket.com link
    end_date: str
    is_ufc: bool
    sport: str                 # tag slug, e.g. "ufc", "nba", "soccer"


@dataclass
class FighterRecord:
    name: str
    nickname: str
    wins: int
    losses: int
    draws: int

    @property
    def total_fights(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def win_pct(self) -> float:
        decided = self.wins + self.losses
        return (self.wins / decided * 100.0) if decided else 0.0


@dataclass
class QualifyingItem:
    market_id: str
    title: str
    flagged_outcome: str       # the specific cheap side
    price: float               # 0..1
    volume: float
    liquidity: float
    event_slug: str
    sport: str
    is_ufc: bool
    flags: list[str] = field(default_factory=list)
    record_detail: str = ""    # populated for FLAG_MISPRICING

    @property
    def key(self) -> str:
        return f"{self.market_id}|{self.flagged_outcome}"
```

- [ ] **Step 4: Write the failing test `tests/test_config.py`**

```python
import os
from polymarket_flagger.config import Config


def test_defaults():
    cfg = Config()
    assert cfg.flag2_ufc_threshold == 0.15
    assert cfg.flag3_sports_threshold == 0.10
    assert cfg.flag1_gap_pct == 15.0
    assert cfg.flag1_min_fights == 4
    assert cfg.name_match_threshold == 85


def test_from_env_reads_secrets(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    cfg = Config.from_env()
    assert cfg.telegram_token == "tok"
    assert cfg.telegram_chat_id == "999"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: polymarket_flagger.config`.

- [ ] **Step 6: Create `polymarket_flagger/config.py`**

```python
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()  # loads .env if present; no-op in CI where env is set directly


@dataclass
class Config:
    gamma_base: str = "https://gamma-api.polymarket.com"
    # Sport tag slugs to scan on the Gamma /events endpoint.
    sport_tag_slugs: tuple = (
        "ufc", "mma", "nba", "nfl", "mlb", "nhl",
        "soccer", "boxing", "tennis", "cricket",
    )
    ufc_tag_slugs: tuple = ("ufc", "mma")

    flag1_gap_pct: float = 15.0
    flag1_min_fights: int = 4
    flag2_ufc_threshold: float = 0.15
    flag3_sports_threshold: float = 0.10
    flag3_min_liquidity: float = 5000.0

    name_match_threshold: int = 85

    telegram_token: str = ""
    telegram_chat_id: str = ""

    state_path: str = "state.json"
    fighter_cache_path: str = "fighters_cache.json"
    events_per_tag: int = 200

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            telegram_token=os.environ.get("TELEGRAM_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .env.example polymarket_flagger tests
git commit -m "feat: scaffold package, models, and config"
```

---

### Task 2: Polymarket client

Fetches active markets for each configured sport tag from the Gamma `/events` endpoint and returns one normalized `Market` per event (the highest-liquidity market on the card, which is the moneyline/winner market). This keeps prop markets (method of victory, round totals) out of scope.

**Files:**
- Create: `polymarket_flagger/polymarket_client.py`
- Create: `tests/fixtures/gamma_events.json`
- Test: `tests/test_polymarket_client.py`

**Interfaces:**
- Consumes: `Config`, `Market` from Task 1.
- Produces: `parse_events(events: list[dict], sport: str, ufc_tag_slugs) -> list[Market]` and `fetch_markets(cfg: Config) -> list[Market]`.

- [ ] **Step 1: Create fixture `tests/fixtures/gamma_events.json`**

This mimics the Gamma `/events` response shape (note `outcomes`/`outcomePrices` are JSON-encoded strings).

```json
[
  {
    "slug": "ufc-dav-ali-2026-07-25",
    "tags": [{"slug": "ufc", "label": "UFC"}, {"slug": "sports", "label": "Sports"}],
    "markets": [
      {
        "id": "2885100",
        "question": "UFC: Mike Davis vs. Nurullo Aliev",
        "outcomes": "[\"Mike Davis\", \"Nurullo Aliev\"]",
        "outcomePrices": "[\"0.92\", \"0.08\"]",
        "volumeNum": 18000.0,
        "liquidityNum": 18000.0,
        "endDate": "2026-07-26T03:59:59.999Z",
        "active": true,
        "closed": false
      },
      {
        "id": "2885101",
        "question": "UFC: Davis vs Aliev - Method of victory",
        "outcomes": "[\"KO/TKO\", \"Decision\", \"Submission\"]",
        "outcomePrices": "[\"0.4\", \"0.4\", \"0.2\"]",
        "volumeNum": 500.0,
        "liquidityNum": 500.0,
        "endDate": "2026-07-26T03:59:59.999Z",
        "active": true,
        "closed": false
      }
    ]
  }
]
```

- [ ] **Step 2: Write the failing test `tests/test_polymarket_client.py`**

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_polymarket_client.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Create `polymarket_flagger/polymarket_client.py`**

```python
import json
import logging

import requests

from .models import Market

log = logging.getLogger(__name__)


def _parse_json_field(raw, default):
    if isinstance(raw, list):
        return raw
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def parse_events(events, sport, ufc_tag_slugs):
    """Turn raw Gamma events into one Market each (highest-liquidity market)."""
    markets = []
    for ev in events:
        tag_slugs = {t.get("slug", "") for t in ev.get("tags", [])}
        is_ufc = bool(tag_slugs & set(ufc_tag_slugs))
        candidates = []
        for mk in ev.get("markets", []):
            if not mk.get("active", False) or mk.get("closed", False):
                continue
            outcomes = _parse_json_field(mk.get("outcomes"), [])
            prices_raw = _parse_json_field(mk.get("outcomePrices"), [])
            if len(outcomes) < 2 or len(outcomes) != len(prices_raw):
                continue
            try:
                prices = [float(p) for p in prices_raw]
            except (ValueError, TypeError):
                continue
            candidates.append((mk, outcomes, prices))
        if not candidates:
            continue
        # Primary market = highest liquidity (the moneyline/winner market)
        mk, outcomes, prices = max(
            candidates, key=lambda c: float(c[0].get("liquidityNum") or 0.0)
        )
        markets.append(Market(
            id=str(mk.get("id", "")),
            title=mk.get("question", ""),
            outcomes=outcomes,
            prices=prices,
            volume=float(mk.get("volumeNum") or 0.0),
            liquidity=float(mk.get("liquidityNum") or 0.0),
            event_slug=ev.get("slug", ""),
            end_date=mk.get("endDate", ""),
            is_ufc=is_ufc,
            sport=sport,
        ))
    return markets


def fetch_markets(cfg):
    """Fetch active markets for every configured sport tag. Deduped by market id."""
    session = requests.Session()
    by_id = {}
    for slug in cfg.sport_tag_slugs:
        try:
            resp = session.get(
                f"{cfg.gamma_base}/events",
                params={
                    "tag_slug": slug,
                    "active": "true",
                    "closed": "false",
                    "limit": cfg.events_per_tag,
                },
                timeout=30,
            )
            resp.raise_for_status()
            events = resp.json()
        except requests.RequestException as exc:
            log.warning("Gamma fetch failed for tag %s: %s", slug, exc)
            continue
        for m in parse_events(events, sport=slug, ufc_tag_slugs=cfg.ufc_tag_slugs):
            # First tag wins; but prefer a UFC-tagged view if any tag marks it UFC
            if m.id not in by_id or (m.is_ufc and not by_id[m.id].is_ufc):
                by_id[m.id] = m
    return list(by_id.values())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_polymarket_client.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Live smoke check (verify real tag slugs return data)**

Run:
```bash
python -c "from polymarket_flagger.config import Config; from polymarket_flagger.polymarket_client import fetch_markets; ms=fetch_markets(Config()); print(len(ms), 'markets;', sum(m.is_ufc for m in ms), 'UFC'); [print(m.sport, m.title, m.prices) for m in ms[:5]]"
```
Expected: prints a non-zero market count. If UFC count is 0 during a period with no scheduled fights, that is acceptable. If total is 0, the sport tag slugs are wrong: inspect one event's `tags` array live and update `Config.sport_tag_slugs`. Record the finding but do not block the commit.

- [ ] **Step 7: Commit**

```bash
git add polymarket_flagger/polymarket_client.py tests/test_polymarket_client.py tests/fixtures/gamma_events.json
git commit -m "feat: Polymarket Gamma client with per-event primary market"
```

---

### Task 3: Fighter record store (UFCStats scrape + fuzzy match)

**Files:**
- Create: `polymarket_flagger/fighter_store.py`
- Create: `tests/fixtures/ufcstats_page.html`
- Test: `tests/test_fighter_store.py`

**Interfaces:**
- Consumes: `Config`, `FighterRecord` from Task 1.
- Produces: `parse_roster_html(html: str) -> list[FighterRecord]`; class `FighterStore` with `FighterStore(records, threshold)`, `.lookup(name) -> FighterRecord | None`, classmethods `.from_cache(path, threshold)` and `.build_and_cache(cfg) -> FighterStore`.

- [ ] **Step 1: Create fixture `tests/fixtures/ufcstats_page.html`**

Minimal copy of the UFCStats roster table structure (one row per fighter: first, last, nickname, W, L, D, then extra columns).

```html
<table class="b-statistics__table">
  <tbody>
    <tr class="b-statistics__table-row"></tr>
    <tr class="b-statistics__table-row">
      <td class="b-statistics__table-col"><a href="#">Jon</a></td>
      <td class="b-statistics__table-col"><a href="#">Jones</a></td>
      <td class="b-statistics__table-col"><a href="#">Bones</a></td>
      <td class="b-statistics__table-col">27</td>
      <td class="b-statistics__table-col">1</td>
      <td class="b-statistics__table-col">0</td>
      <td class="b-statistics__table-col"></td>
      <td class="b-statistics__table-col"></td>
      <td class="b-statistics__table-col"></td>
      <td class="b-statistics__table-col"></td>
      <td class="b-statistics__table-col"></td>
    </tr>
    <tr class="b-statistics__table-row">
      <td class="b-statistics__table-col"><a href="#">Nurullo</a></td>
      <td class="b-statistics__table-col"><a href="#">Aliev</a></td>
      <td class="b-statistics__table-col"></td>
      <td class="b-statistics__table-col">10</td>
      <td class="b-statistics__table-col">0</td>
      <td class="b-statistics__table-col">0</td>
      <td class="b-statistics__table-col"></td>
      <td class="b-statistics__table-col"></td>
      <td class="b-statistics__table-col"></td>
      <td class="b-statistics__table-col"></td>
      <td class="b-statistics__table-col"></td>
    </tr>
  </tbody>
</table>
```

- [ ] **Step 2: Write the failing test `tests/test_fighter_store.py`**

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_fighter_store.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Create `polymarket_flagger/fighter_store.py`**

```python
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
        except (OSError, ValueError):
            return None
        records = [FighterRecord(**d) for d in data]
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_fighter_store.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add polymarket_flagger/fighter_store.py tests/test_fighter_store.py tests/fixtures/ufcstats_page.html
git commit -m "feat: UFCStats fighter store with fuzzy name lookup"
```

---

### Task 4: Flag evaluator

**Files:**
- Create: `polymarket_flagger/flags.py`
- Test: `tests/test_flags.py`

**Interfaces:**
- Consumes: `Market`, `QualifyingItem`, flag constants (Task 1); `FighterStore.lookup` (Task 3); `Config` (Task 1).
- Produces: `evaluate(markets: list[Market], store, cfg: Config) -> list[QualifyingItem]`.

Logic per market, per outcome index `i` with `price = market.prices[i]`:
- Flag 3 (sports longshot): `price < cfg.flag3_sports_threshold and market.liquidity >= cfg.flag3_min_liquidity`.
- Flag 2 (UFC longshot): `market.is_ufc and price < cfg.flag2_ufc_threshold`.
- Flag 1 (UFC mispricing): only for UFC markets with exactly two outcomes. Look up both fighters; both must match and have `total_fights >= cfg.flag1_min_fights`. If `abs(win_pct_a - win_pct_b) <= cfg.flag1_gap_pct` and the cheaper side's `price < 0.20`, flag the cheaper side (index of min price).
One `QualifyingItem` per flagged outcome index, carrying all flags hit on that index.

- [ ] **Step 1: Write the failing test `tests/test_flags.py`**

```python
from polymarket_flagger.config import Config
from polymarket_flagger.models import (
    Market, FighterRecord,
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
    items = evaluate([_ufc_market([0.88, 0.12])], FakeStore({}), cfg)
    assert FLAG_UFC_LONGSHOT in items[0].flags
    assert items[0].flagged_outcome == "B"


def test_flag2_boundary_not_below_threshold():
    cfg = Config()
    # exactly 0.15 is NOT below 0.15
    items = evaluate([_ufc_market([0.85, 0.15])], FakeStore({}), cfg)
    assert items == []


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_flags.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `polymarket_flagger/flags.py`**

```python
import logging

from .models import (
    Market, QualifyingItem,
    FLAG_MISPRICING, FLAG_UFC_LONGSHOT, FLAG_SPORTS_LONGSHOT,
)

log = logging.getLogger(__name__)


def _mispricing_index(market: Market, store, cfg):
    """Return the underdog outcome index if the mispricing flag applies, else None."""
    if not market.is_ufc or len(market.outcomes) != 2:
        return None
    ra = store.lookup(market.outcomes[0])
    rb = store.lookup(market.outcomes[1])
    if ra is None or rb is None:
        return None
    if ra.total_fights < cfg.flag1_min_fights or rb.total_fights < cfg.flag1_min_fights:
        return None
    if abs(ra.win_pct - rb.win_pct) > cfg.flag1_gap_pct:
        return None
    dog = 0 if market.prices[0] <= market.prices[1] else 1
    if market.prices[dog] >= 0.20:
        return None
    return dog, ra, rb


def _record_detail(market, dog, ra, rb):
    recs = [ra, rb]
    fav = recs[1 - dog]
    dogr = recs[dog]
    gap = round(abs(ra.win_pct - rb.win_pct))
    return (f"{fav.name} {fav.wins}-{fav.losses} ({round(fav.win_pct)}%) vs "
            f"{dogr.name} {dogr.wins}-{dogr.losses} ({round(dogr.win_pct)}%), {gap}-pt gap")


def evaluate(markets, store, cfg):
    items = []
    for market in markets:
        flags_by_index = {}

        for i, price in enumerate(market.prices):
            hits = []
            if price < cfg.flag3_sports_threshold and market.liquidity >= cfg.flag3_min_liquidity:
                hits.append(FLAG_SPORTS_LONGSHOT)
            if market.is_ufc and price < cfg.flag2_ufc_threshold:
                hits.append(FLAG_UFC_LONGSHOT)
            if hits:
                flags_by_index.setdefault(i, []).extend(hits)

        detail = ""
        mis = _mispricing_index(market, store, cfg)
        if mis is not None:
            dog, ra, rb = mis
            flags_by_index.setdefault(dog, []).append(FLAG_MISPRICING)
            detail_map = {dog: _record_detail(market, dog, ra, rb)}
        else:
            detail_map = {}

        for i, flags in flags_by_index.items():
            items.append(QualifyingItem(
                market_id=market.id,
                title=market.title,
                flagged_outcome=market.outcomes[i],
                price=market.prices[i],
                volume=market.volume,
                liquidity=market.liquidity,
                event_slug=market.event_slug,
                sport=market.sport,
                is_ufc=market.is_ufc,
                flags=flags,
                record_detail=detail_map.get(i, ""),
            ))
    return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_flags.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add polymarket_flagger/flags.py tests/test_flags.py
git commit -m "feat: three-flag evaluator with dedupe"
```

---

### Task 5: State store and diff

**Files:**
- Create: `polymarket_flagger/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `QualifyingItem` (Task 1).
- Produces: `load_state(path) -> dict`, `save_state(path, items)`, `diff(items, prev) -> tuple[list[QualifyingItem], list[tuple[QualifyingItem, float]]]` returning `(new_items, still_items_with_prev_price)`.

- [ ] **Step 1: Write the failing test `tests/test_state.py`**

```python
import json

from polymarket_flagger.models import QualifyingItem, FLAG_SPORTS_LONGSHOT
from polymarket_flagger.state import load_state, save_state, diff


def _item(mid, outcome, price):
    return QualifyingItem(market_id=mid, title="t", flagged_outcome=outcome,
                          price=price, volume=1.0, liquidity=1.0, event_slug="s",
                          sport="soccer", is_ufc=False, flags=[FLAG_SPORTS_LONGSHOT])


def test_diff_classifies_new_and_still():
    prev = {"m1|A": {"price": 0.09, "flags": [FLAG_SPORTS_LONGSHOT]}}
    items = [_item("m1", "A", 0.06), _item("m2", "B", 0.04)]
    new, still = diff(items, prev)
    assert [i.market_id for i in new] == ["m2"]
    assert len(still) == 1
    still_item, prev_price = still[0]
    assert still_item.market_id == "m1" and prev_price == 0.09


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    save_state(str(path), [_item("m1", "A", 0.06)])
    loaded = load_state(str(path))
    assert loaded["m1|A"]["price"] == 0.06


def test_load_missing_returns_empty(tmp_path):
    assert load_state(str(tmp_path / "nope.json")) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `polymarket_flagger/state.py`**

```python
import json


def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(path, items):
    payload = {it.key: {"price": it.price, "flags": it.flags} for it in items}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def diff(items, prev):
    new_items, still_items = [], []
    for it in items:
        if it.key in prev:
            still_items.append((it, prev[it.key].get("price")))
        else:
            new_items.append(it)
    return new_items, still_items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_state.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add polymarket_flagger/state.py tests/test_state.py
git commit -m "feat: JSON state store with new/still diff"
```

---

### Task 6: Telegram notifier and message formatter

**Files:**
- Create: `polymarket_flagger/telegram_notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `QualifyingItem` (Task 1), `Config` (Task 1).
- Produces: `format_message(now_str, new_items, still_items) -> str`; `send(cfg, text) -> bool`.

- [ ] **Step 1: Write the failing test `tests/test_notifier.py`**

```python
from polymarket_flagger.models import (
    QualifyingItem, FLAG_MISPRICING, FLAG_UFC_LONGSHOT, FLAG_SPORTS_LONGSHOT,
)
from polymarket_flagger.telegram_notifier import format_message


def _item(**kw):
    base = dict(market_id="m", title="A vs. B", flagged_outcome="B", price=0.08,
                volume=18000.0, liquidity=18000.0, event_slug="a-vs-b",
                sport="ufc", is_ufc=True, flags=[FLAG_UFC_LONGSHOT], record_detail="")
    base.update(kw)
    return QualifyingItem(**base)


def test_format_has_new_and_still_sections():
    new = [_item(flags=[FLAG_UFC_LONGSHOT, FLAG_SPORTS_LONGSHOT])]
    still = [(_item(market_id="m2", flagged_outcome="Draw", price=0.06, sport="soccer",
                    is_ufc=False, flags=[FLAG_SPORTS_LONGSHOT]), 0.08)]
    msg = format_message("2026-07-21 14:15 UTC", new, still)
    assert "NEW (1)" in msg
    assert "STILL QUALIFYING (1)" in msg
    assert "8%" in msg            # new item price
    assert "was 8%" in msg        # still item shows previous price
    assert "6%" in msg            # still item current price
    assert "polymarket.com/event/a-vs-b" in msg


def test_mispricing_shows_record_detail():
    item = _item(flags=[FLAG_MISPRICING], record_detail="A 27-1 (96%) vs B 20-4 (83%), 13-pt gap")
    msg = format_message("t", [item], [])
    assert "13-pt gap" in msg
    assert "UFC mispricing" in msg


def test_empty_still_section_omitted():
    msg = format_message("t", [_item()], [])
    assert "STILL QUALIFYING" not in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `polymarket_flagger/telegram_notifier.py`**

```python
import html
import logging

import requests

from .models import FLAG_MISPRICING, FLAG_UFC_LONGSHOT, FLAG_SPORTS_LONGSHOT

log = logging.getLogger(__name__)

_SPORT_EMOJI = {
    "ufc": "🥊", "mma": "🥊", "boxing": "🥊",
    "nba": "🏀", "nfl": "🏈", "mlb": "⚾", "nhl": "🏒",
    "soccer": "⚽", "tennis": "🎾", "cricket": "🏏",
}
_FLAG_LABEL = {
    FLAG_MISPRICING: "UFC mispricing",
    FLAG_UFC_LONGSHOT: "UFC longshot &lt;15%",
    FLAG_SPORTS_LONGSHOT: "Sports longshot &lt;10%",
}


def _pct(p):
    return f"{round(p * 100)}%"


def _money(v):
    if v >= 1000:
        return f"${round(v / 1000)}k"
    return f"${round(v)}"


def _flag_tags(item):
    parts = []
    for f in item.flags:
        label = _FLAG_LABEL.get(f, f)
        if f == FLAG_MISPRICING and item.record_detail:
            label = f"{label} - {html.escape(item.record_detail)}"
        parts.append(label)
    return " · ".join(parts)


def _render_item(item, prev_price=None):
    emoji = _SPORT_EMOJI.get(item.sport, "🎯")
    title = html.escape(item.title)
    outcome = html.escape(item.flagged_outcome)
    price = _pct(item.price)
    was = f" (was {_pct(prev_price)})" if prev_price is not None else ""
    url = f"https://polymarket.com/event/{item.event_slug}"
    return (
        f"{emoji} <b>{title}</b>\n"
        f"{outcome} <b>@ {price}</b>{was} · vol {_money(item.volume)} · liq {_money(item.liquidity)}\n"
        f"Flags: {_flag_tags(item)}\n"
        f'🔗 <a href="{url}">Open on Polymarket</a>'
    )


def format_message(now_str, new_items, still_items):
    lines = [f"🚩 <b>Polymarket Flags</b> · {html.escape(now_str)}", ""]
    lines.append(f"🆕 <b>NEW ({len(new_items)})</b>")
    lines.append("")
    for it in new_items:
        lines.append(_render_item(it))
        lines.append("")
    if still_items:
        lines.append(f"🔁 <b>STILL QUALIFYING ({len(still_items)})</b>")
        lines.append("")
        for it, prev in still_items:
            lines.append(_render_item(it, prev))
            lines.append("")
    return "\n".join(lines).strip()


def send(cfg, text):
    if not cfg.telegram_token or not cfg.telegram_chat_id:
        log.error("Telegram credentials missing; cannot send.")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{cfg.telegram_token}/sendMessage",
            json={
                "chat_id": cfg.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.error("Telegram send failed: %s", exc)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add polymarket_flagger/telegram_notifier.py tests/test_notifier.py
git commit -m "feat: Telegram HTML message formatter and sender"
```

---

### Task 7: Orchestrator (one cycle)

**Files:**
- Create: `polymarket_flagger/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `run_cycle(cfg, client_fn, store, now_str) -> bool` (returns True if a message was sent) and `main()`.

`run_cycle` is written so the network pieces (`client_fn`, `store`, and Telegram `send`) are injectable, making it unit-testable without network. `main()` wires the real implementations.

- [ ] **Step 1: Write the failing test `tests/test_main.py`**

```python
from polymarket_flagger.config import Config
from polymarket_flagger.models import Market, FighterRecord
from polymarket_flagger import main as main_mod


class FakeStore:
    def __init__(self, mapping): self.mapping = mapping
    def lookup(self, name): return self.mapping.get(name)


def _ufc_longshot_market():
    return Market(id="m1", title="A vs. B", outcomes=["A", "B"], prices=[0.9, 0.1],
                  volume=1000.0, liquidity=20000.0, event_slug="a-b", end_date="",
                  is_ufc=True, sport="ufc")


def test_run_cycle_sends_on_new_and_saves_state(tmp_path, monkeypatch):
    cfg = Config(state_path=str(tmp_path / "state.json"))
    sent = {}
    monkeypatch.setattr(main_mod, "send", lambda c, text: sent.setdefault("text", text) or True)

    result = main_mod.run_cycle(cfg, lambda c: [_ufc_longshot_market()], FakeStore({}), "now")
    assert result is True
    assert "NEW (1)" in sent["text"]
    # state saved so next cycle it is no longer NEW
    sent.clear()
    result2 = main_mod.run_cycle(cfg, lambda c: [_ufc_longshot_market()], FakeStore({}), "now")
    assert result2 is False          # no new item -> no send
    assert sent == {}


def test_run_cycle_does_not_save_when_send_fails(tmp_path, monkeypatch):
    cfg = Config(state_path=str(tmp_path / "state.json"))
    monkeypatch.setattr(main_mod, "send", lambda c, text: False)
    result = main_mod.run_cycle(cfg, lambda c: [_ufc_longshot_market()], FakeStore({}), "now")
    assert result is False
    # state NOT advanced, so item is still NEW next time (with a working send)
    calls = {}
    monkeypatch.setattr(main_mod, "send", lambda c, text: calls.setdefault("t", text) or True)
    assert main_mod.run_cycle(cfg, lambda c: [_ufc_longshot_market()], FakeStore({}), "now") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError`.

- [ ] **Step 3: Create `polymarket_flagger/main.py`**

```python
import logging
from datetime import datetime, timezone

from .config import Config
from .polymarket_client import fetch_markets
from .fighter_store import FighterStore
from .flags import evaluate
from .state import load_state, save_state, diff
from .telegram_notifier import format_message, send

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("polymarket_flagger")


def run_cycle(cfg, client_fn, store, now_str):
    """Run one evaluation cycle. Returns True if a Telegram message was sent."""
    markets = client_fn(cfg)
    log.info("Fetched %d markets", len(markets))
    items = evaluate(markets, store, cfg)
    log.info("%d qualifying items", len(items))

    prev = load_state(cfg.state_path)
    new_items, still_items = diff(items, prev)
    log.info("%d new, %d still qualifying", len(new_items), len(still_items))

    if not new_items:
        return False  # only alert on NEW; do not advance state on silent cycles

    text = format_message(now_str, new_items, still_items)
    if not send(cfg, text):
        log.error("Send failed; state not advanced so NEW items are retried next cycle.")
        return False

    save_state(cfg.state_path, items)  # advance state only after a successful send
    return True


def _load_store(cfg):
    store = FighterStore.from_cache(cfg.fighter_cache_path, cfg.name_match_threshold)
    if store is None:
        log.info("No fighter cache; scraping UFCStats roster.")
        store = FighterStore.build_and_cache(cfg)
    return store


def main():
    cfg = Config.from_env()
    store = _load_store(cfg)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sent = run_cycle(cfg, fetch_markets, store, now_str)
    log.info("Cycle done. Message sent: %s", sent)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add polymarket_flagger/main.py tests/test_main.py
git commit -m "feat: orchestrator with send-then-save state discipline"
```

---

### Task 8: GitHub Actions workflow, state branch, and README

**Files:**
- Create: `.github/workflows/flagger.yml`
- Create: `README.md`

**Interfaces:**
- Consumes: `main()` entry point, `state.json`, `fighters_cache.json`.

- [ ] **Step 1: Create `.github/workflows/flagger.yml`**

```yaml
name: Polymarket Flagger

on:
  schedule:
    - cron: "*/15 * * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: flagger
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Restore state from bot-state branch
        run: |
          git fetch origin bot-state --depth=1 || echo "no state branch yet"
          git show origin/bot-state:state.json > state.json 2>/dev/null || echo "{}" > state.json
          git show origin/bot-state:fighters_cache.json > fighters_cache.json 2>/dev/null || rm -f fighters_cache.json

      - name: Run flagger
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python -m polymarket_flagger.main

      - name: Persist state to bot-state branch
        run: |
          git config user.name "flagger-bot"
          git config user.email "flagger-bot@users.noreply.github.com"
          git fetch origin bot-state --depth=1 || true
          if git show-ref --verify --quiet refs/remotes/origin/bot-state; then
            git worktree add /tmp/state bot-state
          else
            git worktree add --orphan -b bot-state /tmp/state
          fi
          cp state.json /tmp/state/ 2>/dev/null || true
          cp fighters_cache.json /tmp/state/ 2>/dev/null || true
          cd /tmp/state
          git add state.json fighters_cache.json 2>/dev/null || true
          git commit -m "state: update [skip ci]" || echo "no changes"
          git push origin HEAD:bot-state
```

- [ ] **Step 2: Verify the workflow YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/flagger.yml')); print('ok')"`
Expected: prints `ok`. (If PyYAML is not installed, run `pip install pyyaml` first. It is a dev-only check, not a runtime dependency.)

- [ ] **Step 3: Create `README.md`**

````markdown
# Polymarket Flagger

Polls Polymarket every 15 minutes and sends a Telegram alert when a sports outcome
trips one of three flags:

1. **UFC mispricing** - two fighters with similar career records, one priced under 20%.
2. **UFC longshot** - any UFC fighter priced under 15%.
3. **Sports longshot** - any sports outcome under 10%, above a liquidity floor.

Alerts fire only when a *new* market qualifies; still-qualifying markets are shown
with updated percentages for context.

## Setup

1. Create a Telegram bot with `@BotFather` (`/newbot`) and copy the token.
2. Message your new bot once, then get your numeric chat id from `@userinfobot`.
3. In the GitHub repo: Settings -> Secrets and variables -> Actions -> add:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. The workflow in `.github/workflows/flagger.yml` runs every 15 minutes automatically.
   Trigger a manual run from the Actions tab (`Run workflow`) to test.

## Local run

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your token and chat id
python -m polymarket_flagger.main
```

## Tests

```bash
python -m pytest -v
```

## Tuning

All thresholds live in `polymarket_flagger/config.py` (`Config`):
gap percentage, minimum fights, the three price thresholds, the liquidity floor,
and the name-match confidence threshold.

## How state works

The bot remembers what it already alerted on in `state.json`, committed to a
dedicated `bot-state` branch each run so `main` history stays clean. State only
advances after a Telegram message is successfully sent, so a new flag is never
silently dropped.
````

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/flagger.yml README.md
git commit -m "feat: GitHub Actions schedule, state branch, and README"
```

---

## Post-implementation manual verification

After all tasks, before relying on it:

1. Add the two GitHub secrets.
2. From the Actions tab, run the workflow manually (`workflow_dispatch`).
3. Confirm the run is green and, if any market currently qualifies, that a Telegram
   message arrives with correct formatting and a working Polymarket link.
4. Confirm a `bot-state` branch was created with `state.json`.
5. Let it run one more scheduled cycle and confirm you are NOT re-alerted for the
   same markets (dedupe works).
