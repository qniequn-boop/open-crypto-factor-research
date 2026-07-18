"""Rolling-window audit for strategy combo candidates.

The combo search report can produce many candidates. This audit script applies
harder, pre-declared filters and then checks non-overlapping 90-day windows
against common baselines.
"""

from __future__ import annotations

import glob
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
import data as data_module
import strategy_research as sr


AUDIT_FILTERS = {
    "is_sharpe_min": 0.0,
    "val_sharpe_min": 2.0,
    "holdout_sharpe_min": 0.0,
    "holdout_drawdown_max": 0.45,
    "rolling_positive_windows_min": 7,
    "rolling_min_sharpe_min": -2.25,
}


BASELINE_DOMINANCE_FIELDS = {
    "require_val_sharpe_gt": True,
    "require_holdout_sharpe_gt": True,
    "require_holdout_drawdown_lte": True,
    "require_rolling_positive_windows_gte": True,
}


def _latest_combo_report() -> Path:
    paths = sorted(glob.glob(str(Path(config.LOG_DIR) / "strategy_combo_report_*.json")))
    if not paths:
        raise FileNotFoundError("no strategy_combo_report_*.json found; run strategy_combo_research.py first")
    return Path(paths[-1])


def _split_member_name(name: str) -> tuple[str, str]:
    rule, update = name.rsplit(":", 1)
    return rule, update


def _combine_positions(positions: list[pd.Series], mode: str, index: pd.DatetimeIndex) -> pd.Series:
    average = sum((position.reindex(index).fillna(0.0) for position in positions), start=pd.Series(0.0, index=index))
    average = average / len(positions)
    if mode == "avg":
        return average.clip(-1.0, 1.0)
    threshold = 0.25 if mode == "threshold_025" else 0.50
    out = pd.Series(0.0, index=index)
    out[average >= threshold] = 1.0
    out[average <= -threshold] = -1.0
    return out


def _combo_position(combo: dict, base_positions: dict[str, pd.Series], index: pd.DatetimeIndex) -> pd.Series:
    positions = []
    member_names = combo.get("member_names") or [member["name"] for member in combo.get("members", [])]
    for member_name in member_names:
        rule, update = _split_member_name(member_name)
        positions.append(sr._hold_to_update(base_positions[rule], update))
    return _combine_positions(positions, combo["mode"], index)


def _rolling_windows(df: pd.DataFrame, days: int = 90) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]]:
    windows = []
    current = df.index.min()
    end = df.index.max()
    while current < end:
        next_time = current + pd.Timedelta(days=days)
        part = df[(df.index >= current) & (df.index < next_time)]
        if len(part) > 200:
            windows.append((current, next_time, part))
        current = next_time
    return windows


def _rolling_audit(position: pd.Series, df: pd.DataFrame, funding_rates: pd.Series | None = None) -> dict:
    windows = []
    for start, end, part in _rolling_windows(df):
        metrics = sr._position_backtest(position.reindex(part.index), part, funding_rate_series=funding_rates)
        windows.append(
            {
                "start": str(start),
                "end_exclusive": str(end),
                "bars": len(part),
                "sharpe": metrics["sharpe"],
                "max_drawdown": metrics["max_drawdown"],
                "turnover": metrics["turnover"],
                "total_return": metrics["total_return"],
                "exposure": metrics["exposure"],
            }
        )
    sharpes = [window["sharpe"] for window in windows]
    return {
        "window_days": 90,
        "window_count": len(windows),
        "positive_windows": int(sum(value > 0 for value in sharpes)),
        "min_sharpe": float(min(sharpes)) if sharpes else 0.0,
        "avg_sharpe": float(sum(sharpes) / len(sharpes)) if sharpes else 0.0,
        "windows": windows,
    }


