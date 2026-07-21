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
