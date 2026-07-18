# btclab/overfit.py
# 过拟合检测 —— 严格按照 PROJECT_DOC.md §4.5
# 多层检测: IS/Val/Holdout + 走步向前 + 参数敏感性 + DSR + PBO + 拥挤度

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from scipy import stats
import config

# ============================================================
# 第一层: 样本外验证
# ============================================================

def check_oos(is_sharpe: float, val_sharpe: float, holdout_sharpe: float = None) -> Tuple[bool, str]:
    """
    Validation 期表现 vs IS 期。IS 好但 Validation 崩 = 过拟合信号
    Holdout 期需独立确认, 不参与此门槛计算
    """
    floor = config.OOS_SHARPE_FLOOR  # 0.6
    if is_sharpe is None or val_sharpe is None:
        return False, "IS或Validation数据不足"

    if val_sharpe < is_sharpe * floor:
        return False, f"Validation夏普({val_sharpe:.3f}) < IS夏普({is_sharpe:.3f}) * {floor}"

    if holdout_sharpe is not None:
        if holdout_sharpe < is_sharpe * floor:
            return False, f"Holdout夏普({holdout_sharpe:.3f}) < IS夏普({is_sharpe:.3f}) * {floor}"

    return True, "OOS验证通过"

# ============================================================
# 第二层: 走步向前 (walk-forward)
# ============================================================

def walk_forward_check(signal: pd.Series, ohlcv: pd.DataFrame,
                       n_splits: int = 5) -> Dict:
    """
    滚动重调参, 模拟真实使用。不是一次性优化, 是分段。
    返回各段的夏普稳定性
    """
    n = len(signal)
    if n < n_splits * 100:
        return {'wf_sharpe_mean': 0, 'wf_sharpe_std': 0, 'wf_stable': False}

    segment_size = n // n_splits
    sharpes = []

    for i in range(n_splits):
        start = i * segment_size
        end = min((i + 1) * segment_size, n)
        if end - start < 50:
            continue

        seg_signal = signal.iloc[start:end]
        seg_ohlcv = ohlcv.iloc[start:end]

        # 简易回测 (不依赖 backtest.py, 避免循环导入)
        pos = pd.Series(np.sign(seg_signal.values), index=seg_signal.index).shift(1).fillna(0)
        ret = seg_ohlcv['close'] / seg_ohlcv['close'].shift(1) - 1
        pnl = pos.values * ret.values
        pnl_series = pd.Series(pnl, index=pos.index).fillna(0)

        if len(pnl_series) > 1 and pnl_series.std() > 0:
            sr = (pnl_series.mean() / pnl_series.std()) * np.sqrt(365 * 24 * 4)
            sharpes.append(sr)

    if len(sharpes) < 2:
        return {'wf_sharpe_mean': 0, 'wf_sharpe_std': 0, 'wf_stable': False}

    mean_sr = np.mean(sharpes)
    std_sr = np.std(sharpes, ddof=1)
    stable = (mean_sr > 0) and (std_sr / abs(mean_sr) < 1.0) if mean_sr != 0 else False

    return {
        'wf_sharpe_mean': mean_sr,
        'wf_sharpe_std': std_sr,
        'wf_stable': stable,
        'wf_n_segments': len(sharpes),
    }

# ============================================================
# 第三层: 参数敏感性
# ============================================================

def parameter_sensitivity(signal: pd.Series, ohlcv: pd.DataFrame,
                          pct_range: float = None) -> Dict:
    """
    信号在时间偏移 +-1~2 bar 下的稳定性。
    如果信号偏移一根K线就大幅变化 = 悬崖(过拟合)。
    如果稳定 = 高原(稳健)。
    """
    pct_range = pct_range or config.PARAM_SENSITIVITY_PCT
    n = len(signal)
    if n < 100:
        return {'sensitivity_score': 1.0, 'is_plateau': False}

    ret = ohlcv['close'] / ohlcv['close'].shift(1) - 1

    # 原始信号 + 前后偏移1-2根
    sharpes = []
    for shift in [0, 1, -1, 2, -2]:
        shifted = signal.shift(shift).fillna(0) if shift != 0 else signal
        pos = pd.Series(np.sign(shifted.values), index=shifted.index).shift(1).fillna(0)
        pnl = pd.Series(pos.values * ret.values, index=pos.index).fillna(0)
        if pnl.std() > 0 and len(pnl) > 1:
            sr = (pnl.mean() / pnl.std()) * np.sqrt(365 * 24 * 4)
        else:
            sr = 0
        sharpes.append(sr)

    # 稳定性: 各偏移夏普的变异系数
    mean_sr = np.mean(sharpes)
    std_sr = np.std(sharpes, ddof=1) if len(sharpes) > 1 else 0
    if abs(mean_sr) > 1e-8:
        cv = std_sr / abs(mean_sr)
    else:
        cv = 1.0 if std_sr > 0.01 else 0.0

    is_plateau = cv < 0.5

    return {
        'sensitivity_score': cv,
        'is_plateau': is_plateau,
        'sharpes': sharpes,
    }

