"""Isolated end-to-end drill for the bounded panel factory.

The drill opens a synthetic admission file only inside its own directory,
injects one schema rejection and one killed formula-audit worker, then requires
the real formula audit, critic, and staged evaluator to finish successfully.
It never writes to the production trial registry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import panel_factory_orchestrator as factory
import panel_factory_scheduler as scheduler


SOURCE_ID = "CRYPTO_MARKET_SIZE_MOMENTUM"
FORMULA = "momentum_7d"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, sort_keys=True, indent=2)
        handle.write("\n")
    return path


def _candidate(candidate_id: str, source_id: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "source_ids": [source_id],
        "hypothesis": "Synthetic drill of an already registered momentum formula.",
        "family": "momentum",
        "required_fields": ["close"],
        "panel_formula": FORMULA,
        "direction": "long",
        "neutralization": "none",
        "bucket_policy": "none",
        "weighting_modes": ["rank_linear"],
        "generated_by": "synthetic_unattended_drill",
    }


def run_drill(substrate_manifest: Path | str, output_root: Path | str) -> dict[str, Any]:
    manifest = Path(substrate_manifest).expanduser().resolve(strict=True)
    root = Path(output_root).expanduser().resolve(strict=False) / f"drill_{_stamp()}_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=False)
    inputs = root / "inputs"
    literature_path = inputs / "literature.md"
    literature_path.parent.mkdir(parents=True, exist_ok=True)
    literature_path.write_text(
        "\n".join(
            [
                "# Synthetic Drill Literature Registry",
                "",
                f"- id: {SOURCE_ID}",
                "  source: Existing registered source used only to exercise factory plumbing.",
                "  mechanism: This drill makes no new economic claim.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    admission_path = _write_json(
        inputs / "source_admission.json",
        {
            "schema_version": 1,
            "policy": {
                "default_admission": False,
                "human_review_required_to_change": True,
                "evaluation_outcomes_cannot_change_admission": True,
                "holdout_cannot_change_admission": True,
            },
            "sources": [
                {
                    "source_id": SOURCE_ID,
                    "status": "synthetic_drill_only",
                    "allowed_for_generation": True,
                    "allowed_panel_formulas": [FORMULA],
                    "max_lifetime_variants": 3,
                    "reason": "Isolated plumbing drill; cannot authorize real research.",
                }
            ],
        },
    )
    policy_path = _write_json(
        inputs / "scheduler_policy.json",
        {
            "schema_version": 1,
            "policy_id": "synthetic_unattended_drill_v1",
            "max_generation_cycles_per_utc_day": 1,
            "cooldown_hours": 24,
            "max_candidates_proposed_per_cycle": 2,
            "max_candidates_accepted_per_cycle": 1,
            "max_active_jobs": 1,
            "one_source_per_cycle": True,
            "source_selection": "lowest_lifetime_variant_count_then_source_id",
            "holdout_feedback_to_ai": False,
            "automatic_admission_changes": False,
            "run_job_after_freeze": True,
            "incomplete_intent_requires_manual_review": True,
            "idle_when_no_source_is_admitted": True,
        },
    )

    isolated_trial_registry = root / "trial_registry.jsonl"
    production_trial_registry = Path(config.LOG_DIR) / "panel_trial_registry.jsonl"
    production_sha_before = _sha256(production_trial_registry)
    factory_root = root / "factory_jobs"
    evaluation_log_dir = root / "evaluation_logs"

    def create_isolated_job(batch_path: Path, substrate_path: Path, **kwargs: Any) -> str:
        kwargs["evaluation_log_dir"] = evaluation_log_dir
        return factory.create_job(batch_path, substrate_path, **kwargs)

    base_runners = factory.default_runners()

    def injected_formula_runner(context: factory.StageContext) -> factory.StageResult:
        if context.attempt == 1:
            def fail_heartbeat() -> None:
                raise RuntimeError("synthetic_worker_interruption")

            interrupted_context = replace(context, heartbeat=fail_heartbeat)
            factory._run_process(
                [
                    sys.executable,
                    "-c",
                    (
                        "import subprocess,sys,time;"
                        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
                        "time.sleep(60)"
                    ),
                ],
                interrupted_context,
            )
            raise AssertionError("injected worker unexpectedly survived")
        return base_runners["formula_audit"](context)

    def run_with_injected_failure(job_id: str, *, root: Path | str) -> dict[str, Any]:
        return factory.run_job(
            job_id,
            root=root,
            runners={
                **base_runners,
                "formula_audit": injected_formula_runner,
            },
        )

    good_id = f"synthetic_drill_momentum_{uuid.uuid4().hex[:8]}"
    bad_id = f"synthetic_drill_reject_{uuid.uuid4().hex[:8]}"
    result = scheduler.run_scheduler_once(
        substrate_manifest=manifest,
        source_admission_path=admission_path,
        policy_path=policy_path,
        literature_path=literature_path,
        trial_registry_path=isolated_trial_registry,
        scheduler_root=root / "scheduler",
        factory_root=factory_root,
        recent_report_path=None,
        raw_candidates=[
            _candidate(good_id, SOURCE_ID),
            _candidate(bad_id, "SYNTHETIC_UNKNOWN_SOURCE"),
        ],
        execute_job=True,
        create_job_fn=create_isolated_job,
        run_job_fn=run_with_injected_failure,
    )

    job_id = str(result.get("factory_job_id") or "")
    job_dir = factory_root / job_id if job_id else factory_root / "missing_job"
    status = factory.job_status(job_dir) if job_dir.is_dir() else {}
    process_final_path = job_dir / "processes" / "formula_audit_attempt_1_final.json"
    process_final = (
        json.loads(process_final_path.read_text(encoding="utf-8"))
        if process_final_path.is_file()
        else {}
    )
    commit_path = job_dir / "outputs" / "trial_event_commit.json"
    commit = json.loads(commit_path.read_text(encoding="utf-8")) if commit_path.is_file() else {}
    trial_rows = []
    if isolated_trial_registry.is_file():
        trial_rows = [
            json.loads(line)
            for line in isolated_trial_registry.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    evaluation_artifact = (status.get("artifacts") or {}).get("evaluation") or {}
    report_path = Path(str(evaluation_artifact.get("path") or ""))
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    production_sha_after = _sha256(production_trial_registry)

    checks = {
        "scheduler_terminal_completed": result.get("status") == "job_terminal_completed",
        "one_candidate_accepted": result.get("accepted_candidate_count") == 1,
        "one_candidate_rejected": result.get("rejected_candidate_count") == 1,
        "formula_worker_retried_once": (status.get("attempts") or {}).get("formula_audit") == 2,
        "critic_ran_once": (status.get("attempts") or {}).get("critic") == 1,
        "evaluation_ran_once": (status.get("attempts") or {}).get("evaluation") == 1,
        "interrupted_process_group_terminated": (
            process_final.get("outcome") == "terminated_on_orchestrator_exception"
            and bool((process_final.get("termination") or {}).get("success"))
        ),
        "no_active_process_marker": not (job_dir / "active_process.json").exists(),
        "immutable_job_inputs_valid": not factory.validate_job_inputs(factory.load_contract(job_dir)),
        "trial_commit_exactly_one_row": commit.get("appended_row_count") == 1,
        "isolated_trial_has_generated_rejected_evaluated": sorted(
            str(row.get("event")) for row in trial_rows
        ) == ["evaluated", "generated", "schema_rejected"],
        "production_trial_registry_unchanged": production_sha_before == production_sha_after,
        "evaluation_report_bound_to_batch": report.get("candidate_batch_id") == result.get("cycle_id"),
        "evaluation_report_present": report_path.is_file(),
        "no_combo_artifact_created": not any(root.rglob("*combo*.json")),
    }
    summary = {
        "schema_version": "panel_factory_unattended_drill_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "drill_root": str(root),
        "substrate_manifest": str(manifest),
        "scheduler_result": result,
        "job_status": status,
        "production_trial_registry_sha256_before": production_sha_before,
        "production_trial_registry_sha256_after": production_sha_after,
        "isolated_trial_row_count": len(trial_rows),
        "evaluation_candidate_statuses": [
            {
                "candidate_id": row.get("candidate_id"),
                "status": row.get("status"),
                "holdout_accessed": row.get("holdout_accessed"),
            }
            for row in report.get("factors", [])
            if row.get("candidate_id")
        ],
        "checks": checks,
        "passed": all(checks.values()),
    }
    summary["summary_sha256"] = hashlib.sha256(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _write_json(root / "SUMMARY.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--substrate-manifest", required=True)
    parser.add_argument("--output-root", default=str(Path(config.LOG_DIR) / "panel_factory_drills"))
    args = parser.parse_args()
    summary = run_drill(args.substrate_manifest, args.output_root)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
