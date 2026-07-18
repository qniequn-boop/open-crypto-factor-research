import math

import numpy as np
import pandas as pd
import pytest

import crypto_factor_zoo_method as method


def _index(days: int) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-01", periods=days, freq="D", tz="UTC")


def test_corwin_schultz_matches_published_closed_form_and_needs_full_window():
    index = _index(30)
    high = pd.Series(np.linspace(100.0, 103.0, len(index)) * 1.01, index=index)
    low = pd.Series(np.linspace(100.0, 103.0, len(index)) * 0.99, index=index)
    actual = method.corwin_schultz_spread(high, low, window_days=30)

    beta = math.log(high.iloc[-2] / low.iloc[-2]) ** 2 + math.log(high.iloc[-1] / low.iloc[-1]) ** 2
    gamma = math.log(max(high.iloc[-2:]) / min(low.iloc[-2:])) ** 2
    denominator = 3.0 - 2.0 * math.sqrt(2.0)
    alpha = (math.sqrt(2.0 * beta) - math.sqrt(beta)) / denominator - math.sqrt(gamma / denominator)
    final_pair = max(2.0 * (math.exp(alpha) - 1.0) / (1.0 + math.exp(alpha)), 0.0)

    assert actual.iloc[:-1].isna().all()
    assert actual.iloc[-1] >= 0.0
    pair_values = method.corwin_schultz_spread(high, low, window_days=2)
    assert pair_values.iloc[-1] == pytest.approx(final_pair)


def test_abdi_ranaldo_matches_two_day_corrected_equation_and_is_causal():
    index = _index(31)
    high = pd.Series(101.0 + np.arange(len(index)) * 0.2, index=index)
    low = pd.Series(99.0 + np.arange(len(index)) * 0.2, index=index)
    close = pd.Series(100.6 + np.arange(len(index)) * 0.2, index=index)

    actual = method.abdi_ranaldo_spread(high, low, close, window_days=2)
    eta_prev = (math.log(high.iloc[-2]) + math.log(low.iloc[-2])) / 2.0
    eta_now = (math.log(high.iloc[-1]) + math.log(low.iloc[-1])) / 2.0
    c_prev = math.log(close.iloc[-2])
    expected = math.sqrt(max(4.0 * (c_prev - eta_prev) * (c_prev - eta_now), 0.0))
    assert actual.iloc[-1] == pytest.approx(expected)

    baseline = method.abdi_ranaldo_spread(high, low, close, window_days=30)
    changed_high = high.copy()
    changed_high.iloc[-1] *= 2.0
    changed = method.abdi_ranaldo_spread(changed_high, low, close, window_days=30)
    pd.testing.assert_series_equal(baseline.iloc[:-1], changed.iloc[:-1])


def test_factor_zoo_bidask_is_simple_average_of_source_estimators():
    index = _index(35)
    base = pd.Series(np.linspace(10.0, 12.0, len(index)), index=index)
    high = base * 1.02
    low = base * 0.98
    close = base * 1.005
    combined = method.factor_zoo_bidask_spread(high, low, close)
    expected = (
        method.corwin_schultz_spread(high, low)
        + method.abdi_ranaldo_spread(high, low, close)
    ) / 2.0
    pd.testing.assert_series_equal(combined, expected)


def test_turnover_and_turnover_volatility_apply_source_filter():
    index = _index(32)
    volume = pd.Series([10.0] * 32, index=index)
    market_cap = pd.Series([100.0] * 32, index=index)
    volume.iloc[10] = 200.0
    turnover = method.daily_turnover(volume, market_cap)
    volatility = method.turnover_volatility(turnover, window_days=30)
    assert turnover.iloc[10] != turnover.iloc[10]
    assert volatility.isna().all()

    volume.iloc[10] = 10.0
    turnover = method.daily_turnover(volume, market_cap)
    volatility = method.turnover_volatility(turnover, window_days=30)
    assert volatility.iloc[-1] == pytest.approx(0.0)


def test_hourly_aggregation_rejects_incomplete_utc_day():
    index = pd.date_range("2026-01-01", periods=47, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": np.arange(47) + 1.0,
            "high": np.arange(47) + 2.0,
            "low": np.arange(47) + 0.5,
            "close": np.arange(47) + 1.5,
            "vol_quote": 10.0,
        },
        index=index,
    )
    daily = method.aggregate_hourly_ohlcv_to_daily(frame)
    assert daily.iloc[0].notna().all()
    assert daily.iloc[1].isna().all()
