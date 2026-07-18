"""Immutable run contracts with a rebuildable SQLite query index.

JSON artifacts are the evidence authority. SQLite is only a projection that
can be deleted and rebuilt from the per-run contract, event, and artifact
metadata files.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import sqlite3
import sys
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


CONTRACT_SCHEMA_VERSION = "panel_factory_run_contract_v1"
EVENT_SCHEMA_VERSION = "panel_factory_run_event_v1"
ARTIFACT_SCHEMA_VERSION = "panel_factory_run_artifact_v1"
TERMINAL_STATUSES = {"completed", "failed"}
ALLOWED_TRANSITIONS = {
    "registered": {"running", "failed"},
    "running": {"completed", "failed", "interrupted"},
    "interrupted": {"running", "failed"},
    "completed": set(),
    "failed": set(),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _compact_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_reference(path: Path | str, role: str) -> dict[str, Any]:
    """Describe an input or code file without requiring it to exist."""

    resolved = Path(path).expanduser().resolve(strict=False)
    exists = resolved.is_file()
    return {
        "role": str(role),
        "path": str(resolved),
        "exists": exists,
        "sha256": _file_sha256(resolved) if exists else None,
        "size_bytes": resolved.stat().st_size if exists else None,
    }


def _reference_fingerprint(references: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "role": row.get("role"),
            "path": row.get("path"),
            "exists": bool(row.get("exists")),
            "sha256": row.get("sha256"),
            "size_bytes": row.get("size_bytes"),
        }
        for row in references
    ]
    return _payload_sha256(sorted(normalized, key=lambda row: (str(row["role"]), str(row["path"]))))


def build_run_contract(
    *,
    run_kind: str,
    stage: str,
    parameters: dict[str, Any],
    input_artifacts: list[dict[str, Any]] | None = None,
    code_artifacts: list[dict[str, Any]] | None = None,
    batch_id: str | None = None,
    parent_run_id: str | None = None,
    policies: dict[str, Any] | None = None,
    run_id: str | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a self-hashing, immutable execution contract."""

    if not str(run_kind).strip():
        raise ValueError("run_kind_required")
    if not str(stage).strip():
        raise ValueError("stage_required")
    input_refs = list(input_artifacts or [])
    code_refs = list(code_artifacts or [])
    missing_code = [row.get("path") for row in code_refs if not row.get("exists") or not row.get("sha256")]
    if missing_code:
        raise ValueError(f"code_artifact_missing:{missing_code}")
    contract = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "run_id": run_id or f"run_{_compact_utc_now()}_{uuid.uuid4().hex[:10]}",
        "created_at_utc": created_at_utc or _utc_now(),
        "run_kind": str(run_kind),
        "stage": str(stage),
        "batch_id": str(batch_id) if batch_id is not None else None,
        "parent_run_id": str(parent_run_id) if parent_run_id is not None else None,
        "parameters": dict(parameters),
        "input_artifacts": input_refs,
        "input_contract_fingerprint": _reference_fingerprint(input_refs),
        "code_artifacts": code_refs,
        "code_fingerprint": _reference_fingerprint(code_refs),
        "policies": dict(policies or {}),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }
    # This also rejects non-JSON values and non-finite floats before execution.
    contract["contract_sha256"] = _payload_sha256(contract)
    validate_run_contract(contract)
    return contract


def validate_run_contract(contract: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "run_id",
        "created_at_utc",
        "run_kind",
        "stage",
        "parameters",
        "input_artifacts",
        "input_contract_fingerprint",
        "code_artifacts",
        "code_fingerprint",
        "policies",
        "contract_sha256",
    }
    missing = sorted(required - set(contract))
    if missing:
        raise ValueError(f"run_contract_missing_fields:{missing}")
    if contract["schema_version"] != CONTRACT_SCHEMA_VERSION:
        raise ValueError("run_contract_schema_version_invalid")
    if not str(contract["run_id"]).startswith("run_"):
        raise ValueError("run_id_invalid")
    if not str(contract["run_kind"]).strip() or not str(contract["stage"]).strip():
        raise ValueError("run_kind_and_stage_required")
    expected = dict(contract)
    declared_hash = str(expected.pop("contract_sha256"))
    if _payload_sha256(expected) != declared_hash:
        raise ValueError("run_contract_sha256_mismatch")


def _immutable_json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write_immutable_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == raw:
            return
        raise FileExistsError(f"immutable_artifact_conflict:{path}")
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise FileExistsError(f"immutable_artifact_conflict:{path}")
    finally:
        temporary.unlink(missing_ok=True)


