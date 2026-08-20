import logging
from datetime import datetime, timezone

from .config import Config
from .entry_odds import advise as advise_entry
from .polymarket_client import fetch_markets
from .fighter_store import FighterStore
from .flags import evaluate
from .state import load_state, save_state, diff
from .telegram_notifier import format_message, format_preview, send

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("polymarket_flagger")


def _enrich_entry(items, cfg, advise_fn):
    """Attach best-effort entry-odds advice; a failure never blocks the alert."""
    for it in items:
        try:
            it.entry_detail = advise_fn(cfg, it)
        except Exception as exc:
            log.warning("Entry advice failed for %s: %s", it.key, exc)


def run_cycle(cfg, client_fn, store, now_str, advise_fn=advise_entry):
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

    _enrich_entry(new_items + [it for it, _ in still_items], cfg, advise_fn)
    text = format_message(now_str, new_items, still_items)
    if not send(cfg, text):
        log.error("Send failed; state not advanced so NEW items are retried next cycle.")
        return False

    save_state(cfg.state_path, items)  # advance state only after a successful send
    return True


def run_preview(cfg, client_fn, store, now_str, advise_fn=advise_entry):
    """Send a snapshot of everything currently qualifying. Never reads or writes
    state, so it cannot swallow a pending NEW alert. Always sends, even when
    nothing qualifies, so an explicit preview request is never silent."""
    markets = client_fn(cfg)
    items = evaluate(markets, store, cfg)
    log.info("Preview: %d markets, %d qualifying", len(markets), len(items))
    _enrich_entry(items, cfg, advise_fn)
    return send(cfg, format_preview(now_str, items))


def _load_store(cfg):
    # Fresh cache -> live PoW scrape -> stale cache -> committed seed. Never empty
    # when the seed exists, so Flag 1 always has data even if the scrape is blocked.
    return FighterStore.load(cfg)


def main(argv=None):
    import sys
    preview = "--preview" in (argv if argv is not None else sys.argv[1:])
    cfg = Config.from_env()
    try:
        store = _load_store(cfg)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if preview:
            sent = run_preview(cfg, fetch_markets, store, now_str)
        else:
            sent = run_cycle(cfg, fetch_markets, store, now_str)
        log.info("Cycle done. Message sent: %s", sent)
    except Exception as exc:
        log.exception("Cycle failed: %s", exc)
        return


if __name__ == "__main__":
    main()
