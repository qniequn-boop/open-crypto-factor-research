# btclab/backtest.py
# 向量化回测引擎 —— 严格按照 PROJECT_DOC.md §10.3
# 关键时序规则(不可违反):
#   信号在 t 根收盘后计算, t+1 根开盘建仓
#   收益用 t+1 根的 close-to-close 收益率
#   持仓 shift(1) 是铁律, 缺了就是未来函数

import numpy as np
import pandas as pd
from typing import Dict, Optional
import config

def sign(x: pd.Series) -> pd.Series:
    # +1多, 0空仓, -1空
    return pd.Series(np.sign(x.values), index=x.index).fillna(0)

def _to_position(signal: pd.Series, clip: float = 1.0) -> pd.Series:
    """连续仓位: 滚动zscore归一化, clip到[-1,+1]。
    保留信号强度信息, 不再用sign()三态化。
    滚动窗口=200 (约2天15m), 用IS期统计量归一化。
    """
    s = signal.copy()
    # 滚动zscore
    roll_mean = s.rolling(200, min_periods=50).mean()
    roll_std = s.rolling(200, min_periods=50).std()
    z = (s - roll_mean) / roll_std.replace(0, np.nan)
    # clip到[-1, +1]
    z = z.clip(-clip, clip)
    return z.fillna(0)

def annualized_sharpe(pnl: pd.Series, periods_per_year: int = None) -> float:
    if periods_per_year is None:
        periods_per_year = _get_periods_per_year()
    if len(pnl) < 2:
        return 0.0
    excess = pnl - 0  # 无风险利率视为0
    if excess.std() == 0:
        return 0.0
    return (excess.mean() / excess.std()) * np.sqrt(periods_per_year)

def max_drawdown(pnl: pd.Series) -> float:
    cum = pnl.cumsum()
    running_max = cum.cummax()
    drawdown = (cum - running_max)
    return abs(drawdown.min()) if len(drawdown) > 0 else 0.0

def _get_periods_per_year() -> int:
    bar = config.BAR
    if bar == '15m':
        return 365 * 24 * 4
    elif bar == '1H':
        return 365 * 24
    elif bar == '4H':
        return 365 * 6
    return 365 * 24 * 4

def calc_funding(position: pd.Series, funding_rate_series: Optional[pd.Series] = None) -> pd.Series:
    # 资金费率: 每8小时(48根15m), 持仓方向付/收
    # 正费率: 多付空收; 负费率: 多收空付
    # 若无真实数据, 先用0估算
    if funding_rate_series is None:
        return pd.Series(0.0, index=position.index)

    interval = config.FUNDING_INTERVAL
    funding_idx = range(0, len(position), interval)

    cost = pd.Series(0.0, index=position.index)
    for i in funding_idx:
        if i < len(position) and i < len(funding_rate_series):
            rate = funding_rate_series.iloc[i]
            # 正费率: 多付(len(position)>0付), 空收
            # 多付 = 多头(>0) * rate, 空收 = 空头(<0) * rate (空头收 = -position * rate)
            # 资金费率按名义价值计算: position方向 * rate * 杠杆
            cost.iloc[i] = position.iloc[i] * rate * config.LEVERAGE

    return cost.fillna(0)

def directional_accuracy(signal: pd.Series, ret: pd.Series) -> float:
    """Single-asset direction hit rate using t signal against t+1 return."""
    aligned = pd.concat([signal.shift(1), ret], axis=1).dropna()
    if aligned.empty:
        return 0.0
    sig = aligned.iloc[:, 0]
    future_ret = aligned.iloc[:, 1]
    mask = (sig != 0) & (future_ret != 0)
    if mask.sum() == 0:
        return 0.0
    return float((np.sign(sig[mask]) == np.sign(future_ret[mask])).mean())

