"""Skeptical audit for strategy research outputs.

This script is intentionally harsh. It treats a candidate as deployable only if
the result survives checks that are hard to fake with a single attractive
backtest: no Holdout selection, alternate split stability, cost stress, baseline
dominance, and explicit funding status.
"""

from __future__ import annotations

import glob
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import data as data_module
import strategy_audit as audit
import strategy_blend_research as blend
import strategy_research as sr


ALT_SPLIT_RATIOS = [
    (0.45, 0.20, 0.35),
    (0.55, 0.15, 0.30),
    (0.40, 0.20, 0.40),
    (0.60, 0.15, 0.25),
]

COST_STRESS_MULTIPLIERS = [1, 2, 3]

STRICT_GATES = {
    "alt_val_sharpe_min": 0.0,
    "alt_holdout_sharpe_min": 0.0,
    "alt_holdout_drawdown_max": 0.45,
    "cost_stress_holdout_sharpe_min": 0.0,
    "cost_stress_holdout_drawdown_max": 0.45,
    "required_cost_stress_multiplier": 3,
}


def _latest_spec_path() -> Path:
    path = Path(config.LOG_DIR) / "strategy_spec_latest.json"
    if path.exists():
        return path
    paths = sorted(glob.glob(str(Path(config.LOG_DIR) / "strategy_spec_*.json")))
    if not paths:
        raise FileNotFoundError("no strategy_spec JSON found; run strategy_export.py first")
    return Path(paths[-1])


def _split_results(position, splits, funding_rates=None) -> dict[str, dict[str, Any]]:
    return {
        split_name: sr._position_backtest(
            position.reindex(split_df.index),
            split_df,
            funding_rate_series=funding_rates,
        )
        for split_name, split_df in zip(["IS", "Val", "Holdout"], splits)
    }


def _build_blend_position(spec: dict, df, funding_rates=None):
    weights = spec["blend"]["weights"]
    base_positions = sr._make_positions(df, funding_rates)
    components = blend._component_positions(base_positions, df.index)
    return blend._blend_position(components, weights, df.index)


def _baselines_for_splits(base_positions, splits, df, funding_rates=None) -> dict:
    out = {}
    for name, position in audit._baseline_positions(base_positions).items():
        out[name] = {
            "splits": _split_results(position, splits, funding_rates),
            "rolling_90d": audit._rolling_audit(position, df, funding_rates),
        }
    return out


def _alternate_split_audit(position, df, base_positions, funding_rates=None) -> dict:
    rows = []
    for ratios in ALT_SPLIT_RATIOS:
        splits = data_module.split_data(df, ratios=ratios)
        results = _split_results(position, splits, funding_rates)
        rolling = audit._rolling_audit(position, df, funding_rates)
        baselines = _baselines_for_splits(base_positions, splits, df, funding_rates)
        dominance = audit._baseline_dominance({"splits": results}, rolling, baselines)
        checks = {
            "val_positive": results["Val"]["sharpe"] >= STRICT_GATES["alt_val_sharpe_min"],
            "holdout_positive": results["Holdout"]["sharpe"] >= STRICT_GATES["alt_holdout_sharpe_min"],
            "holdout_drawdown_ok": results["Holdout"]["max_drawdown"] <= STRICT_GATES["alt_holdout_drawdown_max"],
            "beats_all_baselines": dominance["beats_all_baselines"],
        }
        rows.append(
            {
                "ratios": ratios,
                "splits": results,
                "baseline_dominance": dominance,
                "checks": checks,
                "pass": all(checks.values()),
            }
        )
    return {
        "gates": {
            "ratios": ALT_SPLIT_RATIOS,
            "val_sharpe_min": STRICT_GATES["alt_val_sharpe_min"],
            "holdout_sharpe_min": STRICT_GATES["alt_holdout_sharpe_min"],
            "holdout_drawdown_max": STRICT_GATES["alt_holdout_drawdown_max"],
            "beats_all_baselines_required": True,
        },
        "rows": rows,
        "pass": all(row["pass"] for row in rows),
        "failed_ratios": [row["ratios"] for row in rows if not row["pass"]],
    }