# ============================================================
# 第四层: 多重检验校正 (DSR + PBO)
# ============================================================

def deflated_sharpe_ratio(sharpe: float, n_trials: int, returns: pd.Series,
                          skewness: float = None, kurtosis: float = None) -> Dict:
    """
    DSR (Deflated Sharpe Ratio)
    Bailey & Lopez de Prado (2014) JPM

    DSR = Prob[Max(SR_1..SR_N) <= SR]
    需要: 每个候选的夏普 + 试验总次数 + 收益序列的偏度/峰度
    """
    if returns is None or len(returns) < 10:
        return {'dsr': 0, 'p_value': 1.0, 'passed': False}

    returns_clean = returns.dropna()
    if len(returns_clean) < 10:
        return {'dsr': 0, 'p_value': 1.0, 'passed': False}

    # 计算偏度/峰度
    if skewness is None:
        skewness = returns_clean.skew()
    if kurtosis is None:
        kurtosis = returns_clean.kurtosis()

    # 期望最大夏普 (给定试验次数和收益分布)
    # E[max(SR)] ~= sqrt(Var(SR)) * sqrt(2*log(n_trials))
    # Var(SR) from Lo (2002), 约 (1+0.5*SR^2 - skew*SR + kurt*SR^2/4) / T

    T = len(returns_clean)
    if T < 2:
        return {'dsr': 0, 'p_value': 1.0, 'passed': False}

    # 夏普方差 (Lo 2002)
    sr = sharpe
    var_sr = (1 + 0.5 * sr**2 - skewness * sr + kurtosis * sr**2 / 4) / T
    var_sr = max(var_sr, 1e-10)
    std_sr = np.sqrt(var_sr)

    # 期望最大夏普
    if n_trials > 1:
        e_max_sr = std_sr * np.sqrt(2 * np.log(n_trials))
    else:
        e_max_sr = 0

    # DSR: sr 的标准正态分数
    dsr = (sr - e_max_sr) / std_sr if std_sr > 0 else 0
    p_value = 1 - stats.norm.cdf(dsr) if std_sr > 0 else 1.0
    passed = p_value < 0.05

    return {
        'dsr': dsr,
        'p_value': p_value,
        'passed': passed,
        'e_max_sharpe': e_max_sr,
        'var_sharpe': var_sr,
        'skewness': skewness,
        'kurtosis': kurtosis,
    }