def _passes_hard_audit(combo: dict, rolling: dict) -> bool:
    splits = combo["splits"]
    return (
        splits["IS"]["sharpe"] >= AUDIT_FILTERS["is_sharpe_min"]
        and splits["Val"]["sharpe"] >= AUDIT_FILTERS["val_sharpe_min"]
        and splits["Holdout"]["sharpe"] >= AUDIT_FILTERS["holdout_sharpe_min"]
        and splits["Holdout"]["max_drawdown"] <= AUDIT_FILTERS["holdout_drawdown_max"]
        and rolling["positive_windows"] >= AUDIT_FILTERS["rolling_positive_windows_min"]
        and rolling["min_sharpe"] >= AUDIT_FILTERS["rolling_min_sharpe_min"]
    )


def _baseline_dominance(combo: dict, rolling: dict, baselines: dict) -> dict:
    comparisons = {}
    for name, payload in baselines.items():
        baseline_val = payload["splits"]["Val"]
        baseline_holdout = payload["splits"]["Holdout"]
        baseline_roll = payload["rolling_90d"]
        checks = {
            "val_sharpe_gt": combo["splits"]["Val"]["sharpe"] > baseline_val["sharpe"],
            "holdout_sharpe_gt": combo["splits"]["Holdout"]["sharpe"] > baseline_holdout["sharpe"],
            "holdout_drawdown_lte": combo["splits"]["Holdout"]["max_drawdown"] <= baseline_holdout["max_drawdown"],
            "rolling_positive_windows_gte": rolling["positive_windows"] >= baseline_roll["positive_windows"],
        }
        comparisons[name] = {
            "checks": checks,
            "beats_baseline": all(checks.values()),
            "baseline": {
                "val_sharpe": baseline_val["sharpe"],
                "holdout_sharpe": baseline_holdout["sharpe"],
                "holdout_drawdown": baseline_holdout["max_drawdown"],
                "rolling_positive_windows": baseline_roll["positive_windows"],
            },
            "combo": {
                "val_sharpe": combo["splits"]["Val"]["sharpe"],
                "holdout_sharpe": combo["splits"]["Holdout"]["sharpe"],
                "holdout_drawdown": combo["splits"]["Holdout"]["max_drawdown"],
                "rolling_positive_windows": rolling["positive_windows"],
            },
        }
    return {
        "fields": BASELINE_DOMINANCE_FIELDS,
        "comparisons": comparisons,
        "beats_all_baselines": all(item["beats_baseline"] for item in comparisons.values()),
        "failed_baselines": [name for name, item in comparisons.items() if not item["beats_baseline"]],
    }


def _baseline_positions(base_positions: dict[str, pd.Series]) -> dict[str, pd.Series]:
    return {
        "buy_hold_direct": sr._hold_to_update(base_positions["buy_hold_direct"], "weekly"),
        "naive_momentum_20_weekly": sr._hold_to_update(base_positions["naive_momentum_20_long_short"], "weekly"),
        "naive_mean_reversion_50_weekly": sr._hold_to_update(base_positions["naive_mean_reversion_50_long_short"], "weekly"),
        "rsi_reversal_14_daily": sr._hold_to_update(base_positions["rsi_reversal_14_long_short"], "daily"),
        "bollinger_reversion_daily": sr._hold_to_update(base_positions["bollinger_reversion_long_short"], "daily"),
        "random_noise_weekly": sr._hold_to_update(base_positions["random_noise_control"], "weekly"),
    }