def _cost_stress_audit(position, df, funding_rates=None) -> dict:
    splits = data_module.split_data(df)
    rows = []
    for multiplier in COST_STRESS_MULTIPLIERS:
        cost_bps = config.COST_BPS * multiplier
        slippage_bps = config.SLIPPAGE_BPS * multiplier
        results = {
            split_name: sr._position_backtest(
                position.reindex(split_df.index),
                split_df,
                cost_bps=cost_bps,
                slippage_bps=slippage_bps,
                funding_rate_series=funding_rates,
            )
            for split_name, split_df in zip(["IS", "Val", "Holdout"], splits)
        }
        is_required = multiplier <= STRICT_GATES["required_cost_stress_multiplier"]
        checks = {
            "holdout_positive": results["Holdout"]["sharpe"] >= STRICT_GATES["cost_stress_holdout_sharpe_min"],
            "holdout_drawdown_ok": results["Holdout"]["max_drawdown"] <= STRICT_GATES["cost_stress_holdout_drawdown_max"],
        }
        rows.append(
            {
                "multiplier": multiplier,
                "cost_bps": cost_bps,
                "slippage_bps": slippage_bps,
                "splits": results,
                "checks": checks,
                "required_for_pass": is_required,
                "pass": all(checks.values()) if is_required else True,
            }
        )
    required_rows = [row for row in rows if row["required_for_pass"]]
    return {
        "gates": {
            "multipliers": COST_STRESS_MULTIPLIERS,
            "required_through_multiplier": STRICT_GATES["required_cost_stress_multiplier"],
            "holdout_sharpe_min": STRICT_GATES["cost_stress_holdout_sharpe_min"],
            "holdout_drawdown_max": STRICT_GATES["cost_stress_holdout_drawdown_max"],
        },
        "rows": rows,
        "pass": all(row["pass"] for row in required_rows),
        "failed_multipliers": [row["multiplier"] for row in required_rows if not row["pass"]],
    }


def _selection_integrity(spec: dict) -> dict:
    blend_spec = spec.get("blend", {})
    integrity = blend_spec.get("selection_integrity", {})
    policy = blend_spec.get("selection_policy", {})
    checks = {
        "report_declares_no_holdout_selection": policy.get("holdout_used_for_selection") is False,
        "report_declares_no_holdout_sorting": policy.get("holdout_used_for_sorting") is False,
        "export_declares_no_holdout_choice": integrity.get("holdout_used_to_choose_export") is False,
    }
    return {
        "checks": checks,
        "pass": all(checks.values()),
        "selection_policy": policy,
        "selection_integrity": integrity,
    }


def _funding_audit(spec: dict) -> dict:
    paid = spec.get("cost_model", {}).get("funding_paid_recorded", {})
    abs_paid = spec.get("cost_model", {}).get("funding_abs_paid_recorded", {})
    observations = spec.get("cost_model", {}).get("funding_observations", {})
    source = spec.get("cost_model", {}).get("funding_rate_source", {})
    values = [value for value in paid.values() if value is not None]
    abs_values = [value for value in abs_paid.values() if value is not None]
    obs_values = [value for value in observations.values() if value is not None]
    has_nonzero_funding = any(abs(float(value)) > 0 for value in values)
    has_funding_cost_activity = any(float(value) > 0 for value in abs_values)
    has_observations = bool(obs_values) and all(int(value) > 0 for value in obs_values)
    checks = {
        "funding_metric_present": bool(values),
        "real_funding_series_supplied": source.get("kind") == "okx_public_funding_rate_history",
        "funding_observations_in_all_splits": has_observations,
        "nonzero_funding_observed": has_nonzero_funding,
        "funding_cost_activity_observed": has_funding_cost_activity,
    }
    return {
        "checks": checks,
        "pass": all(checks.values()),
        "source": source,
        "note": "Funding must come from a real public funding-rate series and cover every split; partial recent-only coverage remains a failure.",
    }


