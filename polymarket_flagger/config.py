import os
from dataclasses import dataclass

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
    flag1_underdog_max: float = 0.20
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
