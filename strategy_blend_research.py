"""Val-only weighted blend research for executable BTC strategies.

This script searches a small, pre-declared grid of continuous strategy blends.
Selection uses only IS and Validation. Holdout is reported strictly as an audit.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import config
import data as data_module
import strategy_audit as audit
import strategy_research as sr


SELECTION_FILTERS = {
    "uses_holdout_for_selection": False,
    "is_sharpe_min": 0.0,
    "val_sharpe_min": 2.50,
    "val_subperiod_sharpe_min": 0.0,
    "val_drawdown_max": 0.20,
    "val_turnover_max": 0.02,
    "max_abs_val_component_corr": 0.80,
}

MAX_ACTIVE_BLEND_COMPONENTS = 3
MAX_BLEND_GRID_ROWS = 2500


COMPONENTS = {
    "balanced4": {
        "kind": "composite",
        "members": [
            "ema100_slope_long_flat:daily",
            "atr_expansion_short_filter:weekly",
            "breakout72_low_vol_long_flat:weekly",
            "bollinger_reversion_long_short:daily",
        ],
        "mode": "threshold_050",
        "logic": "Stable hard-audit combo: slow slope + ATR downside filter + low-vol breakout + Bollinger reversion.",
    },
    "mom20": {
        "kind": "single",
        "member": "naive_momentum_20_long_short:weekly",
        "logic": "Naive 20-bar time-series momentum baseline, included at low weight only.",
    },
    "breakout72_low_vol": {
        "kind": "single",
        "member": "breakout72_low_vol_long_flat:weekly",
        "logic": "Low-volatility 72-hour breakout trend continuation.",
    },
    "bollinger_reversion": {
        "kind": "single",
        "member": "bollinger_reversion_long_short:daily",
        "logic": "Daily Bollinger mean-reversion diversifier.",
    },
    "atr_expansion_filter": {
        "kind": "single",
        "member": "atr_expansion_short_filter:weekly",
        "logic": "ATR expansion trend/regime filter.",
    },
    "rsi_reversal": {
        "kind": "single",
        "member": "rsi_reversal_14_long_short:daily",
        "logic": "Daily RSI reversal pressure, distinct from slow trend and breakout exposure.",
    },
    "vwap168_trend": {
        "kind": "single",
        "member": "vwap168_trend_long_flat:weekly",
        "logic": "Long-only VWAP trend state using a slower flow-weighted anchor.",
    },
    "volume_confirmed_momentum": {
        "kind": "single",
        "member": "volume_confirmed_momentum:weekly",
        "logic": "Momentum only when volume participation is above normal.",
    },
    "vol_compression_trend": {
        "kind": "single",
        "member": "vol_compression_trend_long_flat:daily",
        "logic": "Trend exposure gated by lower realized volatility.",
    },
    "ema100_slope": {
        "kind": "single",
        "member": "ema100_slope_long_flat:daily",
        "logic": "Slow long-only EMA slope trend leg.",
    },
    "funding_carry": {
        "kind": "single",
        "member": "funding_carry_long_short:daily",
        "logic": "Carry leg using lagged realized perpetual funding: long negative funding, short expensive positive funding.",
    },
    "funding_extreme_reversal": {
        "kind": "single",
        "member": "funding_extreme_reversal_long_short:daily",
        "logic": "Contrarian pressure after extreme lagged funding z-scores.",
    },
    "trend_carry_aligned": {
        "kind": "single",
        "member": "trend_carry_aligned_long_short:weekly",
        "logic": "Trend exposure only when lagged funding does not fight the carry economics.",
    },
    "trend_no_euphoria": {
        "kind": "single",
        "member": "trend_no_euphoria_long_flat:weekly",
        "logic": "Long trend exposure filtered out during euphoric funding regimes.",
    },
}


def _split_member_name(name: str) -> tuple[str, str]:
    return name.rsplit(":", 1)


def _component_positions(base_positions: dict[str, pd.Series], index: pd.DatetimeIndex) -> dict[str, pd.Series]:
    out = {}
    for name, spec in COMPONENTS.items():
        if spec["kind"] == "single":
            rule, update = _split_member_name(spec["member"])
            out[name] = sr._hold_to_update(base_positions[rule], update)
        else:
            positions = []
            for member in spec["members"]:
                rule, update = _split_member_name(member)
                positions.append(sr._hold_to_update(base_positions[rule], update))
            out[name] = audit._combine_positions(positions, spec["mode"], index)
    return out


def _weight_grid(step: float = 0.1, max_active_components: int = MAX_ACTIVE_BLEND_COMPONENTS) -> list[dict[str, float]]:
    names = list(COMPONENTS)
    units = int(round(1.0 / step))
    rows = []

    def compositions(total: int, parts: int) -> list[tuple[int, ...]]:
        if parts == 1:
            return [(total,)]
        out = []
        for value in range(1, total - parts + 2):
            for rest in compositions(total - value, parts - 1):
                out.append((value,) + rest)
        return out

    for active_count in range(1, min(max_active_components, len(names)) + 1):
        for active_names in itertools.combinations(names, active_count):
            for values in compositions(units, active_count):
                rows.append({name: value * step for name, value in zip(active_names, values)})
                if len(rows) >= MAX_BLEND_GRID_ROWS:
                    return rows
    return rows


def _blend_position(components: dict[str, pd.Series], weights: dict[str, float], index: pd.DatetimeIndex) -> pd.Series:
    return sum((components[name].reindex(index).fillna(0.0) * weight for name, weight in weights.items()), start=pd.Series(0.0, index=index)).clip(-1.0, 1.0)


def _split_results(
    position: pd.Series,
    splits: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
    funding_rates: pd.Series | None = None,
) -> dict:
    return {
        split_name: sr._position_backtest(
            position.reindex(split_df.index),
            split_df,
            funding_rate_series=funding_rates,
        )
        for split_name, split_df in zip(["IS", "Val", "Holdout"], splits)
    }


def _val_subperiods(position: pd.Series, val_data: pd.DataFrame) -> list[dict]:
    return [sr._position_backtest(position.reindex(part.index), part) for part in _split_parts(val_data, 2)]


def _split_parts(df: pd.DataFrame, parts: int) -> list[pd.DataFrame]:
    indexes = [chunk for chunk in np.array_split(range(len(df)), parts)]
    return [df.iloc[list(index)] for index in indexes if len(index) > 0]


def _component_correlations(components: dict[str, pd.Series], weights: dict[str, float], val_index: pd.DatetimeIndex) -> list[dict]:
    rows = []
    names = [name for name, weight in weights.items() if weight > 0]
    for left, right in itertools.combinations(names, 2):
        corr = components[left].reindex(val_index).corr(components[right].reindex(val_index))
        if pd.isna(corr):
            corr = 0.0
        rows.append({"left": left, "right": right, "val_position_corr": float(corr)})
    return rows


def _passes_selection(results: dict, val_subperiods: list[dict], corrs: list[dict]) -> bool:
    val = results["Val"]
    return (
        results["IS"]["sharpe"] >= SELECTION_FILTERS["is_sharpe_min"]
        and val["sharpe"] >= SELECTION_FILTERS["val_sharpe_min"]
        and min(part["sharpe"] for part in val_subperiods) >= SELECTION_FILTERS["val_subperiod_sharpe_min"]
        and val["max_drawdown"] <= SELECTION_FILTERS["val_drawdown_max"]
        and val["turnover"] <= SELECTION_FILTERS["val_turnover_max"]
        and all(abs(item["val_position_corr"]) <= SELECTION_FILTERS["max_abs_val_component_corr"] for item in corrs)
    )


def main() -> int:
    df = data_module.load_data(config.INST_ID, config.BAR, config.HISTORY_DAYS)
    funding_rates = data_module.load_funding_rates(config.INST_ID, config.HISTORY_DAYS)
    splits = data_module.split_data(df)
    split_names = ["IS", "Val", "Holdout"]
    funding_observations_by_split = {
        name: int(funding_rates.reindex(split_df.index).notna().sum())
        for name, split_df in zip(split_names, splits)
    }
    base_positions = sr._make_positions(df, funding_rates)
    components = _component_positions(base_positions, df.index)

    baselines = {}
    for name, position in audit._baseline_positions(base_positions).items():
        baselines[name] = {
            "splits": _split_results(position, splits, funding_rates),
            "rolling_90d": audit._rolling_audit(position, df),
        }

    selected = []
    generated_count = 0
    for weights in _weight_grid(step=0.1):
        generated_count += 1
        position = _blend_position(components, weights, df.index)
        results = _split_results(position, splits, funding_rates)
        val_subperiods = _val_subperiods(position, splits[1])
        corrs = _component_correlations(components, weights, splits[1].index)
        if not _passes_selection(results, val_subperiods, corrs):
            continue
        rolling = audit._rolling_audit(position, df)
        dominance = audit._baseline_dominance({"splits": results}, rolling, baselines)
        hard_checks = {
            "holdout_noncollapse": results["Holdout"]["sharpe"] >= 0.0 and results["Holdout"]["max_drawdown"] <= 0.45,
            "rolling_positive_windows": rolling["positive_windows"] >= 7,
            "rolling_min_sharpe": rolling["min_sharpe"] >= -2.25,
            "beats_all_baselines": dominance["beats_all_baselines"],
        }
        if all(hard_checks.values()):
            status = "blend_full_pass"
        elif hard_checks["holdout_noncollapse"]:
            status = "blend_holdout_survived"
        else:
            status = "blend_holdout_failed"
        selected.append(
            {
                "name": "+".join(f"{name}:{weight:.1f}" for name, weight in weights.items()),
                "weights": weights,
                "status": status,
                "selection_results": {
                    "IS": results["IS"],
                    "Val": results["Val"],
                    "val_subperiods": val_subperiods,
                    "min_val_subperiod_sharpe": min(part["sharpe"] for part in val_subperiods),
                    "val_component_correlations": corrs,
                },
                "audit_results": {
                    "Holdout": results["Holdout"],
                    "rolling_90d": rolling,
                    "baseline_dominance": dominance,
                    "hard_checks": hard_checks,
                },
                "splits": results,
                "val_subperiods": val_subperiods,
                "rolling_90d": rolling,
                "baseline_dominance": dominance,
                "val_component_correlations": corrs,
                "component_specs": {name: COMPONENTS[name] for name in weights},
            }
        )

    selected.sort(
        key=lambda row: (
            row["selection_results"]["Val"]["sharpe"],
            row["selection_results"]["min_val_subperiod_sharpe"],
            row["selection_results"]["IS"]["sharpe"],
            -row["selection_results"]["Val"]["max_drawdown"],
            -row["selection_results"]["Val"]["turnover"],
        ),
        reverse=True,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "created_at_utc": timestamp,
        "selection_filters": SELECTION_FILTERS,
        "search_limits": {
            "max_active_blend_components": MAX_ACTIVE_BLEND_COMPONENTS,
            "max_blend_grid_rows": MAX_BLEND_GRID_ROWS,
        },
        "funding_source": {
            "kind": "okx_public_funding_rate_history",
            "inst_id": config.INST_ID,
            "requested_history_days": config.HISTORY_DAYS,
            "observations_on_bars": int(funding_rates.reindex(df.index).notna().sum()),
            "observations_by_split": funding_observations_by_split,
            "start": str(funding_rates.index.min()),
            "end": str(funding_rates.index.max()),
        },
        "selection_policy": {
            "candidate_gate": "IS and Validation only",
            "ranking_fields": [
                "Val.sharpe",
                "min_val_subperiod_sharpe",
                "IS.sharpe",
                "negative Val.max_drawdown",
                "negative Val.turnover",
            ],
            "holdout_used_for_selection": False,
            "holdout_used_for_sorting": False,
        },
        "component_library": COMPONENTS,
        "generated_count": generated_count,
        "selected_count": len(selected),
        "full_pass_count": sum(row["status"] == "blend_full_pass" for row in selected),
        "baselines": baselines,
        "selected": selected,
    }
    out_path = Path(config.LOG_DIR) / f"strategy_blend_report_{timestamp}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"WROTE {out_path}")
    print(f"GENERATED {generated_count} SELECTED {len(selected)} FULL_PASS {report['full_pass_count']}")
    for row in selected[:30]:
        is_ = row["splits"]["IS"]
        val = row["splits"]["Val"]
        hold = row["splits"]["Holdout"]
        roll = row["rolling_90d"]
        print(
            f"{row['status']:20s} IS {is_['sharpe']:6.2f} Val {val['sharpe']:6.2f} "
            f"Hold {hold['sharpe']:6.2f} HDD {hold['max_drawdown']:5.2%} "
            f"Roll+ {roll['positive_windows']}/{roll['window_count']} "
            f"BeatAll {row['baseline_dominance']['beats_all_baselines']} :: {row['weights']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
