"""Validation-selected strategy combo diagnostics.

Selection rules use only IS/Validation evidence. Holdout is reported as an
audit field and must not be used to tune thresholds or weights.
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
import strategy_research as sr


EXCLUDED_BASELINE_PATTERNS = (
    "buy_hold_direct",
    "random_noise_control",
    "naive_momentum",
    "naive_mean_reversion",
    "rsi_reversal_14",
    "bollinger_reversion",
    "ema50_200",
)

MAX_COMBO_CANDIDATES = 12
MAX_COMBO_SIZE = 4
MAX_COMBOS_EVALUATED = 5000


def _candidate_records(
    df: pd.DataFrame,
    splits: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
    excluded_patterns: tuple[str, ...],
    funding_rates: pd.Series | None = None,
) -> list[dict]:
    records = []
    for rule, raw_position in sr._make_positions(df, funding_rates).items():
        if any(pattern in rule for pattern in excluded_patterns):
            continue
        for update in ["hourly", "daily", "weekly"]:
            position = sr._hold_to_update(raw_position, update)
            metrics = sr._split_results(position, splits, funding_rates)
            val_subperiods = sr._val_subperiods(position, splits[1], funding_rate_series=funding_rates)
            min_val_sub = min(part["sharpe"] for part in val_subperiods)
            val = metrics["Val"]
            selected = (
                val["sharpe"] > 0.70
                and min_val_sub > 0.0
                and val["max_drawdown"] < 0.25
                and val["turnover"] < 0.02
            )
            if selected:
                records.append(
                    {
                        "name": f"{rule}:{update}",
                        "rule": rule,
                        "update": update,
                        "position": position,
                        "splits": metrics,
                        "val_subperiods": val_subperiods,
                        "min_val_subperiod_sharpe": min_val_sub,
                    }
                )
    return records


def _combo_position(items: tuple[dict, ...], mode: str, index: pd.DatetimeIndex) -> pd.Series:
    average = sum((item["position"].reindex(index).fillna(0.0) for item in items), start=pd.Series(0.0, index=index))
    average = average / len(items)
    if mode == "avg":
        return average.clip(-1.0, 1.0)
    out = pd.Series(0.0, index=index)
    if mode == "threshold_025":
        threshold = 0.25
    elif mode == "threshold_050":
        threshold = 0.50
    else:
        raise ValueError(f"unknown combo mode: {mode}")
    out[average >= threshold] = 1.0
    out[average <= -threshold] = -1.0
    return out


def _pairwise_corr_ok(items: tuple[dict, ...], val_index: pd.DatetimeIndex, max_abs_corr: float = 0.75) -> tuple[bool, list[dict]]:
    corrs = []
    for left, right in itertools.combinations(items, 2):
        corr = left["position"].reindex(val_index).corr(right["position"].reindex(val_index))
        if pd.isna(corr):
            corr = 0.0
        corrs.append({"left": left["name"], "right": right["name"], "val_position_corr": float(corr)})
        if abs(corr) > max_abs_corr:
            return False, corrs
    return True, corrs


def _combo_status(metrics: dict, val_subperiods: list[dict]) -> str:
    val = metrics["Val"]
    holdout = metrics["Holdout"]
    min_val_sub = min(part["sharpe"] for part in val_subperiods)
    if val["sharpe"] <= 0.80 or min_val_sub <= -0.25:
        return "combo_rejected_val"
    if holdout["sharpe"] >= -0.50 and holdout["max_drawdown"] <= 0.45:
        return "combo_audit_pass"
    return "combo_audit_failed"


def _generate_combos(
    df: pd.DataFrame,
    splits: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
    records: list[dict],
    funding_rates: pd.Series | None = None,
) -> list[dict]:
    val_index = splits[1].index
    combos = []
    generated_count = 0
    records = sorted(
        records,
        key=lambda row: (
            row["splits"]["Val"]["sharpe"],
            row["min_val_subperiod_sharpe"],
            -row["splits"]["Val"]["max_drawdown"],
            -row["splits"]["Val"]["turnover"],
        ),
        reverse=True,
    )[:MAX_COMBO_CANDIDATES]

    for size in range(2, min(MAX_COMBO_SIZE, len(records)) + 1):
        for items in itertools.combinations(records, size):
            corr_ok, corr_matrix = _pairwise_corr_ok(items, val_index)
            if not corr_ok:
                continue
            for mode in ["avg", "threshold_025", "threshold_050"]:
                if generated_count >= MAX_COMBOS_EVALUATED:
                    break
                generated_count += 1
                position = _combo_position(items, mode, df.index)
                metrics = sr._split_results(position, splits, funding_rates)
                val_subperiods = sr._val_subperiods(position, splits[1], funding_rate_series=funding_rates)
                status = _combo_status(metrics, val_subperiods)
                if status == "combo_rejected_val":
                    continue
                combos.append(
                    {
                        "name": "+".join(item["name"] for item in items),
                        "mode": mode,
                        "member_names": [item["name"] for item in items],
                        "val_position_correlations": corr_matrix,
                        "splits": metrics,
                        "val_subperiods": val_subperiods,
                        "min_val_subperiod_sharpe": min(part["sharpe"] for part in val_subperiods),
                        "status": status,
                    }
                )
            if generated_count >= MAX_COMBOS_EVALUATED:
                break
        if generated_count >= MAX_COMBOS_EVALUATED:
            break

    combos.sort(
        key=lambda row: (
            row["status"] == "combo_audit_pass",
            row["splits"]["Val"]["sharpe"],
            row["splits"]["Holdout"]["sharpe"],
        ),
        reverse=True,
    )
    return combos, generated_count


def _serializable_candidate(record: dict) -> dict:
    return {
        "name": record["name"],
        "rule": record["rule"],
        "update": record["update"],
        "splits": record["splits"],
        "val_subperiods": record["val_subperiods"],
        "min_val_subperiod_sharpe": record["min_val_subperiod_sharpe"],
    }


def main() -> int:
    df = data_module.load_data(config.INST_ID, config.BAR, config.HISTORY_DAYS)
    funding_rates = data_module.load_funding_rates(config.INST_ID, config.HISTORY_DAYS)
    splits = data_module.split_data(df)
    universes = {
        "non_baseline": EXCLUDED_BASELINE_PATTERNS,
        "baseline_allowed": ("buy_hold_direct", "random_noise_control"),
    }
    universe_reports = {}
    for label, excluded_patterns in universes.items():
        records = _candidate_records(df, splits, excluded_patterns, funding_rates)
        combos, generated_count = _generate_combos(df, splits, records, funding_rates)
        universe_reports[label] = {
            "excluded_patterns": excluded_patterns,
            "candidate_count": len(records),
            "candidates": [_serializable_candidate(record) for record in records],
            "generated_combo_count": generated_count,
            "combo_count": len(combos),
            "combos": combos,
        }

    primary = universe_reports["non_baseline"]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "created_at_utc": timestamp,
        "selection_protocol": {
            "uses_holdout_for_selection": False,
            "candidate_val_sharpe_min": 0.70,
            "candidate_min_val_subperiod_sharpe_min": 0.0,
            "candidate_val_drawdown_max": 0.25,
            "candidate_val_turnover_max": 0.02,
            "combo_val_sharpe_min": 0.80,
            "combo_min_val_subperiod_sharpe_min": -0.25,
            "holdout_audit_sharpe_min": -0.50,
            "holdout_audit_drawdown_max": 0.45,
            "max_abs_val_position_corr": 0.75,
            "max_combo_candidates": MAX_COMBO_CANDIDATES,
            "max_combo_size": MAX_COMBO_SIZE,
            "max_combos_evaluated": MAX_COMBOS_EVALUATED,
            "combo_candidate_truncation": "Validation-only ranking; Holdout is not used to choose the truncated search set.",
            "universes": universes,
            "funding_cost_included": True,
        },
        "funding_source": {
            "kind": "okx_public_funding_rate_history",
            "inst_id": config.INST_ID,
            "requested_history_days": config.HISTORY_DAYS,
            "observations_by_split": {
                name: int(funding_rates.reindex(split_df.index).notna().sum())
                for name, split_df in zip(["IS", "Val", "Holdout"], splits)
            },
            "start": str(funding_rates.index.min()),
            "end": str(funding_rates.index.max()),
        },
        "candidate_count": primary["candidate_count"],
        "candidates": primary["candidates"],
        "combo_count": primary["combo_count"],
        "combos": primary["combos"],
        "universes": universe_reports,
    }

    out_path = Path(config.LOG_DIR) / f"strategy_combo_report_{timestamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"WROTE {out_path}")
    for label, universe in universe_reports.items():
        print(f"\nUNIVERSE {label}")
        print("SELECTED_CANDIDATES")
        records_for_print = sorted(universe["candidates"], key=lambda item: item["splits"]["Val"]["sharpe"], reverse=True)
        for record in records_for_print:
            print(
                f"{record['name']:38s} "
                f"Val {record['splits']['Val']['sharpe']:6.2f} "
                f"MinSub {record['min_val_subperiod_sharpe']:6.2f} "
                f"Hold {record['splits']['Holdout']['sharpe']:6.2f}"
            )

        print("\nTOP_COMBOS")
        for combo in universe["combos"][:20]:
            val = combo["splits"]["Val"]
            hold = combo["splits"]["Holdout"]
            print(
                f"{combo['status']:18s} {combo['mode']:13s} "
                f"Val {val['sharpe']:6.2f} MinSub {combo['min_val_subperiod_sharpe']:6.2f} "
                f"Hold {hold['sharpe']:6.2f} HDD {hold['max_drawdown']:5.2%} "
                f"Turn {val['turnover']:.4f} :: {combo['name']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
