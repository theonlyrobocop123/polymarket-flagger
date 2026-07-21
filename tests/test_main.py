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
