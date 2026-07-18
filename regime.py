# -*- coding: utf-8 -*-
"""Regime detection: ATR ratio + ADX to classify bars as trending/ranging."""
import pandas as pd
import numpy as np

def classify_regime(ohlcv: pd.DataFrame, atr_period: int = 14, adx_period: int = 14) -> pd.Series:
    """0=ranging(震荡), 1=trending(趋势)."""
    high, low, close = ohlcv['high'], ohlcv['low'], ohlcv['close']
    # ATR
    tr = pd.concat([(high-low), (high-close.shift(1)).abs(), (low-close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=atr_period, adjust=False).mean()
    # ATR ratio: current ATR vs its own MA — high = volatile/expanding
    atr_ratio = atr / atr.rolling(50, min_periods=20).mean()
    # ADX
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr_ = tr.ewm(span=adx_period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=close.index).ewm(span=adx_period, adjust=False).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=close.index).ewm(span=adx_period, adjust=False).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(span=adx_period, adjust=False).mean().fillna(0)
    # Trending when ADX > 25 and ATR expanding
    trending = ((adx > 25) & (atr_ratio > 1.0)).astype(int)
    return trending.fillna(0)

def regime_split_backtest(signal, ohlcv, regime, backtest_fn, **kwargs):
    """Backtest signal separately in trending and ranging regimes."""
    full = backtest_fn(signal, ohlcv, **kwargs)
    trending_mask = regime == 1
    ranging_mask = regime == 0
    if trending_mask.sum() > 100:
        trend_result = backtest_fn(signal[trending_mask], ohlcv[trending_mask], **kwargs)
    else:
        trend_result = None
    if ranging_mask.sum() > 100:
        range_result = backtest_fn(signal[ranging_mask], ohlcv[ranging_mask], **kwargs)
    else:
        range_result = None
    return {'full': full, 'trending': trend_result, 'ranging': range_result,
            'trending_pct': float(trending_mask.mean()),
            'ranging_pct': float(ranging_mask.mean())}
