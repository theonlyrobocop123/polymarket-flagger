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
