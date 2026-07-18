"""Fail-closed state machine for frozen panel-factor research jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import config
import panel_critic_contract
import panel_formula_audit


JOB_SCHEMA_VERSION = "panel_factory_job_v1"
EVENT_SCHEMA_VERSION = "panel_factory_job_event_v1"
STATUS_SCHEMA_VERSION = "panel_factory_status_v1"
PROCESS_SCHEMA_VERSION = "panel_factory_process_v1"
STAGES = ("formula_audit", "critic", "evaluation")
RUNNING_STATES = {f"{stage}_running" for stage in STAGES}
TERMINAL_STATES = {
    "completed",
    "formula_rejected",
    "critic_rejected",
    "manual_review",
}
DEFAULT_ROOT = Path(config.LOG_DIR) / "panel_factory_jobs"
PROJECT_DIR = Path(__file__).resolve().parent
PROCESS_HEARTBEAT_INTERVAL_SECONDS = 1.0
PROCESS_TERMINATION_GRACE_SECONDS = 5.0


class JobLeaseBusy(RuntimeError):
    pass


class DuplicateBatchJob(RuntimeError):
    pass


@dataclass(frozen=True)
class StageResult:
    status: str
    report_path: Path | str | None = None
    reason: str = ""
    retryable: bool = False
    returncode: int | None = None


@dataclass(frozen=True)
class StageContext:
    stage: str
    attempt: int
    contract: dict[str, Any]
    job_dir: Path
    artifacts: dict[str, dict[str, Any]]
    heartbeat: Callable[[], None]
    lease_owner: str


StageRunner = Callable[[StageContext], StageResult]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _compact_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


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
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reference(path: Path | str, role: str) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve(strict=True)
    return {
        "role": role,
        "path": str(resolved),
        "sha256": _file_sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _write_immutable(path: Path, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(raw)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable_artifact_conflict:{path}")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _pid_exists(pid: int) -> bool:
    if int(pid) <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            int(pid),
        )
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        try:
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return int(exit_code.value) == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _recover_stale_lock(path: Path, *, stale_after_seconds: float) -> bool:
    try:
        raw = path.read_text(encoding="utf-8")
        stat = path.stat()
    except FileNotFoundError:
        return True
    try:
        metadata = json.loads(raw)
    except json.JSONDecodeError:
        first_line = raw.splitlines()[0] if raw.splitlines() else "0"
        metadata = {"pid": int(first_line) if first_line.isdigit() else 0}
    created_epoch = float(metadata.get("created_epoch") or stat.st_mtime)
    age_seconds = max(0.0, time.time() - created_epoch)
    if age_seconds < float(stale_after_seconds):
        return False
    owner_host = str(metadata.get("hostname") or socket.gethostname())
    owner_pid = int(metadata.get("pid") or 0)
    if owner_host == socket.gethostname() and _pid_exists(owner_pid):
        return False
    if owner_host != socket.gethostname() and age_seconds < max(300.0, stale_after_seconds):
        return False
    stale_dir = path.parent / "stale_locks"
    stale_dir.mkdir(parents=True, exist_ok=True)
    destination = stale_dir / f"{path.name.lstrip('.')}_{_compact_now()}_{uuid.uuid4().hex[:8]}.json"
    try:
        if path.read_text(encoding="utf-8") != raw or path.stat().st_mtime_ns != stat.st_mtime_ns:
            return False
        os.replace(path, destination)
    except FileNotFoundError:
        return True
    return True


@contextmanager
def _exclusive_lock(
    path: Path,
    timeout_seconds: float = 10.0,
    *,
    stale_after_seconds: float = 30.0,
) -> Iterator[None]:
    deadline = time.monotonic() + timeout_seconds
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    token = uuid.uuid4().hex
    metadata = {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at_utc": _utc_now(),
        "created_epoch": time.time(),
        "token": token,
    }
    while descriptor is None:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, (_canonical_bytes(metadata) + b"\n"))
        except FileExistsError:
            _recover_stale_lock(path, stale_after_seconds=stale_after_seconds)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"state_lock_timeout:{path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            current = {}
        if current.get("token") == token:
            path.unlink(missing_ok=True)


def _batch_claim_path(
    root: Path,
    *,
    batch_sha256: str,
    substrate_sha256: str,
) -> Path:
    identity = _payload_sha256(
        {"candidate_batch_sha256": batch_sha256, "substrate_manifest_sha256": substrate_sha256}
    )
    return root / "batch_claims" / f"claim_{identity}.json"


def _claim_frozen_batch(
    root: Path,
    *,
    job_id: str,
    batch_id: str,
    batch_path: Path,
    substrate_path: Path,
) -> Path:
    batch_sha256 = _file_sha256(batch_path)
    substrate_sha256 = _file_sha256(substrate_path)
    claim_path = _batch_claim_path(
        root,
        batch_sha256=batch_sha256,
        substrate_sha256=substrate_sha256,
    )
    claim = {
        "schema_version": "panel_factory_batch_claim_v1",
        "created_at_utc": _utc_now(),
        "job_id": job_id,
        "batch_id": batch_id,
        "candidate_batch_sha256": batch_sha256,
        "substrate_manifest_sha256": substrate_sha256,
        "policy": "one_job_per_exact_frozen_batch_and_substrate",
    }
    try:
        _write_immutable(claim_path, claim)
    except FileExistsError as exc:
        existing = json.loads(claim_path.read_text(encoding="utf-8"))
        raise DuplicateBatchJob(
            f"exact_frozen_batch_already_claimed:{existing.get('job_id')}:{claim_path}"
        ) from exc
    return claim_path


def _snapshot(source: Path | str, destination: Path, *, allow_missing: bool = False) -> dict[str, Any]:
    source_path = Path(source).expanduser().resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_file():
        raw = source_path.read_bytes()
    elif allow_missing:
        raw = b""
    else:
        raise FileNotFoundError(source_path)
    try:
        with destination.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        if destination.read_bytes() != raw:
            raise FileExistsError(f"input_snapshot_conflict:{destination}")
    return {
        "source_path": str(source_path),
        **_reference(destination, destination.stem),
    }


def create_job(
    candidate_batch_path: Path | str,
    substrate_manifest_path: Path | str,
    *,
    root: Path | str = DEFAULT_ROOT,
    trial_registry_path: Path | str = Path(config.LOG_DIR) / "panel_trial_registry.jsonl",
    literature_registry_path: Path | str = PROJECT_DIR / "LITERATURE_REPLICATION_REGISTRY.json",
    hypothesis_registry_path: Path | str = PROJECT_DIR / "LITERATURE_HYPOTHESIS_REGISTRY.md",
    symbols: list[str] | None = None,
    days: int | None = None,
    min_assets: int | None = None,
    rebalance_hours: int | None = None,
    evaluation_log_dir: Path | str | None = None,
    max_formula_attempts: int = 2,
    max_critic_attempts: int = 2,
    job_id: str | None = None,
) -> str:
    if max_formula_attempts < 1 or max_critic_attempts < 1:
        raise ValueError("stage_attempt_budget_must_be_positive")
    batch_source = Path(candidate_batch_path).expanduser().resolve(strict=True)
    substrate_source = Path(substrate_manifest_path).expanduser().resolve(strict=True)
    batch = json.loads(batch_source.read_text(encoding="utf-8"))
    batch_id = str(batch.get("batch_id") or "")
    candidates = batch.get("candidates")
    if not batch_id or not isinstance(candidates, list) or not candidates:
        raise ValueError("candidate_batch_invalid_or_empty")
    identifier = job_id or f"job_{_compact_now()}_{uuid.uuid4().hex[:10]}"
    if not identifier.startswith("job_"):
        raise ValueError("job_id_invalid")
    root_path = Path(root).expanduser().resolve(strict=False)
    root_path.mkdir(parents=True, exist_ok=True)
    job_dir = root_path / identifier
    job_dir.mkdir(parents=True, exist_ok=False)
    inputs_dir = job_dir / "inputs"
    snapshots = {
        "candidate_batch": _snapshot(batch_source, inputs_dir / "candidate_batch.json"),
        "trial_registry": _snapshot(
            trial_registry_path,
            inputs_dir / "panel_trial_registry.jsonl",
            allow_missing=True,
        ),
        "literature_registry": _snapshot(
            literature_registry_path,
            inputs_dir / "literature_replication_registry.json",
        ),
        "hypothesis_registry": _snapshot(
            hypothesis_registry_path,
            inputs_dir / "literature_hypothesis_registry.md",
        ),
    }
    substrate_manifest = json.loads(substrate_source.read_text(encoding="utf-8"))
    manifest_request = substrate_manifest.get("request_contract") or {}
    manifest_symbols = list(manifest_request.get("inst_ids") or [])
    manifest_cutoff = manifest_request.get("cutoff") or {}
    selected_symbols = list(symbols or manifest_symbols or getattr(config, "PANEL_INST_IDS", []))
    code_paths = [
        Path(__file__),
        PROJECT_DIR / "panel_formula_audit.py",
        PROJECT_DIR / "panel_research_critic.py",
        PROJECT_DIR / "panel_critic_contract.py",
        PROJECT_DIR / "panel_factor_research.py",
        PROJECT_DIR / "panel_candidate_registry.py",
        PROJECT_DIR / "panel_run_registry.py",
        PROJECT_DIR / "panel_substrate_cache.py",
        PROJECT_DIR / "panel_stage_policy.py",
        PROJECT_DIR / "config.py",
    ]
    try:
        batch_claim_path = _claim_frozen_batch(
            root_path,
            job_id=identifier,
            batch_id=batch_id,
            batch_path=batch_source,
            substrate_path=substrate_source,
        )
    except DuplicateBatchJob:
        if job_dir.parent == root_path and not (job_dir / "job_contract.json").exists():
            shutil.rmtree(job_dir)
        raise
    contract = {
        "schema_version": JOB_SCHEMA_VERSION,
        "job_id": identifier,
        "created_at_utc": _utc_now(),
        "batch_id": batch_id,
        "candidate_count": len(candidates),
        "input_snapshots": snapshots,
        "external_inputs": {
            "batch_claim": _reference(batch_claim_path, "exact_frozen_batch_claim"),
            "panel_substrate_manifest": _reference(substrate_source, "panel_substrate_manifest"),
            "panel_universe_registry": _reference(config.PANEL_UNIVERSE_REGISTRY, "panel_universe_registry"),
        },
        "output_sinks": {
            "trial_event_registry": {
                "role": "append_only_trial_event_registry",
                "path": str(Path(trial_registry_path).expanduser().resolve(strict=False)),
            },
            "evaluation_log_dir": {
                "role": "mutable_evaluation_artifact_directory",
                "path": str(
                    Path(evaluation_log_dir or config.LOG_DIR)
                    .expanduser()
                    .resolve(strict=False)
                ),
            },
        },
        "code_artifacts": [_reference(path, f"code:{path.name}") for path in code_paths],
        "evaluation_parameters": {
            "days": int(
                days
                if days is not None
                else manifest_request.get("days")
                or getattr(config, "PANEL_HISTORY_DAYS", config.HISTORY_DAYS)
            ),
            "symbols": selected_symbols,
            "min_assets": int(min_assets if min_assets is not None else getattr(config, "PANEL_MIN_ASSETS", 5)),
            "rebalance_hours": int(
                rebalance_hours
                if rebalance_hours is not None
                else getattr(config, "PANEL_REBALANCE_HOURS", 24)
            ),
            "factor_scope": "candidates_and_baselines",
            "evaluation_funnel": "staged_v1",
            "as_of": (
                manifest_cutoff.get("value")
                if manifest_cutoff.get("mode") == "explicit_as_of"
                else None
            ),
        },
        "retry_policy": {
            "formula_audit_max_attempts": int(max_formula_attempts),
            "critic_max_attempts": int(max_critic_attempts),
            "evaluation_max_attempts": 1,
            "evaluation_failure_requires_manual_review": True,
        },
        "policies": {
            "candidate_batch_frozen_before_execution": True,
            "critic_approval_required_before_evaluation": True,
            "holdout_feedback_to_ai": False,
            "evaluation_outcome_retry_forbidden": True,
            "state_derived_from_append_only_events": True,
        },
    }
    contract["contract_sha256"] = _payload_sha256(contract)
    _write_immutable(job_dir / "job_contract.json", contract)
    append_event(job_dir, "job_registered", "formula_audit_pending")
    write_job_status(job_dir)
    refresh_factory_status(Path(root))
    return identifier


def load_contract(job_dir: Path | str) -> dict[str, Any]:
    directory = Path(job_dir).resolve(strict=True)
    contract = json.loads((directory / "job_contract.json").read_text(encoding="utf-8"))
    if contract.get("schema_version") != JOB_SCHEMA_VERSION:
        raise ValueError("job_contract_schema_invalid")
    declared_hash = contract.get("contract_sha256")
    unsigned = dict(contract)
    unsigned.pop("contract_sha256", None)
    if _payload_sha256(unsigned) != declared_hash:
        raise ValueError("job_contract_sha256_mismatch")
    if contract.get("job_id") != directory.name:
        raise ValueError("job_contract_directory_mismatch")
    return contract


def validate_job_inputs(contract: dict[str, Any]) -> list[str]:
    failures = []
    references = [
        *contract.get("input_snapshots", {}).values(),
        *contract.get("external_inputs", {}).values(),
        *contract.get("code_artifacts", []),
    ]
    for reference in references:
        path = Path(str(reference.get("path") or ""))
        role = str(reference.get("role") or path.name)
        if not path.is_file():
            failures.append(f"input_missing:{role}")
        elif _file_sha256(path) != reference.get("sha256"):
            failures.append(f"input_hash_changed:{role}")
    return failures


def append_event(
    job_dir: Path | str,
    event_type: str,
    state: str,
    *,
    stage: str | None = None,
    attempt: int | None = None,
    details: dict[str, Any] | None = None,
    artifact: dict[str, Any] | None = None,
) -> Path:
    directory = Path(job_dir).resolve(strict=True)
    contract = load_contract(directory)
    events_dir = directory / "events"
    with _exclusive_lock(directory / ".state.lock"):
        existing = sorted(events_dir.glob("*.json")) if events_dir.is_dir() else []
        sequence = len(existing) + 1
        event = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": f"event_{_compact_now()}_{uuid.uuid4().hex[:8]}",
            "sequence": sequence,
            "created_at_utc": _utc_now(),
            "job_id": contract["job_id"],
            "event_type": str(event_type),
            "state": str(state),
            "stage": stage,
            "attempt": attempt,
            "details": dict(details or {}),
            "artifact": artifact,
        }
        event["event_sha256"] = _payload_sha256(event)
        path = events_dir / f"{sequence:06d}_{event['event_id']}.json"
        _write_immutable(path, event)
    return path


def read_events(job_dir: Path | str) -> list[dict[str, Any]]:
    directory = Path(job_dir).resolve(strict=True)
    contract = load_contract(directory)
    events = []
    for expected_sequence, path in enumerate(sorted((directory / "events").glob("*.json")), start=1):
        event = json.loads(path.read_text(encoding="utf-8"))
        declared_hash = event.get("event_sha256")
        unsigned = dict(event)
        unsigned.pop("event_sha256", None)
        if event.get("schema_version") != EVENT_SCHEMA_VERSION:
            raise ValueError(f"job_event_schema_invalid:{path}")
        if event.get("job_id") != contract["job_id"] or event.get("sequence") != expected_sequence:
            raise ValueError(f"job_event_sequence_invalid:{path}")
        if _payload_sha256(unsigned) != declared_hash:
            raise ValueError(f"job_event_sha256_mismatch:{path}")
        events.append(event)
    if not events:
        raise ValueError("job_has_no_events")
    return events


def job_status(job_dir: Path | str) -> dict[str, Any]:
    directory = Path(job_dir).resolve(strict=True)
    contract = load_contract(directory)
    events = read_events(directory)
    latest = events[-1]
    attempts = {
        stage: sum(1 for row in events if row.get("event_type") == "stage_started" and row.get("stage") == stage)
        for stage in STAGES
    }
    artifacts = {
        str(row["stage"]): row["artifact"]
        for row in events
        if row.get("artifact") and row.get("stage") in STAGES
    }
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "job_id": contract["job_id"],
        "batch_id": contract["batch_id"],
        "state": latest["state"],
        "terminal": latest["state"] in TERMINAL_STATES,
        "latest_event_type": latest["event_type"],
        "latest_event_at_utc": latest["created_at_utc"],
        "attempts": attempts,
        "artifacts": artifacts,
        "event_count": len(events),
        "contract_sha256": contract["contract_sha256"],
    }


def write_job_status(job_dir: Path | str) -> dict[str, Any]:
    directory = Path(job_dir).resolve(strict=True)
    status = job_status(directory)
    _atomic_write(
        directory / "status.json",
        json.dumps(status, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
    )
    lines = [
        f"# Panel Factory Job {status['job_id']}",
        "",
        f"- Batch: `{status['batch_id']}`",
        f"- State: `{status['state']}`",
        f"- Terminal: `{str(status['terminal']).lower()}`",
        f"- Events: `{status['event_count']}`",
        f"- Attempts: `{json.dumps(status['attempts'], sort_keys=True)}`",
        "",
    ]
    _atomic_write(directory / "STATUS.md", "\n".join(lines))
    return status


def refresh_factory_status(root: Path | str = DEFAULT_ROOT) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve(strict=False)
    root_path.mkdir(parents=True, exist_ok=True)
    jobs = []
    for contract_path in sorted(root_path.glob("job_*/job_contract.json")):
        try:
            jobs.append(job_status(contract_path.parent))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            jobs.append({"job_id": contract_path.parent.name, "state": "evidence_invalid", "error": str(exc)})
    counts: dict[str, int] = {}
    for row in jobs:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    payload = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "updated_at_utc": _utc_now(),
        "job_count": len(jobs),
        "state_counts": counts,
        "jobs": jobs,
    }
    _atomic_write(root_path / "factory_status.json", json.dumps(payload, sort_keys=True, indent=2) + "\n")
    lines = ["# Panel Factory Status", "", f"- Jobs: `{len(jobs)}`", f"- States: `{json.dumps(counts, sort_keys=True)}`", ""]
    for row in jobs:
        lines.append(f"- `{row['job_id']}`: `{row['state']}`")
    lines.append("")
    _atomic_write(root_path / "FACTORY_STATUS.md", "\n".join(lines))
    return payload


def _acquire_lease(job_dir: Path, owner: str, ttl_seconds: float) -> dict[str, Any] | None:
    lease_path = job_dir / "lease.json"
    stale = None
    with _exclusive_lock(job_dir / ".state.lock"):
        if lease_path.is_file():
            current = json.loads(lease_path.read_text(encoding="utf-8"))
            if float(current.get("expires_epoch") or 0.0) > time.time():
                raise JobLeaseBusy(f"job_lease_busy:{current.get('owner')}")
            stale = current
            history = job_dir / "lease_history"
            history.mkdir(parents=True, exist_ok=True)
            shutil.move(str(lease_path), str(history / f"stale_{_compact_now()}.json"))
        lease = {
            "owner": owner,
            "acquired_at_utc": _utc_now(),
            "heartbeat_at_utc": _utc_now(),
            "expires_epoch": time.time() + ttl_seconds,
            "ttl_seconds": ttl_seconds,
        }
        _atomic_write(lease_path, json.dumps(lease, sort_keys=True, indent=2) + "\n")
    return stale


def _heartbeat(job_dir: Path, owner: str, ttl_seconds: float) -> None:
    with _exclusive_lock(job_dir / ".state.lock"):
        lease_path = job_dir / "lease.json"
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
        if lease.get("owner") != owner:
            raise JobLeaseBusy("job_lease_owner_changed")
        lease["heartbeat_at_utc"] = _utc_now()
        lease["expires_epoch"] = time.time() + ttl_seconds
        _atomic_write(lease_path, json.dumps(lease, sort_keys=True, indent=2) + "\n")


def _release_lease(job_dir: Path, owner: str) -> None:
    with _exclusive_lock(job_dir / ".state.lock"):
        lease_path = job_dir / "lease.json"
        if not lease_path.is_file():
            return
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
        if lease.get("owner") == owner:
            lease_path.unlink()


def _process_group_exists(process_group_id: int) -> bool:
    if os.name == "nt":
        return _pid_exists(process_group_id)
    proc_root = Path("/proc")
    if proc_root.is_dir():
        for stat_path in proc_root.glob("[0-9]*/stat"):
            try:
                raw = stat_path.read_text(encoding="ascii")
                fields = raw[raw.rfind(")") + 2 :].split()
                state = fields[0]
                process_group = int(fields[2])
            except (OSError, ValueError, IndexError):
                continue
            if process_group == int(process_group_id) and state != "Z":
                return True
        return False
    try:
        os.killpg(int(process_group_id), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_process_group_by_id(
    process_id: int,
    process_group_id: int,
    *,
    grace_seconds: float = PROCESS_TERMINATION_GRACE_SECONDS,
) -> dict[str, Any]:
    process_id = int(process_id)
    process_group_id = int(process_group_id)
    if process_id <= 0 or process_group_id <= 0:
        return {"success": False, "reason": "invalid_process_identity"}
    if not _process_group_exists(process_group_id):
        return {"success": True, "reason": "already_exited", "forced": False}
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/PID", str(process_id), "/T", "/F"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        deadline = time.monotonic() + float(grace_seconds)
        while _pid_exists(process_id) and time.monotonic() < deadline:
            time.sleep(0.05)
        return {
            "success": not _pid_exists(process_id),
            "reason": "taskkill_tree",
            "forced": True,
            "taskkill_returncode": int(completed.returncode),
        }
    if process_group_id == os.getpgrp():
        return {"success": False, "reason": "refused_to_kill_orchestrator_process_group"}
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return {"success": True, "reason": "already_exited", "forced": False}
    deadline = time.monotonic() + float(grace_seconds)
    while _process_group_exists(process_group_id) and time.monotonic() < deadline:
        time.sleep(0.05)
    forced = _process_group_exists(process_group_id)
    if forced:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            forced = False
        deadline = time.monotonic() + float(grace_seconds)
        while _process_group_exists(process_group_id) and time.monotonic() < deadline:
            time.sleep(0.05)
    return {
        "success": not _process_group_exists(process_group_id),
        "reason": "posix_process_group_signal",
        "forced": forced,
    }


def _terminate_live_process_group(
    process: subprocess.Popen[Any],
    *,
    grace_seconds: float = PROCESS_TERMINATION_GRACE_SECONDS,
) -> dict[str, Any]:
    if process.poll() is not None:
        return {"success": True, "reason": "already_exited", "forced": False}
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        try:
            process.wait(timeout=float(grace_seconds))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=float(grace_seconds))
        return {
            "success": process.poll() is not None,
            "reason": "taskkill_live_tree",
            "forced": True,
            "taskkill_returncode": int(completed.returncode),
        }
    process_group_id = int(process.pid)
    if process_group_id == os.getpgrp():
        return {"success": False, "reason": "refused_to_kill_orchestrator_process_group"}
    forced = False
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        process.wait(timeout=float(grace_seconds))
        return {"success": True, "reason": "already_exited", "forced": False}
    try:
        process.wait(timeout=float(grace_seconds))
    except subprocess.TimeoutExpired:
        forced = True
        os.killpg(process_group_id, signal.SIGKILL)
        process.wait(timeout=float(grace_seconds))
    if _process_group_exists(process_group_id):
        forced = True
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + float(grace_seconds)
    while _process_group_exists(process_group_id) and time.monotonic() < deadline:
        time.sleep(0.05)
    return {
        "success": process.poll() is not None and not _process_group_exists(process_group_id),
        "reason": "posix_live_process_group_signal",
        "forced": forced,
    }


def _register_active_process(
    context: StageContext,
    process: subprocess.Popen[Any],
    command: list[str],
) -> dict[str, Any]:
    record = {
        "schema_version": PROCESS_SCHEMA_VERSION,
        "process_token": uuid.uuid4().hex,
        "job_id": context.contract["job_id"],
        "batch_id": context.contract["batch_id"],
        "stage": context.stage,
        "attempt": int(context.attempt),
        "lease_owner": context.lease_owner,
        "pid": int(process.pid),
        "process_group_id": int(process.pid),
        "isolated_process_group": True,
        "started_at_utc": _utc_now(),
        "command_sha256": _payload_sha256(command),
    }
    with _exclusive_lock(context.job_dir / ".state.lock"):
        active_path = context.job_dir / "active_process.json"
        if active_path.is_file():
            active = json.loads(active_path.read_text(encoding="utf-8"))
            raise RuntimeError(
                f"active_process_conflict:{active.get('stage')}:{active.get('attempt')}:{active.get('pid')}"
            )
        process_dir = context.job_dir / "processes"
        spawn_path = process_dir / f"{context.stage}_attempt_{context.attempt}_spawn.json"
        _write_immutable(spawn_path, record)
        _atomic_write(active_path, json.dumps(record, sort_keys=True, indent=2) + "\n")
    return record


def _finalize_active_process(
    context: StageContext,
    record: dict[str, Any],
    *,
    outcome: str,
    returncode: int | None,
    termination: dict[str, Any] | None = None,
) -> None:
    final = {
        **record,
        "finished_at_utc": _utc_now(),
        "outcome": outcome,
        "returncode": returncode,
        "termination": termination,
    }
    with _exclusive_lock(context.job_dir / ".state.lock"):
        final_path = (
            context.job_dir
            / "processes"
            / f"{context.stage}_attempt_{context.attempt}_final.json"
        )
        _write_immutable(final_path, final)
        active_path = context.job_dir / "active_process.json"
        if active_path.is_file():
            active = json.loads(active_path.read_text(encoding="utf-8"))
            if active.get("process_token") == record.get("process_token"):
                active_path.unlink()


def _recover_active_process(
    job_dir: Path,
    status: dict[str, Any],
    stale_lease: dict[str, Any] | None,
) -> dict[str, Any]:
    if status["state"] not in RUNNING_STATES:
        return {"success": True, "action": "not_running"}
    active_path = job_dir / "active_process.json"
    if not active_path.is_file():
        return {"success": True, "action": "no_recorded_process"}
    record = json.loads(active_path.read_text(encoding="utf-8"))
    stage = status["state"].removesuffix("_running")
    expected_attempt = int(status["attempts"][stage])
    validation_failures = []
    if record.get("schema_version") != PROCESS_SCHEMA_VERSION:
        validation_failures.append("process_schema_invalid")
    if record.get("job_id") != status["job_id"]:
        validation_failures.append("process_job_mismatch")
    if record.get("stage") != stage or int(record.get("attempt") or 0) != expected_attempt:
        validation_failures.append("process_stage_attempt_mismatch")
    if not bool(record.get("isolated_process_group")):
        validation_failures.append("process_group_not_isolated")
    if stale_lease and record.get("lease_owner") != stale_lease.get("owner"):
        validation_failures.append("process_lease_owner_mismatch")
    if validation_failures:
        return {
            "success": False,
            "action": "process_record_validation_failed",
            "failures": validation_failures,
            "record": record,
        }
    termination = _terminate_process_group_by_id(
        int(record["pid"]),
        int(record["process_group_id"]),
    )
    if not termination["success"]:
        return {
            "success": False,
            "action": "process_group_termination_failed",
            "termination": termination,
            "record": record,
        }
    with _exclusive_lock(job_dir / ".state.lock"):
        recovery_path = (
            job_dir
            / "processes"
            / f"{stage}_attempt_{expected_attempt}_recovery_{_compact_now()}.json"
        )
        _write_immutable(
            recovery_path,
            {
                **record,
                "recovered_at_utc": _utc_now(),
                "termination": termination,
            },
        )
        if active_path.is_file():
            current = json.loads(active_path.read_text(encoding="utf-8"))
            if current.get("process_token") == record.get("process_token"):
                active_path.unlink()
    return {
        "success": True,
        "action": "recorded_process_group_terminated",
        "termination": termination,
        "record": record,
    }


def _artifact_reference(path: Path | str, role: str) -> dict[str, Any]:
    return _reference(path, role)


def _recover_running_state(job_dir: Path, status: dict[str, Any], stale_lease: dict[str, Any] | None) -> dict[str, Any]:
    if status["state"] not in RUNNING_STATES:
        return status
    stage = status["state"].removesuffix("_running")
    details = {"reason": "abandoned_running_stage", "stale_lease": stale_lease}
    if stage == "evaluation":
        append_event(
            job_dir,
            "evaluation_abandoned_manual_review",
            "manual_review",
            stage=stage,
            attempt=status["attempts"][stage],
            details=details,
        )
    else:
        append_event(
            job_dir,
            "stage_abandoned_recoverable",
            f"{stage}_pending",
            stage=stage,
            attempt=status["attempts"][stage],
            details=details,
        )
    return write_job_status(job_dir)


def _stage_budget(contract: dict[str, Any], stage: str) -> int:
    key = {
        "formula_audit": "formula_audit_max_attempts",
        "critic": "critic_max_attempts",
        "evaluation": "evaluation_max_attempts",
    }[stage]
    return int(contract["retry_policy"][key])


def _validate_stage_artifact(
    stage: str,
    result: StageResult,
    contract: dict[str, Any],
    status: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if result.report_path is None:
        raise ValueError(f"{stage}_report_missing")
    report_path = Path(result.report_path).resolve(strict=True)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    batch_id = contract["batch_id"]
    if stage == "formula_audit":
        if report.get("schema_version") != panel_formula_audit.AUDIT_SCHEMA_VERSION:
            raise ValueError("formula_audit_schema_invalid")
        if str(report.get("candidate_batch_id") or "") != batch_id:
            raise ValueError("formula_audit_batch_mismatch")
        passed = bool(report.get("passed"))
    elif stage == "critic":
        batch_path = contract["input_snapshots"]["candidate_batch"]["path"]
        passed, failures = panel_critic_contract.validate_critic_approval(report, batch_path)
        if result.status == "passed" and not passed:
            raise ValueError("critic_approval_contract_invalid:" + ",".join(failures))
    else:
        if str(report.get("candidate_batch_id") or "") != batch_id:
            raise ValueError("evaluation_batch_mismatch")
        passed = result.status == "passed"
    if result.status == "passed" and not passed:
        raise ValueError(f"{stage}_reported_pass_but_artifact_failed")
    return report, _artifact_reference(report_path, f"{stage}_report")


def run_job(
    job_id: str,
    *,
    root: Path | str = DEFAULT_ROOT,
    runners: dict[str, StageRunner] | None = None,
    lease_ttl_seconds: float = 120.0,
    owner: str | None = None,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve(strict=False)
    job_dir = (root_path / job_id).resolve(strict=True)
    contract = load_contract(job_dir)
    selected_runners = runners or default_runners()
    missing_runners = sorted(set(STAGES) - set(selected_runners))
    if missing_runners:
        raise ValueError(f"stage_runners_missing:{missing_runners}")
    lease_owner = owner or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    stale_lease = _acquire_lease(job_dir, lease_owner, lease_ttl_seconds)
    try:
        status = job_status(job_dir)
        process_recovery = _recover_active_process(job_dir, status, stale_lease)
        if not process_recovery["success"]:
            append_event(
                job_dir,
                "stale_process_recovery_failed",
                "manual_review",
                details=process_recovery,
            )
            status = write_job_status(job_dir)
        else:
            if process_recovery["action"] == "recorded_process_group_terminated":
                append_event(
                    job_dir,
                    "stale_process_group_terminated",
                    status["state"],
                    stage=status["state"].removesuffix("_running"),
                    details=process_recovery,
                )
                status = job_status(job_dir)
            status = _recover_running_state(job_dir, status, stale_lease)
        while not status["terminal"]:
            input_failures = validate_job_inputs(contract)
            if input_failures:
                append_event(
                    job_dir,
                    "immutable_input_validation_failed",
                    "manual_review",
                    details={"failures": input_failures},
                )
                status = write_job_status(job_dir)
                break
            state = status["state"]
            if state.endswith("_pending"):
                stage = state.removesuffix("_pending")
            else:
                raise ValueError(f"unexpected_nonterminal_job_state:{state}")
            attempts = status["attempts"][stage]
            budget = _stage_budget(contract, stage)
            if attempts >= budget:
                append_event(
                    job_dir,
                    "stage_attempt_budget_exhausted",
                    "manual_review",
                    stage=stage,
                    attempt=attempts,
                )
                status = write_job_status(job_dir)
                break
            if stage == "evaluation" and attempts > 0:
                append_event(
                    job_dir,
                    "evaluation_retry_forbidden",
                    "manual_review",
                    stage=stage,
                    attempt=attempts,
                )
                status = write_job_status(job_dir)
                break
            attempt = attempts + 1
            _heartbeat(job_dir, lease_owner, lease_ttl_seconds)
            append_event(job_dir, "stage_started", f"{stage}_running", stage=stage, attempt=attempt)
            status = write_job_status(job_dir)
            context = StageContext(
                stage=stage,
                attempt=attempt,
                contract=contract,
                job_dir=job_dir,
                artifacts=status["artifacts"],
                heartbeat=lambda: _heartbeat(job_dir, lease_owner, lease_ttl_seconds),
                lease_owner=lease_owner,
            )
            try:
                result = selected_runners[stage](context)
                _heartbeat(job_dir, lease_owner, lease_ttl_seconds)
                _, artifact = _validate_stage_artifact(stage, result, contract, status)
                trial_event_commit = None
                if stage == "evaluation" and result.status == "passed":
                    trial_event_commit = _commit_evaluation_trial_events(context)
            except Exception as exc:
                retryable = stage != "evaluation" and attempt < budget
                append_event(
                    job_dir,
                    "stage_execution_failed",
                    f"{stage}_pending" if retryable else "manual_review",
                    stage=stage,
                    attempt=attempt,
                    details={"error_type": type(exc).__name__, "message": str(exc)[:2000], "retryable": retryable},
                )
                status = write_job_status(job_dir)
                continue
            if result.status == "passed":
                next_state = {
                    "formula_audit": "critic_pending",
                    "critic": "evaluation_pending",
                    "evaluation": "completed",
                }[stage]
                append_event(
                    job_dir,
                    "stage_passed",
                    next_state,
                    stage=stage,
                    attempt=attempt,
                    details={
                        "returncode": result.returncode,
                        "reason": result.reason,
                        "trial_event_commit": trial_event_commit,
                    },
                    artifact=artifact,
                )
            elif result.status == "rejected":
                terminal = "formula_rejected" if stage == "formula_audit" else "critic_rejected"
                if stage == "evaluation":
                    terminal = "manual_review"
                append_event(
                    job_dir,
                    "stage_rejected",
                    terminal,
                    stage=stage,
                    attempt=attempt,
                    details={"returncode": result.returncode, "reason": result.reason},
                    artifact=artifact,
                )
            elif result.status == "failed":
                retryable = bool(result.retryable) and stage != "evaluation" and attempt < budget
                append_event(
                    job_dir,
                    "stage_failed",
                    f"{stage}_pending" if retryable else "manual_review",
                    stage=stage,
                    attempt=attempt,
                    details={"returncode": result.returncode, "reason": result.reason, "retryable": retryable},
                    artifact=artifact,
                )
            else:
                raise ValueError(f"stage_result_status_invalid:{result.status}")
            status = write_job_status(job_dir)
        refresh_factory_status(root_path)
        return status
    finally:
        _release_lease(job_dir, lease_owner)


def _run_process(command: list[str], context: StageContext) -> tuple[int, str, str]:
    log_dir = context.job_dir / "stage_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{context.stage}_attempt_{context.attempt}_stdout.txt"
    stderr_path = log_dir / f"{context.stage}_attempt_{context.attempt}_stderr.txt"
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        popen_options: dict[str, Any] = {
            "cwd": PROJECT_DIR,
            "stdout": stdout_handle,
            "stderr": stderr_handle,
        }
        if os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True
        process = subprocess.Popen(command, **popen_options)
        try:
            record = _register_active_process(context, process, command)
        except BaseException:
            _terminate_live_process_group(process)
            raise
        try:
            while process.poll() is None:
                time.sleep(PROCESS_HEARTBEAT_INTERVAL_SECONDS)
                context.heartbeat()
            returncode = int(process.returncode)
            _finalize_active_process(
                context,
                record,
                outcome="exited",
                returncode=returncode,
            )
        except BaseException:
            termination = _terminate_live_process_group(process)
            returncode = int(process.returncode) if process.returncode is not None else None
            _finalize_active_process(
                context,
                record,
                outcome="terminated_on_orchestrator_exception",
                returncode=returncode,
                termination=termination,
            )
            raise
    return (
        returncode,
        stdout_path.read_text(encoding="utf-8", errors="replace"),
        stderr_path.read_text(encoding="utf-8", errors="replace"),
    )


def _wrote_path(stdout: str) -> Path | None:
    for line in stdout.splitlines():
        if line.startswith("WROTE "):
            path = Path(line.removeprefix("WROTE ").strip())
            return path if path.is_absolute() else (PROJECT_DIR / path)
    return None


def _discover_report_path(
    stdout: str,
    report_dir: Path,
    *,
    started_epoch: float,
    timeout_seconds: float = 3.0,
    glob_pattern: str = "*.json",
) -> Path | None:
    declared = _wrote_path(stdout)
    deadline = time.monotonic() + timeout_seconds
    while True:
        if declared is not None and declared.is_file():
            return declared
        candidates = [
            path
            for path in report_dir.glob(glob_pattern)
            if not path.name.endswith("_latest.json")
            and path.stat().st_mtime >= started_epoch - 1.0
        ] if report_dir.is_dir() else []
        if candidates:
            return max(candidates, key=lambda path: path.stat().st_mtime_ns)
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


def _attempt_report_dir(context: StageContext) -> Path:
    return (
        context.job_dir
        / "stage_reports"
        / context.stage
        / f"attempt_{int(context.attempt):04d}"
    )


def _formula_runner(context: StageContext) -> StageResult:
    inputs = context.contract["input_snapshots"]
    report_dir = _attempt_report_dir(context)
    command = [
        sys.executable,
        "-u",
        str(PROJECT_DIR / "panel_formula_audit.py"),
        "--substrate-manifest",
        context.contract["external_inputs"]["panel_substrate_manifest"]["path"],
        "--candidate-batch",
        inputs["candidate_batch"]["path"],
        "--hypothesis-registry",
        inputs["hypothesis_registry"]["path"],
        "--report-dir",
        str(report_dir),
    ]
    started_epoch = time.time()
    returncode, stdout, stderr = _run_process(command, context)
    report_path = _discover_report_path(stdout, report_dir, started_epoch=started_epoch)
    if report_path and report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return StageResult(
            "passed" if bool(report.get("passed")) else "rejected",
            report_path,
            reason="differential_formula_audit",
            returncode=returncode,
        )
    return StageResult("failed", reason=(stderr or stdout)[-2000:], retryable=True, returncode=returncode)


def _critic_runner(context: StageContext) -> StageResult:
    inputs = context.contract["input_snapshots"]
    formula_artifact = context.artifacts.get("formula_audit") or {}
    report_dir = _attempt_report_dir(context)
    command = [
        sys.executable,
        "-u",
        str(PROJECT_DIR / "panel_research_critic.py"),
        "--candidate-batch",
        inputs["candidate_batch"]["path"],
        "--formula-audit-report",
        str(formula_artifact.get("path") or ""),
        "--trial-registry",
        inputs["trial_registry"]["path"],
        "--literature-registry",
        inputs["literature_registry"]["path"],
        "--hypothesis-registry",
        inputs["hypothesis_registry"]["path"],
        "--report-dir",
        str(report_dir),
    ]
    started_epoch = time.time()
    returncode, stdout, stderr = _run_process(command, context)
    report_path = _discover_report_path(stdout, report_dir, started_epoch=started_epoch)
    if report_path and report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return StageResult(
            "passed" if bool(report.get("approved")) else "rejected",
            report_path,
            reason=str(report.get("decision") or "critic_decision"),
            returncode=returncode,
        )
    return StageResult("failed", reason=(stderr or stdout)[-2000:], retryable=True, returncode=returncode)


def _evaluation_runner(context: StageContext) -> StageResult:
    inputs = context.contract["input_snapshots"]
    parameters = context.contract["evaluation_parameters"]
    critic_artifact = context.artifacts.get("critic") or {}
    trial_event_path = _attempt_report_dir(context) / "panel_trial_events.jsonl"
    command = [
        sys.executable,
        "-u",
        str(PROJECT_DIR / "panel_factor_research.py"),
        "--days",
        str(parameters["days"]),
        "--symbols",
        ",".join(parameters["symbols"]),
        "--min-assets",
        str(parameters["min_assets"]),
        "--rebalance-hours",
        str(parameters["rebalance_hours"]),
        "--candidate-batch",
        inputs["candidate_batch"]["path"],
        "--critic-report",
        str(critic_artifact.get("path") or ""),
        "--trial-registry",
        inputs["trial_registry"]["path"],
        "--trial-event-registry",
        str(trial_event_path),
        "--run-log-dir",
        context.contract["output_sinks"]["evaluation_log_dir"]["path"],
        "--hypothesis-registry",
        inputs["hypothesis_registry"]["path"],
        "--substrate-manifest",
        context.contract["external_inputs"]["panel_substrate_manifest"]["path"],
        "--factor-scope",
        parameters["factor_scope"],
        "--evaluation-funnel",
        parameters["evaluation_funnel"],
    ]
    if parameters.get("as_of"):
        command.extend(["--as-of", str(parameters["as_of"])])
    started_epoch = time.time()
    returncode, stdout, stderr = _run_process(command, context)
    report_path = _wrote_path(stdout)
    if returncode == 0 and report_path and report_path.is_file():
        return StageResult("passed", report_path, reason="historical_panel_audit_complete", returncode=returncode)
    if report_path and report_path.is_file():
        return StageResult("failed", report_path, reason=(stderr or stdout)[-2000:], returncode=returncode)
    raise RuntimeError(f"evaluation_failed_without_report:{returncode}:{(stderr or stdout)[-2000:]}")


def _trial_event_identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("batch_id") or ""),
        str(row.get("candidate_id") or ""),
        str(row.get("event") or ""),
    )


def _commit_evaluation_trial_events(context: StageContext) -> dict[str, Any]:
    source_path = _attempt_report_dir(context) / "panel_trial_events.jsonl"
    if not source_path.is_file():
        raise ValueError("evaluation_trial_events_missing")
    source_rows = []
    for line_number, line in enumerate(source_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"evaluation_trial_event_invalid_json:{line_number}") from exc
        if not isinstance(row, dict) or row.get("event") != "evaluated":
            raise ValueError(f"evaluation_trial_event_invalid:{line_number}")
        if str(row.get("batch_id") or "") != str(context.contract["batch_id"]):
            raise ValueError(f"evaluation_trial_event_batch_mismatch:{line_number}")
        source_rows.append(row)
    expected_candidates = int(context.contract["candidate_count"])
    if len(source_rows) != expected_candidates:
        raise ValueError(
            f"evaluation_trial_event_count_mismatch:{len(source_rows)}!={expected_candidates}"
        )

    destination = Path(
        context.contract["output_sinks"]["trial_event_registry"]["path"]
    ).resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    appended_rows = 0
    with _exclusive_lock(destination.with_name(destination.name + ".lock")):
        before_bytes = destination.read_bytes() if destination.is_file() else b""
        before_sha256 = hashlib.sha256(before_bytes).hexdigest()
        existing_text = destination.read_text(encoding="utf-8") if destination.is_file() else ""
        existing_rows = [json.loads(line) for line in existing_text.splitlines() if line.strip()]
        existing_by_identity = {_trial_event_identity(row): row for row in existing_rows}
        additions = []
        for row in source_rows:
            identity = _trial_event_identity(row)
            existing = existing_by_identity.get(identity)
            if existing is not None:
                comparable_fields = (
                    "status",
                    "candidate_signature",
                    "signal_signature",
                    "variant_count",
                )
                if any(existing.get(field) != row.get(field) for field in comparable_fields):
                    raise ValueError(
                        "evaluation_trial_event_identity_conflict:" + ":".join(identity)
                    )
                continue
            additions.append(row)
            existing_by_identity[identity] = row
        if additions:
            merged_lines = [line for line in existing_text.splitlines() if line.strip()]
            merged_lines.extend(json.dumps(row, ensure_ascii=False) for row in additions)
            _atomic_write(destination, "\n".join(merged_lines) + "\n")
            appended_rows = len(additions)
        after_bytes = destination.read_bytes() if destination.is_file() else b""

    commit = {
        "schema_version": "panel_factory_trial_event_commit_v1",
        "job_id": context.contract["job_id"],
        "batch_id": context.contract["batch_id"],
        "source_path": str(source_path.resolve()),
        "source_sha256": _file_sha256(source_path),
        "destination_path": str(destination),
        "destination_sha256_before": before_sha256,
        "destination_sha256_after": hashlib.sha256(after_bytes).hexdigest(),
        "source_row_count": len(source_rows),
        "appended_row_count": appended_rows,
        "idempotent_row_count": len(source_rows) - appended_rows,
        "committed_at_utc": _utc_now(),
    }
    commit_path = context.job_dir / "outputs" / "trial_event_commit.json"
    if commit_path.is_file():
        existing_commit = json.loads(commit_path.read_text(encoding="utf-8"))
        if existing_commit.get("destination_sha256_after") != commit["destination_sha256_after"]:
            raise ValueError("evaluation_trial_event_commit_conflict")
        return existing_commit
    _write_immutable(commit_path, commit)
    return commit


def default_runners() -> dict[str, StageRunner]:
    return {
        "formula_audit": _formula_runner,
        "critic": _critic_runner,
        "evaluation": _evaluation_runner,
    }


def _job_exit_code(status: dict[str, Any]) -> int:
    if status["state"] == "completed":
        return 0
    if status["state"] in {"formula_rejected", "critic_rejected"}:
        return 2
    return 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "create-run"):
        create_parser = subparsers.add_parser(name)
        create_parser.add_argument("--candidate-batch", required=True)
        create_parser.add_argument("--substrate-manifest", required=True)
        create_parser.add_argument("--trial-registry", default=str(Path(config.LOG_DIR) / "panel_trial_registry.jsonl"))
        create_parser.add_argument("--literature-registry", default=str(PROJECT_DIR / "LITERATURE_REPLICATION_REGISTRY.json"))
        create_parser.add_argument("--hypothesis-registry", default=str(PROJECT_DIR / "LITERATURE_HYPOTHESIS_REGISTRY.md"))
        create_parser.add_argument("--days", type=int)
        create_parser.add_argument("--symbols")
        create_parser.add_argument("--min-assets", type=int)
        create_parser.add_argument("--rebalance-hours", type=int)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--job-id", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--job-id")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.command in {"create", "create-run"}:
        identifier = create_job(
            args.candidate_batch,
            args.substrate_manifest,
            root=root,
            trial_registry_path=args.trial_registry,
            literature_registry_path=args.literature_registry,
            hypothesis_registry_path=args.hypothesis_registry,
            symbols=[item.strip() for item in args.symbols.split(",") if item.strip()] if args.symbols else None,
            days=args.days,
            min_assets=args.min_assets,
            rebalance_hours=args.rebalance_hours,
        )
        print(f"CREATED {identifier}")
        if args.command == "create":
            return 0
        status = run_job(identifier, root=root)
        print(f"STATE {status['state']}")
        return _job_exit_code(status)
    if args.command == "run":
        status = run_job(args.job_id, root=root)
        print(f"STATE {status['state']}")
        return _job_exit_code(status)
    if args.job_id:
        status = write_job_status(root / args.job_id)
    else:
        status = refresh_factory_status(root)
    print(json.dumps(status, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