def _normal_sf(value: float) -> float:
    return 0.5 * math.erfc(value / math.sqrt(2.0))


def _multiple_testing_adjustment(val_sharpe: float, val_bars: int, generated_count: int | None) -> dict:
    periods_per_year = sr._periods_per_year()
    if generated_count is None or generated_count <= 0 or val_bars <= 1:
        return {
            "method": "sidak_one_sided_normal_approx",
            "applied": False,
            "pass": False,
            "reason": "missing generated_count or validation bar count",
        }

    z_score = val_sharpe * math.sqrt(val_bars / periods_per_year)
    raw_p = _normal_sf(z_score)
    adjusted_p = 1.0 - (1.0 - raw_p) ** generated_count
    bonferroni_p = min(1.0, raw_p * generated_count)
    return {
        "method": "sidak_one_sided_normal_approx",
        "applied": True,
        "pass": adjusted_p < 0.05,
        "val_sharpe": val_sharpe,
        "val_bars": val_bars,
        "periods_per_year": periods_per_year,
        "generated_count": generated_count,
        "z_score": z_score,
        "raw_one_sided_p": raw_p,
        "sidak_adjusted_p": adjusted_p,
        "bonferroni_adjusted_p": bonferroni_p,
        "alpha": 0.05,
        "note": "Conservative multiple-testing guard. It assumes independent trials; correlated trials still require deeper DSR/PBO work.",
    }


def _trial_audit(spec: dict, df) -> dict:
    source = spec.get("source_blend_report")
    generated_count = None
    selected_count = None
    full_pass_count = None
    if source and Path(source).exists():
        report = json.loads(Path(source).read_text(encoding="utf-8"))
        generated_count = report.get("generated_count")
        selected_count = report.get("selected_count")
        full_pass_count = report.get("full_pass_count")
    val_bars = len(data_module.split_data(df)[1])
    val_sharpe = float(spec.get("evidence", {}).get("splits", {}).get("Val", {}).get("sharpe", 0.0))
    multiple_testing = _multiple_testing_adjustment(val_sharpe, val_bars, generated_count)
    return {
        "generated_count": generated_count,
        "selected_count": selected_count,
        "full_pass_count": full_pass_count,
        "trial_count_logged": generated_count is not None and generated_count > 0,
        "multiple_testing_penalty_applied": multiple_testing["applied"],
        "multiple_testing_penalty_pass": multiple_testing["pass"],
        "multiple_testing": multiple_testing,
        "pass": generated_count is not None and generated_count > 0 and multiple_testing["pass"],
        "note": "Uses a conservative one-sided normal approximation with Sidak correction across generated blend trials.",
    }


def _failed_reasons(checks: dict[str, bool]) -> list[str]:
    return [name for name, ok in checks.items() if not ok]


def _structural_blockers(funding: dict, trials: dict) -> list[dict]:
    blockers = []
    funding_checks = funding.get("checks", {})
    if funding_checks.get("real_funding_series_supplied") and not funding_checks.get("funding_observations_in_all_splits"):
        source = funding.get("source", {})
        blockers.append(
            {
                "name": "funding_history_does_not_cover_all_splits",
                "scope": "all_candidates_under_current_data_split",
                "reason": "The real funding-rate source has no observations in at least one split, so every candidate fails the funding gate.",
                "observations_by_split": source.get("observations_by_split"),
                "source_start": source.get("start"),
                "source_end": source.get("end"),
            }
        )
    multiple = trials.get("multiple_testing", {})
    if multiple.get("applied") and not multiple.get("pass"):
        blockers.append(
            {
                "name": "selected_candidate_fails_multiple_testing_penalty",
                "scope": "current_exported_candidate",
                "reason": "The selected candidate's Validation Sharpe is not significant after correcting for generated trials.",
                "sidak_adjusted_p": multiple.get("sidak_adjusted_p"),
                "generated_count": multiple.get("generated_count"),
            }
        )
    return blockers


