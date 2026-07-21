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
