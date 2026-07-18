"""Validate the server-owned runtime binding for the panel factory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import panel_substrate_cache


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_RUNTIME_PATH = PROJECT_DIR / "PANEL_FACTORY_RUNTIME_V1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_runtime_substrate(
    runtime_path: Path | str = DEFAULT_RUNTIME_PATH,
    *,
    project_dir: Path | str = PROJECT_DIR,
) -> tuple[Path, dict[str, Any]]:
    contract_path = Path(runtime_path).expanduser().resolve(strict=True)
    project = Path(project_dir).expanduser().resolve(strict=True)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if int(contract.get("schema_version") or 0) != 1:
        raise ValueError("panel_factory_runtime_schema_invalid")
    substrate = contract.get("substrate") or {}
    required = {
        "asset_count",
        "days",
        "explicit_as_of_utc",
        "failure_count",
        "manifest_file_sha256",
        "manifest_payload_sha256",
        "relative_manifest_path",
        "substrate_id",
    }
    missing = sorted(required - set(substrate))
    if missing:
        raise ValueError("panel_factory_runtime_missing_fields:" + ",".join(missing))
    relative = Path(str(substrate["relative_manifest_path"]))
    if relative.is_absolute():
        raise ValueError("panel_factory_runtime_manifest_must_be_relative")
    manifest_path = (project / relative).resolve(strict=True)
    try:
        manifest_path.relative_to(project)
    except ValueError as exc:
        raise ValueError("panel_factory_runtime_manifest_outside_project") from exc
    if _sha256(manifest_path) != str(substrate["manifest_file_sha256"]):
        raise ValueError("panel_factory_runtime_manifest_file_hash_mismatch")
    store = panel_substrate_cache.PanelSubstrateStore(manifest_path.parents[2])
    manifest = store.read_manifest(manifest_path)
    request = manifest.get("request_contract") or {}
    cutoff = request.get("cutoff") or {}
    checks = {
        "substrate_id": manifest.get("substrate_id") == substrate["substrate_id"],
        "manifest_payload_sha256": manifest.get("manifest_sha256")
        == substrate["manifest_payload_sha256"],
        "asset_count": len(manifest.get("assets") or {}) == int(substrate["asset_count"]),
        "failure_count": len(manifest.get("failures") or []) == int(substrate["failure_count"]),
        "days": int(request.get("days") or 0) == int(substrate["days"]),
        "cutoff_mode": cutoff.get("mode") == "explicit_as_of",
        "cutoff_value": cutoff.get("value") == substrate["explicit_as_of_utc"],
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    if failures:
        raise ValueError("panel_factory_runtime_manifest_contract_mismatch:" + ",".join(failures))
    return manifest_path, contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default=str(DEFAULT_RUNTIME_PATH))
    parser.add_argument("--project-dir", default=str(PROJECT_DIR))
    parser.add_argument("--print-substrate", action="store_true")
    args = parser.parse_args()
    manifest_path, contract = resolve_runtime_substrate(
        args.runtime,
        project_dir=args.project_dir,
    )
    if args.print_substrate:
        print(manifest_path)
    else:
        print(json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
