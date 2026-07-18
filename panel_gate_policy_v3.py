"""Nonbinding staged gate policy for balanced factor discovery and promotion.

Gate v3 does not relabel legacy results. It separates a low-stakes historical
screen from prospective evidence and final strategy promotion.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


GATE_POLICY_VERSION = "panel_gate_v3_literature_staged_shadow_20260714"
DISCOVERY_FDR_Q = 0.10
FINAL_FDR_Q = 0.05


def false_discovery_adjustment(
    p_values: dict[str, float],
    *,
    q: float = DISCOVERY_FDR_Q,
    method: str = "benjamini_hochberg",
) -> dict[str, dict[str, Any]]:
    """Return monotone BH/BY adjusted p-values for a preregistered family."""
    if not 0.0 < float(q) < 1.0:
        raise ValueError("fdr_q_must_be_between_zero_and_one")
    if method not in {"benjamini_hochberg", "benjamini_yekutieli"}:
        raise ValueError(f"unsupported_fdr_method:{method}")
    clean: list[tuple[str, float]] = []
    for hypothesis_id, value in p_values.items():
        p_value = float(value)
        if not math.isfinite(p_value) or not 0.0 <= p_value <= 1.0:
            raise ValueError(f"invalid_p_value:{hypothesis_id}")
        clean.append((str(hypothesis_id), p_value))
    clean.sort(key=lambda item: (item[1], item[0]))
    if not clean:
        return {}
    count = len(clean)
    dependence_scale = sum(1.0 / rank for rank in range(1, count + 1)) if method == "benjamini_yekutieli" else 1.0
    adjusted_sorted = [1.0] * count
    running_min = 1.0
    for index in range(count - 1, -1, -1):
        rank = index + 1
        raw_adjusted = clean[index][1] * count * dependence_scale / rank
        running_min = min(running_min, raw_adjusted)
        adjusted_sorted[index] = min(running_min, 1.0)
    return {
        hypothesis_id: {
            "raw_p": p_value,
            "adjusted_p": float(adjusted_sorted[index]),
            "passed": bool(adjusted_sorted[index] <= q),
            "q": float(q),
            "method": method,
            "family_hypothesis_count": count,
        }
        for index, (hypothesis_id, p_value) in enumerate(clean)
    }


def classify_historical_discovery(
    checks: dict[str, bool],
    *,
    fdr_state: str,
) -> dict[str, Any]:
    """Classify historical evidence without ever producing a formal pass."""
    validity_required = {"coverage_ok", "return_evidence_complete_while_held"}
    primary_required = {"val_ic_positive", "dependence_aware_val_ic_clue"}
    discovery_quality = {"val_long_short_positive", "turnover_reasonable", "rolling_ic_stable"}

    validity_blockers = sorted(name for name in validity_required if not bool(checks.get(name)))
    primary_blockers = sorted(name for name in primary_required if not bool(checks.get(name)))
    if validity_blockers or primary_blockers:
        return {
            "status": "historical_reject",
            "reason": "invalid_evidence_or_no_dependence_aware_primary_clue",
            "blockers": validity_blockers + primary_blockers,
            "formal_pass_possible": False,
        }
    if not bool(checks.get("holdout_noncollapse")):
        return {
            "status": "historical_reject",
            "reason": "frozen_holdout_collapse",
            "blockers": ["holdout_noncollapse"],
            "formal_pass_possible": False,
        }
    if fdr_state != "pass":
        return {
            "status": "historical_clue",
            "reason": "primary_clue_requires_complete_family_fdr_evidence",
            "blockers": [f"family_fdr:{fdr_state}"],
            "formal_pass_possible": False,
        }
    quality_blockers = sorted(name for name in discovery_quality if not bool(checks.get(name)))
    if quality_blockers:
        return {
            "status": "historical_clue",
            "reason": "statistical_clue_not_yet_economically_robust",
            "blockers": quality_blockers,
            "formal_pass_possible": False,
        }
    return {
        "status": "prospective_eligible",
        "reason": "historical_screen_passed_for_frozen_paper_observation_only",
        "blockers": [],
        "formal_pass_possible": False,
    }


def _candidate_empirical_p(row: dict[str, Any]) -> float | None:
    audit = (((row.get("dependence_aware_rank_ic") or {}).get("Val") or {}).get("empirical_block_audit") or {})
    value = audit.get("empirical_one_sided_p")
    if value is None:
        return None
    p_value = float(value)
    return p_value if math.isfinite(p_value) and 0.0 <= p_value <= 1.0 else None


def attach_gate_v3_drafts(
    factor_rows: list[dict[str, Any]],
    *,
    registry_breakdown: dict[str, Any],
    additional_candidate_p_values: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach shadow discovery classifications to rows in place."""
    current_ids_by_family: dict[str, set[str]] = defaultdict(set)
    p_values_by_family: dict[str, dict[str, float]] = defaultdict(dict)
    for row in factor_rows:
        candidate_id = row.get("candidate_id")
        if not candidate_id:
            continue
        family = str(row.get("family") or "unclassified")
        candidate_id = str(candidate_id)
        current_ids_by_family[family].add(candidate_id)
        p_value = _candidate_empirical_p(row)
        if p_value is not None:
            p_values_by_family[family][candidate_id] = p_value
    for candidate_id, evidence in (additional_candidate_p_values or {}).items():
        family = str(evidence.get("family") or "unclassified")
        current_ids_by_family[family].add(str(candidate_id))
        p_value = evidence.get("p_value")
        if p_value is None:
            continue
        p_value = float(p_value)
        if not math.isfinite(p_value) or not 0.0 <= p_value <= 1.0:
            raise ValueError(f"invalid_additional_candidate_p_value:{candidate_id}")
        p_values_by_family[family][str(candidate_id)] = p_value

    historical_by_family = {
        str(family): set(ids)
        for family, ids in (registry_breakdown.get("outcome_seen_candidate_ids_by_family") or {}).items()
    }
    family_audits: dict[str, dict[str, Any]] = {}
    for family, current_ids in current_ids_by_family.items():
        expected_ids = set(historical_by_family.get(family, set())) | current_ids
        observed_ids = set(p_values_by_family.get(family, {}))
        ledger_complete = expected_ids <= observed_ids
        bh = false_discovery_adjustment(p_values_by_family[family]) if ledger_complete else {}
        by = (
            false_discovery_adjustment(p_values_by_family[family], method="benjamini_yekutieli")
            if ledger_complete
            else {}
        )
        family_audits[family] = {
            "ledger_complete": ledger_complete,
            "expected_outcome_seen_candidate_ids": sorted(expected_ids),
            "observed_p_value_candidate_ids": sorted(observed_ids),
            "missing_p_value_candidate_ids": sorted(expected_ids - observed_ids),
            "discovery_method": "benjamini_hochberg_within_preregistered_mechanism_family",
            "discovery_q": DISCOVERY_FDR_Q,
            "bh": bh,
            "by_dependence_sensitivity": by,
        }

    status_counts: dict[str, int] = defaultdict(int)
    for row in factor_rows:
        candidate_id = row.get("candidate_id")
        if not candidate_id:
            row["gate_v3_draft"] = {
                "policy_version": GATE_POLICY_VERSION,
                "binding": False,
                "classification": {"status": "benchmark_only", "formal_pass_possible": False},
                "legacy_status_unchanged": True,
            }
            continue
        family = str(row.get("family") or "unclassified")
        family_audit = family_audits[family]
        fdr_result = family_audit["bh"].get(str(candidate_id)) if family_audit["ledger_complete"] else None
        if not family_audit["ledger_complete"]:
            fdr_state = "insufficient"
        elif fdr_result and fdr_result["passed"]:
            fdr_state = "pass"
        else:
            fdr_state = "fail"
        checks = dict(row.get("checks") or {})
        classification = classify_historical_discovery(checks, fdr_state=fdr_state)
        status_counts[classification["status"]] += 1
        row["gate_v3_draft"] = {
            "policy_version": GATE_POLICY_VERSION,
            "binding": False,
            "classification": classification,
            "family_fdr_state": fdr_state,
            "family_fdr": fdr_result,
            "family_ledger_complete": family_audit["ledger_complete"],
            "holdout_role": "one_frozen_noncollapse_audit_only",
            "not_required_for_prospective_entry": [
                "deflated_sharpe_pass",
                "cscv_pbo_pass",
                "holdout_sharpe_positive",
                "holdout_ic_positive",
                "all_universal_subgroup_sign_checks",
            ],
            "still_required_before_formal_strategy_promotion": [
                "mature_preregistered_prospective_evidence",
                "residual_or_conditional_incremental_alpha",
                "strategy_or_combo_level_deflated_sharpe",
                "strategy_or_combo_level_cscv_pbo",
                "capacity_cost_and_stress_audit",
            ],
            "legacy_status_unchanged": True,
        }
    return {
        "policy_version": GATE_POLICY_VERSION,
        "binding": False,
        "purpose": "historical_discovery_to_prospective_observation_not_capital_promotion",
        "discovery_fdr_q": DISCOVERY_FDR_Q,
        "final_fdr_q": FINAL_FDR_Q,
        "family_audits": family_audits,
        "candidate_path_status_counts": dict(status_counts),
        "formal_pass_count": 0,
        "note": "No historical-only classification can produce panel_factor_pass.",
    }
