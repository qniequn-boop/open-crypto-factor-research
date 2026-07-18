"""Content-addressed storage for resolved point-in-time panel inputs."""

from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


SUBSTRATE_SCHEMA_VERSION = "panel_substrate_v1"
SERIALIZATION_VERSION = "per_asset_field_parquet_blobs_v1"
PANEL_FIELDS = ("ohlcv", "spot_ohlcv", "funding", "open_interest", "market_cap")
SUBSTRATE_IDENTITY_KEYS = (
    "schema_version",
    "serialization_version",
    "request_contract",
    "panel_fingerprint",
    "failures",
    "assets",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


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


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not np.isfinite(value):
            if np.isnan(value):
                return {"__panel_substrate_scalar__": "nan"}
            return {"__panel_substrate_scalar__": "positive_infinity" if value > 0 else "negative_infinity"}
        return value
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, (pd.Timestamp, datetime)):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _restore_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        special = value.get("__panel_substrate_scalar__") if len(value) == 1 else None
        if special == "nan":
            return float("nan")
        if special == "positive_infinity":
            return float("inf")
        if special == "negative_infinity":
            return float("-inf")
        return {key: _restore_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_restore_jsonable(item) for item in value]
    return value


def _write_immutable_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise FileExistsError(f"content_address_conflict:{path}")
        return
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
                raise FileExistsError(f"content_address_conflict:{path}")
    finally:
        temporary.unlink(missing_ok=True)


