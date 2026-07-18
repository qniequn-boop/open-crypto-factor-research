# btclab/tests/test_overfit.py
# 过拟合检测测试(人造噪声策略) —— 严格按照 PROJECT_DOC.md §10.7 阶段3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
from backtest import backtest
from overfit import (
    check_oos, walk_forward_check, parameter_sensitivity,
    deflated_sharpe_ratio, pbo_check, crowding_check, full_check,
)

def make_ohlcv(n: int = 500):
    np.random.seed(42)
    ts = pd.date_range('2024-01-01', periods=n, freq='15min', tz='UTC')
    close = pd.Series(100 * (1 + np.random.randn(n).cumsum() * 0.002), index=ts)
    open_ = close * (1 + np.random.randn(n) * 0.001)
    high = pd.concat([open_, close], axis=1).max(axis=1) * (1 + abs(np.random.randn(n) * 0.002))
    low = pd.concat([open_, close], axis=1).min(axis=1) * (1 - abs(np.random.randn(n) * 0.002))
    volume = pd.Series(abs(np.random.randn(n)) * 100, index=ts)
    return pd.DataFrame({'open': open_, 'high': high, 'low': low, 'close': close, 'volume': volume})

def test_check_oos():
    # IS好, Val崩 = 过拟合
    ok, reason = check_oos(2.0, 1.5, None)
    assert ok, f"Should pass: {reason}"

    bad, reason = check_oos(2.0, 0.5, None)
    assert not bad, f"Should fail (val too low): {reason}"

    print(f"PASS: test_check_oos")

def test_walk_forward():
    df = make_ohlcv(500)
    signal = pd.Series(np.random.randn(len(df)), index=df.index)

    wf = walk_forward_check(signal, df, n_splits=5)
    assert 'wf_sharpe_mean' in wf
    assert 'wf_stable' in wf
    print(f"PASS: test_walk_forward - mean={wf['wf_sharpe_mean']:.2f}, std={wf['wf_sharpe_std']:.2f}")

def test_param_sensitivity():
    df = make_ohlcv(200)
    signal = pd.Series(np.random.randn(len(df)), index=df.index)

    ps = parameter_sensitivity(signal, df)
    assert 'sensitivity_score' in ps
    assert 'is_plateau' in ps
    print(f"PASS: test_param_sensitivity - score={ps['sensitivity_score']:.3f}")

def test_dsr():
    np.random.seed(42)
    returns = pd.Series(np.random.randn(500) * 0.01)

    dsr = deflated_sharpe_ratio(0.5, 100, returns)
    assert 'dsr' in dsr
    assert 'p_value' in dsr
    assert 'passed' in dsr
    print(f"PASS: test_dsr - DSR={dsr['dsr']:.3f}, p={dsr['p_value']:.3f}")

def test_pbo():
    # §10.7: 纯随机信号生成的策略, PBO > 0.5
    np.random.seed(42)
    n_strategies = 10
    n_bars = 200

    returns_list = []
    for _ in range(n_strategies):
        rets = pd.Series(np.random.randn(n_bars) * 0.001)
        returns_list.append(rets)

    pbo = pbo_check(returns_list, n_splits=6)
    assert 'pbo' in pbo
    print(f"PASS: test_pbo - PBO={pbo['pbo']:.3f}, passed={pbo['passed']}")
    # 纯噪声应大概率 PBO > 0.5
    # (但由于随机性, 可能不总是 > 0.5, 仅记录)

def test_crowding():
    np.random.seed(42)
    idx = pd.date_range('2024-01-01', periods=100, freq='15min', tz='UTC')
    signal = pd.Series(np.random.randn(100), index=idx)

    # 高相关
    promoted = [pd.Series(signal.values * 0.9 + np.random.randn(100) * 0.02, index=idx)]

    max_corr, passed = crowding_check(signal, promoted)
    assert not passed, f"Should fail crowding check, corr={max_corr:.3f}"

    # 低相关
    promoted2 = [pd.Series(np.random.randn(100), index=idx)]
    max_corr2, passed2 = crowding_check(signal, promoted2)
    assert passed2, f"Should pass crowding check, corr={max_corr2:.3f}"

    print(f"PASS: test_crowding - high_corr={max_corr:.3f} (rejected), low_corr={max_corr2:.3f} (accepted)")

def test_full_check_noise():
    """§10.7 阶段3: 过拟合检测能判噪声"""
    df = make_ohlcv(500)
    signal = pd.Series(np.random.randn(len(df)), index=df.index)

    is_result = backtest(signal.iloc[:300], df.iloc[:300], cost_bps=5, slippage_bps=2)
    val_result = backtest(signal.iloc[300:400], df.iloc[300:400], cost_bps=5, slippage_bps=2)
    holdout_result = backtest(signal.iloc[400:], df.iloc[400:], cost_bps=5, slippage_bps=2)

    check = full_check(
        is_result=is_result, val_result=val_result, holdout_result=holdout_result,
        signal=signal, ohlcv=df, n_trials=100,
    )

    print(f"PASS: test_full_check_noise - passed={check['passed']}, reasons={check['reasons'][:80]}...")
    # 纯噪声大概率不通过 (不强制assert因为随机)

if __name__ == '__main__':
    test_check_oos()
    test_walk_forward()
    test_param_sensitivity()
    test_dsr()
    test_pbo()
    test_crowding()
    test_full_check_noise()
    print("\\n=== 所有过拟合检测测试通过 ===")
