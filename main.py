# btclab/main.py
# 主循环 —— 严格按照 PROJECT_DOC.md §10.1

import numpy as np
import pandas as pd
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict
import config
import data as data_module
from dsl import execute, parse_and_validate, DSLValidationError
from backtest import backtest, run_backtest_on_splits, annualized_sharpe, max_drawdown
from overfit import full_check, regime_conditional_check
from regime import classify_regime, regime_split_backtest
from generator import generate_candidates, FACTOR_FAMILIES
from log import classify_family
from log import append_entry, summarize, get_families_covered, count_entries, create_entry
from llm_client import Candidate

def _setup_data():
    print("=" * 60)
    print("BTC 策略挖掘系统 v1.0")
    print("=" * 60)

    print(f"\\n[1/3] 加载数据: {config.INST_ID} {config.BAR}")
    df = data_module.load_data(config.INST_ID, config.BAR, config.HISTORY_DAYS)
    print(f"  数据: {len(df)} bar, {df.index[0]} ~ {df.index[-1]}")

    print(f"\\n[2/3] 数据切分 (IS:Val:Holdout = {config.SPLIT_RATIOS})")
    is_data, val_data, holdout_data = data_module.split_data(df)
    print(f"  IS:       {len(is_data)} bar, {is_data.index[0]} ~ {is_data.index[-1]}")
    print(f"  Val:      {len(val_data)} bar, {val_data.index[0]} ~ {val_data.index[-1]}")
    print(f"  Holdout:  {len(holdout_data)} bar, {holdout_data.index[0]} ~ {holdout_data.index[-1]}")

    # Regime classification on full dataset
    regime = classify_regime(df)
    t_pct = float(regime.mean())
    print(f'  Regime: trending {t_pct:.0%}, ranging {1-t_pct:.0%}')
    return df, is_data, val_data, holdout_data, regime

def _process_candidate(candidate: Candidate, splits: tuple,
                       promoted_signals: List[pd.Series], regime: pd.Series = None) -> Dict:
    is_data, val_data, holdout_data = splits
    full_df = pd.concat([is_data, val_data, holdout_data])

    # Step 2: DSL parse + execute
    try:
        signal = execute(candidate.dsl_expr, {
            'close': full_df['close'],
            'open': full_df['open'],
            'high': full_df['high'],
            'low': full_df['low'],
            'volume': full_df['volume'],
        })
    except DSLValidationError as e:
        return {'error': f"DSL执行失败: {e}"}

    # Step 3: 回测
    results = run_backtest_on_splits(signal, splits, config.COST_BPS, config.SLIPPAGE_BPS)

    is_result = results.get('IS')
    val_result = results.get('Validation')
    holdout_result = results.get('Holdout')

    if is_result is None:
        return {'error': "IS回测数据不足"}

    # Step 3.5: Regime-split analysis
    regime_results = {}
    if regime is not None:
        from backtest import backtest as bt_fn
        for name, df_split in [('IS', is_data), ('Validation', val_data)]:
            if df_split is not None and len(df_split) > 100:
                r = regime.reindex(df_split.index).fillna(0)
                sig_split = signal.reindex(df_split.index)
                regime_results[name] = regime_split_backtest(
                    sig_split, df_split, r, bt_fn,
                    cost_bps=config.COST_BPS, slippage_bps=config.SLIPPAGE_BPS)
    regime_report = ''
    for name, rr in regime_results.items():
        tr = rr.get('trending')
        rg = rr.get('ranging')
        tr_sr = tr['sharpe'] if tr else 'N/A'
        rg_sr = rg['sharpe'] if rg else 'N/A'
        if isinstance(tr_sr, float): tr_sr = f'{tr_sr:.2f}'
        if isinstance(rg_sr, float): rg_sr = f'{rg_sr:.2f}'
        regime_report += f'{name}[trend={tr_sr},range={rg_sr}] '

    # Step 4: Regime-conditional 过拟合检测
    # 不再要求全周期通过, 而是要求在某个regime下IS+Val都为正
    is_regime = regime_results.get('IS', {}) if regime_results else {}
    val_regime = regime_results.get('Validation', {}) if regime_results else {}

    is_trend = is_regime.get('trending') if is_regime else None
    is_range = is_regime.get('ranging') if is_regime else None
    val_trend = val_regime.get('trending') if val_regime else None
    val_range = val_regime.get('ranging') if val_regime else None

    if is_trend and is_range and val_trend and val_range:
        overfit_result = regime_conditional_check(
            is_regime_results={'trending': is_trend, 'ranging': is_range},
            val_regime_results={'trending': val_trend, 'ranging': val_range},
            n_trials=count_entries() + 1,
            promoted_signals=promoted_signals,
            signal=signal,
        )
    else:
        # Fallback to full_check if regime data unavailable
        overfit_result = full_check(
            is_result=is_result if isinstance(is_result, dict) else {},
            val_result=val_result if isinstance(val_result, dict) else {},
            holdout_result=holdout_result if isinstance(holdout_result, dict) else None,
            signal=signal, ohlcv=full_df,
            n_trials=count_entries() + 1,
            promoted_signals=promoted_signals,
        )

    return {
        'signal': signal,
        'is_result': is_result,
        'val_result': val_result,
        'holdout_result': holdout_result,
        'overfit_result': overfit_result,
        'regime_report': regime_report,
    }

