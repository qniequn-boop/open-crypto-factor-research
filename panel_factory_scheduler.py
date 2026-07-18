"""Bounded source-admission scheduler for the panel factor factory.

One invocation can start at most one generation cycle. The scheduler idles
when no literature source is admitted and never changes source admission from
backtest outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import config
import panel_ai_candidate_generator as generator
import panel_candidate_registry as candidate_registry
import panel_factory_orchestrator as factory
import panel_factor_research as panel


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_ADMISSION_PATH = PROJECT_DIR / "PANEL_SOURCE_ADMISSION_REGISTRY_V1.json"
DEFAULT_POLICY_PATH = PROJECT_DIR / "PANEL_FACTORY_SCHEDULER_POLICY_V1.json"
DEFAULT_LITERATURE_PATH = PROJECT_DIR / "LITERATURE_HYPOTHESIS_REGISTRY.md"
DEFAULT_TRIAL_REGISTRY_PATH = Path(config.LOG_DIR) / "panel_trial_registry.jsonl"
DEFAULT_SCHEDULER_ROOT = Path(config.LOG_DIR) / "panel_factory_scheduler"
RECORD_SCHEMA = "panel_factory_scheduler_record_v1"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _compact(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_immutable_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    record = dict(payload)
    record["record_schema"] = RECORD_SCHEMA
    record["record_sha256"] = _payload_sha256(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=True, sort_keys=True, indent=2)
        handle.write("\n")
    return record


def _load_records(directory: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        declared = record.get("record_sha256")
        unsigned = dict(record)
        unsigned.pop("record_sha256", None)
        if record.get("record_schema") != RECORD_SCHEMA or _payload_sha256(unsigned) != declared:
            raise ValueError(f"scheduler_record_integrity_failed:{path}")
        record["_path"] = str(path.resolve())
        records.append(record)
    return records


def load_source_admission_registry(
    path: Path | str = DEFAULT_ADMISSION_PATH,
    *,
    literature_path: Path | str = DEFAULT_LITERATURE_PATH,
) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(payload.get("schema_version") or 0) != 1:
        raise ValueError("source_admission_schema_invalid")
    policy = payload.get("policy") or {}
    required_policy = {
        "default_admission": False,
        "human_review_required_to_change": True,
        "evaluation_outcomes_cannot_change_admission": True,
        "holdout_cannot_change_admission": True,
    }
    for field, expected in required_policy.items():
        if policy.get(field) is not expected:
            raise ValueError(f"source_admission_policy_invalid:{field}")
    rows = payload.get("sources")
    if not isinstance(rows, list):
        raise ValueError("source_admission_sources_required")
    entries: dict[str, dict[str, Any]] = {}
    known_formulas = set(panel.FACTOR_DEFINITIONS)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"source_admission_row_not_object:{index}")
        required = {
            "source_id",
            "status",
            "allowed_for_generation",
            "allowed_panel_formulas",
            "max_lifetime_variants",
            "reason",
        }
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"source_admission_missing_fields:{index}:{','.join(missing)}")
        source_id = str(row["source_id"])
        if source_id in entries:
            raise ValueError(f"source_admission_duplicate_source:{source_id}")
        formulas = row["allowed_panel_formulas"]
        budget = int(row["max_lifetime_variants"])
        if not isinstance(formulas, list):
            raise ValueError(f"source_admission_formulas_not_list:{source_id}")
        unknown_formulas = sorted(set(map(str, formulas)) - known_formulas)
        if unknown_formulas:
            raise ValueError(
                f"source_admission_unknown_formulas:{source_id}:{','.join(unknown_formulas)}"
            )
        if row["allowed_for_generation"] is True:
            if not formulas or budget < 1:
                raise ValueError(f"source_admission_open_without_formula_budget:{source_id}")
        elif formulas or budget != 0:
            raise ValueError(f"source_admission_closed_with_formula_budget:{source_id}")
        entries[source_id] = dict(row)
    literature_ids = candidate_registry.load_literature_source_ids(literature_path)
    missing = sorted(literature_ids - set(entries))
    unknown = sorted(set(entries) - literature_ids)
    if missing or unknown:
        raise ValueError(
            "source_admission_literature_mismatch:"
            f"missing={','.join(missing)}:unknown={','.join(unknown)}"
        )
    return entries


def load_scheduler_policy(path: Path | str = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(policy.get("schema_version") or 0) != 1:
        raise ValueError("scheduler_policy_schema_invalid")
    positive_fields = {
        "max_generation_cycles_per_utc_day",
        "cooldown_hours",
        "max_candidates_proposed_per_cycle",
        "max_candidates_accepted_per_cycle",
        "max_active_jobs",
    }
    for field in positive_fields:
        if int(policy.get(field) or 0) < 1:
            raise ValueError(f"scheduler_policy_positive_field_invalid:{field}")
    if int(policy["max_candidates_accepted_per_cycle"]) > int(
        policy["max_candidates_proposed_per_cycle"]
    ):
        raise ValueError("scheduler_policy_accepted_exceeds_proposed")
    required_bools = {
        "one_source_per_cycle": True,
        "holdout_feedback_to_ai": False,
        "automatic_admission_changes": False,
        "incomplete_intent_requires_manual_review": True,
        "idle_when_no_source_is_admitted": True,
    }
    for field, expected in required_bools.items():
        if policy.get(field) is not expected:
            raise ValueError(f"scheduler_policy_invalid:{field}")
    return policy


def _receipt(
    scheduler_root: Path,
    *,
    run_id: str,
    now: datetime,
    status: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return _write_immutable_json(
        scheduler_root / "runs" / f"{run_id}.json",
        {
            "run_id": run_id,
            "created_at_utc": _iso(now),
            "status": status,
            "generation_attempted": False,
            **details,
        },
    )


def _active_jobs(status: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in status.get("jobs", [])
        if not bool(row.get("terminal")) or row.get("state") == "evidence_invalid"
    ]


def run_scheduler_once(
    *,
    substrate_manifest: Path | str | None = None,
    source_admission_path: Path | str = DEFAULT_ADMISSION_PATH,
    policy_path: Path | str = DEFAULT_POLICY_PATH,
    literature_path: Path | str = DEFAULT_LITERATURE_PATH,
    trial_registry_path: Path | str = DEFAULT_TRIAL_REGISTRY_PATH,
    scheduler_root: Path | str = DEFAULT_SCHEDULER_ROOT,
    factory_root: Path | str = factory.DEFAULT_ROOT,
    recent_report_path: Path | str | None = generator.LATEST_REPORT_PATH,
    client: Any = None,
    raw_candidates: list[dict[str, Any]] | None = None,
    execute_job: bool | None = None,
    now: datetime | None = None,
    factory_status_fn: Callable[..., dict[str, Any]] = factory.refresh_factory_status,
    create_job_fn: Callable[..., str] = factory.create_job,
    run_job_fn: Callable[..., dict[str, Any]] = factory.run_job,
) -> dict[str, Any]:
    current = (now or _utc_now()).astimezone(timezone.utc)
    root = Path(scheduler_root).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    run_id = f"scheduler_run_{_compact(current)}_{uuid.uuid4().hex[:8]}"
    admission_path = Path(source_admission_path).resolve(strict=True)
    schedule_policy_path = Path(policy_path).resolve(strict=True)
    hypothesis_path = Path(literature_path).resolve(strict=True)
    trial_path = Path(trial_registry_path).resolve(strict=False)
    entries = load_source_admission_registry(admission_path, literature_path=hypothesis_path)
    policy = load_scheduler_policy(schedule_policy_path)
    common = {
        "policy_id": policy.get("policy_id"),
        "policy_sha256": _file_sha256(schedule_policy_path),
        "source_admission_sha256": _file_sha256(admission_path),
        "literature_sha256": _file_sha256(hypothesis_path),
    }

    with factory._exclusive_lock(root / ".scheduler.lock"):
        intents = _load_records(root / "intents")
        results = _load_records(root / "results")
        completed_cycle_ids = {str(row.get("cycle_id")) for row in results}
        incomplete = [row for row in intents if str(row.get("cycle_id")) not in completed_cycle_ids]
        if incomplete:
            return _receipt(
                root,
                run_id=run_id,
                now=current,
                status="blocked_incomplete_generation_intent",
                details={**common, "incomplete_cycle_ids": [row["cycle_id"] for row in incomplete]},
            )

        factory_status = factory_status_fn(root=factory_root)
        active = _active_jobs(factory_status)
        if len(active) >= int(policy["max_active_jobs"]):
            return _receipt(
                root,
                run_id=run_id,
                now=current,
                status="idle_active_job_limit",
                details={**common, "active_job_ids": [row.get("job_id") for row in active]},
            )

        todays_intents = [
            row for row in intents if _parse_utc(str(row["created_at_utc"])).date() == current.date()
        ]
        if len(todays_intents) >= int(policy["max_generation_cycles_per_utc_day"]):
            return _receipt(
                root,
                run_id=run_id,
                now=current,
                status="idle_daily_generation_quota",
                details={**common, "generation_cycles_today": len(todays_intents)},
            )
        if intents:
            latest_started = max(_parse_utc(str(row["created_at_utc"])) for row in intents)
            next_allowed = latest_started + timedelta(hours=int(policy["cooldown_hours"]))
            if current < next_allowed:
                return _receipt(
                    root,
                    run_id=run_id,
                    now=current,
                    status="idle_generation_cooldown",
                    details={**common, "next_generation_allowed_at_utc": _iso(next_allowed)},
                )

        admitted = [row for row in entries.values() if row["allowed_for_generation"] is True]
        if not admitted:
            return _receipt(
                root,
                run_id=run_id,
                now=current,
                status="idle_no_admitted_source",
                details={**common, "admitted_source_count": 0},
            )

        source_counts = candidate_registry.historical_source_variant_counts(trial_path)
        eligible = [
            row
            for row in admitted
            if source_counts.get(str(row["source_id"]), 0) < int(row["max_lifetime_variants"])
        ]
        if not eligible:
            return _receipt(
                root,
                run_id=run_id,
                now=current,
                status="idle_source_budgets_exhausted",
                details={**common, "source_variant_counts": source_counts},
            )
        selected = min(
            eligible,
            key=lambda row: (source_counts.get(str(row["source_id"]), 0), str(row["source_id"])),
        )
        source_id = str(selected["source_id"])
        manifest_path = Path(substrate_manifest).resolve(strict=True) if substrate_manifest else None
        if manifest_path is None:
            return _receipt(
                root,
                run_id=run_id,
                now=current,
                status="blocked_substrate_manifest_required",
                details={**common, "selected_source_id": source_id},
            )

        cycle_id = f"cycle_{_compact(current)}_{uuid.uuid4().hex[:8]}"
        remaining = int(selected["max_lifetime_variants"]) - source_counts.get(source_id, 0)
        proposed_limit = min(int(policy["max_candidates_proposed_per_cycle"]), remaining)
        intent = _write_immutable_json(
            root / "intents" / f"{cycle_id}.json",
            {
                "cycle_id": cycle_id,
                "created_at_utc": _iso(current),
                "selected_source_id": source_id,
                "allowed_panel_formulas": sorted(map(str, selected["allowed_panel_formulas"])),
                "proposed_candidate_limit": proposed_limit,
                "accepted_candidate_limit": int(policy["max_candidates_accepted_per_cycle"]),
                "source_variant_count_before": source_counts.get(source_id, 0),
                "source_lifetime_variant_budget": int(selected["max_lifetime_variants"]),
                "substrate_manifest_path": str(manifest_path),
                "substrate_manifest_sha256": _file_sha256(manifest_path),
                "trial_registry_sha256_before": _file_sha256(trial_path) if trial_path.is_file() else None,
                **common,
            },
        )

        result: dict[str, Any] = {
            "cycle_id": cycle_id,
            "created_at_utc": _iso(current),
            "generation_attempted": True,
            "selected_source_id": source_id,
            "intent_sha256": intent["record_sha256"],
            **common,
        }
        try:
            allowed_sources = {source_id}
            allowed_formulas = set(map(str, selected["allowed_panel_formulas"]))
            proposals = raw_candidates
            if proposals is None:
                proposals = generator.generate_raw_candidates(
                    max_candidates=proposed_limit,
                    client=client,
                    literature_path=hypothesis_path,
                    recent_report_path=recent_report_path,
                    allowed_source_ids=allowed_sources,
                    allowed_panel_formulas=allowed_formulas,
                )
            batch_path, accepted, rejected = generator.freeze_generated_candidates(
                proposals,
                max_candidates=proposed_limit,
                max_accepted_candidates=int(policy["max_candidates_accepted_per_cycle"]),
                log_dir=root / "batches",
                literature_path=hypothesis_path,
                trial_registry_path=trial_path,
                batch_id=cycle_id,
                allowed_source_ids=allowed_sources,
                allowed_panel_formulas=allowed_formulas,
                source_variant_budgets={source_id: int(selected["max_lifetime_variants"])},
            )
            result.update(
                {
                    "candidate_batch_path": str(batch_path.resolve()),
                    "candidate_batch_sha256": _file_sha256(batch_path),
                    "proposed_candidate_count": min(len(proposals), proposed_limit),
                    "accepted_candidate_count": len(accepted),
                    "rejected_candidate_count": len(rejected),
                    "trial_registry_sha256_after": _file_sha256(trial_path),
                }
            )
            if not accepted:
                result["status"] = "no_accepted_candidates"
            else:
                job_id = create_job_fn(
                    batch_path,
                    manifest_path,
                    root=factory_root,
                    trial_registry_path=trial_path,
                    hypothesis_registry_path=hypothesis_path,
                )
                result["factory_job_id"] = job_id
                should_execute = policy["run_job_after_freeze"] if execute_job is None else execute_job
                if should_execute:
                    job_status = run_job_fn(job_id, root=factory_root)
                    result["factory_job_state"] = job_status.get("state")
                    result["status"] = f"job_terminal_{job_status.get('state')}"
                else:
                    result["status"] = "job_registered"
        except Exception as exc:
            result.update(
                {
                    "status": "scheduler_error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:2000],
                }
            )
        return _write_immutable_json(root / "results" / f"{cycle_id}.json", result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--substrate-manifest")
    parser.add_argument("--source-admission", default=str(DEFAULT_ADMISSION_PATH))
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--literature", default=str(DEFAULT_LITERATURE_PATH))
    parser.add_argument("--trial-registry", default=str(DEFAULT_TRIAL_REGISTRY_PATH))
    parser.add_argument("--scheduler-root", default=str(DEFAULT_SCHEDULER_ROOT))
    parser.add_argument("--factory-root", default=str(factory.DEFAULT_ROOT))
    parser.add_argument("--from-json")
    parser.add_argument("--register-only", action="store_true")
    args = parser.parse_args()
    proposals = None
    if args.from_json:
        proposals = generator.parse_llm_candidates(Path(args.from_json).read_text(encoding="utf-8"))
    result = run_scheduler_once(
        substrate_manifest=args.substrate_manifest,
        source_admission_path=args.source_admission,
        policy_path=args.policy,
        literature_path=args.literature,
        trial_registry_path=args.trial_registry,
        scheduler_root=args.scheduler_root,
        factory_root=args.factory_root,
        raw_candidates=proposals,
        execute_job=False if args.register_only else None,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 2 if str(result.get("status", "")).startswith(("blocked_", "scheduler_error")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
