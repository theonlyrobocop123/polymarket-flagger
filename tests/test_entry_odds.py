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


def _flat_history(price=0.12, hours=169):
    return _history([price] * hours)


def _enough_trades(price=0.12, n=6, outcome="B"):
    return [_trade(NOW - i * 600, price, 100.0, outcome) for i in range(n)]


def test_normalize_trades_converts_complement_outcome():
    trades = [
        _trade(NOW, 0.12, 100.0, outcome="B"),
        _trade(NOW, 0.90, 50.0, outcome="A"),   # complement: counts as B at 0.10
        _trade(NOW, 0.12, 10.0, outcome="C"),   # unknown outcome: dropped
    ]
    norm = normalize_trades(trades, flagged_outcome="B", other_outcome="A")
    assert [(t[1], t[2]) for t in norm] == [(0.12, 100.0), (0.10, 50.0)]


def test_vwap_math_via_compute():
    # 24h trades: 100 @ 0.10 and 100 @ 0.14 -> VWAP 0.12.
    trades = [
        _trade(NOW - HOUR, 0.10, 100.0),
        _trade(NOW - 2 * HOUR, 0.14, 100.0),
        _trade(NOW - 3 * HOUR, 0.12, 100.0),
        _trade(NOW - 4 * HOUR, 0.12, 100.0),
        _trade(NOW - 5 * HOUR, 0.12, 100.0),
        # 7d-only trade pulls the 7d VWAP up.
        _trade(NOW - 3 * 24 * HOUR, 0.20, 500.0),
    ]
    adv = compute_entry(trades, _flat_history(), now_price=0.12,
                        flagged_outcome="B", other_outcome="A", now_ts=NOW)
    assert round(adv.vwap24, 4) == 0.12
    assert adv.vwap7d > adv.vwap24


def test_rising_trend_enter_now():
    # Steadily climbing over the last day: EMA8 > EMA21 and +2pts in 24h.
    prices = [0.10] * 140 + [0.10 + 0.004 * i for i in range(29)]
    adv = compute_entry(_enough_trades(), _history(prices), now_price=0.14,
                        flagged_outcome="B", other_outcome="A", now_ts=NOW)
    assert adv.trend == "rising"
    assert adv.action == "enter now"
    assert adv.limit_price is None


def test_flat_trend_below_vwap_enters_now():
    trades = [_trade(NOW - i * HOUR, 0.14, 100.0) for i in range(1, 7)]  # vwap24 0.14
    adv = compute_entry(trades, _flat_history(0.12), now_price=0.12,
                        flagged_outcome="B", other_outcome="A", now_ts=NOW)
    assert adv.trend == "flat"
    assert adv.action == "enter now"


def test_flat_trend_above_vwap_limits_at_vwap():
    trades = [_trade(NOW - i * HOUR, 0.10, 100.0) for i in range(1, 7)]  # vwap24 0.10
    adv = compute_entry(trades, _flat_history(0.12), now_price=0.12,
                        flagged_outcome="B", other_outcome="A", now_ts=NOW)
    assert adv.trend == "flat"
    assert adv.action == "limit"
    assert round(adv.limit_price, 4) == 0.10


def test_falling_trend_limits_at_24h_low():
    # Steadily dropping over the last day, low of the last 24h is the final price.
    prices = [0.16] * 140 + [0.16 - 0.002 * i for i in range(29)]
    adv = compute_entry(_enough_trades(), _history(prices), now_price=0.104,
                        flagged_outcome="B", other_outcome="A", now_ts=NOW)
    assert adv.trend == "falling"
    assert adv.action == "limit"
    assert round(adv.limit_price, 4) == round(0.16 - 0.002 * 28, 4)


def test_fewer_than_five_trades_in_24h_returns_none():
    trades = [_trade(NOW - HOUR, 0.12, 100.0)] * 4 + [_trade(NOW - 3 * 24 * HOUR, 0.12, 100.0)]
    assert compute_entry(trades, _flat_history(), now_price=0.12,
                         flagged_outcome="B", other_outcome="A", now_ts=NOW) is None


def test_short_history_returns_none():
    assert compute_entry(_enough_trades(), _history([0.12] * 10), now_price=0.12,
                         flagged_outcome="B", other_outcome="A", now_ts=NOW) is None


def test_format_entry_line():
    adv = EntryAdvice(now_price=0.12, vwap24=0.135, vwap7d=0.142,
                      low24=0.11, range7d=(0.09, 0.16),
                      trend="falling", action="limit", limit_price=0.11)
    line = format_entry(adv)
    assert line == "now 12% · VWAP 13.5% (24h) / 14.2% (7d) · 7d range 9-16% · trend ↓ → limit @ 11%"


def test_format_entry_enter_now():
    adv = EntryAdvice(now_price=0.12, vwap24=0.13, vwap7d=0.14,
                      low24=0.11, range7d=(0.09, 0.16),
                      trend="rising", action="enter now", limit_price=None)
    line = format_entry(adv)
    assert line.endswith("trend ↑ → enter now")