def _ridge_combine(signals_dict, is_data, full_df, return_weights=False):
    """Ridge combine factor pool. Fit weights on IS only.
    Returns combined signal series."""
    from sklearn.linear_model import Ridge
    import numpy as np

    sig_df = pd.DataFrame(signals_dict)
    is_idx = is_data.index
    ret = full_df["close"] / full_df["close"].shift(1) - 1

    # Standardize on IS
    sig_std = sig_df.copy()
    for col in sig_df.columns:
        m = sig_df.loc[is_idx, col].mean()
        s = sig_df.loc[is_idx, col].std()
        sig_std[col] = (sig_df[col] - m) / s if s > 0 else 0

    X_is = sig_std.loc[is_idx].fillna(0)
    y_is = ret.loc[is_idx].fillna(0)

    if len(sig_df.columns) < 2:
        # Not enough factors to combine, return equal weight
        combined = sig_std.mean(axis=1)
        weights = {str(col): 1.0 / max(len(sig_df.columns), 1) for col in sig_df.columns}
        return (combined, weights) if return_weights else combined

    ridge = Ridge(alpha=1.0)
    ridge.fit(X_is, y_is)

    combined = pd.Series(sig_std.fillna(0) @ ridge.coef_, index=sig_df.index)
    weights = {str(col): float(weight) for col, weight in zip(sig_df.columns, ridge.coef_)}
    return (combined, weights) if return_weights else combined


def _max_behavior_corr(candidate_signal, factor_pool, is_index):
    """Max absolute signal correlation versus the current pool on IS only."""
    if not factor_pool:
        return 0.0, None
    candidate = candidate_signal.reindex(is_index)
    max_corr = 0.0
    max_id = None
    for factor_id, existing_signal in factor_pool.items():
        existing = existing_signal.reindex(is_index)
        corr = candidate.corr(existing)
        if pd.isna(corr):
            corr = 0.0
        corr = abs(float(corr))
        if corr > max_corr:
            max_corr = corr
            max_id = factor_id
    return max_corr, max_id


def _apply_candidate_direction(signal, direction):
    """Orient signal before evaluation. LLM direction is part of the hypothesis."""
    direction = (direction or 'neutral').lower()
    if direction == 'short':
        return -signal
    return signal


def _factor_pool_path():
    return Path(config.LOG_DIR) / 'factor_pool.json'


def _load_factor_pool(data, is_index):
    """Reload admitted factor expressions and recompute their signals."""
    path = _factor_pool_path()
    factor_pool = {}
    factor_meta = {}
    if not path.exists():
        return factor_pool, factor_meta

    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        print(f"  Factor pool load skipped: {exc}")
        return factor_pool, factor_meta

    factors = payload.get('factors', {}) if isinstance(payload, dict) else {}
    for factor_id, meta in factors.items():
        expr = meta.get('dsl_expr')
        if not expr:
            continue
        try:
            signal = execute(expr, data)
            signal = _apply_candidate_direction(signal, meta.get('direction'))
        except Exception as exc:
            print(f"  Factor pool item skipped [{factor_id}]: {exc}")
            continue
        factor_pool[factor_id] = signal
        factor_meta[factor_id] = dict(meta)

    if factor_pool:
        print(f"  Loaded persistent factor pool: {len(factor_pool)} factors")
    return factor_pool, factor_meta