def pbo_check(returns_list: List[pd.Series], n_splits: int = 10) -> Dict:
    """
    PBO/CSCV (Probability of Backtest Overfitting)
    Bailey et al. (2017) JCF

    需要每个候选的完整收益时间序列, 用组合对称交叉验证计算过拟合概率。
    PBO > 0.5 表示很可能过拟合。
    """
    if len(returns_list) < 2:
        return {'pbo': 1.0, 'passed': False, 'n_strategies': 0}

    # 对齐所有收益序列
    all_returns = pd.concat(returns_list, axis=1).dropna()
    if all_returns.shape[1] < 2 or all_returns.shape[0] < 20:
        return {'pbo': 1.0, 'passed': False, 'n_strategies': all_returns.shape[1]}

    n_obs = all_returns.shape[0]
    n_strategies = all_returns.shape[1]
    n_splits = min(n_splits, n_obs // 10)
    if n_splits < 2:
        return {'pbo': 1.0, 'passed': False, 'n_strategies': n_strategies}

    # 将数据分成偶数段 (CSCV需要偶数)
    if n_splits % 2 != 0:
        n_splits -= 1

    segment_size = n_obs // n_splits
    if segment_size < 5:
        return {'pbo': 1.0, 'passed': False, 'n_strategies': n_strategies}

    # 组合对称交叉验证
    n_combinations = 0
    overfit_count = 0

    for i in range(n_splits):
        for j in range(i + 1, n_splits):
            # 用段 i 作为 IS, 段 j 作为 OOS
            is_start = i * segment_size
            is_end = (i + 1) * segment_size
            oos_start = j * segment_size
            oos_end = (j + 1) * segment_size

            is_data = all_returns.iloc[is_start:is_end]
            oos_data = all_returns.iloc[oos_start:oos_end]

            if len(is_data) < 5 or len(oos_data) < 5:
                continue

            # IS 期夏普
            is_sharpes = []
            oos_sharpes = []
            for col in all_returns.columns:
                is_sr = _compute_sharpe(is_data[col].dropna())
                oos_sr = _compute_sharpe(oos_data[col].dropna())
                is_sharpes.append(is_sr)
                oos_sharpes.append(oos_sr)

            # 最佳IS策略 vs 最差IS策略的OOS表现
            if len(is_sharpes) < 2:
                continue

            is_arr = np.array(is_sharpes)
            oos_arr = np.array(oos_sharpes)

            best_is = np.argmax(is_arr)
            worst_is = np.argmin(is_arr)

            n_combinations += 1
            if oos_arr[best_is] <= oos_arr[worst_is]:
                overfit_count += 1

    pbo = overfit_count / n_combinations if n_combinations > 0 else 1.0

    return {
        'pbo': pbo,
        'passed': pbo <= 0.5,
        'n_strategies': n_strategies,
        'n_combinations': n_combinations,
    }

def _compute_sharpe(returns: pd.Series) -> float:
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    return (returns.mean() / returns.std()) * np.sqrt(365 * 24 * 4)

# ============================================================
# 第五层: 拥挤度检测
# ============================================================

def crowding_check(signal: pd.Series, promoted_signals: List[pd.Series]) -> Tuple[float, bool]:
    """
    候选与已知热门策略的相关性。高相关 = 拥挤 = 预期衰减快。
    """
    if not promoted_signals:
        return 0.0, True

    max_corr = 0.0
    for ps in promoted_signals:
        common_idx = signal.index.intersection(ps.index)
        if len(common_idx) < 20:
            continue
        corr = signal.reindex(common_idx).corr(ps.reindex(common_idx))
        if abs(corr) > max_corr:
            max_corr = abs(corr)

    passed = max_corr < config.MAX_CORRELATION
    return max_corr, passed

# ============================================================
# 综合检测
# ============================================================

def full_check(is_result: Dict, val_result: Dict, holdout_result: Dict = None,
               signal: pd.Series = None, ohlcv: pd.DataFrame = None,
               n_trials: int = 1, promoted_signals: List[pd.Series] = None) -> Dict:
    is_sharpe = is_result.get('sharpe', 0) if is_result else 0
    val_sharpe = val_result.get('sharpe', 0) if val_result else 0
    holdout_sharpe = holdout_result.get('sharpe', 0) if holdout_result else None

    checks = {}

    # 1. OOS
    oos_ok, oos_reason = check_oos(is_sharpe, val_sharpe, holdout_sharpe)
    checks['oos'] = {'passed': oos_ok, 'reason': oos_reason}

    # 2. Walk-forward
    if signal is not None and ohlcv is not None:
        wf = walk_forward_check(signal, ohlcv)
        checks['walk_forward'] = wf
    else:
        checks['walk_forward'] = {'wf_stable': True}

    # 3. 参数敏感性
    if signal is not None and ohlcv is not None:
        ps = parameter_sensitivity(signal, ohlcv)
        checks['param_sensitivity'] = ps
    else:
        checks['param_sensitivity'] = {'is_plateau': True}

    # 4. DSR
    if is_result and is_result.get('net_pnl_series') is not None:
        returns = is_result['net_pnl_series']
        dsr = deflated_sharpe_ratio(is_sharpe, n_trials, returns)
        checks['dsr'] = dsr
    else:
        checks['dsr'] = {'passed': True}

    # 5. 最大回撤
    max_dd = is_result.get('max_drawdown', 0) if is_result else 0
    dd_ok = max_dd < config.MAX_DRAWDOWN
    checks['max_drawdown'] = {'passed': dd_ok, 'value': max_dd,
                               'threshold': config.MAX_DRAWDOWN}

    # 6. 拥挤度
    if signal is not None and promoted_signals:
        max_corr, crowding_ok = crowding_check(signal, promoted_signals)
        checks['crowding'] = {'passed': crowding_ok, 'max_correlation': max_corr}
    else:
        checks['crowding'] = {'passed': True, 'max_correlation': 0}

    # 综合判定
    all_passed = (
        oos_ok and
        checks['walk_forward'].get('wf_stable', True) and
        checks['param_sensitivity'].get('is_plateau', True) and
        checks['dsr'].get('passed', True) and
        dd_ok and
        checks['crowding'].get('passed', True)
    )

    reasons = []
    if not oos_ok:
        reasons.append(f"OOS: {oos_reason}")
    if not checks['walk_forward'].get('wf_stable', True):
        reasons.append("WF不稳定")
    if not checks['param_sensitivity'].get('is_plateau', True):
        reasons.append("参数敏感(悬崖)")
    if not checks['dsr'].get('passed', True):
        reasons.append(f"DSR未通过: p={checks['dsr'].get('p_value', 1):.3f}")
    if not dd_ok:
        reasons.append(f"最大回撤({max_dd:.1%})超限({config.MAX_DRAWDOWN:.0%})")
    if not checks['crowding'].get('passed', True):
        reasons.append(f"拥挤: corr={checks['crowding'].get('max_correlation', 0):.3f}")

    return {
        'passed': all_passed,
        'reasons': '; '.join(reasons) if reasons else '全部通过',
        'checks': checks,
    }

def regime_conditional_check(is_regime_results: Dict, val_regime_results: Dict,
                             n_trials: int = 1, promoted_signals: List = None,
                             signal: pd.Series = None) -> Dict:
    """Regime-conditional promotion: factor passes if it works in ANY single regime.

    A factor that has positive Sharpe in trending IS + trending Validation
    gets promoted as a trending-only factor. Same for ranging.
    This is the key change: no longer require full-period pass.
    """
    checks = {}

    for regime_name in ['trending', 'ranging']:
        is_r = is_regime_results.get(regime_name)
        val_r = val_regime_results.get(regime_name)

        if is_r is None or val_r is None:
            checks[regime_name] = {'passed': False, 'reason': 'insufficient data'}
            continue

        is_sr = is_r.get('sharpe', 0) if is_r else 0
        val_sr = val_r.get('sharpe', 0) if val_r else 0
        is_dd = is_r.get('max_drawdown', 0) if is_r else 0

        reasons = []
        passed = True

        # 1. Both IS and Val must be positive
        if is_sr <= 0:
            passed = False
            reasons.append(f'IS {regime_name} Sharpe={is_sr:.2f} <= 0')
        if val_sr <= 0:
            passed = False
            reasons.append(f'Val {regime_name} Sharpe={val_sr:.2f} <= 0')

        # 2. Val should not collapse more than 50% from IS
        if is_sr > 0 and val_sr < is_sr * 0.5:
            passed = False
            reasons.append(f'Val/IS decay: {val_sr:.2f}/{is_sr:.2f}')

        # 3. Max drawdown check
        if is_dd > config.MAX_DRAWDOWN:
            passed = False
            reasons.append(f'MaxDD {is_dd:.1%} > {config.MAX_DRAWDOWN:.0%}')

        # 4. DSR (if we have returns)
        if is_r and is_r.get('net_pnl_series') is not None and is_sr > 0:
            dsr = deflated_sharpe_ratio(is_sr, n_trials, is_r['net_pnl_series'])
            if not dsr.get('passed', True):
                passed = False
                reasons.append(f'DSR p={dsr.get("p_value",1):.3f}')

        checks[regime_name] = {
            'passed': passed,
            'is_sharpe': is_sr,
            'val_sharpe': val_sr,
            'reason': '; '.join(reasons) if reasons else 'passed',
        }

    # Promote if ANY regime passes
    best_regime = None
    best_val_sr = -999
    for regime_name, c in checks.items():
        if c['passed'] and c.get('val_sharpe', 0) > best_val_sr:
            best_regime = regime_name
            best_val_sr = c.get('val_sharpe', 0)

    all_passed = best_regime is not None
    all_reasons = []
    for rn, c in checks.items():
        if not c['passed']:
            all_reasons.append(f'{rn}: {c["reason"]}')

    return {
        'passed': all_passed,
        'reasons': f'PASSED in {best_regime}' if all_passed else '; '.join(all_reasons),
        'checks': checks,
        'best_regime': best_regime,
    }