def _write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    _write_immutable_bytes(path, _immutable_json_bytes(payload))


@contextmanager
def _exclusive_file_lock(path: Path, timeout_seconds: float = 15.0) -> Iterator[None]:
    """Cross-platform advisory lock for one run's state transitions."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"run_lock_timeout:{path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class RunRegistry:
    """Write immutable run evidence and maintain its SQLite projection."""

    def __init__(self, artifact_root: Path | str, index_path: Path | str):
        self.artifact_root = Path(artifact_root).expanduser().resolve(strict=False)
        self.index_path = Path(index_path).expanduser().resolve(strict=False)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_index()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.index_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize_index(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    run_kind TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    batch_id TEXT,
                    parent_run_id TEXT,
                    data_fingerprint TEXT,
                    input_contract_fingerprint TEXT NOT NULL,
                    code_fingerprint TEXT NOT NULL,
                    contract_sha256 TEXT NOT NULL,
                    contract_path TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    started_at_utc TEXT,
                    completed_at_utc TEXT,
                    duration_seconds REAL,
                    failure_reason TEXT,
                    primary_report_path TEXT,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    event_type TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    status TEXT,
                    stage TEXT NOT NULL,
                    data_fingerprint TEXT,
                    failure_reason TEXT,
                    details_json TEXT NOT NULL,
                    evidence_path TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    role TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    evidence_path TEXT NOT NULL,
                    UNIQUE(run_id, role, path)
                );
                CREATE INDEX IF NOT EXISTS idx_runs_batch ON runs(batch_id);
                CREATE INDEX IF NOT EXISTS idx_runs_stage ON runs(stage);
                CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
                CREATE INDEX IF NOT EXISTS idx_runs_data_fingerprint ON runs(data_fingerprint);
                CREATE INDEX IF NOT EXISTS idx_runs_failure_reason ON runs(failure_reason);
                CREATE INDEX IF NOT EXISTS idx_events_run_created ON run_events(run_id, created_at_utc);
                CREATE INDEX IF NOT EXISTS idx_artifacts_run_role ON run_artifacts(run_id, role);
                """
            )

    def _run_dir(self, run_id: str) -> Path:
        return self.artifact_root / run_id

    def create_run(self, contract: dict[str, Any]) -> Path:
        validate_run_contract(contract)
        run_id = str(contract["run_id"])
        contract_path = self._run_dir(run_id) / "run_contract.json"
        with _exclusive_file_lock(self._run_dir(run_id) / ".run.lock"):
            _write_immutable_json(contract_path, contract)
        self._index_contract(contract, contract_path)
        code_snapshot_path = self._write_code_snapshot(contract)
        self.record_artifact(run_id, "code_snapshot_bundle", code_snapshot_path)
        return contract_path

    def _write_code_snapshot(self, contract: dict[str, Any]) -> Path:
        entries = []
        source_payloads = []
        for index, reference in enumerate(contract.get("code_artifacts") or []):
            source = Path(reference["path"]).resolve(strict=True)
            raw = source.read_bytes()
            actual_hash = hashlib.sha256(raw).hexdigest()
            if actual_hash != reference["sha256"]:
                raise ValueError(f"run_code_changed_after_contract:{source}")
            snapshot_name = f"code/{index:03d}_{source.name}"
            entries.append(
                {
                    "role": reference["role"],
                    "original_path": str(source),
                    "snapshot_path": snapshot_name,
                    "sha256": actual_hash,
                    "size_bytes": len(raw),
                }
            )
            source_payloads.append((snapshot_name, raw))
        bundle_manifest = {
            "schema_version": "panel_factory_code_snapshot_v1",
            "run_id": contract["run_id"],
            "contract_sha256": contract["contract_sha256"],
            "code_fingerprint": contract["code_fingerprint"],
            "files": entries,
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            payloads = [
                (
                    "manifest.json",
                    (json.dumps(bundle_manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8"),
                ),
                *source_payloads,
            ]
            for name, raw in payloads:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        snapshot_path = self._run_dir(contract["run_id"]) / "code_snapshot.zip"
        _write_immutable_bytes(snapshot_path, buffer.getvalue())
        return snapshot_path

    def _index_contract(self, contract: dict[str, Any], contract_path: Path) -> None:
        values = (
            contract["run_id"],
            contract["run_kind"],
            contract["stage"],
            "registered",
            contract.get("batch_id"),
            contract.get("parent_run_id"),
            contract["input_contract_fingerprint"],
            contract["code_fingerprint"],
            contract["contract_sha256"],
            str(contract_path.resolve(strict=False)),
            contract["created_at_utc"],
            contract["created_at_utc"],
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO runs (
                    run_id, run_kind, stage, status, batch_id, parent_run_id,
                    input_contract_fingerprint, code_fingerprint,
                    contract_sha256, contract_path, created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            existing = connection.execute(
                "SELECT contract_sha256, contract_path FROM runs WHERE run_id = ?",
                (contract["run_id"],),
            ).fetchone()
            if existing is None or existing["contract_sha256"] != contract["contract_sha256"]:
                raise ValueError(f"run_id_contract_conflict:{contract['run_id']}")

    def _load_contract(self, run_id: str) -> dict[str, Any]:
        path = self._run_dir(run_id) / "run_contract.json"
        if not path.is_file():
            raise FileNotFoundError(f"run_contract_not_found:{run_id}")
        contract = json.loads(path.read_text(encoding="utf-8"))
        validate_run_contract(contract)
        return contract

    def _event_paths(self, run_id: str) -> list[Path]:
        return sorted((self._run_dir(run_id) / "events").glob("*.json"))

    def _current_status_from_evidence(self, run_id: str) -> str:
        self._load_contract(run_id)
        status = "registered"
        for path in self._event_paths(run_id):
            event = json.loads(path.read_text(encoding="utf-8"))
            new_status = event.get("status")
            if not new_status:
                continue
            if new_status not in ALLOWED_TRANSITIONS.get(status, set()):
                raise ValueError(f"invalid_evidence_transition:{status}->{new_status}:{path}")
            status = new_status
        return status

    def record_event(
        self,
        run_id: str,
        *,
        event_type: str,
        status: str | None = None,
        data_fingerprint: str | None = None,
        failure_reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> Path:
        if not str(event_type).strip():
            raise ValueError("event_type_required")
        contract = self._load_contract(run_id)
        run_dir = self._run_dir(run_id)
        with _exclusive_file_lock(run_dir / ".run.lock"):
            current_status = self._current_status_from_evidence(run_id)
            if status is not None and status not in ALLOWED_TRANSITIONS.get(current_status, set()):
                raise ValueError(f"invalid_run_transition:{current_status}->{status}")
            if status == "failed" and not failure_reason:
                raise ValueError("failure_reason_required")
            event = {
                "schema_version": EVENT_SCHEMA_VERSION,
                "event_id": uuid.uuid4().hex,
                "run_id": run_id,
                "event_type": str(event_type),
                "created_at_utc": _utc_now(),
                "stage": contract["stage"],
                "from_status": current_status,
                "status": status,
                "data_fingerprint": str(data_fingerprint) if data_fingerprint is not None else None,
                "failure_reason": str(failure_reason) if failure_reason is not None else None,
                "details": dict(details or {}),
            }
            event_path = run_dir / "events" / f"{_compact_utc_now()}_{event['event_id']}.json"
            _write_immutable_json(event_path, event)
        self._index_event(event, event_path)
        return event_path

    def _index_event(self, event: dict[str, Any], event_path: Path) -> None:
        if event.get("schema_version") != EVENT_SCHEMA_VERSION:
            raise ValueError(f"run_event_schema_invalid:{event_path}")
        with self._connect() as connection:
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO run_events (
                    event_id, run_id, event_type, created_at_utc, status, stage,
                    data_fingerprint, failure_reason, details_json, evidence_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["run_id"],
                    event["event_type"],
                    event["created_at_utc"],
                    event.get("status"),
                    event["stage"],
                    event.get("data_fingerprint"),
                    event.get("failure_reason"),
                    json.dumps(event.get("details") or {}, sort_keys=True, separators=(",", ":")),
                    str(event_path.resolve(strict=False)),
                ),
            ).rowcount
            if not inserted:
                return
            current = connection.execute(
                "SELECT status, started_at_utc FROM runs WHERE run_id = ?",
                (event["run_id"],),
            ).fetchone()
            if current is None:
                raise ValueError(f"event_run_not_indexed:{event['run_id']}")
            new_status = event.get("status")
            if new_status and new_status not in ALLOWED_TRANSITIONS.get(current["status"], set()):
                raise ValueError(f"invalid_index_transition:{current['status']}->{new_status}")
            started_at = current["started_at_utc"]
            if new_status == "running" and not started_at:
                started_at = event["created_at_utc"]
            completed_at = event["created_at_utc"] if new_status in TERMINAL_STATUSES else None
            duration = None
            if completed_at and started_at:
                duration = (
                    datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                    - datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                ).total_seconds()
            connection.execute(
                """
                UPDATE runs SET
                    status = COALESCE(?, status),
                    data_fingerprint = COALESCE(?, data_fingerprint),
                    started_at_utc = COALESCE(?, started_at_utc),
                    completed_at_utc = COALESCE(?, completed_at_utc),
                    duration_seconds = COALESCE(?, duration_seconds),
                    failure_reason = COALESCE(?, failure_reason),
                    updated_at_utc = ?
                WHERE run_id = ?
                """,
                (
                    new_status,
                    event.get("data_fingerprint"),
                    started_at,
                    completed_at,
                    duration,
                    event.get("failure_reason"),
                    event["created_at_utc"],
                    event["run_id"],
                ),
            )

    def start_run(self, run_id: str, *, details: dict[str, Any] | None = None) -> Path:
        return self.record_event(run_id, event_type="run_started", status="running", details=details)

    def complete_run(self, run_id: str, *, details: dict[str, Any] | None = None) -> Path:
        return self.record_event(run_id, event_type="run_completed", status="completed", details=details)

    def interrupt_run(self, run_id: str, *, details: dict[str, Any] | None = None) -> Path:
        return self.record_event(run_id, event_type="run_interrupted", status="interrupted", details=details)

    def fail_run(self, run_id: str, failure_reason: str, *, details: dict[str, Any] | None = None) -> Path:
        return self.record_event(
            run_id,
            event_type="run_failed",
            status="failed",
            failure_reason=failure_reason,
            details=details,
        )

    def record_data_fingerprint(
        self,
        run_id: str,
        data_fingerprint: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> Path:
        return self.record_event(
            run_id,
            event_type="data_resolved",
            data_fingerprint=data_fingerprint,
            details=details,
        )

    def record_artifact(self, run_id: str, role: str, path: Path | str) -> dict[str, Any]:
        self._load_contract(run_id)
        resolved = Path(path).expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"run_artifact_not_file:{resolved}")
        artifact = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "artifact_id": uuid.uuid4().hex,
            "run_id": run_id,
            "role": str(role),
            "path": str(resolved),
            "sha256": _file_sha256(resolved),
            "size_bytes": resolved.stat().st_size,
            "created_at_utc": _utc_now(),
        }
        metadata_path = (
            self._run_dir(run_id)
            / "artifacts"
            / f"{_compact_utc_now()}_{artifact['artifact_id']}.json"
        )
        with _exclusive_file_lock(self._run_dir(run_id) / ".run.lock"):
            for existing_path in sorted((self._run_dir(run_id) / "artifacts").glob("*.json")):
                existing = json.loads(existing_path.read_text(encoding="utf-8"))
                if existing.get("role") != artifact["role"] or existing.get("path") != artifact["path"]:
                    continue
                if existing.get("sha256") != artifact["sha256"]:
                    raise FileExistsError(f"run_artifact_content_conflict:{resolved}")
                self._index_artifact(existing, existing_path, verify_file=False)
                return existing
            _write_immutable_json(metadata_path, artifact)
        self._index_artifact(artifact, metadata_path, verify_file=False)
        return artifact

    def snapshot_file(self, run_id: str, role: str, source_path: Path | str) -> dict[str, Any]:
        """Copy a mutable input into the run before it can change."""

        self._load_contract(run_id)
        source = Path(source_path).expanduser().resolve(strict=False)
        source_exists = source.is_file()
        raw = source.read_bytes() if source_exists else b""
        digest = hashlib.sha256(raw).hexdigest()
        safe_role = "".join(character if character.isalnum() or character in "-_" else "_" for character in role)
        suffix = source.suffix if source.suffix else ".bin"
        snapshot_path = self._run_dir(run_id) / "snapshots" / f"{safe_role}_{digest}{suffix}"
        with _exclusive_file_lock(self._run_dir(run_id) / ".run.lock"):
            _write_immutable_bytes(snapshot_path, raw)
        artifact = self.record_artifact(run_id, role, snapshot_path)
        return {
            **artifact,
            "snapshot_source_path": str(source),
            "snapshot_source_exists": source_exists,
        }

    def _index_artifact(self, artifact: dict[str, Any], metadata_path: Path, *, verify_file: bool) -> None:
        if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
            raise ValueError(f"run_artifact_schema_invalid:{metadata_path}")
        artifact_path = Path(artifact["path"])
        if verify_file:
            if not artifact_path.is_file() or _file_sha256(artifact_path) != artifact["sha256"]:
                raise ValueError(f"run_artifact_hash_mismatch:{artifact_path}")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO run_artifacts (
                    artifact_id, run_id, role, path, sha256, size_bytes,
                    created_at_utc, evidence_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact["artifact_id"],
                    artifact["run_id"],
                    artifact["role"],
                    artifact["path"],
                    artifact["sha256"],
                    int(artifact["size_bytes"]),
                    artifact["created_at_utc"],
                    str(metadata_path.resolve(strict=False)),
                ),
            )
            if artifact["role"] == "primary_report":
                connection.execute(
                    """
                    UPDATE runs SET
                        primary_report_path = ?,
                        updated_at_utc = CASE
                            WHEN updated_at_utc < ? THEN ?
                            ELSE updated_at_utc
                        END
                    WHERE run_id = ?
                    """,
                    (
                        artifact["path"],
                        artifact["created_at_utc"],
                        artifact["created_at_utc"],
                        artifact["run_id"],
                    ),
                )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row is not None else None

    def query_runs(
        self,
        *,
        batch_id: str | None = None,
        stage: str | None = None,
        status: str | None = None,
        data_fingerprint: str | None = None,
        failure_reason: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        filters = {
            "batch_id": batch_id,
            "stage": stage,
            "status": status,
            "data_fingerprint": data_fingerprint,
            "failure_reason": failure_reason,
        }
        clauses = []
        values: list[Any] = []
        for column, value in filters.items():
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(int(limit), 10_000)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM runs{where} ORDER BY created_at_utc DESC LIMIT ?",
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM run_events WHERE run_id = ? ORDER BY created_at_utc, event_id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM run_artifacts WHERE run_id = ? ORDER BY created_at_utc, artifact_id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def rebuild_index(self) -> dict[str, int]:
        """Replace the SQLite projection from immutable JSON evidence."""

        temporary = self.index_path.with_name(f".{self.index_path.name}.{uuid.uuid4().hex}.rebuild")
        rebuilt = RunRegistry(self.artifact_root, temporary)
        counts = {"runs": 0, "events": 0, "artifacts": 0}
        try:
            for contract_path in sorted(self.artifact_root.glob("run_*/run_contract.json")):
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                validate_run_contract(contract)
                rebuilt._index_contract(contract, contract_path)
                counts["runs"] += 1
                run_dir = contract_path.parent
                for event_path in sorted((run_dir / "events").glob("*.json")):
                    event = json.loads(event_path.read_text(encoding="utf-8"))
                    rebuilt._index_event(event, event_path)
                    counts["events"] += 1
                for metadata_path in sorted((run_dir / "artifacts").glob("*.json")):
                    artifact = json.loads(metadata_path.read_text(encoding="utf-8"))
                    rebuilt._index_artifact(artifact, metadata_path, verify_file=True)
                    counts["artifacts"] += 1
            with rebuilt._connect() as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            for suffix in ("-wal", "-shm"):
                Path(str(self.index_path) + suffix).unlink(missing_ok=True)
            os.replace(temporary, self.index_path)
            return counts
        finally:
            temporary.unlink(missing_ok=True)
            Path(str(temporary) + "-wal").unlink(missing_ok=True)
            Path(str(temporary) + "-shm").unlink(missing_ok=True)


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Query or rebuild the panel factory run index")
    parser.add_argument("--artifact-root", default="logs/factory_runs")
    parser.add_argument("--index", default="logs/factory_run_index.sqlite3")
    subparsers = parser.add_subparsers(dest="command", required=True)
    query = subparsers.add_parser("query")
    query.add_argument("--batch-id")
    query.add_argument("--stage")
    query.add_argument("--status")
    query.add_argument("--data-fingerprint")
    query.add_argument("--failure-reason")
    query.add_argument("--limit", type=int, default=100)
    show = subparsers.add_parser("show")
    show.add_argument("run_id")
    subparsers.add_parser("rebuild")
    args = parser.parse_args()
    registry = RunRegistry(args.artifact_root, args.index)
    if args.command == "query":
        payload = registry.query_runs(
            batch_id=args.batch_id,
            stage=args.stage,
            status=args.status,
            data_fingerprint=args.data_fingerprint,
            failure_reason=args.failure_reason,
            limit=args.limit,
        )
    elif args.command == "show":
        payload = {
            "run": registry.get_run(args.run_id),
            "events": registry.list_events(args.run_id),
            "artifacts": registry.list_artifacts(args.run_id),
        }
    else:
        payload = registry.rebuild_index()
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