def _save_factor_pool(factor_meta):
    path = _factor_pool_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'schema_version': 1,
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'pool_policy': {
            'admission': 'IS positive in at least one regime plus behavior-correlation gate',
            'holdout': 'audit_only_not_selection_gate',
        },
        'factors': factor_meta,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _metric_snapshot(result):
    if not result:
        return None
    keys = [
        'sharpe', 'dir_acc', 'directional_accuracy', 'ic_pearson',
        'ic_spearman', 'max_drawdown', 'win_rate', 'expectancy',
        'exposure', 'turnover', 'annualized_return', 'total_return',
    ]
    return {key: result.get(key) for key in keys if key in result}


def _factor_evidence(signal, splits):
    results = run_backtest_on_splits(signal, splits, config.COST_BPS, config.SLIPPAGE_BPS)
    return {
        'IS': _metric_snapshot(results.get('IS')),
        'Validation': _metric_snapshot(results.get('Validation')),
        'Holdout': _metric_snapshot(results.get('Holdout')),
    }, results


def _single_factor_status(evidence):
    val = evidence.get('Validation') or {}
    sharpe = val.get('sharpe') or 0.0
    dir_acc = val.get('dir_acc') or 0.0
    if sharpe > 0 and dir_acc > 0.5:
        return 'single_factor_val_pass'
    if sharpe > 0:
        return 'single_factor_val_sharpe_pass'
    return 'pooled_is_only'


def _metric_value(evidence, split_name, metric, default=0.0):
    split = evidence.get(split_name) or {}
    value = split.get(metric)
    if value is None or pd.isna(value):
        return default
    return float(value)


def _is_combo_eligible(meta):
    evidence = meta.get('split_evidence') or {}
    is_sr = _metric_value(evidence, 'IS', 'sharpe', -999.0)
    val_sr = _metric_value(evidence, 'Validation', 'sharpe', -999.0)
    is_dir = _metric_value(evidence, 'IS', 'dir_acc', 0.0)
    val_dir = _metric_value(evidence, 'Validation', 'dir_acc', 0.0)
    val_dd = _metric_value(evidence, 'Validation', 'max_drawdown', 999.0)

    min_is_sr = getattr(config, 'COMBO_MIN_IS_SHARPE', -0.10)
    min_val_sr = getattr(config, 'COMBO_MIN_VAL_SHARPE', 0.20)
    min_is_dir = getattr(config, 'COMBO_MIN_IS_DIR_ACC', 0.500)
    min_val_dir = getattr(config, 'COMBO_MIN_VAL_DIR_ACC', 0.500)
    max_val_dd = getattr(config, 'COMBO_MAX_VAL_DD', 0.30)
    return (
        is_sr >= min_is_sr
        and val_sr >= min_val_sr
        and is_dir >= min_is_dir
        and val_dir >= min_val_dir
        and val_dd <= max_val_dd
    )


def _select_combo_pool(factor_pool, factor_meta):
    eligible_ids = [fid for fid in factor_pool if _is_combo_eligible(factor_meta.get(fid, {}))]
    eligible_ids.sort(
        key=lambda fid: _metric_value(factor_meta.get(fid, {}).get('split_evidence') or {}, 'Validation', 'sharpe', -999.0),
        reverse=True,
    )
    max_factors = getattr(config, 'COMBO_MAX_FACTORS', 6)
    selected = eligible_ids[:max_factors]
    return {fid: factor_pool[fid] for fid in selected}, {fid: factor_meta[fid] for fid in selected}


def _regime_evidence(is_trend_r, is_range_r):
    return {
        'IS_trending': _metric_snapshot(is_trend_r),
        'IS_ranging': _metric_snapshot(is_range_r),
    }


def _baselines_path():
    return Path(config.LOG_DIR) / 'baselines_latest.json'


def _write_baselines(payload):
    path = _baselines_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _best_baseline_sharpe(baseline_payload, split_name):
    best = -999.0
    for split_map in baseline_payload.get('baselines', {}).values():
        result = split_map.get(split_name) or {}
        sharpe = result.get('sharpe')
        if sharpe is not None and not pd.isna(sharpe):
            best = max(best, float(sharpe))
    return best if best > -999.0 else 0.0


