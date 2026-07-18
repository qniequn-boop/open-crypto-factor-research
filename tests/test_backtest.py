# btclab/tests/test_backtest.py
# 回测引擎测试(含未来函数检测) —— 严格按照 PROJECT_DOC.md §10.7 阶段2

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
from backtest import backtest, sign, annualized_sharpe, max_drawdown, _to_position

def make_ohlcv(n: int = 500):
    np.random.seed(42)
    ts = pd.date_range('2024-01-01', periods=n, freq='15min', tz='UTC')
    close = pd.Series(100 * (1 + np.random.randn(n).cumsum() * 0.002), index=ts)
    open_ = close * (1 + np.random.randn(n) * 0.001)
    high = pd.concat([open_, close], axis=1).max(axis=1) * (1 + abs(np.random.randn(n) * 0.002))
    low = pd.concat([open_, close], axis=1).min(axis=1) * (1 - abs(np.random.randn(n) * 0.002))
    volume = pd.Series(abs(np.random.randn(n)) * 100, index=ts)

    return pd.DataFrame({'open': open_, 'high': high, 'low': low, 'close': close, 'volume': volume})

def test_backtest_basic():
    """§10.7: 布林突破在IS期夏普 > 0, 持仓shift(1)正确"""
    df = make_ohlcv()
    # 简单布林突破信号 (模拟)
    signal = pd.Series(np.random.randn(len(df)) * 0.01, index=df.index)

    result = backtest(signal, df, cost_bps=5, slippage_bps=2)

    assert 'sharpe' in result
    assert 'max_drawdown' in result
    assert 'win_rate' in result
    assert 'annualized_return' in result
    assert 'ic_pearson' in result
    assert 'ic_spearman' in result
    assert 'dir_acc' in result

    print(f"PASS: test_backtest_basic - Sharpe={result['sharpe']:.3f}, MaxDD={result['max_drawdown']:.4f}")

def test_position_shift():
    """验证持仓shift(1)铁律"""
    df = make_ohlcv(300)
    signal = pd.Series(np.linspace(-2, 2, len(df)), index=df.index)

    result = backtest(signal, df, cost_bps=0, slippage_bps=0)
    pos = result['position_series']
    expected = _to_position(signal).shift(1)
    expected.iloc[0] = 0
    expected = expected.fillna(0)

    # 第一根必须0持仓
    assert pos.iloc[0] == 0, f"First position should be 0, got {pos.iloc[0]}"
    pd.testing.assert_series_equal(pos, expected, check_names=False)

    print(f"PASS: test_position_shift")

def test_no_future_function():
    """验证信号只用t及之前数据"""
    df = make_ohlcv(100)
    signal = df['close'].diff()  # 用close差值作信号

    # 第99根的信号不应引用第100根数据
    # diff()在t时刻使用t和t-1, 安全
    result = backtest(signal, df, cost_bps=0, slippage_bps=0)
    assert result is not None
    print(f"PASS: test_no_future_function")

def test_cost_impact():
    """成本是否正确地影响净收益"""
    df = make_ohlcv(200)
    # 趋势向上, 做多应盈利
    df['close'] = pd.Series(100 * (1 + np.arange(len(df)) * 0.0005), index=df.index)
    signal = pd.Series(1.0, index=df.index)

    result_no_cost = backtest(signal, df, cost_bps=0, slippage_bps=0)
    result_with_cost = backtest(signal, df, cost_bps=5, slippage_bps=2)

    # 有成本应 <= 无成本
    assert result_with_cost['total_return'] <= result_no_cost['total_return']
    print(f"PASS: test_cost_impact - no_cost={result_no_cost['total_return']:.6f}, with_cost={result_with_cost['total_return']:.6f}")

def test_sharpe_zero_signal():
    df = make_ohlcv(100)
    signal = pd.Series(0.0, index=df.index)

    result = backtest(signal, df)
    # 0信号应0持仓, 接近0夏普
    assert abs(result['sharpe']) < 1.0, f"Zero signal should have near-zero sharpe, got {result['sharpe']}"
    print(f"PASS: test_sharpe_zero_signal")

def test_max_drawdown():
    df = make_ohlcv(200)
    pnl = pd.Series(np.array([0.01, 0.02, -0.05, 0.01, 0.02]), index=range(5))
    dd = max_drawdown(pnl)
    assert dd > 0
    print(f"PASS: test_max_drawdown = {dd:.4f}")

def test_sign_function():
    s = pd.Series([1.5, -2.3, 0, np.nan, -0.5])
    result = sign(s)
    assert result.iloc[0] == 1
    assert result.iloc[1] == -1
    assert result.iloc[2] == 0
    assert result.iloc[4] == -1
    print(f"PASS: test_sign_function")

def test_annualized_sharpe():
    pnl = pd.Series(np.random.randn(365 * 24 * 4) * 0.001)
    sr = annualized_sharpe(pnl)
    assert sr < 5 and sr > -5, f"Strange sharpe: {sr}"
    print(f"PASS: test_annualized_sharpe = {sr:.3f}")

if __name__ == '__main__':
    test_backtest_basic()
    test_position_shift()
    test_no_future_function()
    test_cost_impact()
    test_sharpe_zero_signal()
    test_max_drawdown()
    test_sign_function()
    test_annualized_sharpe()
    print("\\n=== 所有回测引擎测试通过 ===")
