import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
import data as data_module
from dsl import execute
from log import classify_family
from main import (
    _apply_candidate_direction,
    _best_baseline_sharpe,
    _combo_audit_status,
    _factor_evidence,
    _is_combo_eligible,
    _max_behavior_corr,
    _metric_value,
    _print_baselines,
    _ridge_combine,
    _select_combo_pool,
    _subperiod_backtests,
)
from backtest import backtest


SEED_FACTORS = [
    {
        "name": "slow_ema_rank",
        "family": "structure",
        "hypothesis": "Slow trend rank may capture persistent BTC macro drift.",
        "expr": "ts_rank(ema(close, 20), 100)",
    },
    {
        "name": "slow_ema_slope",
        "family": "structure",
        "hypothesis": "Long-horizon EMA slope may capture slow institutional trend.",
        "expr": "diff(ema(close, 200), 5)",
    },
    {
        "name": "atr_normalized_slow_trend",
        "family": "structure",
        "hypothesis": "Trend distance normalized by ATR should be more stable across volatility regimes.",
        "expr": "div(sub(close, ema(close, 200)), atr(high, low, close, 14))",
    },
    {
        "name": "vwap_proxy_deviation",
        "family": "liquidity",
        "hypothesis": "Deviation from a volume-weighted price proxy may identify flow imbalance.",
        "expr": "sub(close, div(ema(mul(close, volume), 20), ema(volume, 20)))",
    },
    {
        "name": "vwap_proxy_level",
        "family": "liquidity",
        "hypothesis": "Volume-weighted price proxy may capture where informed flow transacted.",
        "expr": "div(ema(mul(close, volume), 10), ema(volume, 10))",
    },
    {
        "name": "volume_shock_reversal",
        "family": "liquidity",
        "hypothesis": "Large volume shocks after short returns may mean exhaustion rather than continuation.",
        "expr": "mul(zscore(volume, 50), returns(close, 5))",
    },
    {
        "name": "range_position_50",
        "family": "structure",
        "hypothesis": "Position inside the 50-bar range may capture breakout or exhaustion behavior.",
        "expr": "div(sub(close, ts_min(low, 50)), sub(ts_max(high, 50), ts_min(low, 50)))",
    },
    {
        "name": "range_position_change",
        "family": "structure",
        "hypothesis": "Change in channel position may capture acceleration inside market structure.",
        "expr": "diff(div(sub(close, ts_min(low, 50)), sub(ts_max(high, 50), ts_min(low, 50))), 5)",
    },
    {
        "name": "volatility_compression",
        "family": "volatility",
        "hypothesis": "Low current volatility versus long volatility may precede expansion.",
        "expr": "sub(std(returns(close, 10), 40), std(returns(close, 20), 120))",
    },
    {
        "name": "atr_change",
        "family": "volatility",
        "hypothesis": "Rising ATR may mark risk-on/risk-off regime shifts.",
        "expr": "sub(atr(high, low, close, 14), ts_delay(atr(high, low, close, 14), 50))",
    },
    {
        "name": "price_volume_corr",
        "family": "liquidity",
        "hypothesis": "Correlation between price returns and volume changes may proxy informed participation.",
        "expr": "ts_corr(returns(close, 5), returns(volume, 5), 30)",
    },
    {
        "name": "amihud_proxy",
        "family": "liquidity",
        "hypothesis": "Return magnitude per unit volume may proxy fragile liquidity.",
        "expr": "div(abs(returns(close, 5)), ts_mean(volume, 20))",
    },
    {
        "name": "rsi_slow_deviation",
        "family": "reversal",
        "hypothesis": "Slow RSI deviation may capture crowded directional positioning.",
        "expr": "sub(rsi(close, 50), 50)",
    },
    {
        "name": "bb_percent_b_slow",
        "family": "reversal",
        "hypothesis": "Bollinger percent-b at slow horizon may capture mean-reversion pressure.",
        "expr": "sub(bb_pctb(close, 50, 2), 0.5)",
    },
]


def _clean_metric(result, key, default=0.0):
    value = result.get(key) if result else default
    if value is None or pd.isna(value):
        return default
    return float(value)


