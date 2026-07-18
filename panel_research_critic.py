"""Independent fail-closed critic for frozen panel candidate batches."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import panel_ai_candidate_generator
import panel_candidate_registry
import panel_critic_contract
import panel_factor_research
import panel_formula_audit
import panel_literature_registry


CRITIC_SCHEMA_VERSION = panel_critic_contract.CRITIC_SCHEMA_VERSION
MAX_BATCH_CANDIDATES = panel_ai_candidate_generator.DEFAULT_MAX_CANDIDATES
MAX_FAMILY_VARIANTS = panel_ai_candidate_generator.DEFAULT_MAX_FAMILY_VARIANTS
LOG_DIR = Path(config.LOG_DIR)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _variant_count(candidate: dict[str, Any]) -> int:
    modes = candidate.get("weighting_modes")
    return max(len(modes), 1) if isinstance(modes, list) else 1


def _contains_forbidden_holdout_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if "holdout" in str(key).lower():
                return True
            if _contains_forbidden_holdout_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_holdout_key(item) for item in value)
    return False


def _historical_guardrail_context(
    trial_rows: list[dict[str, Any]],
    *,
    current_batch_id: str,
) -> dict[str, Any]:
    historical = [row for row in trial_rows if str(row.get("batch_id") or "") != current_batch_id]
    candidate_ids = {
        str(row["candidate_id"])
        for row in historical
        if row.get("candidate_id") and str(row.get("status")) != "rejected"
    }
    signatures: set[str] = set()
    family_by_candidate: dict[str, tuple[str, int]] = {}
    for row in historical:
        if str(row.get("status")) == "rejected":
            continue
        if row.get("candidate_signature"):
            signatures.add(str(row["candidate_signature"]))
        if row.get("source_ids") and row.get("panel_formula"):
            signatures.add(panel_candidate_registry.candidate_signature(row, approximate=True))
        candidate_id = str(row.get("candidate_id") or "")
        family = str(row.get("family") or "")
        if candidate_id and family:
            old_family, old_count = family_by_candidate.get(candidate_id, (family, 0))
            family_by_candidate[candidate_id] = (
                old_family,
                max(old_count, int(row.get("variant_count") or 1)),
            )
    family_counts: dict[str, int] = {}
    for family, count in family_by_candidate.values():
        family_counts[family] = family_counts.get(family, 0) + count
    return {
        "candidate_ids": candidate_ids,
        "signatures": signatures,
        "family_counts": family_counts,
        "historical_row_count": len(historical),
    }


def review_batch(
    candidate_batch: dict[str, Any],
    formula_audit_report: dict[str, Any],
    *,
    literature_registry: dict[str, Any],
    trial_rows: list[dict[str, Any]],
    literature_source_ids: set[str] | None = None,
    max_batch_candidates: int = MAX_BATCH_CANDIDATES,
    max_family_variants: int = MAX_FAMILY_VARIANTS,
) -> dict[str, Any]:
    batch_id = str(candidate_batch.get("batch_id") or "")
    candidates = candidate_batch.get("candidates")
    if not batch_id or not isinstance(candidates, list):
        raise ValueError("frozen_candidate_batch_invalid")
    source_ids = (
        set(literature_source_ids)
        if literature_source_ids is not None
        else panel_candidate_registry.load_literature_source_ids()
    )
    authorizing_entries = panel_literature_registry.candidate_authorizing_entries(literature_registry)
    authorizers_by_source: dict[str, list[dict[str, Any]]] = {}
    for entry in authorizing_entries:
        authorizers_by_source.setdefault(str(entry["source_id"]), []).append(entry)
    all_entries_by_source: dict[str, list[dict[str, Any]]] = {}
    for entry in literature_registry["entries"]:
        all_entries_by_source.setdefault(str(entry["source_id"]), []).append(entry)

    audit_batch_matches = str(formula_audit_report.get("candidate_batch_id") or "") == batch_id
    audit_schema_valid = formula_audit_report.get("schema_version") == panel_formula_audit.AUDIT_SCHEMA_VERSION
    audit_leakage_free = bool(formula_audit_report.get("leakage_free"))
    audit_holdout_free = not _contains_forbidden_holdout_key(formula_audit_report)
    audit_results = formula_audit_report.get("required_factor_results") or {}
    historical = _historical_guardrail_context(trial_rows, current_batch_id=batch_id)

    seen_ids: set[str] = set()
    seen_signatures: set[str] = set()
    batch_family_variants: dict[str, int] = {}
    candidate_reviews = []
    for candidate in candidates:
        candidate = dict(candidate)
        candidate_id = str(candidate.get("candidate_id") or "")
        family = str(candidate.get("family") or "")
        signature = panel_candidate_registry.candidate_signature(candidate)
        approximate_signature = panel_candidate_registry.candidate_signature(candidate, approximate=True)
        schema_ok, schema_errors = panel_candidate_registry.validate_candidate(
            candidate,
            literature_source_ids=source_ids,
            known_formulas=set(panel_factor_research.FACTOR_DEFINITIONS),
            allowed_weighting_modes=set(panel_factor_research.WEIGHTING_MODES),
        )
        formula_spec = panel_factor_research.FACTOR_DEFINITIONS.get(str(candidate.get("panel_formula")), {})
        expected_direction = panel_factor_research._formula_candidate_direction(formula_spec)
        cited_sources = [str(value) for value in candidate.get("source_ids") or []]
        source_authorization = {
            source_id: [entry["replication_id"] for entry in authorizers_by_source.get(source_id, [])]
            for source_id in cited_sources
        }
        unauthorized_sources = sorted(
            source_id for source_id, replication_ids in source_authorization.items() if not replication_ids
        )
        engineering_source_misuse = sorted(
            source_id
            for source_id in cited_sources
            if all_entries_by_source.get(source_id)
            and all(entry["allowed_use"] == "engineering_pattern" for entry in all_entries_by_source[source_id])
        )
        prior_signature_duplicate = (
            signature in historical["signatures"] or approximate_signature in historical["signatures"]
        )
        within_batch_duplicate = candidate_id in seen_ids or signature in seen_signatures or approximate_signature in seen_signatures
        projected_family_variants = (
            int(historical["family_counts"].get(family, 0))
            + int(batch_family_variants.get(family, 0))
            + _variant_count(candidate)
        )
        checks = {
            "schema_valid": schema_ok,
            "candidate_id_unique": candidate_id not in seen_ids,
            "candidate_id_not_historically_reused": candidate_id not in historical["candidate_ids"],
            "candidate_signature_unique": not within_batch_duplicate and not prior_signature_duplicate,
            "formula_direction_valid": not expected_direction or str(candidate.get("direction", "")).lower() == expected_direction,
            "formula_not_deprecated": not bool(formula_spec.get("deprecated_for_candidates")),
            "all_sources_formally_authorized": bool(cited_sources) and not unauthorized_sources,
            "engineering_sources_not_used_as_alpha_evidence": not engineering_source_misuse,
            "family_budget_available": projected_family_variants <= int(max_family_variants),
            "formula_audit_batch_matches": audit_batch_matches,
            "formula_audit_schema_valid": audit_schema_valid,
            "formula_audit_leakage_free": audit_leakage_free,
            "formula_audit_contains_no_holdout": audit_holdout_free,
            "candidate_formula_causally_verified": audit_results.get(candidate_id) == "causal_pass",
        }
        blockers = [name for name, passed in checks.items() if not passed]
        candidate_reviews.append(
            {
                "candidate_id": candidate_id,
                "family": family,
                "checks": checks,
                "blockers": blockers,
                "approved": not blockers,
                "schema_errors": schema_errors,
                "source_authorization": source_authorization,
                "unauthorized_sources": unauthorized_sources,
                "engineering_source_misuse": engineering_source_misuse,
                "historical_signature_duplicate": prior_signature_duplicate,
                "projected_family_variants": projected_family_variants,
                "family_variant_budget": int(max_family_variants),
                "formula_audit_status": audit_results.get(candidate_id, "missing"),
            }
        )
        seen_ids.add(candidate_id)
        seen_signatures.add(signature)
        seen_signatures.add(approximate_signature)
        batch_family_variants[family] = batch_family_variants.get(family, 0) + _variant_count(candidate)

    batch_checks = {
        "candidate_count_positive": len(candidates) > 0,
        "candidate_count_within_budget": len(candidates) <= int(max_batch_candidates),
        "formula_audit_batch_matches": audit_batch_matches,
        "formula_audit_schema_valid": audit_schema_valid,
        "formula_audit_leakage_free": audit_leakage_free,
        "formula_audit_contains_no_holdout": audit_holdout_free,
        "all_candidates_approved": bool(candidate_reviews) and all(row["approved"] for row in candidate_reviews),
    }
    batch_blockers = [name for name, passed in batch_checks.items() if not passed]
    approved = not batch_blockers
    return {
        "created_at_utc": _stamp(),
        "schema_version": CRITIC_SCHEMA_VERSION,
        "critic_type": "deterministic_independent_fail_closed",
        "batch_id": batch_id,
        "decision": "critic_approved" if approved else "critic_rejected",
        "approved": approved,
        "batch_checks": batch_checks,
        "batch_blockers": batch_blockers,
        "candidate_count": len(candidates),
        "candidate_reviews": candidate_reviews,
        "budgets": {
            "max_batch_candidates": int(max_batch_candidates),
            "max_family_variants": int(max_family_variants),
        },
        "historical_guardrail_context": {
            "historical_row_count": historical["historical_row_count"],
            "family_variant_counts": historical["family_counts"],
        },
        "holdout_read_by_critic": False,
        "performance_outcomes_read_by_critic": False,
        "formal_promotion_possible": False,
        "references": [
            {
                "name": "R&D-Agent framework",
                "url": "https://rdagent.readthedocs.io/en/latest/project_framework_introduction.html",
                "adopted_principle": "separate hypothesis, implementation, execution feedback, and critic responsibilities",
            }
        ],
    }


def _write_report(report: dict[str, Any], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path = report_dir / f"panel_critic_report_{report['batch_id']}_{report['created_at_utc']}.json"
    path.write_text(payload, encoding="utf-8")
    (report_dir / "panel_critic_report_latest.json").write_text(payload, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-batch", required=True)
    parser.add_argument("--formula-audit-report", required=True)
    parser.add_argument("--trial-registry", default=str(panel_candidate_registry.TRIAL_REGISTRY_PATH))
    parser.add_argument("--literature-registry", default=str(panel_literature_registry.REGISTRY_PATH))
    parser.add_argument(
        "--hypothesis-registry",
        default=str(panel_candidate_registry.REGISTRY_PATH),
    )
    parser.add_argument("--report-dir", default=str(LOG_DIR))
    parser.add_argument("--record-trial-events", action="store_true")
    args = parser.parse_args(argv)

    batch_path = Path(args.candidate_batch).resolve(strict=True)
    audit_path = Path(args.formula_audit_report).resolve(strict=True)
    trial_path = Path(args.trial_registry)
    literature_path = Path(args.literature_registry).resolve(strict=True)
    hypothesis_path = Path(args.hypothesis_registry).resolve(strict=True)
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    literature = panel_literature_registry.load_registry(literature_path)
    trial_rows = panel_candidate_registry.load_trial_rows(trial_path)
    report = review_batch(
        batch,
        audit,
        literature_registry=literature,
        trial_rows=trial_rows,
        literature_source_ids=panel_candidate_registry.load_literature_source_ids(hypothesis_path),
    )
    report["inputs"] = {
        "candidate_batch": {"path": str(batch_path), "sha256": _sha256(batch_path)},
        "formula_audit_report": {"path": str(audit_path), "sha256": _sha256(audit_path)},
        "trial_registry": {
            "path": str(trial_path.resolve(strict=False)),
            "sha256": _sha256(trial_path) if trial_path.is_file() else None,
        },
        "literature_registry": {"path": str(literature_path), "sha256": _sha256(literature_path)},
        "hypothesis_registry": {"path": str(hypothesis_path), "sha256": _sha256(hypothesis_path)},
    }
    report_path = _write_report(report, Path(args.report_dir))
    report_sha256 = _sha256(report_path)
    if args.record_trial_events:
        candidates_by_id = {str(row["candidate_id"]): row for row in batch["candidates"]}
        for review in report["candidate_reviews"]:
            panel_candidate_registry.append_trial_event(
                candidates_by_id[review["candidate_id"]],
                event="critic_reviewed",
                status="approved" if review["approved"] else "rejected",
                reason=";".join(review["blockers"]),
                batch_id=report["batch_id"],
                log_dir=trial_path.parent,
                extra={
                    "critic_schema_version": CRITIC_SCHEMA_VERSION,
                    "critic_report_path": str(report_path),
                    "critic_report_sha256": report_sha256,
                },
            )
    print(f"WROTE {report_path}")
    print(f"DECISION {report['decision']} CANDIDATES {report['candidate_count']}")
    for review in report["candidate_reviews"]:
        print(review["candidate_id"], "APPROVED" if review["approved"] else "BLOCKED", ",".join(review["blockers"]))
    return 0 if report["approved"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
