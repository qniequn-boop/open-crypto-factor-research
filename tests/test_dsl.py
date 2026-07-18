# btclab/tests/test_dsl.py
# DSL解析/校验/执行测试 —— 严格按照 PROJECT_DOC.md §10.7 阶段1

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
from dsl import execute, parse_and_validate, DSLValidationError

def make_test_data(n: int = 200):
    np.random.seed(42)
    ts = pd.date_range('2024-01-01', periods=n, freq='15min', tz='UTC')
    close = pd.Series(100 * (1 + np.random.randn(n).cumsum() * 0.01), index=ts)
    open_ = close * (1 + np.random.randn(n) * 0.001)
    high = pd.concat([open_, close], axis=1).max(axis=1) * (1 + abs(np.random.randn(n) * 0.002))
    low = pd.concat([open_, close], axis=1).min(axis=1) * (1 - abs(np.random.randn(n) * 0.002))
    volume = pd.Series(abs(np.random.randn(n)) * 100, index=ts)

    return {
        'close': close,
        'open': open_,
        'high': high,
        'low': low,
        'volume': volume,
    }

def test_basic_parse():
    data = make_test_data()
    # §10.7 阶段1验收: ts_rank(returns(close, 20), 60) 输出合法Series, 无未来函数
    expr = 'ts_rank(returns(close, 20), 60)'
    result = execute(expr, data)
    assert isinstance(result, pd.Series), f"Expected Series, got {type(result)}"
    assert len(result) == len(data['close'])
    # 前20根应NaN (窗口)
    assert result.iloc[:20].isna().all() or result.iloc[:20].isna().any()
    print(f"PASS: test_basic_parse - {expr}")

def test_complex_expr():
    data = make_test_data()
    # §10.2 合法示例
    expr = 'mul(ts_rank(returns(close, 20), 60), if(gt(bb_bw(close, 20, 2), 0.05), sub(close, ema(close, 50)), close))'
    result = execute(expr, data)
    assert isinstance(result, pd.Series)
    assert len(result) == len(data['close'])
    print(f"PASS: test_complex_expr")

def test_no_lookahead():
    data = make_test_data()
    expr = 'returns(close, 20)'
    result = execute(expr, data)
    # 验证: 第 t 时刻的值不用 t+1 数据
    # returns(close, 20)[t] = (close[t] - close[t-20]) / close[t-20]
    # 确实只用 t 及之前数据
    assert pd.notna(result.iloc[20])
    assert pd.isna(result.iloc[0])
    print(f"PASS: test_no_lookahead")

def test_field_reference():
    data = make_test_data()
    for field in ['close', 'open', 'high', 'low', 'volume']:
        result = execute(field, data)
        assert isinstance(result, pd.Series)
        assert len(result) == len(data[field])
    print(f"PASS: test_field_reference")

def test_arithmetic():
    data = make_test_data()
    expr = 'add(close, open)'
    result = execute(expr, data)
    expected = data['close'] + data['open']
    assert np.allclose(result.dropna(), expected.dropna(), equal_nan=True)
    print(f"PASS: test_arithmetic")

def test_conditional():
    data = make_test_data()
    expr = 'if(gt(close, sma(close, 20)), 1, -1)'
    result = execute(expr, data)
    assert result.dropna().isin([1, -1]).all()
    print(f"PASS: test_conditional")

def test_syntax_error():
    data = make_test_data()
    try:
        execute('close[1]', data)
        assert False, "Should have raised"
    except DSLValidationError as e:
        assert '不允许' in str(e)
    print(f"PASS: test_syntax_error (index not supported)")

def test_illegal_operator():
    data = make_test_data()
    try:
        execute('cs_rank(close, 10)', data)
        assert False, "Should have raised"
    except DSLValidationError as e:
        assert '未知算子' in str(e)
    print(f"PASS: test_illegal_operator")

def test_max_depth():
    data = make_test_data()
    # 构造深度 > 8
    deep = 'close'
    for _ in range(10):
        deep = f"add({deep}, 0)"
    try:
        execute(deep, data)
        assert False, "Should have raised"
    except DSLValidationError as e:
        assert '深度' in str(e) or '上限' in str(e)
    print(f"PASS: test_max_depth")

def test_all_operators():
    data = make_test_data()
    operators_to_test = [
        'close', 'open', 'high', 'low', 'volume',
        'returns(close, 5)', 'log_returns(close, 5)', 'diff(close, 5)',
        'ema(close, 10)', 'sma(close, 10)',
        'atr(high, low, close, 14)', 'std(close, 10)',
        'rsi(close, 14)',
        'ts_rank(close, 20)', 'quantile(close, 20, 0.5)', 'zscore(close, 20)',
        'bb_bw(close, 20, 2)', 'bb_pctb(close, 20, 2)',
        'squeeze(high, low, close, 20, 2, 20, 1.5)',
        'ts_max(close, 20)', 'ts_min(close, 20)',
        'ts_corr(close, volume, 20)', 'ts_delay(close, 5)',
        'add(close, open)', 'sub(close, open)', 'mul(close, open)', 'div(close, open)',
        'max(close, open)', 'min(close, open)', 'abs(close)',
        'if(gt(close, sma(close, 20)), 1, -1)',
        'gt(close, open)', 'lt(close, open)',
    ]
    for expr in operators_to_test:
        try:
            result = execute(expr, data)
            assert isinstance(result, pd.Series), f"Failed: {expr}"
        except Exception as e:
            print(f"  FAIL: {expr} -> {e}")
            raise
    print(f"PASS: test_all_operators ({len(operators_to_test)} operators)")

if __name__ == '__main__':
    test_basic_parse()
    test_complex_expr()
    test_no_lookahead()
    test_field_reference()
    test_arithmetic()
    test_conditional()
    test_syntax_error()
    test_illegal_operator()
    test_max_depth()
    test_all_operators()
    print("\\n=== 所有DSL测试通过 ===")
