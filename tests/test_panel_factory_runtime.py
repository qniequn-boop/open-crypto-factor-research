import hashlib
import json

import pytest

import panel_factory_runtime as runtime


def _runtime_environment(tmp_path, monkeypatch):
    manifest_path = (
        tmp_path
        / "data_cache"
        / "panel_substrates"
        / "v1"
        / "objects"
        / "substrate_test"
        / "manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text('{"test":true}\n', encoding="utf-8")
    manifest = {
        "substrate_id": "substrate_test",
        "manifest_sha256": "payload_hash",
        "assets": {"A": {}, "B": {}},
        "failures": [],
        "request_contract": {
            "days": 730,
            "cutoff": {"mode": "explicit_as_of", "value": "2026-07-15T23:00:00+00:00"},
        },
    }
    monkeypatch.setattr(runtime.panel_substrate_cache.PanelSubstrateStore, "read_manifest", lambda *_: manifest)
    contract = {
        "schema_version": 1,
        "substrate": {
            "asset_count": 2,
            "days": 730,
            "explicit_as_of_utc": "2026-07-15T23:00:00+00:00",
            "failure_count": 0,
            "manifest_file_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "manifest_payload_sha256": "payload_hash",
            "relative_manifest_path": str(manifest_path.relative_to(tmp_path)),
            "substrate_id": "substrate_test",
        },
    }
    contract_path = tmp_path / "runtime.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    return contract_path, manifest_path


def test_runtime_contract_resolves_and_validates_manifest(tmp_path, monkeypatch):
    contract_path, manifest_path = _runtime_environment(tmp_path, monkeypatch)

    resolved, _ = runtime.resolve_runtime_substrate(contract_path, project_dir=tmp_path)

    assert resolved == manifest_path


def test_runtime_contract_rejects_manifest_file_tampering(tmp_path, monkeypatch):
    contract_path, manifest_path = _runtime_environment(tmp_path, monkeypatch)
    manifest_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest_file_hash_mismatch"):
        runtime.resolve_runtime_substrate(contract_path, project_dir=tmp_path)
