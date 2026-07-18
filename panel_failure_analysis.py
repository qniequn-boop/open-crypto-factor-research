"""Failure analysis for preregistered panel candidate batches.

The report is deliberately diagnostic: it explains why a frozen batch did not
advance, without creating new candidates or tuning rejected ones.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import config
import panel_candidate_registry as registry


LOG_DIR = Path(config.LOG_DIR)


def _candidate_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in report.get("factors", []) if row.get("candidate_id")]


def build_failure_analysis(
    *,
    batch: dict[str, Any],
    report: dict[str, Any],
    trial_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = batch.get("candidates", [])
    candidate_ids = {candidate.get("candidate_id") for candidate in candidates}
    rows = _candidate_rows(report)
    rows_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_candidate[str(row.get("candidate_id"))].append(row)

    source_counts = Counter()
    family_counts = Counter()
    formula_counts = Counter()
    failed_check_counts = Counter()
    statuses = Counter()
    candidate_summaries = []

    for candidate in candidates:
        cid = str(candidate.get("candidate_id"))
        source_counts.update(candidate.get("source_ids", []))
        family_counts.update([candidate.get("family")])
        formula_counts.update([candidate.get("panel_formula")])
        evaluated_rows = rows_by_candidate.get(cid, [])
        row_statuses = [row.get("status") for row in evaluated_rows]
        statuses.update(row_statuses)
        for row in evaluated_rows:
            failed_check_counts.update(row.get("failed_checks", []))
        candidate_summaries.append(
            {
                "candidate_id": cid,
                "source_ids": candidate.get("source_ids", []),
                "family": candidate.get("family"),
                "panel_formula": candidate.get("panel_formula"),
                "weighting_modes": candidate.get("weighting_modes", []),
                "evaluated_variants": len(evaluated_rows),
                "statuses": row_statuses,
                "failed_checks": sorted({check for row in evaluated_rows for check in row.get("failed_checks", [])}),
            }
        )

    trial_events = [
        row
        for row in trial_rows
        if row.get("batch_id") == batch.get("batch_id") or row.get("candidate_id") in candidate_ids
    ]
    generated = [row for row in trial_events if row.get("event") == "generated"]
    rejected = [row for row in trial_events if str(row.get("status")) == "rejected"]
    evaluated = [row for row in trial_events if row.get("event") == "evaluated"]
    pass_count = int(report.get("pass_count") or 0)

    recommendations = []
    if any(
        failed_check_counts.get(name, 0)
        for name in ("multiple_testing_pass", "deflated_sharpe_pass", "cscv_pbo_pass")
    ):
        recommendations.append("keep candidate budget small; multiple-testing penalty is already binding")
    if failed_check_counts.get("rolling_ic_stable", 0) or failed_check_counts.get("rolling_sharpe_not_fragile", 0):
        recommendations.append("prioritize regime/rolling stability before adding formula variants")
    if formula_counts:
        repeated_formulas = [formula for formula, count in formula_counts.items() if count > 1]
        if repeated_formulas:
            recommendations.append("avoid near-duplicate formulas in the next AI batch")
    if not recommendations:
        recommendations.append("archive this batch and improve data/audit coverage before the next generation round")

    return {
        "schema_version": 1,
        "batch_id": batch.get("batch_id"),
        "report_created_at_utc": report.get("created_at_utc"),
        "candidate_count": len(candidates),
        "candidate_variant_count": sum(max(len(c.get("weighting_modes", [])), 1) for c in candidates),
        "report_candidate_factor_definition_count": report.get("candidate_factor_definition_count"),
        "report_factor_count": report.get("factor_count"),
        "multiple_testing_trial_count": report.get("multiple_testing_trial_count"),
        "pass_count": pass_count,
        "watchlist_count": int(report.get("watchlist_count") or 0),
        "combo_allowed": bool(pass_count > 0),
        "combo_policy": "Only panel_factor_pass candidates may enter combo.",
        "status_counts": dict(statuses),
        "source_counts": dict(source_counts),
        "family_counts": dict(family_counts),
        "formula_counts": dict(formula_counts),
        "failed_check_counts": dict(failed_check_counts),
        "trial_event_counts": {
            "generated": len(generated),
            "rejected": len(rejected),
            "evaluated": len(evaluated),
        },
        "candidates": candidate_summaries,
        "recommendations": recommendations,
        "interpretation": (
            "This is failure analysis for research process control, not evidence "
            "that rejected candidates should be tuned or revived."
        ),
    }


def write_failure_analysis(
    *,
    batch_path: Path | str,
    report_path: Path | str,
    trial_registry_path: Path | str = registry.TRIAL_REGISTRY_PATH,
    log_dir: Path | str = LOG_DIR,
) -> Path:
    batch = json.loads(Path(batch_path).read_text(encoding="utf-8"))
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    trial_rows = registry.load_trial_rows(trial_registry_path)
    analysis = build_failure_analysis(batch=batch, report=report, trial_rows=trial_rows)
    out_dir = Path(log_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"panel_failure_analysis_{analysis['batch_id']}.json"
    out_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    out_path = write_failure_analysis(batch_path=args.batch, report_path=args.report)
    print(f"WROTE {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
