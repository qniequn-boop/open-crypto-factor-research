"""Method-faithful liquidity characteristics from Mercik et al. (2026).

The functions in this module construct characteristics only. They do not
choose a portfolio, evaluate returns, or authorize a factor trial.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


PandasObject = pd.Series | pd.DataFrame


def _positive_ohlc_mask(high: PandasObject, low: PandasObject) -> PandasObject:
    return high.notna() & low.notna() & high.gt(0) & low.gt(0) & high.ge(low)


def corwin_schultz_spread(
    high: PandasObject,
    low: PandasObject,
    *,
    window_days: int = 30,
) -> PandasObject:
    """Return the rolling Corwin-Schultz full spread estimate in decimal units.

    Each value averages all overlapping two-day estimates inside the trailing
    ``window_days`` observations. Negative two-day estimates are set to zero,
    matching the simple estimator used in Corwin and Schultz (2012). Crypto
    trades continuously, so no closed-market overnight adjustment is applied.
    """

    if int(window_days) < 2:
        raise ValueError("window_days_must_be_at_least_two")
    high, low = high.align(low, join="outer")
    valid = _positive_ohlc_mask(high, low)
    log_range = np.log((high / low).where(valid))
    beta = log_range.pow(2).shift(1) + log_range.pow(2)
    two_day_high = high.combine(high.shift(1), np.maximum)
    two_day_low = low.combine(low.shift(1), np.minimum)
    pair_valid = valid & valid.shift(1, fill_value=False)
    gamma = np.log((two_day_high / two_day_low).where(pair_valid)).pow(2)

    denominator = 3.0 - 2.0 * math.sqrt(2.0)
    alpha = (
        (np.sqrt(2.0 * beta) - np.sqrt(beta)) / denominator
        - np.sqrt(gamma / denominator)
    )
    exp_alpha = np.exp(alpha.clip(upper=50.0))
    pair_spread = (2.0 * (exp_alpha - 1.0) / (1.0 + exp_alpha)).clip(lower=0.0)
    pair_spread = pair_spread.where(pair_valid)
    pair_count = int(window_days) - 1
    return pair_spread.rolling(pair_count, min_periods=pair_count).mean()


def abdi_ranaldo_spread(
    high: PandasObject,
    low: PandasObject,
    close: PandasObject,
    *,
    window_days: int = 30,
) -> PandasObject:
    """Return the rolling two-day-corrected Abdi-Ranaldo full spread.

    A pair estimate reported on day ``t`` uses the close from ``t-1`` and the
    high/low mid-ranges from ``t-1`` and ``t``. Consequently the result is
    causal at the end of day ``t``. Negative squared-spread estimates are set
    to zero before square roots and averaging, as in equation (11) of Abdi and
    Ranaldo (2017).
    """

    if int(window_days) < 2:
        raise ValueError("window_days_must_be_at_least_two")
    high, low = high.align(low, join="outer")
    high, close = high.align(close, join="outer")
    low = low.reindex_like(high)
    valid = _positive_ohlc_mask(high, low) & close.notna() & close.gt(0)
    log_high = np.log(high.where(valid))
    log_low = np.log(low.where(valid))
    log_close = np.log(close.where(valid))
    mid_range = (log_high + log_low) / 2.0

    pair_valid = valid & valid.shift(1, fill_value=False)
    prior_close = log_close.shift(1)
    squared_spread = 4.0 * (prior_close - mid_range.shift(1)) * (prior_close - mid_range)
    pair_spread = np.sqrt(squared_spread.clip(lower=0.0)).where(pair_valid)
    pair_count = int(window_days) - 1
    return pair_spread.rolling(pair_count, min_periods=pair_count).mean()


def factor_zoo_bidask_spread(
    high: PandasObject,
    low: PandasObject,
    close: PandasObject,
    *,
    window_days: int = 30,
) -> PandasObject:
    """Average the 30-day Corwin-Schultz and Abdi-Ranaldo estimates."""

    cs = corwin_schultz_spread(high, low, window_days=window_days)
    ar = abdi_ranaldo_spread(high, low, close, window_days=window_days)
    return (cs + ar) / 2.0


def daily_turnover(
    quote_volume: PandasObject,
    market_cap: PandasObject,
    *,
    maximum_ratio: float = 1.0,
) -> PandasObject:
    """Construct daily dollar volume divided by point-in-time market value."""

    quote_volume, market_cap = quote_volume.align(market_cap, join="outer")
    valid = quote_volume.notna() & market_cap.notna() & quote_volume.gt(0) & market_cap.gt(0)
    turnover = (quote_volume / market_cap).where(valid)
    return turnover.where(turnover.le(float(maximum_ratio)))


def turnover_volatility(
    turnover: PandasObject,
    *,
    window_days: int = 30,
) -> PandasObject:
    """Residual standard deviation from a 30-day intercept-only regression."""

    if int(window_days) < 2:
        raise ValueError("window_days_must_be_at_least_two")
    return turnover.rolling(int(window_days), min_periods=int(window_days)).std(ddof=1)


def aggregate_hourly_ohlcv_to_daily(
    frame: pd.DataFrame,
    *,
    required_bars_per_day: int = 24,
) -> pd.DataFrame:
    """Aggregate complete UTC hourly bars to daily OHLC and quote volume."""

    required = {"open", "high", "low", "close", "vol_quote"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("missing_ohlcv_columns:" + ",".join(missing))
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("ohlcv_index_must_be_datetime")
    work = frame.sort_index().copy()
    if work.index.tz is None:
        work.index = work.index.tz_localize("UTC")
    else:
        work.index = work.index.tz_convert("UTC")
    day = work.index.floor("D")
    daily = work.groupby(day).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        vol_quote=("vol_quote", "sum"),
    )
    counts = work["close"].groupby(day).count()
    complete = counts.ge(int(required_bars_per_day))
    return daily.where(complete.reindex(daily.index).fillna(False), np.nan)