def _write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    raw = (json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    _write_immutable_bytes(path, raw)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _normalized_cutoff(as_of: Any | None, dynamic_day_utc: str | None = None) -> dict[str, Any]:
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
        return {"mode": "explicit_as_of", "value": cutoff.isoformat()}
    day = dynamic_day_utc or datetime.now(timezone.utc).date().isoformat()
    return {"mode": "dynamic_utc_day", "value": str(day)}


def code_fingerprint(paths: list[Path | str]) -> dict[str, Any]:
    rows = []
    for raw_path in paths:
        path = Path(raw_path).resolve(strict=True)
        rows.append(
            {
                "name": path.name,
                "sha256": _file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    rows.sort(key=lambda row: (row["name"], row["sha256"]))
    return {"sha256": _payload_sha256(rows), "files": rows}


def build_request_contract(
    *,
    inst_ids: list[str],
    days: int,
    bar: str,
    as_of: Any | None,
    load_spot: bool,
    load_open_interest: bool,
    load_market_cap: bool,
    universe_registry_path: Path | str,
    loader_code_paths: list[Path | str],
    dynamic_day_utc: str | None = None,
) -> dict[str, Any]:
    universe_path = Path(universe_registry_path).resolve(strict=True)
    loader_fingerprint = code_fingerprint(loader_code_paths)
    contract = {
        "schema_version": SUBSTRATE_SCHEMA_VERSION,
        "serialization_version": SERIALIZATION_VERSION,
        "inst_ids": [str(item) for item in inst_ids],
        "days": int(days),
        "bar": str(bar),
        "cutoff": _normalized_cutoff(as_of, dynamic_day_utc),
        "fields": {
            "perpetual_ohlcv": True,
            "sparse_real_funding": True,
            "spot_ohlcv": bool(load_spot),
            "open_interest_daily": bool(load_open_interest),
            "market_cap_daily": bool(load_market_cap),
        },
        "missingness_policy": {
            "funding_events_forward_filled": False,
            "spot_basis_padded": False,
            "open_interest_padded": False,
            "market_cap_padded": False,
            "pre_listing_history_filled": False,
        },
        "universe_registry": {
            "name": universe_path.name,
            "sha256": _file_sha256(universe_path),
        },
        "loader_code": loader_fingerprint,
    }
    contract["request_key"] = _payload_sha256(contract)
    return contract


def _source_path_rows(
    data_module: Any,
    inst_ids: list[str],
    days: int,
    bar: str,
    *,
    load_spot: bool,
    load_open_interest: bool,
    load_market_cap: bool,
) -> list[tuple[str, Path]]:
    rows: list[tuple[str, Path]] = [("instrument_snapshot", data_module._instrument_cache_path("SWAP"))]
    for inst_id in inst_ids:
        rows.extend(
            [
                (f"{inst_id}:perpetual_ohlcv", data_module._cache_path(inst_id, bar, days)),
                (f"{inst_id}:funding", data_module._funding_cache_path(inst_id, days)),
            ]
        )
        if load_spot:
            spot_id = data_module.swap_to_spot_inst_id(inst_id)
            rows.append((f"{inst_id}:spot_ohlcv", data_module._spot_cache_path(spot_id, bar, days)))
        if load_open_interest:
            rows.append(
                (f"{inst_id}:open_interest", data_module._open_interest_cache_path(inst_id, days, "1D"))
            )
        if load_market_cap:
            rows.append((f"{inst_id}:market_cap", data_module._market_cap_cache_path(inst_id, days)))
    return rows


def collect_source_inventory(
    data_module: Any,
    inst_ids: list[str],
    days: int,
    bar: str,
    *,
    load_spot: bool,
    load_open_interest: bool,
    load_market_cap: bool,
) -> dict[str, Any]:
    entries = []
    for role, raw_path in _source_path_rows(
        data_module,
        inst_ids,
        days,
        bar,
        load_spot=load_spot,
        load_open_interest=load_open_interest,
        load_market_cap=load_market_cap,
    ):
        path = Path(raw_path).resolve(strict=False)
        exists = path.is_file()
        entries.append(
            {
                "role": role,
                "name": path.name,
                "exists": exists,
                "sha256": _file_sha256(path) if exists else None,
                "size_bytes": path.stat().st_size if exists else None,
            }
        )
    fingerprint_rows = [
        {key: row[key] for key in ("role", "name", "exists", "sha256", "size_bytes")}
        for row in entries
    ]
    return {
        "fingerprint": _payload_sha256(fingerprint_rows),
        "file_count": len(entries),
        "existing_file_count": sum(row["exists"] for row in entries),
        "entries": entries,
    }


def request_compatibility(
    frozen: dict[str, Any],
    requested: dict[str, Any],
    *,
    allow_loader_code_change: bool,
) -> tuple[bool, list[str]]:
    ignored = {"request_key"}
    if allow_loader_code_change:
        ignored.add("loader_code")
    failures = []
    keys = sorted((set(frozen) | set(requested)) - ignored)
    for key in keys:
        if frozen.get(key) != requested.get(key):
            failures.append(f"request_contract_changed:{key}")
    return not failures, failures


class PanelSubstrateStore:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve(strict=False)
        self.blob_dir = self.root / "blobs"
        self.object_dir = self.root / "objects"
        self.alias_dir = self.root / "aliases"
        self.root.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, digest: str) -> Path:
        return self.blob_dir / digest[:2] / f"{digest}.parquet"

    def _store_frame(self, value: pd.DataFrame | pd.Series) -> dict[str, Any]:
        kind = "series" if isinstance(value, pd.Series) else "dataframe"
        series_name = _jsonable(value.name) if isinstance(value, pd.Series) else None
        frame = value.to_frame(name=value.name or "value") if isinstance(value, pd.Series) else value
        buffer = io.BytesIO()
        frame.to_parquet(buffer, index=True)
        raw = buffer.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        blob_path = self._blob_path(digest)
        _write_immutable_bytes(blob_path, raw)
        return {
            "present": True,
            "kind": kind,
            "series_name": series_name,
            "blob_sha256": digest,
            "blob_path": str(blob_path.relative_to(self.root)),
            "size_bytes": len(raw),
            "rows": int(len(frame)),
            "columns": [str(column) for column in frame.columns],
            "dtypes": [str(dtype) for dtype in frame.dtypes],
        }

    def write(
        self,
        *,
        panel: dict[str, dict[str, Any]],
        failures: list[dict[str, Any]],
        request_contract: dict[str, Any],
        panel_fingerprint: dict[str, Any],
        source_inventory: dict[str, Any],
    ) -> dict[str, Any]:
        asset_rows: dict[str, Any] = {}
        for inst_id in request_contract["inst_ids"]:
            if inst_id not in panel:
                continue
            item = panel[inst_id]
            fields = {}
            for field in PANEL_FIELDS:
                value = item.get(field)
                fields[field] = {"present": False} if value is None else self._store_frame(value)
            asset_rows[inst_id] = {
                "metadata": _jsonable({key: value for key, value in item.items() if key not in PANEL_FIELDS}),
                "fields": fields,
            }
        manifest_content = {
            "schema_version": SUBSTRATE_SCHEMA_VERSION,
            "serialization_version": SERIALIZATION_VERSION,
            "request_contract": request_contract,
            "panel_fingerprint": panel_fingerprint,
            "source_inventory": source_inventory,
            "failures": _jsonable(failures),
            "assets": asset_rows,
        }
        substrate_identity = {key: manifest_content[key] for key in SUBSTRATE_IDENTITY_KEYS}
        substrate_id = _payload_sha256(substrate_identity)
        manifest = {
            **manifest_content,
            "substrate_id": substrate_id,
            "created_at_utc": _utc_now(),
        }
        manifest_without_hash = dict(manifest)
        manifest["manifest_sha256"] = _payload_sha256(manifest_without_hash)
        manifest_path = self.object_dir / substrate_id / "manifest.json"
        if manifest_path.exists():
            existing = self.read_manifest(manifest_path)
            if existing["substrate_id"] != substrate_id:
                raise FileExistsError(f"substrate_object_conflict:{manifest_path}")
            manifest = existing
        else:
            _write_immutable_json(manifest_path, manifest)
        alias = {
            "schema_version": SUBSTRATE_SCHEMA_VERSION,
            "request_key": request_contract["request_key"],
            "substrate_id": manifest["substrate_id"],
            "manifest_path": str(manifest_path),
            "manifest_file_sha256": _file_sha256(manifest_path),
            "source_inventory_fingerprint": source_inventory["fingerprint"],
            "updated_at_utc": _utc_now(),
        }
        _atomic_write_json(self.alias_dir / f"{request_contract['request_key']}.json", alias)
        return {**manifest, "manifest_path": str(manifest_path)}

    def read_manifest(self, path: Path | str) -> dict[str, Any]:
        manifest_path = Path(path).expanduser().resolve(strict=True)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != SUBSTRATE_SCHEMA_VERSION:
            raise ValueError("panel_substrate_schema_invalid")
        if manifest.get("serialization_version") != SERIALIZATION_VERSION:
            raise ValueError("panel_substrate_serialization_version_invalid")
        declared_hash = str(manifest.get("manifest_sha256") or "")
        payload = dict(manifest)
        payload.pop("manifest_sha256", None)
        if _payload_sha256(payload) != declared_hash:
            raise ValueError("panel_substrate_manifest_sha256_mismatch")
        substrate_identity = {key: manifest[key] for key in SUBSTRATE_IDENTITY_KEYS}
        if _payload_sha256(substrate_identity) != manifest.get("substrate_id"):
            raise ValueError("panel_substrate_id_mismatch")
        return manifest

    def lookup(
        self,
        request_contract: dict[str, Any],
        source_inventory: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        alias_path = self.alias_dir / f"{request_contract['request_key']}.json"
        if not alias_path.is_file():
            return None, "alias_missing"
        alias = json.loads(alias_path.read_text(encoding="utf-8"))
        if alias.get("request_key") != request_contract["request_key"]:
            return None, "alias_request_key_mismatch"
        if alias.get("source_inventory_fingerprint") != source_inventory["fingerprint"]:
            return None, "source_inventory_changed"
        manifest_path = Path(str(alias.get("manifest_path") or "")).resolve(strict=False)
        try:
            manifest_path.relative_to(self.object_dir)
        except ValueError as exc:
            raise ValueError("panel_substrate_alias_path_outside_store") from exc
        if not manifest_path.is_file():
            return None, "manifest_missing"
        if _file_sha256(manifest_path) != alias.get("manifest_file_sha256"):
            raise ValueError("panel_substrate_alias_manifest_hash_mismatch")
        manifest = self.read_manifest(manifest_path)
        if manifest.get("substrate_id") != alias.get("substrate_id"):
            raise ValueError("panel_substrate_alias_object_id_mismatch")
        return {**manifest, "manifest_path": str(manifest_path)}, "hit"

    def load(
        self,
        manifest_path: Path | str,
        *,
        panel_fingerprint_fn: Callable[[dict[str, dict[str, Any]]], dict[str, Any]] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        manifest_path = Path(manifest_path).expanduser().resolve(strict=True)
        manifest = self.read_manifest(manifest_path)
        panel: dict[str, dict[str, Any]] = {}
        for inst_id in manifest["request_contract"]["inst_ids"]:
            asset = manifest["assets"].get(inst_id)
            if asset is None:
                continue
            item = _restore_jsonable(asset["metadata"])
            for field in PANEL_FIELDS:
                descriptor = asset["fields"][field]
                if not descriptor.get("present"):
                    item[field] = None
                    continue
                blob_path = (self.root / descriptor["blob_path"]).resolve(strict=False)
                try:
                    blob_path.relative_to(self.blob_dir)
                except ValueError as exc:
                    raise ValueError(f"panel_substrate_blob_path_outside_store:{inst_id}:{field}") from exc
                raw = blob_path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != descriptor["blob_sha256"]:
                    raise ValueError(f"panel_substrate_blob_hash_mismatch:{inst_id}:{field}")
                frame = pd.read_parquet(io.BytesIO(raw))
                if descriptor["kind"] == "series":
                    value = frame.iloc[:, 0]
                    value.name = descriptor.get("series_name")
                    item[field] = value
                else:
                    item[field] = frame
            panel[inst_id] = item
        if panel_fingerprint_fn is not None:
            actual = panel_fingerprint_fn(panel)
            if actual != manifest["panel_fingerprint"]:
                raise ValueError("panel_substrate_roundtrip_fingerprint_mismatch")
        return panel, list(manifest["failures"]), {**manifest, "manifest_path": str(manifest_path)}
