"""Shared validation contract for independent panel critic approvals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


CRITIC_SCHEMA_VERSION = "panel_research_critic_v1"
FORMULA_AUDIT_SCHEMA_VERSION = "panel_formula_differential_audit_v1"


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_critic_approval(
    report: dict[str, Any],
    candidate_batch_path: Path | str,
) -> tuple[bool, list[str]]:
    batch_path = Path(candidate_batch_path).resolve(strict=True)
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    batch_id = str(batch.get("batch_id") or "")
    candidate_ids = {
        str(row.get("candidate_id") or "")
        for row in batch.get("candidates") or []
    }
    reviews = report.get("candidate_reviews") if isinstance(report.get("candidate_reviews"), list) else []
    reviewed_ids = {str(row.get("candidate_id") or "") for row in reviews}
    failures = []
    if report.get("schema_version") != CRITIC_SCHEMA_VERSION:
        failures.append("critic_schema_invalid")
    if not bool(report.get("approved")) or report.get("decision") != "critic_approved":
        failures.append("critic_not_approved")
    if str(report.get("batch_id") or "") != batch_id:
        failures.append("critic_batch_id_mismatch")
    if candidate_ids != reviewed_ids or not candidate_ids:
        failures.append("critic_candidate_ids_mismatch")
    if any(not bool(row.get("approved")) for row in reviews):
        failures.append("critic_contains_rejected_candidate")
    if any(row.get("blockers") for row in reviews):
        failures.append("critic_contains_candidate_blockers")
    if any(
        not isinstance(row.get("checks"), dict)
        or not row["checks"]
        or not all(bool(value) for value in row["checks"].values())
        for row in reviews
    ):
        failures.append("critic_candidate_checks_incomplete")
    batch_checks = report.get("batch_checks")
    if (
        not isinstance(batch_checks, dict)
        or not batch_checks
        or not all(bool(value) for value in batch_checks.values())
        or report.get("batch_blockers")
    ):
        failures.append("critic_batch_checks_incomplete")
    if bool(report.get("holdout_read_by_critic")):
        failures.append("critic_read_holdout")
    if bool(report.get("performance_outcomes_read_by_critic")):
        failures.append("critic_read_performance_outcomes")
    batch_input = ((report.get("inputs") or {}).get("candidate_batch") or {})
    if batch_input.get("sha256") != file_sha256(batch_path):
        failures.append("critic_candidate_batch_sha256_mismatch")
    formula_input = ((report.get("inputs") or {}).get("formula_audit_report") or {})
    formula_path_value = formula_input.get("path")
    if not formula_input.get("sha256") or not formula_path_value:
        failures.append("critic_formula_audit_reference_missing")
    else:
        formula_path = Path(formula_path_value)
        if not formula_path.is_file():
            failures.append("critic_formula_audit_file_missing")
        elif file_sha256(formula_path) != formula_input.get("sha256"):
            failures.append("critic_formula_audit_sha256_mismatch")
        else:
            try:
                formula_report = json.loads(formula_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                failures.append("critic_formula_audit_invalid_json")
            else:
                formula_results = formula_report.get("required_factor_results") or {}
                if formula_report.get("schema_version") != FORMULA_AUDIT_SCHEMA_VERSION:
                    failures.append("critic_formula_audit_schema_invalid")
                if str(formula_report.get("candidate_batch_id") or "") != batch_id:
                    failures.append("critic_formula_audit_batch_id_mismatch")
                if not bool(formula_report.get("leakage_free")):
                    failures.append("critic_formula_audit_leakage_detected")
                if any("holdout" in str(key).lower() for key in formula_report):
                    failures.append("critic_formula_audit_contains_holdout")
                if set(formula_results) != candidate_ids or any(
                    formula_results.get(candidate_id) != "causal_pass"
                    for candidate_id in candidate_ids
                ):
                    failures.append("critic_formula_results_not_all_causal_pass")
    return not failures, failures
