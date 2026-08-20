import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
    game_start_time: str = ""  # Gamma gameStartTime, e.g. "2026-08-22 21:00:00+00"
    condition_id: str = ""     # Gamma conditionId, keys the trade-history API
    clob_token_ids: list = field(default_factory=list)  # aligned with outcomes


def parse_game_start(raw) -> "datetime | None":
    """Parse Gamma's gameStartTime into an aware UTC datetime, or None.

    Gamma sends offsets like "+00" which datetime.fromisoformat rejects on the
    Pythons we target, so hour-only offsets are widened to "+00:00". Naive
    timestamps are assumed UTC.
    """
    if not raw or not isinstance(raw, str):
        return None
    text = re.sub(r"([+-]\d{2})$", r"\1:00", raw.strip().replace("Z", "+00:00"))
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
    record_detail: str = ""    # W-L + win rate for both fighters (UFC markets)
    condition_id: str = ""
    clob_token_id: str = ""    # token of the flagged outcome
    other_outcome: str = ""    # the opposing outcome in a 2-way market
    entry_detail: str = ""     # entry-odds advice line, best-effort

    @property
    def key(self) -> str:
        return f"{self.market_id}|{self.flagged_outcome}"