def main() -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    spec_path = _latest_spec_path()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if "blend" not in spec:
        top_level_checks = {
            "exportable_candidate_exists": False,
        }
        report = {
            "schema_version": 1,
            "created_at_utc": timestamp,
            "source_strategy_spec": str(spec_path),
            "strict_objective_satisfied": False,
            "current_conditions_no_strict_pass": False,
            "structural_blockers": [],
            "top_level_checks": top_level_checks,
            "failed_reasons": _failed_reasons(top_level_checks),
            "no_candidate_reason": spec.get("evidence", {}).get("no_candidate_reason", "No blend candidate exported."),
        }
        out_path = Path(config.LOG_DIR) / f"strategy_skeptic_audit_{timestamp}.json"
        latest_path = Path(config.LOG_DIR) / "strategy_skeptic_audit_latest.json"
        payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        out_path.write_text(payload, encoding="utf-8")
        latest_path.write_text(payload, encoding="utf-8")
        print(f"WROTE {out_path}")
        print(f"WROTE {latest_path}")
        print("STRICT_OBJECTIVE_SATISFIED False")
        print(f"FAILED_REASONS {report['failed_reasons']}")
        print(f"NO_CANDIDATE {report['no_candidate_reason']}")
        return 0

    df = data_module.load_data(config.INST_ID, config.BAR, config.HISTORY_DAYS)
    funding_rates = data_module.load_funding_rates(config.INST_ID, config.HISTORY_DAYS)
    base_positions = sr._make_positions(df, funding_rates)
    position = _build_blend_position(spec, df, funding_rates)

    selection = _selection_integrity(spec)
    alternate = _alternate_split_audit(position, df, base_positions, funding_rates)
    cost_stress = _cost_stress_audit(position, df, funding_rates)
    funding = _funding_audit(spec)
    trials = _trial_audit(spec, df)

    top_level_checks = {
        "no_holdout_selection_or_export_choice": selection["pass"],
        "original_report_full_pass": spec.get("research_status", {}).get("full_objective_satisfied") is True,
        "alternate_split_pass": alternate["pass"],
        "cost_stress_pass": cost_stress["pass"],
        "funding_real_or_explicitly_supplied": funding["pass"],
        "trial_count_logged": trials["trial_count_logged"],
        "multiple_testing_penalty_applied": trials["multiple_testing_penalty_applied"],
        "multiple_testing_penalty_pass": trials["multiple_testing_penalty_pass"],
    }
    blockers = _structural_blockers(funding, trials)

    report = {
        "schema_version": 1,
        "created_at_utc": timestamp,
        "source_strategy_spec": str(spec_path),
        "strict_objective_satisfied": all(top_level_checks.values()),
        "current_conditions_no_strict_pass": any(
            item["scope"] == "all_candidates_under_current_data_split" for item in blockers
        ),
        "structural_blockers": blockers,
        "top_level_checks": top_level_checks,
        "failed_reasons": _failed_reasons(top_level_checks),
        "selection_integrity": selection,
        "alternate_split_audit": alternate,
        "cost_stress_audit": cost_stress,
        "funding_audit": funding,
        "trial_audit": trials,
    }

    out_path = Path(config.LOG_DIR) / f"strategy_skeptic_audit_{timestamp}.json"
    latest_path = Path(config.LOG_DIR) / "strategy_skeptic_audit_latest.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    out_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")

    print(f"WROTE {out_path}")
    print(f"WROTE {latest_path}")
    print(f"STRICT_OBJECTIVE_SATISFIED {report['strict_objective_satisfied']}")
    print(f"FAILED_REASONS {report['failed_reasons']}")
    print(f"ALT_SPLIT_PASS {alternate['pass']} FAILED {alternate['failed_ratios']}")
    print(f"COST_STRESS_PASS {cost_stress['pass']} FAILED {cost_stress['failed_multipliers']}")
    print(f"FUNDING_PASS {funding['pass']} CHECKS {funding['checks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
