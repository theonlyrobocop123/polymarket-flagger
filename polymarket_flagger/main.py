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
