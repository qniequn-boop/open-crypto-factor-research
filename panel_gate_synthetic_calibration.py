"""End-to-end economic power calibration for the draft panel gate policy."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import panel_gate_calibration as inference
import panel_gate_policy as policy
import panel_overfit_audit as overfit


SCENARIOS = {
    "stationary_complete": {
        "holdout_alpha_multiplier": 1.0,
        "adverse_funding_bps_per_day": 0.0,
        "static_missing_asset_rate": 0.0,
    },
    "regime_decay": {
        "holdout_alpha_multiplier": 0.20,
        "adverse_funding_bps_per_day": 0.0,
        "static_missing_asset_rate": 0.0,
    },
    "funding_stress": {
        "holdout_alpha_multiplier": 1.0,
        "adverse_funding_bps_per_day": 4.0,
        "static_missing_asset_rate": 0.0,
    },
    "basis_sparse": {
        "holdout_alpha_multiplier": 1.0,
        "adverse_funding_bps_per_day": 0.0,
        "static_missing_asset_rate": 0.15,
    },
}


def _rank_weights(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    weights = np.zeros_like(values, dtype=float)
    for row in range(values.shape[0]):
        columns = np.flatnonzero(valid[row] & np.isfinite(values[row]))
        if len(columns) < 2:
            continue
        order = np.argsort(values[row, columns], kind="mergesort")
        ranks = np.empty(len(columns), dtype=float)
        ranks[order] = np.arange(1, len(columns) + 1, dtype=float)
        centered = ranks / len(columns) - 0.5
        centered -= centered.mean()
        gross = np.abs(centered).sum()
        if gross > 0:
            weights[row, columns] = centered / gross
    return weights


def _spearman_rows(signal: np.ndarray, future_return: np.ndarray, valid: np.ndarray) -> np.ndarray:
    output = np.full(signal.shape[0], np.nan, dtype=float)
    for row in range(signal.shape[0]):
        columns = np.flatnonzero(valid[row] & np.isfinite(signal[row]) & np.isfinite(future_return[row]))
        if len(columns) < 4:
            continue
        x_order = np.argsort(signal[row, columns], kind="mergesort")
        y_order = np.argsort(future_return[row, columns], kind="mergesort")
        x_rank = np.empty(len(columns), dtype=float)
        y_rank = np.empty(len(columns), dtype=float)
        x_rank[x_order] = np.arange(len(columns), dtype=float)
        y_rank[y_order] = np.arange(len(columns), dtype=float)
        output[row] = float(np.corrcoef(x_rank, y_rank)[0, 1])
    return output


def _annualized_daily_sharpe(values: np.ndarray) -> float:
    clean = values[np.isfinite(values)]
    if len(clean) < 2 or float(clean.std(ddof=1)) == 0.0:
        return 0.0
    return float(clean.mean() / clean.std(ddof=1) * math.sqrt(365.0))


def _max_drawdown(values: np.ndarray) -> float:
    equity = np.cumsum(np.nan_to_num(values, nan=0.0))
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    return float(np.max(peak - equity)) if len(equity) else 0.0


def _wilson_interval(successes: int, observations: int, z: float = 1.959963984540054) -> list[float]:
    if observations <= 0:
        return [0.0, 1.0]
    rate = successes / observations
    denominator = 1.0 + z**2 / observations
    center = (rate + z**2 / (2.0 * observations)) / denominator
    radius = z * math.sqrt(rate * (1.0 - rate) / observations + z**2 / (4.0 * observations**2)) / denominator
    lower = 0.0 if successes == 0 else float(max(0.0, center - radius))
    upper = 1.0 if successes == observations else float(min(1.0, center + radius))
    return [lower, upper]


def _split_slices(days: int) -> dict[str, slice]:
    is_end = int(days * 0.60)
    val_end = int(days * 0.80)
    return {"IS": slice(0, is_end), "Val": slice(is_end, val_end), "Holdout": slice(val_end, days)}


def _portfolio_metrics(net: np.ndarray, turnover: np.ndarray, part: slice) -> dict[str, float]:
    values = net[part]
    return {
        "sharpe": _annualized_daily_sharpe(values),
        "total_return": float(np.nansum(values)),
        "max_drawdown": _max_drawdown(values),
        "hourly_equivalent_turnover": float(np.nanmean(turnover[part]) / 24.0),
    }


def _mean_ic(values: np.ndarray, part: slice) -> float:
    selected = values[part]
    return float(np.nanmean(selected)) if np.isfinite(selected).any() else 0.0


def _rolling_checks(ic: np.ndarray, net: np.ndarray) -> tuple[bool, bool]:
    ic_rows = []
    sharpe_rows = []
    for start in range(0, len(ic), 90):
        end = min(start + 90, len(ic))
        if end - start < 30:
            continue
        ic_rows.append(float(np.nanmean(ic[start:end])))
        sharpe_rows.append(_annualized_daily_sharpe(net[start:end]))
    ic_pass = bool(ic_rows and np.mean(np.asarray(ic_rows) > 0) >= 0.60 and min(ic_rows) > -0.10)
    sharpe_pass = bool(sharpe_rows and np.mean(np.asarray(sharpe_rows) > 0) >= 0.45 and min(sharpe_rows) > -3.0)
    return ic_pass, sharpe_pass


def _family_neutral(signal: np.ndarray, valid: np.ndarray, families: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    output = np.full_like(signal, np.nan, dtype=float)
    output_valid = np.zeros_like(valid, dtype=bool)
    for family in np.unique(families):
        members = np.flatnonzero(families == family)
        for row in range(signal.shape[0]):
            selected = members[valid[row, members] & np.isfinite(signal[row, members])]
            if len(selected) < 2:
                continue
            output[row, selected] = signal[row, selected] - signal[row, selected].mean()
            output_valid[row, selected] = True
    return output, output_valid


def _ar1_matrix(rng: np.random.Generator, days: int, columns: int, rho: float = 0.10) -> np.ndarray:
    innovations = rng.normal(size=(days, columns))
    output = np.empty_like(innovations)
    output[0] = innovations[0]
    scale = math.sqrt(1.0 - rho**2)
    for day in range(1, days):
        output[day] = rho * output[day - 1] + scale * innovations[day]
    return output


def _correlated_trial_returns(
    rng: np.random.Generator,
    candidate_net: np.ndarray,
    *,
    trial_count: int,
    cost_drag: float,
) -> np.ndarray:
    """Build the complete selection batch with correlated null candidate families."""
    trial_count = max(int(trial_count), 2)
    alternative_count = trial_count - 1
    family_ids = np.arange(alternative_count) // 5
    family_count = int(family_ids.max()) + 1
    common = _ar1_matrix(rng, len(candidate_net), 1)
    family = _ar1_matrix(rng, len(candidate_net), family_count)
    idiosyncratic = _ar1_matrix(rng, len(candidate_net), alternative_count)
    standardized = (
        math.sqrt(0.10) * common
        + math.sqrt(0.45) * family[:, family_ids]
        + math.sqrt(0.45) * idiosyncratic
    )
    candidate_scale = float(np.nanstd(candidate_net, ddof=1))
    if not np.isfinite(candidate_scale) or candidate_scale <= 0.0:
        candidate_scale = 0.01
    alternatives = standardized * candidate_scale - float(cost_drag)
    return np.column_stack([candidate_net, alternatives])


def simulate_gate_decision(
    *,
    seed: int,
    target_ic: float,
    scope: str,
    pass_critical_tstat: float,
    watchlist_critical_tstat: float,
    days: int = 730,
    asset_count: int = 40,
    total_cost_bps: float = 7.0,
    signal_trial_count: int = 51,
    scenario: str = "stationary_complete",
) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown_scenario:{scenario}")
    scenario_spec = SCENARIOS[scenario]
    rng = np.random.default_rng(seed)
    scores = np.empty((days, asset_count), dtype=float)
    scores[0] = rng.normal(size=asset_count)
    for day in range(1, days):
        scores[day] = 0.25 * scores[day - 1] + math.sqrt(1.0 - 0.25**2) * rng.normal(size=asset_count)

    noise = rng.normal(size=(days, asset_count))
    returns = np.empty_like(scores)
    returns[0] = 0.04 * noise[0]
    loading = float(np.clip(target_ic, -0.95, 0.95))
    loadings = np.full(days - 1, loading)
    holdout_start = _split_slices(days)["Holdout"].start
    loadings[max(holdout_start - 1, 0):] *= float(scenario_spec["holdout_alpha_multiplier"])
    returns[1:] = 0.04 * (
        loadings[:, None] * scores[:-1]
        + np.sqrt(np.maximum(1.0 - loadings**2, 1e-9))[:, None] * noise[1:]
    )
    returns += rng.normal(0.0, 0.015, size=(days, 1))

    liquidity_order = np.arange(asset_count, dtype=float)
    large_assets = np.argsort(liquidity_order)[-8:]
    large_mask = np.zeros((days, asset_count), dtype=bool)
    large_mask[:, large_assets] = True
    valid = np.ones((days, asset_count), dtype=bool)
    if scope == "large_liquid_only":
        valid &= large_mask
    elif scope != "full_panel":
        raise ValueError(f"unknown_scope:{scope}")
    missing_rate = float(scenario_spec["static_missing_asset_rate"])
    if missing_rate > 0.0:
        available_assets = rng.random(asset_count) >= missing_rate
        valid &= available_assets[None, :]

    raw_weights = _rank_weights(scores, valid)
    held_weights = np.vstack([np.zeros((1, asset_count)), raw_weights[:-1]])
    turnover = np.abs(np.diff(held_weights, axis=0, prepend=np.zeros((1, asset_count)))).sum(axis=1)
    gross = (held_weights * returns).sum(axis=1)
    adverse_funding_cost = float(scenario_spec["adverse_funding_bps_per_day"]) / 10000.0
    exposure = np.abs(held_weights).sum(axis=1)
    net = gross - turnover * total_cost_bps / 10000.0 - exposure * adverse_funding_cost

    signal_for_return = np.vstack([np.full((1, asset_count), np.nan), scores[:-1]])
    ic = _spearman_rows(signal_for_return, returns, valid)
    large_ic = _spearman_rows(signal_for_return, returns, large_mask)
    splits = _split_slices(days)
    split_metrics = {name: _portfolio_metrics(net, turnover, part) for name, part in splits.items()}
    rolling_ic, rolling_sharpe = _rolling_checks(ic, net)

    bucket_edges = np.array_split(np.argsort(liquidity_order), 3)
    bucket_val = []
    bucket_holdout = []
    for assets in bucket_edges:
        mask = np.zeros_like(valid)
        mask[:, assets] = True
        bucket_ic = _spearman_rows(signal_for_return, returns, mask & valid)
        bucket_val.append(_mean_ic(bucket_ic, splits["Val"]))
        bucket_holdout.append(_mean_ic(bucket_ic, splits["Holdout"]))

    families = np.arange(asset_count) % 5
    family_signal, family_valid = _family_neutral(signal_for_return, valid, families)
    family_ic = _spearman_rows(family_signal, returns, family_valid)

    cost_drag = float(np.nanmean(turnover) * total_cost_bps / 10000.0 + adverse_funding_cost)
    trial_returns = _correlated_trial_returns(
        rng,
        net,
        trial_count=signal_trial_count,
        cost_drag=cost_drag,
    )
    baseline_sharpes = [
        _annualized_daily_sharpe(trial_returns[splits["Val"], column])
        for column in range(1, min(7, trial_returns.shape[1]))
    ]
    val_index = pd.date_range("2020-01-01", periods=splits["Val"].stop - splits["Val"].start, freq="D", tz="UTC")
    selection_index = pd.date_range("2020-01-01", periods=splits["Val"].stop, freq="D", tz="UTC")
    val_trial_sharpes = [
        overfit.unannualized_sharpe(pd.Series(trial_returns[splits["Val"], column], index=val_index))
        for column in range(trial_returns.shape[1])
    ]
    dsr = overfit.deflated_sharpe_audit(
        pd.Series(net[splits["Val"]], index=val_index),
        n_trials=signal_trial_count,
        observed_trial_sharpes=val_trial_sharpes,
    )
    pbo = overfit.cscv_pbo_audit(
        pd.DataFrame(
            trial_returns[:splits["Val"].stop],
            index=selection_index,
            columns=[f"trial_{index:03d}" for index in range(trial_returns.shape[1])],
        ),
        n_splits=10,
        pass_threshold=0.20,
    )

    val_ic = ic[splits["Val"]]
    usable_val = val_ic[np.isfinite(val_ic)]
    usable_days = (len(usable_val) // 7) * 7
    blocks = usable_val[:usable_days].reshape(-1, 7).mean(axis=1)
    block_std = float(blocks.std(ddof=1)) if len(blocks) > 1 else 0.0
    block_tstat = float(blocks.mean() / (block_std / math.sqrt(len(blocks)))) if block_std > 0 else 0.0
    statistical_clue = block_tstat > watchlist_critical_tstat
    required_assets = 8 if scope == "large_liquid_only" else 20
    coverage_ok = bool(np.min(valid.sum(axis=1)) >= required_assets)

    checks = {name: True for name in policy.GATE_CATALOG}
    checks.update(
        {
            "coverage_ok": coverage_ok,
            "return_evidence_complete_while_held": True,
            "val_ic_positive": _mean_ic(ic, splits["Val"]) > 0.0,
            "dependence_aware_val_ic_clue": statistical_clue,
            "val_long_short_positive": split_metrics["Val"]["sharpe"] > 0.0 and split_metrics["Val"]["total_return"] > 0.0,
            "holdout_noncollapse": split_metrics["Holdout"]["sharpe"] > -0.25 and split_metrics["Holdout"]["max_drawdown"] < 0.35,
            "holdout_sharpe_positive": split_metrics["Holdout"]["sharpe"] > 0.0,
            "holdout_ic_positive": _mean_ic(ic, splits["Holdout"]) > 0.0,
            "turnover_reasonable": split_metrics["Val"]["hourly_equivalent_turnover"] < 0.08,
            "is_not_opposite": split_metrics["IS"]["sharpe"] > -0.50,
            "rolling_ic_stable": rolling_ic,
            "rolling_sharpe_not_fragile": rolling_sharpe,
            "multiple_testing_pass": block_tstat > pass_critical_tstat,
            "robust_large_liquid_val_ic_positive": _mean_ic(large_ic, splits["Val"]) > 0.0,
            "robust_large_liquid_holdout_nonnegative": _mean_ic(large_ic, splits["Holdout"]) >= 0.0,
            "robust_bucket_val_not_single_bucket": sum(value > 0.0 for value in bucket_val) >= 2,
            "robust_bucket_holdout_not_single_bucket": sum(value > 0.0 for value in bucket_holdout) >= 2,
            "robust_family_neutral_val_ic_positive": _mean_ic(family_ic, splits["Val"]) > 0.0,
            "robust_family_neutral_holdout_nonnegative": _mean_ic(family_ic, splits["Holdout"]) >= 0.0,
            "baseline_incremental_evidence": split_metrics["Val"]["sharpe"] > max(baseline_sharpes),
            "deflated_sharpe_pass": bool(dsr.get("valid") and dsr.get("passed")),
            "cscv_pbo_pass": bool(pbo.get("valid") and pbo.get("passed")),
            "evidence_universe_formal_promotion_allowed": True,
        }
    )
    states = policy.annotate_gate_states(
        checks,
        candidate_definition={"bucket_policy": "large_liquid_only" if scope == "large_liquid_only" else "none"},
    )
    calibrated_draft = policy.classify_gate_v2_draft(states)
    unscreened_checks = dict(checks)
    unscreened_checks["dependence_aware_val_ic_clue"] = True
    unscreened_states = policy.annotate_gate_states(
        unscreened_checks,
        candidate_definition={"bucket_policy": "large_liquid_only" if scope == "large_liquid_only" else "none"},
    )
    unscreened_draft = policy.classify_gate_v2_draft(unscreened_states)
    return {
        "target_ic": float(target_ic),
        "scope": scope,
        "scenario": scenario,
        "realized_val_ic": _mean_ic(ic, splits["Val"]),
        "realized_holdout_ic": _mean_ic(ic, splits["Holdout"]),
        "val_sharpe": split_metrics["Val"]["sharpe"],
        "holdout_sharpe": split_metrics["Holdout"]["sharpe"],
        "block_tstat": block_tstat,
        "statistical_clue": statistical_clue,
        "coverage_ok": coverage_ok,
        "deflated_sharpe_pass": bool(dsr.get("valid") and dsr.get("passed")),
        "deflated_sharpe_p_value": float(dsr.get("p_value", 1.0)),
        "cscv_pbo_pass": bool(pbo.get("valid") and pbo.get("passed")),
        "cscv_pbo": float(pbo.get("pbo", 1.0)),
        "draft_status": unscreened_draft["status"],
        "statistically_screened_status": calibrated_draft["status"],
        "watchlist_blockers": calibrated_draft["watchlist_blockers"],
        "pass_blockers": calibrated_draft["pass_blockers"],
    }


def run_synthetic_calibration(
    *,
    replications: int = 200,
    target_ics: tuple[float, ...] = (0.0, 0.02, 0.05, 0.10, 0.15, 0.20),
    scopes: tuple[str, ...] = ("full_panel", "large_liquid_only"),
    signal_trial_count: int = 51,
    stress_scenarios: tuple[str, ...] = ("regime_decay", "funding_stress", "basis_sparse"),
    stress_target_ic: float = 0.15,
) -> dict[str, Any]:
    null_tstats = inference.simulate_nonoverlapping_block_tstats(
        mean_ic=0.0,
        replications=50000,
        seed=99991,
    )
    per_trial_alpha = 1.0 - (1.0 - 0.05) ** (1.0 / signal_trial_count)
    pass_critical = float(np.quantile(null_tstats, 1.0 - per_trial_alpha, method="higher"))
    watchlist_critical = float(np.quantile(null_tstats, 0.90, method="higher"))
    rows = []
    seed = 0
    experiments = [
        (scope, target_ic, "stationary_complete", "power_curve")
        for scope in scopes
        for target_ic in target_ics
    ]
    experiments.extend(
        (scope, stress_target_ic, scenario, "stress")
        for scope in scopes
        for scenario in stress_scenarios
    )
    for scope, target_ic, scenario, row_type in experiments:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown_scenario:{scenario}")
        outcomes = []
        for _ in range(replications):
            outcomes.append(
                simulate_gate_decision(
                    seed=seed,
                    target_ic=target_ic,
                    scope=scope,
                    pass_critical_tstat=pass_critical,
                    watchlist_critical_tstat=watchlist_critical,
                    signal_trial_count=signal_trial_count,
                    scenario=scenario,
                )
            )
            seed += 1
        draft_successes = sum(row["draft_status"] != "panel_factor_reject" for row in outcomes)
        screened_successes = sum(row["statistically_screened_status"] != "panel_factor_reject" for row in outcomes)
        pass_successes = sum(row["statistically_screened_status"] == "panel_factor_pass" for row in outcomes)
        dsr_successes = sum(row["deflated_sharpe_pass"] for row in outcomes)
        pbo_successes = sum(row["cscv_pbo_pass"] for row in outcomes)
        blocker_counts: dict[str, int] = {}
        for outcome in outcomes:
            for blocker in set(outcome["watchlist_blockers"]) | set(outcome["pass_blockers"]):
                blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        rows.append(
            {
                "row_type": row_type,
                "scope": scope,
                "scenario": scenario,
                "target_ic": float(target_ic),
                "replications": replications,
                "mean_realized_val_ic": float(np.mean([row["realized_val_ic"] for row in outcomes])),
                "draft_watchlist_or_pass_rate": float(draft_successes / replications),
                "draft_watchlist_or_pass_rate_wilson95": _wilson_interval(draft_successes, replications),
                "screened_watchlist_or_pass_rate": float(screened_successes / replications),
                "screened_watchlist_or_pass_rate_wilson95": _wilson_interval(screened_successes, replications),
                "draft_pass_rate": float(pass_successes / replications),
                "draft_pass_rate_wilson95": _wilson_interval(pass_successes, replications),
                "dsr_pass_rate": float(dsr_successes / replications),
                "cscv_pbo_pass_rate": float(pbo_successes / replications),
                "gate_blocker_rates": {
                    name: float(count / replications)
                    for name, count in sorted(blocker_counts.items())
                },
            }
        )
    null_rows = [
        row for row in rows
        if row["row_type"] == "power_curve"
        and row["scenario"] == "stationary_complete"
        and row["target_ic"] == 0.0
    ]
    strong_rows = [
        row for row in rows
        if row["row_type"] == "power_curve"
        and row["scenario"] == "stationary_complete"
        and row["target_ic"] >= 0.20
    ]
    max_null_pass_upper95 = max(
        (row["draft_pass_rate_wilson95"][1] for row in null_rows),
        default=1.0,
    )
    min_strong_pass_rate = min(
        (row["draft_pass_rate"] for row in strong_rows),
        default=0.0,
    )
    calibration_assessment = {
        "null_false_positive_upper95_max": float(max_null_pass_upper95),
        "strong_signal_min_pass_rate": float(min_strong_pass_rate),
        "strong_signal_definition": "stationary planted rank IC >= 0.20 in both declared scopes",
        "synthetic_gate_not_logically_deadlocked": bool(strong_rows and min_strong_pass_rate > 0.0),
        "synthetic_false_positive_control_consistent_with_5pct": bool(
            null_rows and max_null_pass_upper95 <= 0.05
        ),
        "threshold_change_recommended": False,
        "decision": "retain_draft_thresholds_pending_prospective_evidence",
    }
    return {
        "method": "synthetic_daily_panel_gate_v2_draft_calibration",
        "outcome_blind": True,
        "days": 730,
        "asset_count": 40,
        "signal_trial_count": signal_trial_count,
        "pass_critical_tstat": pass_critical,
        "watchlist_critical_tstat": watchlist_critical,
        "watchlist_null_per_signal_target": 0.10,
        "overfit_gates_simulated": ["deflated_sharpe_pass", "cscv_pbo_pass"],
        "formal_prospective_gate_assumption": "set_pass_to_measure_power_conditional_on_mature_preregistered_evidence",
        "stress_target_ic": float(stress_target_ic),
        "calibration_assessment": calibration_assessment,
        "rows": rows,
        "limitations": [
            "Daily synthetic panel, not a replay of named historical candidates.",
            "Formal prospective maturity is set to pass because elapsed future evidence cannot be simulated as historical proof.",
            "DSR and PBO use the production audit functions over a complete correlated synthetic trial batch.",
            "Stress scenarios are structural sensitivity tests, not estimates of real-world scenario probabilities.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replications", type=int, default=200)
    parser.add_argument("--out")
    args = parser.parse_args()
    report = run_synthetic_calibration(replications=args.replications)
    encoded = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        print(f"WROTE {path}")
    else:
        print(encoded.decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
