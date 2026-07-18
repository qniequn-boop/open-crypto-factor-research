"""Machine-readable draft policy for panel factor gate-v2 calibration."""

from __future__ import annotations

from typing import Any


GATE_POLICY_VERSION = "panel_gate_v2_synthetically_calibrated_20260714"
CALIBRATION_EVIDENCE = {
    "complete_power_report": "logs/panel_gate_complete_calibration_20260714.json",
    "null_confirmation_report": "logs/panel_gate_null_confirmation_20260714.json",
    "combined_summary": "logs/panel_gate_complete_calibration_summary_20260714.json",
}
VALID_STATES = {"pass", "fail", "not_applicable", "insufficient"}


def _gate(
    check_name: str,
    *,
    category: str,
    owner_layer: str,
    evidence_phase: str,
    applicability: str = "always",
    failure_meaning: str,
) -> dict[str, str]:
    return {
        "check_name": check_name,
        "category": category,
        "owner_layer": owner_layer,
        "evidence_phase": evidence_phase,
        "applicability": applicability,
        "failure_meaning": failure_meaning,
    }


GATE_CATALOG = {
    row["check_name"]: row
    for row in [
        _gate("coverage_ok", category="validity", owner_layer="factor", evidence_phase="all", failure_meaning="insufficient_cross_section"),
        _gate("val_ic_positive", category="primary_evidence", owner_layer="factor", evidence_phase="Val", failure_meaning="no_positive_rank_evidence"),
        _gate("dependence_aware_val_ic_clue", category="primary_evidence", owner_layer="factor", evidence_phase="Val", failure_meaning="val_rank_evidence_indistinguishable_from_weak_null_noise"),
        _gate("val_long_short_positive", category="primary_evidence", owner_layer="factor", evidence_phase="Val", failure_meaning="no_positive_net_portfolio_evidence"),
        _gate("holdout_noncollapse", category="audit", owner_layer="factor", evidence_phase="Holdout", failure_meaning="audit_collapse"),
        _gate("holdout_sharpe_positive", category="audit", owner_layer="factor", evidence_phase="Holdout", failure_meaning="audit_not_positive"),
        _gate("holdout_ic_positive", category="audit", owner_layer="factor", evidence_phase="Holdout", failure_meaning="audit_rank_ic_not_positive"),
        _gate("turnover_reasonable", category="implementation", owner_layer="factor", evidence_phase="Val", failure_meaning="turnover_too_high_for_factor_test"),
        _gate("is_not_opposite", category="diagnostic", owner_layer="factor", evidence_phase="IS", failure_meaning="mechanism_direction_conflict"),
        _gate("rolling_ic_stable", category="robustness", owner_layer="factor", evidence_phase="IS_and_Val", failure_meaning="rank_evidence_time_fragile"),
        _gate("rolling_sharpe_not_fragile", category="robustness", owner_layer="factor", evidence_phase="IS_and_Val", failure_meaning="portfolio_evidence_time_fragile"),
        _gate("multiple_testing_pass", category="multiplicity", owner_layer="factor", evidence_phase="Val", failure_meaning="insufficient_trial_adjusted_rank_evidence"),
        _gate("robust_large_liquid_val_ic_positive", category="scope_robustness", owner_layer="factor", evidence_phase="Val", failure_meaning="large_liquid_val_not_positive"),
        _gate("robust_large_liquid_holdout_nonnegative", category="scope_robustness", owner_layer="factor", evidence_phase="Holdout", failure_meaning="large_liquid_audit_negative"),
        _gate(
            "robust_bucket_val_not_single_bucket",
            category="scope_robustness",
            owner_layer="factor",
            evidence_phase="Val",
            applicability="not_for_large_liquid_only",
            failure_meaning="val_effect_concentrated_in_one_liquidity_bucket",
        ),
        _gate(
            "robust_bucket_holdout_not_single_bucket",
            category="scope_robustness",
            owner_layer="factor",
            evidence_phase="Holdout",
            applicability="not_for_large_liquid_only",
            failure_meaning="audit_effect_concentrated_in_one_liquidity_bucket",
        ),
        _gate("robust_family_neutral_val_ic_positive", category="scope_robustness", owner_layer="factor", evidence_phase="Val", failure_meaning="family_neutral_val_not_positive"),
        _gate("robust_family_neutral_holdout_nonnegative", category="scope_robustness", owner_layer="factor", evidence_phase="Holdout", failure_meaning="family_neutral_audit_negative"),
        _gate("robust_crash_window_count", category="stress_diagnostic", owner_layer="factor", evidence_phase="all", failure_meaning="insufficient_stress_windows"),
        _gate("robust_crash_loss_contained", category="stress_diagnostic", owner_layer="combo_or_strategy_review", evidence_phase="all", failure_meaning="stress_loss_large"),
        _gate("robust_crash_not_mostly_negative", category="stress_diagnostic", owner_layer="combo_or_strategy_review", evidence_phase="all", failure_meaning="stress_performance_mostly_negative"),
        _gate("deflated_sharpe_pass", category="multiplicity", owner_layer="factor", evidence_phase="Val", failure_meaning="deflated_sharpe_not_significant"),
        _gate("cscv_pbo_pass", category="multiplicity", owner_layer="research_batch", evidence_phase="IS_and_Val", failure_meaning="backtest_overfit_probability_high"),
        _gate("evidence_universe_formal_promotion_allowed", category="evidence_scope", owner_layer="promotion", evidence_phase="prospective", failure_meaning="survivor_conditioned_or_immature_evidence"),
        _gate("baseline_incremental_evidence", category="benchmark", owner_layer="factor", evidence_phase="Val", failure_meaning="no_incremental_evidence_beyond_baselines"),
        _gate("return_evidence_complete_while_held", category="validity", owner_layer="factor", evidence_phase="all", failure_meaning="held_position_has_unpriceable_return_bars"),
    ]
}