def _subperiod_backtests(signal, split_data, parts=2):
    if parts <= 1 or len(split_data) < parts * 50:
        return []
    idx_parts = np.array_split(np.arange(len(split_data)), parts)
    results = []
    for idx in idx_parts:
        if len(idx) < 50:
            continue
        sub_data = split_data.iloc[idx]
        sub_signal = signal.reindex(sub_data.index)
        results.append(_metric_snapshot(backtest(sub_signal, sub_data, config.COST_BPS, config.SLIPPAGE_BPS)))
    return results


def _combo_audit_status(val_result, holdout_result, baseline_payload, val_subperiods=None):
    val_sr = float(val_result.get('sharpe', 0.0))
    holdout_sr = float(holdout_result.get('sharpe', 0.0))
    holdout_dd = float(holdout_result.get('max_drawdown', 0.0))
    baseline_val = _best_baseline_sharpe(baseline_payload, 'Val')

    val_subperiods = val_subperiods or []
    min_sub_val = min((r.get('sharpe', 0.0) for r in val_subperiods), default=val_sr)

    val_selected = val_sr > max(0.0, baseline_val) and min_sub_val > getattr(config, 'COMBO_MIN_VAL_SUBPERIOD_SHARPE', -0.25)
    holdout_ok = (
        holdout_sr >= getattr(config, 'COMBO_MIN_HOLDOUT_SHARPE_AUDIT', -0.50)
        and holdout_dd <= getattr(config, 'COMBO_MAX_HOLDOUT_DD_AUDIT', 0.45)
    )

    if val_selected and holdout_ok:
        return 'combo_audit_pass'
    if val_selected:
        return 'combo_audit_failed'
    return 'combo_rejected_val'


def _buy_hold_result(ohlcv):
    ret = (ohlcv['close'] / ohlcv['close'].shift(1) - 1).fillna(0)
    return {
        'sharpe': annualized_sharpe(ret),
        'dir_acc': float((ret > 0).mean()) if len(ret) else 0.0,
        'max_drawdown': max_drawdown(ret),
        'total_return': float(ret.sum()),
    }


def _benchmark_signals(full_df):
    close = full_df['close']
    rng = np.random.default_rng(config.RANDOM_SEED)
    return {
        'naive_momentum_20': close / close.shift(20) - 1,
        'naive_mean_reversion_50': -(close - close.rolling(50, min_periods=20).mean()),
        'rsi_reversal_14': execute('sub(50, rsi(close, 14))', {
            'close': full_df['close'], 'open': full_df['open'],
            'high': full_df['high'], 'low': full_df['low'],
            'volume': full_df['volume'],
        }),
        'random_noise_control': pd.Series(rng.normal(0, 1, len(full_df)), index=full_df.index),
    }


def _print_baselines(full_df, splits):
    is_data, val_data, holdout_data = splits
    payload = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'cost_bps': config.COST_BPS,
        'slippage_bps': config.SLIPPAGE_BPS,
        'baselines': {},
    }
    print("\n--- Baselines (not selection targets) ---")
    payload['baselines']['buy_hold_direct'] = {}
    for name, split_data in [("IS", is_data), ("Val", val_data), ("Holdout", holdout_data)]:
        r = _buy_hold_result(split_data)
        payload['baselines']['buy_hold_direct'][name] = _metric_snapshot(r)
        print(f"  buy_hold_direct/{name}: Sharpe={r['sharpe']:.2f} DirAcc={r['dir_acc']:.2%} MaxDD={r['max_drawdown']:.1%} Ret={r['total_return']:.4f}")

    for bench_name, signal in _benchmark_signals(full_df).items():
        parts = []
        payload['baselines'][bench_name] = {}
        for name, split_data in [("IS", is_data), ("Val", val_data), ("Holdout", holdout_data)]:
            r = backtest(signal.reindex(split_data.index), split_data, config.COST_BPS, config.SLIPPAGE_BPS)
            payload['baselines'][bench_name][name] = _metric_snapshot(r)
            parts.append(f"{name}:SR={r['sharpe']:.2f},DA={r.get('dir_acc', 0):.1%}")
        print(f"  {bench_name}: " + " | ".join(parts))
    _write_baselines(payload)
    return payload


