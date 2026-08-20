import logging

import requests

from polymarket_flagger.config import Config
from polymarket_flagger.models import (
    QualifyingItem, FLAG_MISPRICING, FLAG_UFC_LONGSHOT, FLAG_SPORTS_LONGSHOT,
)
from polymarket_flagger.telegram_notifier import format_message, send


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


def test_longshot_shows_record_detail_too():
    # Record line renders for any item that has one, not only mispricing.
    item = _item(flags=[FLAG_UFC_LONGSHOT], record_detail="A 25-1 (96%) vs B 5-10 (33%)")
    msg = format_message("t", [item], [])
    assert "A 25-1 (96%) vs B 5-10 (33%)" in msg


def test_ufc_longshot_label_says_10_pct():
    msg = format_message("t", [_item(flags=[FLAG_UFC_LONGSHOT])], [])
    assert "UFC longshot &lt;10%" in msg


def test_empty_still_section_omitted():
    msg = format_message("t", [_item()], [])
    assert "STILL QUALIFYING" not in msg


def test_title_and_outcome_are_html_escaped():
    item = _item(title="A <script> & B", flagged_outcome="<X> & Y")
    msg = format_message("t", [item], [])
    assert "<script>" not in msg
    assert "A &lt;script&gt; &amp; B" in msg
    assert "&lt;X&gt; &amp; Y" in msg


_SECRET = "123456789:AA-super-secret-token"


class _Resp:
    status_code = 401

    def raise_for_status(self):
        raise requests.HTTPError(
            f"401 Client Error for url: https://api.telegram.org/bot{_SECRET}/sendMessage"
        )


def test_send_http_error_does_not_leak_token(monkeypatch, caplog):
    cfg = Config(telegram_token=_SECRET, telegram_chat_id="42")
    monkeypatch.setattr("polymarket_flagger.telegram_notifier.requests.post",
                        lambda *a, **k: _Resp())
    with caplog.at_level(logging.ERROR):
        assert send(cfg, "hi") is False
    assert _SECRET not in caplog.text
    assert "HTTP 401" in caplog.text


def test_send_connection_error_scrubs_token(monkeypatch, caplog):
    cfg = Config(telegram_token=_SECRET, telegram_chat_id="42")

    def _raise(*a, **k):
        raise requests.ConnectionError(
            f"Failed to connect to https://api.telegram.org/bot{_SECRET}/sendMessage"
        )

    monkeypatch.setattr("polymarket_flagger.telegram_notifier.requests.post", _raise)
    with caplog.at_level(logging.ERROR):
        assert send(cfg, "hi") is False
    assert _SECRET not in caplog.text