def _status(evidence):
    val = evidence.get("Validation") or {}
    if _clean_metric(val, "sharpe") > 0 and _clean_metric(val, "dir_acc") > 0.5:
        return "single_factor_val_pass"
    if _clean_metric(val, "sharpe") > 0:
        return "single_factor_val_sharpe_pass"
    return "pooled_is_only"


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    df = data_module.load_data(config.INST_ID, config.BAR, config.HISTORY_DAYS)
    splits = data_module.split_data(df)
    is_data, val_data, holdout_data = splits
    full_df = pd.concat(splits)
    data = {
        "close": full_df["close"],
        "open": full_df["open"],
        "high": full_df["high"],
        "low": full_df["low"],
        "volume": full_df["volume"],
    }

    baseline_payload = _print_baselines(full_df, splits)
    factor_pool = {}
    factor_meta = {}
    rows = []

    for seed in SEED_FACTORS:
        for direction in ("long", "short"):
            factor_id = f"seed_{stamp}_{seed['name']}_{direction}"
            raw_signal = execute(seed["expr"], data)
            signal = _apply_candidate_direction(raw_signal, direction)
            evidence, results = _factor_evidence(signal, splits)
            max_corr, nearest = _max_behavior_corr(signal, factor_pool, is_data.index)
            status = _status(evidence)

            meta = {
                "hypothesis": seed["hypothesis"],
                "dsl_expr": seed["expr"],
                "direction": direction,
                "family": seed.get("family") or classify_family(seed["expr"]),
                "seed_name": seed["name"],
                "split_evidence": evidence,
                "single_factor_status": status,
                "max_pool_corr": max_corr,
                "nearest_factor": nearest,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "seed_research",
            }

            if max_corr <= getattr(config, "POOL_CORR_THRESHOLD", 0.80):
                factor_pool[factor_id] = signal
                factor_meta[factor_id] = meta

            val = evidence.get("Validation") or {}
            holdout = evidence.get("Holdout") or {}
            is_ev = evidence.get("IS") or {}
            rows.append({
                "id": factor_id,
                "seed": seed["name"],
                "direction": direction,
                "family": meta["family"],
                "status": status,
                "is_sharpe": _clean_metric(is_ev, "sharpe"),
                "val_sharpe": _clean_metric(val, "sharpe"),
                "val_dir_acc": _clean_metric(val, "dir_acc"),
                "holdout_sharpe": _clean_metric(holdout, "sharpe"),
                "holdout_maxdd": _clean_metric(holdout, "max_drawdown"),
                "max_pool_corr": max_corr,
                "expr": seed["expr"],
            })

    combo_pool, combo_meta = _select_combo_pool(factor_pool, factor_meta)
    combo = None
    if len(combo_pool) >= 2:
        combined, weights = _ridge_combine(combo_pool, is_data, full_df, return_weights=True)
        val_result = backtest(combined.reindex(val_data.index), val_data, config.COST_BPS, config.SLIPPAGE_BPS)
        holdout_result = backtest(combined.reindex(holdout_data.index), holdout_data, config.COST_BPS, config.SLIPPAGE_BPS)
        is_result = backtest(combined.reindex(is_data.index), is_data, config.COST_BPS, config.SLIPPAGE_BPS)
        val_subperiods = _subperiod_backtests(combined, val_data, parts=2)
        combo_status = _combo_audit_status(val_result, holdout_result, baseline_payload, val_subperiods)
        combo = {
            "status": combo_status,
            "factors": list(combo_pool.keys()),
            "weights": weights,
            "is": is_result,
            "validation": val_result,
            "holdout": holdout_result,
            "val_subperiods": val_subperiods,
            "baseline_best_val_sharpe": _best_baseline_sharpe(baseline_payload, "Val"),
            "baseline_best_holdout_sharpe": _best_baseline_sharpe(baseline_payload, "Holdout"),
        }

    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed_count": len(SEED_FACTORS),
        "directional_tests": len(rows),
        "admitted_pool_size": len(factor_pool),
        "combo_eligible_size": len(combo_pool),
        "rows": sorted(rows, key=lambda r: r["val_sharpe"], reverse=True),
        "combo": combo,
    }

    Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)
    report_path = Path(config.LOG_DIR) / f"seed_report_{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    pool_path = Path(config.LOG_DIR) / f"seed_factor_pool_{stamp}.json"
    pool_path.write_text(json.dumps({"factors": factor_meta}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"seed_report={report_path}")
    print(f"admitted_pool_size={len(factor_pool)} combo_eligible_size={len(combo_pool)}")
    for row in report["rows"][:10]:
        print(
            f"{row['id']} val={row['val_sharpe']:.2f} holdout={row['holdout_sharpe']:.2f} "
            f"dir={row['val_dir_acc']:.2%} {row['family']} {row['expr']}"
        )
    if combo:
        print(
            "combo "
            f"status={combo['status']} val={combo['validation']['sharpe']:.2f} "
            f"holdout={combo['holdout']['sharpe']:.2f} factors={len(combo['factors'])}"
        )
    else:
        print("combo skipped")


if __name__ == "__main__":
    main()
