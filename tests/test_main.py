from polymarket_flagger.config import Config
from polymarket_flagger.models import Market
from polymarket_flagger import main as main_mod


class FakeStore:
    def __init__(self, mapping): self.mapping = mapping
    def lookup(self, name): return self.mapping.get(name)


def _ufc_longshot_market():
    return Market(id="m1", title="A vs. B", outcomes=["A", "B"], prices=[0.92, 0.08],
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


def test_preview_sends_all_current_items_without_touching_state(tmp_path, monkeypatch):
    # Preview mode: snapshot of everything currently qualifying, no dedupe, no state writes.
    cfg = Config(state_path=str(tmp_path / "state.json"))
    sent = {}

    def fake_send(c, text):
        sent["text"] = text
        return True

    monkeypatch.setattr(main_mod, "send", fake_send)
    assert main_mod.run_preview(cfg, lambda c: [_ufc_longshot_market()], FakeStore({}), "now") is True
    assert "PREVIEW" in sent["text"]
    assert "A vs. B" in sent["text"]
    assert not (tmp_path / "state.json").exists()  # state untouched

    # A normal cycle afterwards still treats the item as NEW.
    sent.clear()
    assert main_mod.run_cycle(cfg, lambda c: [_ufc_longshot_market()], FakeStore({}), "now") is True
    assert "NEW (1)" in sent["text"]


def test_preview_sends_even_when_nothing_qualifies(tmp_path, monkeypatch):
    # An explicit preview request always answers, so silence is never ambiguous.
    cfg = Config(state_path=str(tmp_path / "state.json"))
    sent = {}

    def fake_send(c, text):
        sent["text"] = text
        return True

    monkeypatch.setattr(main_mod, "send", fake_send)
    assert main_mod.run_preview(cfg, lambda c: [], FakeStore({}), "now") is True
    assert "0" in sent["text"]


def test_run_cycle_does_not_save_when_send_fails(tmp_path, monkeypatch):
    cfg = Config(state_path=str(tmp_path / "state.json"))
    monkeypatch.setattr(main_mod, "send", lambda c, text: False)
    result = main_mod.run_cycle(cfg, lambda c: [_ufc_longshot_market()], FakeStore({}), "now")
    assert result is False
    # state NOT advanced, so item is still NEW next time (with a working send)
    calls = {}
    monkeypatch.setattr(main_mod, "send", lambda c, text: calls.setdefault("t", text) or True)
    assert main_mod.run_cycle(cfg, lambda c: [_ufc_longshot_market()], FakeStore({}), "now") is True
