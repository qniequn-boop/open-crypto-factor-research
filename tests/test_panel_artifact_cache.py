import json
from pathlib import Path

import pandas as pd
import pytest

import panel_artifact_cache


def _payload():
    index = pd.date_range("2026-01-01", periods=4, freq="D", tz="UTC")
    return {
        "schema_version": "test_payload_v1",
        "frame": pd.DataFrame({"A": [1.0, 2.0, float("nan"), 4.0]}, index=index),
        "nested": {"series": pd.Series([0.1, 0.2, 0.3, 0.4], index=index, name="returns")},
        "metrics": {"sharpe": 1.25, "valid": True},
    }


def test_artifact_cache_roundtrip_and_content_deduplication(tmp_path):
    store = panel_artifact_cache.PanelArtifactStore(tmp_path / "cache")
    request = {"kind": "factor_path", "panel": "abc", "mode": "rank_linear"}

    first = store.write(request, _payload())
    second = store.write(request, _payload())
    loaded, reason = store.lookup(request)

    assert reason == "hit"
    assert loaded is not None
    assert first["artifact_id"] == second["artifact_id"] == loaded["artifact_id"]
    pd.testing.assert_frame_equal(loaded["payload"]["frame"], _payload()["frame"])
    pd.testing.assert_series_equal(loaded["payload"]["nested"]["series"], _payload()["nested"]["series"])
    assert loaded["payload"]["metrics"] == _payload()["metrics"]
    assert len(list((tmp_path / "cache" / "objects").glob("*/manifest.json"))) == 1


def test_artifact_cache_rejects_conflicting_payload_for_same_request(tmp_path):
    store = panel_artifact_cache.PanelArtifactStore(tmp_path / "cache")
    request = {"kind": "factor_path", "panel": "abc", "mode": "rank_linear"}
    first = _payload()
    second = _payload()
    second["metrics"] = {"sharpe": -9.0, "valid": True}
    store.write(request, first)

    with pytest.raises(ValueError, match="panel_artifact_request_payload_conflict"):
        store.write(request, second)


def test_artifact_cache_fails_closed_on_blob_tampering(tmp_path):
    store = panel_artifact_cache.PanelArtifactStore(tmp_path / "cache")
    request = {"kind": "factor_path", "panel": "abc"}
    stored = store.write(request, _payload())
    manifest = json.loads(Path(stored["manifest_path"]).read_text(encoding="utf-8"))
    blob_path = store.root / manifest["payload"]["frame"]["blob_path"]
    blob_path.write_bytes(blob_path.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="panel_artifact_blob_sha256_mismatch"):
        store.lookup(request)


def test_artifact_cache_rejects_alias_path_escape(tmp_path):
    store = panel_artifact_cache.PanelArtifactStore(tmp_path / "cache")
    request = {"kind": "factor_path", "panel": "abc"}
    store.write(request, _payload())
    alias_path = store.alias_dir / f"{store.request_key(request)}.json"
    alias = json.loads(alias_path.read_text(encoding="utf-8"))
    alias["manifest_path"] = "../outside/manifest.json"
    alias_path.write_text(json.dumps(alias), encoding="utf-8")

    with pytest.raises(ValueError, match="panel_artifact_alias_path_outside_store"):
        store.lookup(request)