def main():
    import numpy as np
    from regime import classify_regime
    from overfit import regime_conditional_check
    from sklearn.linear_model import Ridge

    np.random.seed(config.RANDOM_SEED)

    # Load data
    print("=" * 60)
    print("BTC Strategy Mining System v2.0 (HypCrypto pipeline)")
    print("=" * 60)

    print(f"\n[1/4] Loading data: {config.INST_ID} {config.BAR}")
    df = data_module.load_data(config.INST_ID, config.BAR, config.HISTORY_DAYS)
    print(f"  Data: {len(df)} bars, {df.index[0]} -> {df.index[-1]}")

    print(f"\n[2/4] Split (IS:Val:Holdout = {config.SPLIT_RATIOS})")
    is_data, val_data, holdout_data = data_module.split_data(df)
    print(f"  IS: {len(is_data)}, Val: {len(val_data)}, Holdout: {len(holdout_data)}")

    print(f"\n[3/4] Regime classification")
    regime = classify_regime(df)
    print(f"  Trending: {regime.mean():.0%}, Ranging: {1-regime.mean():.0%}")

    splits = (is_data, val_data, holdout_data)
    full_df = pd.concat([is_data, val_data, holdout_data])
    data = {
        'close': full_df['close'], 'open': full_df['open'],
        'high': full_df['high'], 'low': full_df['low'],
        'volume': full_df['volume'],
    }

    baseline_payload = _print_baselines(full_df, splits)

    # Factor pool: factors that passed IS regime-conditional gate.
    factor_pool, factor_meta = _load_factor_pool(data, is_data.index)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

    print(f"\n[4/4] Search loop ({config.MAX_ROUNDS} rounds)")
    print("=" * 60)

    for round_num in range(config.MAX_ROUNDS):
        print(f"\n{'='*40}")
        print(f"Round {round_num + 1}/{config.MAX_ROUNDS}")
        print(f"  Factor pool: {len(factor_pool)} factors")
        print(f"{'='*40}")

        # Step 1: Generate candidates
        log_summary = summarize(n_recent_rounds=3)
        families_covered = list(set(factor_meta.get(k, {}).get('family', '') for k in factor_pool))

        print(f"  Generating {config.CANDIDATES_PER_ROUND} candidates...")
        candidates = generate_candidates(round_num, len(factor_pool), log_summary, families_covered)
        print(f"  Valid candidates: {len(candidates)}")

        if not candidates:
            continue

        # Step 2: For each candidate - DSL execute + IS regime gate
        round_added = 0
        for i, candidate in enumerate(candidates):
            cid = f"{run_id}_R{round_num+1:02d}C{i+1:03d}"

            try:
                raw_signal = execute(candidate.dsl_expr, data)
                signal = _apply_candidate_direction(raw_signal, candidate.direction)
            except DSLValidationError as e:
                continue

            split_evidence, split_results = _factor_evidence(signal, splits)
            single_factor_status = _single_factor_status(split_evidence)

            # IS regime-conditional check (ONLY IS, not Val)
            is_regime = regime.reindex(is_data.index).fillna(0)
            is_signal = signal.reindex(is_data.index)

            is_trending_mask = is_regime == 1
            is_ranging_mask = is_regime == 0

            is_trend_r = backtest(is_signal[is_trending_mask], is_data[is_trending_mask],
                                  config.COST_BPS, config.SLIPPAGE_BPS) if is_trending_mask.sum() > 50 else None
            is_range_r = backtest(is_signal[is_ranging_mask], is_data[is_ranging_mask],
                                  config.COST_BPS, config.SLIPPAGE_BPS) if is_ranging_mask.sum() > 50 else None

            # Gate: factor must have positive IS Sharpe in at least one regime
            is_trend_sr = is_trend_r['sharpe'] if is_trend_r else -999
            is_range_sr = is_range_r['sharpe'] if is_range_r else -999

            passed_gate = (is_trend_sr > 0 or is_range_sr > 0)
            max_pool_corr, nearest_factor = _max_behavior_corr(signal, factor_pool, is_data.index)
            pool_corr_threshold = getattr(config, 'POOL_CORR_THRESHOLD', 0.80)
            regime_ev = _regime_evidence(is_trend_r, is_range_r)

            if passed_gate:
                if max_pool_corr > pool_corr_threshold:
                    entry = create_entry(
                        cid, candidate.hypothesis, candidate.dsl_expr,
                        split_results.get('IS'),
                        split_results.get('Validation'),
                        split_results.get('Holdout'),
                        {
                            'passed': False,
                            'reasons': f'behavior correlation {max_pool_corr:.2f} with {nearest_factor}',
                            'checks': {'pool_correlation': {'max_correlation': max_pool_corr, 'nearest_factor': nearest_factor}},
                        },
                        promoted=False,
                        family=classify_family(candidate.dsl_expr),
                        existing_candidates=None,
                        direction=candidate.direction,
                        admitted_to_pool=False,
                        status='rejected_redundant',
                    )
                    entry['single_factor_status'] = single_factor_status
                    entry['split_evidence'] = split_evidence
                    entry['regime_evidence'] = regime_ev
                    append_entry(entry)
                    print(f"    [{i+1}/{len(candidates)}] {cid}: REDUNDANT | corr={max_pool_corr:.2f} with {nearest_factor}")
                    continue

                factor_pool[cid] = signal
                family = classify_family(candidate.dsl_expr)
                factor_meta[cid] = {
                    'hypothesis': candidate.hypothesis,
                    'dsl_expr': candidate.dsl_expr,
                    'direction': candidate.direction,
                    'family': family,
                    'is_trend_sr': is_trend_sr,
                    'is_range_sr': is_range_sr,
                    'max_pool_corr': max_pool_corr,
                    'nearest_factor': nearest_factor,
                    'split_evidence': split_evidence,
                    'regime_evidence': regime_ev,
                    'single_factor_status': single_factor_status,
                    'direction_applied': (candidate.direction or 'neutral').lower(),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'status': 'pooled_is_gate',
                }
                round_added += 1
                best_regime = 'trend' if is_trend_sr > is_range_sr else 'range'
                val_sr = (split_evidence.get('Validation') or {}).get('sharpe') or 0.0
                print(f"    [{i+1}/{len(candidates)}] {cid}: POOLED | IS[{best_regime}]={max(is_trend_sr,is_range_sr):.2f} Val={val_sr:.2f} | {single_factor_status} | {family} | {candidate.dsl_expr[:50]}...")

                # Log entry
                entry = create_entry(
                    cid, candidate.hypothesis, candidate.dsl_expr,
                    split_results.get('IS'),
                    split_results.get('Validation'),
                    split_results.get('Holdout'),
                    {'passed': True, 'reasons': f'IS gate passed ({best_regime})'},
                    promoted=False, family=family, existing_candidates=None, direction=candidate.direction,
                    admitted_to_pool=True, status='pooled_is_gate'
                )
                entry['single_factor_status'] = single_factor_status
                entry['split_evidence'] = split_evidence
                entry['regime_evidence'] = regime_ev
                entry['max_pool_corr'] = max_pool_corr
                entry['nearest_factor'] = nearest_factor
                entry['direction_applied'] = (candidate.direction or 'neutral').lower()
                append_entry(entry)
                _save_factor_pool(factor_meta)
            else:
                # Log rejected
                entry = create_entry(
                    cid, candidate.hypothesis, candidate.dsl_expr,
                    split_results.get('IS'),
                    split_results.get('Validation'),
                    split_results.get('Holdout'),
                    {'passed': False, 'reasons': f'IS both regimes negative'},
                    promoted=False, family=classify_family(candidate.dsl_expr),
                    existing_candidates=None, direction=candidate.direction,
                    admitted_to_pool=False, status='rejected_is_gate'
                )
                entry['single_factor_status'] = single_factor_status
                entry['split_evidence'] = split_evidence
                entry['regime_evidence'] = regime_ev
                append_entry(entry)

        print(f"  Round {round_num+1}: added {round_added} to pool (total: {len(factor_pool)})")
        if round_added:
            _save_factor_pool(factor_meta)

        # Step 3: Ridge combine and test on Val + Holdout
        combo_pool, combo_meta = _select_combo_pool(factor_pool, factor_meta)
        if len(combo_pool) >= 2:
            print(f"\n  --- Ridge combination ({len(combo_pool)}/{len(factor_pool)} eligible factors) ---")
            combined, combo_weights = _ridge_combine(combo_pool, is_data, full_df, return_weights=True)

            # Test on each period
            for name, split_data in [("IS", is_data), ("Val", val_data), ("Holdout", holdout_data)]:
                sig_split = combined.reindex(split_data.index)
                r = backtest(sig_split, split_data, config.COST_BPS, config.SLIPPAGE_BPS)
                status = "POSITIVE" if r['sharpe'] > 0 else "negative"
                print(f"    {name}: Sharpe={r['sharpe']:.2f} DirAcc={r.get('dir_acc', 0):.2%} MaxDD={r['max_drawdown']:.1%} Ret={r['total_return']:.4f} [{status}]")

            # Check Holdout
            holdout_result = backtest(combined.reindex(holdout_data.index), holdout_data,
                                      config.COST_BPS, config.SLIPPAGE_BPS)
            val_result = backtest(combined.reindex(val_data.index), val_data,
                                  config.COST_BPS, config.SLIPPAGE_BPS)
            val_subperiods = _subperiod_backtests(combined, val_data, parts=2)
            combo_status = _combo_audit_status(val_result, holdout_result, baseline_payload, val_subperiods)

            if combo_status != 'combo_rejected_val':
                print(f"\n  >> COMBO {combo_status.upper()} | Val={val_result['sharpe']:.2f} HoldoutAudit={holdout_result['sharpe']:.2f}")

                # Holdout is recorded as audit. Only audit-pass combos are final candidates.
                import json
                combo_info = {
                    'type': 'ridge_combo',
                    'status': combo_status,
                    'factors': list(combo_pool.keys()),
                    'factor_exprs': {k: combo_meta[k]['dsl_expr'] for k in combo_pool},
                    'weights': combo_weights,
                    'val_sharpe': val_result['sharpe'],
                    'val_dir_acc': val_result.get('dir_acc'),
                    'val_ic_spearman': val_result.get('ic_spearman'),
                    'val_subperiods': val_subperiods,
                    'baseline_best_val_sharpe': _best_baseline_sharpe(baseline_payload, 'Val'),
                    'baseline_best_holdout_sharpe': _best_baseline_sharpe(baseline_payload, 'Holdout'),
                    'holdout_sharpe': holdout_result['sharpe'],
                    'holdout_dir_acc': holdout_result.get('dir_acc'),
                    'holdout_ic_spearman': holdout_result.get('ic_spearman'),
                    'holdout_maxdd': holdout_result['max_drawdown'],
                    'holdout_return': holdout_result['total_return'],
                    'holdout_policy': 'audit_only_not_selection_gate',
                    'combo_policy': 'uses combo-eligible factors only, not the full research pool',
                    'round': round_num + 1,
                }
                combo_prefix = 'combo_promoted' if combo_status == 'combo_audit_pass' else 'combo_audit_failed'
                with open(f"logs/{combo_prefix}_r{round_num+1}.json", 'w') as f:
                    json.dump(combo_info, f, ensure_ascii=False, indent=2)
            else:
                print(f"    Combo not promoted (need Val > best baseline and stable Val subperiods)")
        elif len(factor_pool) >= 2:
            print(f"\n  --- Ridge skipped: {len(combo_pool)}/{len(factor_pool)} factors combo-eligible ---")

    # Final summary
    print(f"\n{'='*60}")
    print(f"Search complete: {len(factor_pool)} factors in pool")
    print(f"Log: {config.LOG_DIR}/experiment_log.jsonl")

    # Final ridge combo
    combo_pool, combo_meta = _select_combo_pool(factor_pool, factor_meta)
    if len(combo_pool) >= 2:
        combined, combo_weights = _ridge_combine(combo_pool, is_data, full_df, return_weights=True)
        print(f"\nFinal combo performance:")
        for name, split_data in [("IS", is_data), ("Val", val_data), ("Holdout", holdout_data)]:
            r = backtest(combined.reindex(split_data.index), split_data, config.COST_BPS, config.SLIPPAGE_BPS)
            print(f"  {name}: Sharpe={r['sharpe']:.2f} DirAcc={r.get('dir_acc', 0):.2%} MaxDD={r['max_drawdown']:.1%}")
    elif len(factor_pool) >= 2:
        print(f"\nFinal combo skipped: {len(combo_pool)}/{len(factor_pool)} factors combo-eligible")

    print(f"{'='*60}")


if __name__ == '__main__':
    main()