def backtest(signal: pd.Series, ohlcv: pd.DataFrame,
             cost_bps: int = None, slippage_bps: int = None,
             funding_rate_series: pd.Series = None) -> Dict:
    cost_bps = cost_bps if cost_bps is not None else config.COST_BPS
    slippage_bps = slippage_bps if slippage_bps is not None else config.SLIPPAGE_BPS
    signal = signal.reindex(ohlcv.index)
    signal = signal.replace([np.inf, -np.inf], np.nan).fillna(0)

    # 1. 信号已在 t 时刻收盘后计算完毕(无未来函数)

    # 2. 持仓: 连续仓位, 用滚动zscore归一化到[-1,+1]
    #    保留信号强度信息, 不再用sign()三态化
    position = _to_position(signal)
    position = position.shift(1)  # 延迟一根: t根信号 -> t+1根持仓
    position.iloc[0] = 0  # 第一根无持仓
    position = position.fillna(0)

    # 3. 毛收益: 持仓 * 下一根的收益率(t+1 的 close-to-close)
    close = ohlcv['close']
    ret = close / close.shift(1) - 1
    gross_pnl = position.values * ret.values
    gross_pnl = pd.Series(gross_pnl, index=position.index)

    # 4. 交易成本: 持仓变化时扣费
    turnover = position.diff().abs()
    cost = turnover * (cost_bps + slippage_bps) / 10000
    cost = cost.fillna(0)

    # 5. 资金费率
    funding_cost = calc_funding(position, funding_rate_series)

    # 6. 净收益
    net_pnl = gross_pnl - cost - funding_cost
    net_pnl = net_pnl.fillna(0)

    # 7. 指标计算
    cum_pnl = net_pnl.cumsum()
    periods_per_year = _get_periods_per_year()
    sharpe = annualized_sharpe(net_pnl, periods_per_year)
    dd = max_drawdown(net_pnl)

    # 年化收益率
    total_return = net_pnl.sum()
    if len(net_pnl) > 0 and abs(config.INITIAL_CAPITAL) > 0:
        annual_return = (1 + total_return / config.INITIAL_CAPITAL) ** (periods_per_year / len(net_pnl)) - 1
    else:
        annual_return = 0.0

    win_rate = (net_pnl > 0).mean() if len(net_pnl) > 0 else 0.0
    expect_val = net_pnl.mean() if len(net_pnl) > 0 else 0.0
    exposure = (position != 0).mean() if len(position) > 0 else 0.0
    avg_turnover = turnover.mean() if len(turnover) > 0 else 0.0

    # IC (信息系数): Pearson + Rank(Spearman)
    ic_pearson = signal.shift(1).corr(ret) if len(signal) > 1 else 0.0
    ic_spearman = signal.shift(1).corr(ret, method='spearman') if len(signal) > 1 else 0.0
    dir_acc = directional_accuracy(signal, ret)

    # 分桶收益: 信号五分位的多空价差
    bucket_returns = _bucket_returns(signal, ohlcv)

    result = {
        'sharpe': sharpe,
        'max_drawdown': dd,
        'win_rate': win_rate,
        'expectancy': expect_val,
        'exposure': exposure,
        'turnover': avg_turnover,
        'annualized_return': annual_return,
        'ic_pearson': ic_pearson,
        'ic_spearman': ic_spearman,
        'dir_acc': dir_acc,
        'directional_accuracy': dir_acc,
        'bucket_returns': bucket_returns,
        'net_pnl_series': net_pnl,
        'position_series': position,
        'total_return': total_return,
    }

    return result

def _bucket_returns(signal: pd.Series, ohlcv: pd.DataFrame) -> dict:
    # 信号五分位的多空价差
    clean_signal = signal.dropna()
    if len(clean_signal) < 5:
        return {}

    try:
        buckets = pd.qcut(clean_signal, 5, labels=False, duplicates='drop')
        ret = ohlcv['close'] / ohlcv['close'].shift(1) - 1
        ret = ret.reindex(clean_signal.index)

        bucket_mean = ret.groupby(buckets).mean()
        long_short = bucket_mean.max() - bucket_mean.min()
        return {
            'quintile_returns': bucket_mean.to_dict(),
            'long_short_spread': long_short,
        }
    except Exception:
        return {}

def run_backtest_on_splits(signal_series: pd.Series, splits: tuple,
                           cost_bps: int = None, slippage_bps: int = None,
                           funding_rate_series: pd.Series = None) -> Dict:
    is_data, val_data, holdout_data = splits

    results = {}
    for name, df in [('IS', is_data), ('Validation', val_data), ('Holdout', holdout_data)]:
        if len(df) < 2:
            results[name] = None
            continue
        common_idx = signal_series.index.intersection(df.index)
        if len(common_idx) < 2:
            results[name] = None
            continue
        sig = signal_series.reindex(common_idx)
        df_aligned = df.reindex(common_idx)
        fr = funding_rate_series.reindex(common_idx) if funding_rate_series is not None else None
        results[name] = backtest(sig, df_aligned, cost_bps, slippage_bps, fr)

    return results