def main() -> int:
    df = data_module.load_data(config.INST_ID, config.BAR, config.HISTORY_DAYS)
    funding_rates = data_module.load_funding_rates(config.INST_ID, config.HISTORY_DAYS)
    splits = data_module.split_data(df)
    base_positions = sr._make_positions(df, funding_rates)
    report_path = _latest_combo_report()
    combo_report = json.loads(report_path.read_text(encoding="utf-8"))
    universe = combo_report["universes"]["baseline_allowed"]
    combos = universe["combos"]
    candidate_lookup = {candidate["name"]: candidate for candidate in universe["candidates"]}

    baselines = {}
    for name, position in _baseline_positions(base_positions).items():
        baselines[name] = {
            "splits": {
                split_name: sr._position_backtest(
                    position.reindex(split_df.index),
                    split_df,
                    funding_rate_series=funding_rates,
                )
                for split_name, split_df in zip(["IS", "Val", "Holdout"], splits)
            },
            "rolling_90d": _rolling_audit(position, df, funding_rates),
        }

    audited = []
    for combo in combos:
        if combo["status"] != "combo_audit_pass":
            continue
        position = _combo_position(combo, base_positions, df.index)
        rolling = _rolling_audit(position, df, funding_rates)
        hard_pass = _passes_hard_audit(combo, rolling)
        dominance = _baseline_dominance(combo, rolling, baselines)
        if hard_pass and dominance["beats_all_baselines"]:
            status = "hard_audit_and_baseline_pass"
        elif hard_pass:
            status = "hard_audit_pass"
        else:
            status = "hard_audit_failed"
        audited.append(
            {
                "name": combo["name"],
                "mode": combo["mode"],
                "status": status,
                "splits": combo["splits"],
                "val_subperiods": combo["val_subperiods"],
                "min_val_subperiod_sharpe": combo["min_val_subperiod_sharpe"],
                "rolling_90d": rolling,
                "baseline_dominance": dominance,
                "members": [
                    candidate_lookup.get(name, {"name": name})
                    for name in (combo.get("member_names") or [member["name"] for member in combo.get("members", [])])
                ],
                "val_position_correlations": combo["val_position_correlations"],
            }
        )

    audited.sort(
        key=lambda row: (
            row["status"] == "hard_audit_and_baseline_pass",
            row["status"] == "hard_audit_pass",
            row["rolling_90d"]["positive_windows"],
            row["rolling_90d"]["min_sharpe"],
            row["splits"]["Val"]["sharpe"] + row["splits"]["Holdout"]["sharpe"],
        ),
        reverse=True,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "created_at_utc": timestamp,
        "source_combo_report": str(report_path),
        "audit_filters": AUDIT_FILTERS,
        "baseline_count": len(baselines),
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
        "baselines": baselines,
        "audited_combo_count": len(audited),
        "hard_pass_count": sum(row["status"] in ("hard_audit_pass", "hard_audit_and_baseline_pass") for row in audited),
        "hard_and_baseline_pass_count": sum(row["status"] == "hard_audit_and_baseline_pass" for row in audited),
        "audited_combos": audited,
    }

    out_path = Path(config.LOG_DIR) / f"strategy_audit_report_{timestamp}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"WROTE {out_path}")
    print("BASELINES")
    for name, payload in baselines.items():
        val = payload["splits"]["Val"]
        hold = payload["splits"]["Holdout"]
        roll = payload["rolling_90d"]
        print(
            f"{name:34s} Val {val['sharpe']:6.2f} Hold {hold['sharpe']:6.2f} "
            f"HDD {hold['max_drawdown']:5.2%} Roll+ {roll['positive_windows']}/{roll['window_count']} "
            f"RollMin {roll['min_sharpe']:6.2f}"
        )

    print("\nTOP_AUDITED_COMBOS")
    for row in audited[:20]:
        val = row["splits"]["Val"]
        hold = row["splits"]["Holdout"]
        roll = row["rolling_90d"]
        print(
            f"{row['status']:18s} Val {val['sharpe']:6.2f} Hold {hold['sharpe']:6.2f} "
            f"HDD {hold['max_drawdown']:5.2%} Roll+ {roll['positive_windows']}/{roll['window_count']} "
            f"BeatAll {row['baseline_dominance']['beats_all_baselines']} "
            f"RollMin {roll['min_sharpe']:6.2f} :: {row['mode']} {row['name']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