WATCHLIST_REQUIRED_GATES = {
    "coverage_ok",
    "return_evidence_complete_while_held",
    "val_ic_positive",
    "dependence_aware_val_ic_clue",
    "val_long_short_positive",
    "is_not_opposite",
    "holdout_noncollapse",
}

PASS_REQUIRED_GATES = WATCHLIST_REQUIRED_GATES | {
    "turnover_reasonable",
    "rolling_ic_stable",
    "rolling_sharpe_not_fragile",
    "multiple_testing_pass",
    "deflated_sharpe_pass",
    "cscv_pbo_pass",
    "holdout_sharpe_positive",
    "holdout_ic_positive",
    "robust_large_liquid_val_ic_positive",
    "robust_large_liquid_holdout_nonnegative",
    "robust_bucket_val_not_single_bucket",
    "robust_bucket_holdout_not_single_bucket",
    "robust_family_neutral_val_ic_positive",
    "robust_family_neutral_holdout_nonnegative",
    "baseline_incremental_evidence",
    "evidence_universe_formal_promotion_allowed",
}


def gate_is_applicable(check_name: str, candidate_definition: dict[str, Any] | None = None) -> tuple[bool, str | None]:
    if check_name not in GATE_CATALOG:
        raise KeyError(f"unregistered_gate:{check_name}")
    rule = GATE_CATALOG[check_name]["applicability"]
    candidate_definition = candidate_definition or {}
    if rule == "not_for_large_liquid_only" and candidate_definition.get("bucket_policy") == "large_liquid_only":
        return False, "candidate_estimand_is_predeclared_large_liquid_only"
    return True, None


def annotate_gate_states(
    checks: dict[str, bool],
    *,
    candidate_definition: dict[str, Any] | None = None,
    evidence_coverage: dict[str, dict[str, int]] | None = None,
) -> dict[str, dict[str, Any]]:
    evidence_coverage = evidence_coverage or {}
    states: dict[str, dict[str, Any]] = {}
    for check_name, passed in checks.items():
        applicable, reason = gate_is_applicable(check_name, candidate_definition)
        coverage = evidence_coverage.get(check_name)
        if not applicable:
            state = "not_applicable"
        elif coverage and int(coverage.get("observed", 0)) < int(coverage.get("required", 0)):
            state = "insufficient"
            reason = f"evidence_coverage:{coverage.get('observed', 0)}<{coverage.get('required', 0)}"
        else:
            state = "pass" if bool(passed) else "fail"
        states[check_name] = {
            "state": state,
            "reason": reason,
            "catalog": GATE_CATALOG[check_name],
        }
    return states


def effective_failures(states: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name, row in states.items() if row.get("state") == "fail"]


def insufficient_evidence(states: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name, row in states.items() if row.get("state") == "insufficient"]


def _required_gate_state(states: dict[str, dict[str, Any]], gate_name: str) -> str:
    row = states.get(gate_name)
    return str((row or {}).get("state") or "insufficient")


def classify_gate_v2_draft(states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    watchlist_blockers = {
        name: _required_gate_state(states, name)
        for name in sorted(WATCHLIST_REQUIRED_GATES)
        if _required_gate_state(states, name) not in {"pass", "not_applicable"}
    }
    if watchlist_blockers:
        return {
            "status": "panel_factor_reject",
            "reason": "missing_primary_val_evidence_or_clear_audit_contradiction",
            "watchlist_blockers": watchlist_blockers,
            "pass_blockers": {},
            "binding": False,
        }

    pass_blockers = {
        name: _required_gate_state(states, name)
        for name in sorted(PASS_REQUIRED_GATES)
        if _required_gate_state(states, name) not in {"pass", "not_applicable"}
    }
    if pass_blockers:
        return {
            "status": "panel_factor_watchlist",
            "reason": "val_clue_survives_basic_audit_but_pass_evidence_is_incomplete",
            "watchlist_blockers": {},
            "pass_blockers": pass_blockers,
            "binding": False,
        }
    return {
        "status": "panel_factor_pass",
        "reason": "all_applicable_draft_pass_evidence_present",
        "watchlist_blockers": {},
        "pass_blockers": {},
        "binding": False,
    }


def assert_catalog_covers(check_names: set[str]) -> None:
    missing = sorted(check_names - set(GATE_CATALOG))
    if missing:
        raise ValueError(f"uncataloged_gates:{','.join(missing)}")


def policy_summary() -> dict[str, Any]:
    by_layer: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for row in GATE_CATALOG.values():
        by_layer[row["owner_layer"]] = by_layer.get(row["owner_layer"], 0) + 1
        by_category[row["category"]] = by_category.get(row["category"], 0) + 1
    return {
        "policy_version": GATE_POLICY_VERSION,
        "gate_count": len(GATE_CATALOG),
        "by_owner_layer": by_layer,
        "by_category": by_category,
        "status": "synthetically_calibrated_nonbinding_pending_prospective_evidence",
        "calibration_evidence": CALIBRATION_EVIDENCE,
    }
