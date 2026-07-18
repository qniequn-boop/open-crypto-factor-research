"""Content-addressed immutable cache for panel research evidence artifacts."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ARTIFACT_SCHEMA_VERSION = "panel_evidence_artifact_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_scalar(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        return {"__timestamp__": value.isoformat()}
    if isinstance(value, float) and not np.isfinite(value):
        return {"__float__": str(value)}
    if value is pd.NA:
        return {"__pandas_na__": True}
    return value


def _restore_scalar(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__timestamp__"}:
        return pd.Timestamp(value["__timestamp__"])
    if isinstance(value, dict) and set(value) == {"__float__"}:
        return float(value["__float__"])
    if isinstance(value, dict) and set(value) == {"__pandas_na__"}:
        return pd.NA
    return value


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def _write_immutable(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"immutable_artifact_conflict:{path}")
        return
    _atomic_write(path, payload)


class PanelArtifactStore:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve(strict=False)
        self.blob_dir = self.root / "blobs"
        self.object_dir = self.root / "objects"
        self.alias_dir = self.root / "aliases"
        self.root.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, digest: str) -> Path:
        return self.blob_dir / digest[:2] / f"{digest}.parquet"

    def _store_pandas(self, value: pd.DataFrame | pd.Series) -> dict[str, Any]:
        kind = "series" if isinstance(value, pd.Series) else "dataframe"
        series_name = _json_scalar(value.name) if isinstance(value, pd.Series) else None
        frame = value.to_frame(name="__series_value__") if isinstance(value, pd.Series) else value
        buffer = io.BytesIO()
        frame.to_parquet(buffer, index=True)
        raw = buffer.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        path = self._blob_path(digest)
        _write_immutable(path, raw)
        return {
            "__pandas__": kind,
            "blob_sha256": digest,
            "blob_path": str(path.relative_to(self.root)).replace("\\", "/"),
            "size_bytes": len(raw),
            "series_name": series_name,
            "index_freq": value.index.freqstr if isinstance(value.index, pd.DatetimeIndex) else None,
        }

    def _encode(self, value: Any) -> Any:
        if isinstance(value, (pd.DataFrame, pd.Series)):
            return self._store_pandas(value)
        if isinstance(value, dict):
            return {str(key): self._encode(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._encode(item) for item in value]
        return _json_scalar(value)

    def _decode(self, value: Any) -> Any:
        if isinstance(value, dict) and "__pandas__" in value:
            blob_path = (self.root / value["blob_path"]).resolve(strict=False)
            try:
                blob_path.relative_to(self.blob_dir)
            except ValueError as exc:
                raise ValueError("panel_artifact_blob_path_outside_store") from exc
            raw = blob_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != value["blob_sha256"]:
                raise ValueError("panel_artifact_blob_sha256_mismatch")
            frame = pd.read_parquet(io.BytesIO(raw))
            if value.get("index_freq") and isinstance(frame.index, pd.DatetimeIndex):
                frame.index = pd.DatetimeIndex(frame.index, freq=value["index_freq"])
            if value["__pandas__"] == "series":
                series = frame.iloc[:, 0]
                series.name = _restore_scalar(value.get("series_name"))
                return series
            return frame
        if isinstance(value, dict):
            scalar = _restore_scalar(value)
            if scalar is not value:
                return scalar
            return {key: self._decode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._decode(item) for item in value]
        return value

    @staticmethod
    def request_key(request: dict[str, Any]) -> str:
        return _payload_sha256(request)

    def write(self, request: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        request_key = self.request_key(request)
        encoded_payload = self._encode(payload)
        identity = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "request": request,
            "payload": encoded_payload,
        }
        artifact_id = _payload_sha256(identity)
        alias_path = self.alias_dir / f"{request_key}.json"
        if alias_path.exists():
            existing_alias = json.loads(alias_path.read_text(encoding="utf-8"))
            if existing_alias.get("request_key") != request_key:
                raise ValueError("panel_artifact_alias_request_key_mismatch")
            if existing_alias.get("artifact_id") != artifact_id:
                raise ValueError("panel_artifact_request_payload_conflict")
        manifest = {
            **identity,
            "request_key": request_key,
            "artifact_id": artifact_id,
            "created_at_utc": _utc_now(),
        }
        manifest_without_hash = dict(manifest)
        manifest["manifest_sha256"] = _payload_sha256(manifest_without_hash)
        manifest_path = self.object_dir / artifact_id / "manifest.json"
        if manifest_path.exists():
            existing = self.read_manifest(manifest_path)
            existing_identity = {key: existing[key] for key in ("schema_version", "request", "payload")}
            if existing_identity != identity or existing.get("artifact_id") != artifact_id:
                raise FileExistsError(f"immutable_artifact_conflict:{manifest_path}")
            manifest = existing
        else:
            _write_immutable(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
            )
        alias = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "request_key": request_key,
            "artifact_id": artifact_id,
            "manifest_path": str(manifest_path.relative_to(self.root)).replace("\\", "/"),
            "manifest_file_sha256": _file_sha256(manifest_path),
            "updated_at_utc": _utc_now(),
        }
        _atomic_write(
            alias_path,
            json.dumps(alias, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        )
        return {
            "artifact_id": artifact_id,
            "request_key": request_key,
            "manifest_path": str(manifest_path),
            "manifest_file_sha256": alias["manifest_file_sha256"],
            "payload": payload,
        }

    def read_manifest(self, path: Path | str) -> dict[str, Any]:
        manifest_path = Path(path).expanduser().resolve(strict=True)
        try:
            manifest_path.relative_to(self.object_dir)
        except ValueError as exc:
            raise ValueError("panel_artifact_manifest_path_outside_store") from exc
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
            raise ValueError("panel_artifact_schema_invalid")
        declared_hash = str(manifest.get("manifest_sha256") or "")
        unhashed = dict(manifest)
        unhashed.pop("manifest_sha256", None)
        if _payload_sha256(unhashed) != declared_hash:
            raise ValueError("panel_artifact_manifest_sha256_mismatch")
        identity = {key: manifest[key] for key in ("schema_version", "request", "payload")}
        if _payload_sha256(identity) != manifest.get("artifact_id"):
            raise ValueError("panel_artifact_id_mismatch")
        if self.request_key(manifest["request"]) != manifest.get("request_key"):
            raise ValueError("panel_artifact_request_key_mismatch")
        return manifest

    def lookup(self, request: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        request_key = self.request_key(request)
        alias_path = self.alias_dir / f"{request_key}.json"
        if not alias_path.is_file():
            return None, "alias_missing"
        alias = json.loads(alias_path.read_text(encoding="utf-8"))
        if alias.get("request_key") != request_key:
            raise ValueError("panel_artifact_alias_request_key_mismatch")
        manifest_path = (self.root / str(alias.get("manifest_path") or "")).resolve(strict=False)
        try:
            manifest_path.relative_to(self.object_dir)
        except ValueError as exc:
            raise ValueError("panel_artifact_alias_path_outside_store") from exc
        if not manifest_path.is_file():
            return None, "manifest_missing"
        if _file_sha256(manifest_path) != alias.get("manifest_file_sha256"):
            raise ValueError("panel_artifact_alias_manifest_hash_mismatch")
        manifest = self.read_manifest(manifest_path)
        if manifest["request"] != request:
            raise ValueError("panel_artifact_request_payload_mismatch")
        return {
            "artifact_id": manifest["artifact_id"],
            "request_key": request_key,
            "manifest_path": str(manifest_path),
            "manifest_file_sha256": alias["manifest_file_sha256"],
            "payload": self._decode(manifest["payload"]),
        }, "hit"
