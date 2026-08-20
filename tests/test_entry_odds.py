from polymarket_flagger.entry_odds import (
    EntryAdvice, compute_entry, format_entry, normalize_trades,
)

NOW = 1_787_260_000  # arbitrary fixed "now" (unix seconds)
HOUR = 3600


def _trade(ts, price, size, outcome="B"):
    return {"timestamp": ts, "price": price, "size": size, "outcome": outcome}


def _history(prices, end_ts=NOW, step=HOUR):
    """Hourly midpoint series ending at end_ts, oldest first."""
    start = end_ts - (len(prices) - 1) * step
    return [{"t": start + i * step, "p": p} for i, p in enumerate(prices)]


def test_normalize_trades_converts_complement_outcome():
    trades = [
        _trade(NOW, 0.12, 100.0, outcome="B"),
        _trade(NOW, 0.90, 50.0, outcome="A"),   # complement: counts as B at 0.10
        _trade(NOW, 0.12, 10.0, outcome="C"),   # unknown outcome: dropped
    ]
    norm = normalize_trades(trades, flagged_outcome="B", other_outcome="A")
    assert [(t[1], t[2]) for t in norm] == [(0.12, 100.0), (0.10, 50.0)]


def test_vwap_math():
    # 24h trades: 100 @ 0.10 and 100 @ 0.14 -> VWAP 0.12.
    trades = [
        _trade(NOW - HOUR, 0.10, 100.0),
        _trade(NOW - 2 * HOUR, 0.14, 100.0),
        # 7d-only trade pulls the 7d VWAP up.
        _trade(NOW - 3 * 24 * HOUR, 0.20, 200.0),
    ]
    adv = compute_entry(trades, _history([0.09, 0.16, 0.12]), now_price=0.12,
                        flagged_outcome="B", other_outcome="A", now_ts=NOW)
    assert round(adv.vwap24, 4) == 0.12
    assert round(adv.vwap7d, 4) == 0.16
    assert adv.range7d == (0.09, 0.16)


def test_single_trade_still_produces_vwap():
    # Thin markets (prelim fights) must still get the line.
    trades = [_trade(NOW - HOUR, 0.11, 10.0)]
    adv = compute_entry(trades, _history([0.10, 0.12]), now_price=0.12,
                        flagged_outcome="B", other_outcome="A", now_ts=NOW)
    assert round(adv.vwap24, 4) == 0.11
    assert round(adv.vwap7d, 4) == 0.11


def test_no_24h_trades_leaves_vwap24_none():
    trades = [_trade(NOW - 3 * 24 * HOUR, 0.14, 100.0)]
    adv = compute_entry(trades, _history([0.10, 0.12]), now_price=0.12,
                        flagged_outcome="B", other_outcome="A", now_ts=NOW)
    assert adv.vwap24 is None
    assert round(adv.vwap7d, 4) == 0.14


def test_no_history_omits_range():
    trades = [_trade(NOW - HOUR, 0.11, 10.0)]
    adv = compute_entry(trades, [], now_price=0.12,
                        flagged_outcome="B", other_outcome="A", now_ts=NOW)
    assert adv.range7d is None
    assert round(adv.vwap24, 4) == 0.11


def test_no_data_at_all_returns_none():
    assert compute_entry([], [], now_price=0.12,
                         flagged_outcome="B", other_outcome="A", now_ts=NOW) is None


def test_stale_history_outside_week_is_ignored():
    trades = [_trade(NOW - HOUR, 0.11, 10.0)]
    old = _history([0.30, 0.40], end_ts=NOW - 8 * 24 * HOUR)
    adv = compute_entry(trades, old, now_price=0.12,
                        flagged_outcome="B", other_outcome="A", now_ts=NOW)
    assert adv.range7d is None


def test_format_entry_full_line():
    adv = EntryAdvice(now_price=0.12, vwap24=0.135, vwap7d=0.142, range7d=(0.09, 0.16))
    assert format_entry(adv) == "now 12% · VWAP 13.5% (24h) / 14.2% (7d) · 7d range 9-16%"


def test_format_entry_partial_data():
    adv = EntryAdvice(now_price=0.12, vwap24=None, vwap7d=0.14, range7d=None)
    assert format_entry(adv) == "now 12% · VWAP n/a (24h) / 14% (7d)"
