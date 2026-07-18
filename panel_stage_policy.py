"""Versioned selection-only policy for the staged panel evaluator.

Stage 2 is deliberately limited to IS and Validation evidence.  Every check
below is a necessary condition for a candidate path to spend Holdout and
robustness compute in Stage 3; none of these checks is a formal promotion.
"""

from __future__ import annotations

from typing import Any


STAGE_POLICY_VERSION = "panel_stage_2_selection_only_v1_20260715"
SELECTION_SPLITS = ("IS", "Val")


def evaluate_stage_2(
    split_metrics: dict[str, dict[str, Any]],
    rank_ic: dict[str, dict[str, Any]],
    coverage: dict[str, int],
    *,
    required_min_assets: int,
) -> dict[str, Any]:
    """Return an early-stop decision without accepting Holdout inputs."""
    missing_splits = [
        split_name
        for split_name in SELECTION_SPLITS
        if split_name not in split_metrics or split_name not in rank_ic or split_name not in coverage
    ]
    if missing_splits:
        raise ValueError(f"stage_2_selection_split_missing:{','.join(missing_splits)}")
    if "Holdout" in split_metrics or "Holdout" in rank_ic or "Holdout" in coverage:
        raise ValueError("stage_2_holdout_input_forbidden")

    val_metrics = split_metrics["Val"]
    checks = {
        "coverage_ok": all(int(coverage[name]) >= int(required_min_assets) for name in SELECTION_SPLITS),
        "val_ic_positive": float(rank_ic["Val"].get("mean_rank_ic") or 0.0) > 0.0,
        "val_long_short_positive": (
            float(val_metrics.get("sharpe") or 0.0) > 0.0
            and float(val_metrics.get("total_return") or 0.0) > 0.0
        ),
        "turnover_reasonable": float(val_metrics.get("turnover") or 0.0) < 0.08,
        "is_not_opposite": float(split_metrics["IS"].get("sharpe") or 0.0) > -0.50,
        "return_evidence_complete_while_held": all(
            bool(split_metrics[name].get("return_evidence_complete_while_held"))
            for name in SELECTION_SPLITS
        ),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    survives = not failed_checks
    return {
        "policy_version": STAGE_POLICY_VERSION,
        "executed": True,
        "selection_splits": list(SELECTION_SPLITS),
        "holdout_input_allowed": False,
        "checks": checks,
        "failed_checks": failed_checks,
        "survives_to_stage_3": survives,
        "decision": "advance_to_stage_3" if survives else "reject_before_holdout",
        "formal_promotion": False,
    }


def policy_summary() -> dict[str, Any]:
    return {
        "policy_version": STAGE_POLICY_VERSION,
        "selection_splits": list(SELECTION_SPLITS),
        "holdout_input_allowed": False,
        "purpose": "necessary-condition compute gate before full historical audit",
        "formal_promotion": False,
    }
