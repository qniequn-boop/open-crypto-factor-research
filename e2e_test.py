import sys, os, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/ubuntu/btclab')
os.chdir('/home/ubuntu/btclab')

print('=== 1. Data fetch ===')
import data as data_module
import config
df = data_module.load_data(config.INST_ID, config.BAR, config.HISTORY_DAYS)
print(f'Loaded: {len(df)} bars, {df.index[0]} -> {df.index[-1]}')
print(f'Columns: {list(df.columns)}')
print(f'Sample close: {df["close"].iloc[-3]:.2f}, {df["close"].iloc[-2]:.2f}, {df["close"].iloc[-1]:.2f}')

print()
print('=== 2. Split ===')
is_data, val_data, holdout_data = data_module.split_data(df)
print(f'IS: {len(is_data)} bars, {is_data.index[0]} -> {is_data.index[-1]}')
print(f'Val: {len(val_data)} bars, {val_data.index[0]} -> {val_data.index[-1]}')
print(f'Holdout: {len(holdout_data)} bars, {holdout_data.index[0]} -> {holdout_data.index[-1]}')

print()
print('=== 3. DSL execute on real data ===')
from dsl import execute
data = {
    'close': df['close'], 'open': df['open'], 'high': df['high'],
    'low': df['low'], 'volume': df['volume'],
}
expr = 'mul(ts_rank(returns(close, 20), 60), sub(close, ema(close, 50)))'
signal = execute(expr, data)
print(f'Expression: {expr}')
print(f'Signal: len={len(signal)}, non-null={signal.notna().sum()}, last={signal.dropna().iloc[-1]:.6f}')

print()
print('=== 4. Backtest on real data ===')
from backtest import run_backtest_on_splits
splits = (is_data, val_data, holdout_data)
results = run_backtest_on_splits(signal, splits, config.COST_BPS, config.SLIPPAGE_BPS)
for name in ['IS', 'Validation', 'Holdout']:
    r = results.get(name)
    if r:
        print(f'{name}: Sharpe={r["sharpe"]:.2f}, MaxDD={r["max_drawdown"]:.4f}, '
              f'WinRate={r["win_rate"]:.2%}, Exposure={r["exposure"]:.2%}, '
              f'Turnover={r["turnover"]:.4f}')
    else:
        print(f'{name}: insufficient data')

print()
print('=== 5. Overfit check on real data ===')
from overfit import full_check
is_r = results.get('IS', {})
val_r = results.get('Validation', {})
holdout_r = results.get('Holdout')
check = full_check(
    is_result=is_r, val_result=val_r, holdout_result=holdout_r,
    signal=signal, ohlcv=df, n_trials=1, promoted_signals=[],
)
print(f'Passed: {check["passed"]}')
print(f'Reasons: {check["reasons"][:200]}')

print()
print('=== E2E pipeline OK ===')
