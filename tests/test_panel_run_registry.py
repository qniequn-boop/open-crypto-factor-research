import json
from pathlib import Path
import zipfile

import pytest

import panel_run_registry as runs


def _contract(tmp_path: Path, *, run_id: str, batch_id: str | None = "batch_1") -> dict:
    code_path = tmp_path / "evaluator.py"
    code_path.write_text("VALUE = 1\n", encoding="utf-8")
    input_path = tmp_path / "batch.json"
    input_path.write_text('{"batch_id":"batch_1"}\n', encoding="utf-8")
    return runs.build_run_contract(
        run_kind="panel_factor_research",
        stage="stage_3_full_historical_audit",
        batch_id=batch_id,
        parameters={"days": 730, "factor_scope": "candidates_and_baselines"},
        input_artifacts=[runs.file_reference(input_path, "candidate_batch")],
        code_artifacts=[runs.file_reference(code_path, "evaluator_code")],
        policies={"holdout_feedback_to_ai": False},
        run_id=run_id,
        created_at_utc="2026-07-15T12:00:00.000000Z",
    )


def _registry(tmp_path: Path) -> runs.RunRegistry:
    return runs.RunRegistry(tmp_path / "factory_runs", tmp_path / "factory_run_index.sqlite3")


def test_run_contract_is_self_hashing_and_tamper_evident(tmp_path):
    contract = _contract(tmp_path, run_id="run_contract_test")

    runs.validate_run_contract(contract)
    tampered = {**contract, "parameters": {"days": 60}}

    with pytest.raises(ValueError, match="run_contract_sha256_mismatch"):
        runs.validate_run_contract(tampered)


def test_run_lifecycle_is_queryable_by_required_dimensions(tmp_path):
    registry = _registry(tmp_path)
    contract = _contract(tmp_path, run_id="run_query_test")
    contract_path = registry.create_run(contract)
    registry.start_run(contract["run_id"])
    registry.record_data_fingerprint(
        contract["run_id"],
        "panel_fingerprint_1",
        details={"asset_count": 40},
    )
    report_path = tmp_path / "report.json"
    report_path.write_text('{"pass_count":0}\n', encoding="utf-8")
    report_artifact = registry.record_artifact(contract["run_id"], "primary_report", report_path)
    registry.complete_run(contract["run_id"], details={"primary_report_sha256": report_artifact["sha256"]})

    row = registry.get_run(contract["run_id"])
    assert row["status"] == "completed"
    assert row["data_fingerprint"] == "panel_fingerprint_1"
    assert row["primary_report_path"] == str(report_path.resolve())
    assert Path(row["contract_path"]) == contract_path
    assert registry.query_runs(batch_id="batch_1")[0]["run_id"] == contract["run_id"]
    assert registry.query_runs(stage="stage_3_full_historical_audit")[0]["run_id"] == contract["run_id"]
    assert registry.query_runs(status="completed")[0]["run_id"] == contract["run_id"]
    assert registry.query_runs(data_fingerprint="panel_fingerprint_1")[0]["run_id"] == contract["run_id"]
    assert [event["event_type"] for event in registry.list_events(contract["run_id"])] == [
        "run_started",
        "data_resolved",
        "run_completed",
    ]

    with pytest.raises(ValueError, match="invalid_run_transition:completed->running"):
        registry.start_run(contract["run_id"])


def test_run_preserves_exact_code_snapshot_bundle(tmp_path):
    registry = _registry(tmp_path)
    contract = _contract(tmp_path, run_id="run_code_snapshot_test")
    registry.create_run(contract)

    artifact = next(
        row for row in registry.list_artifacts(contract["run_id"]) if row["role"] == "code_snapshot_bundle"
    )
    with zipfile.ZipFile(artifact["path"]) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        snapshot_name = manifest["files"][0]["snapshot_path"]
        snapshotted_code = archive.read(snapshot_name)

    assert manifest["contract_sha256"] == contract["contract_sha256"]
    assert __import__("hashlib").sha256(snapshotted_code).hexdigest() == contract["code_artifacts"][0]["sha256"]


def test_failure_reason_is_indexed_without_overwriting_evidence(tmp_path):
    registry = _registry(tmp_path)
    contract = _contract(tmp_path, run_id="run_failure_test", batch_id=None)
    registry.create_run(contract)
    registry.start_run(contract["run_id"])
    registry.fail_run(contract["run_id"], "panel_min_assets_not_met", details={"loaded": 3})

    failures = registry.query_runs(failure_reason="panel_min_assets_not_met")

    assert len(failures) == 1
    assert failures[0]["status"] == "failed"
    assert json.loads(registry.list_events(contract["run_id"])[-1]["details_json"]) == {"loaded": 3}


def test_sqlite_index_rebuilds_from_immutable_json_evidence(tmp_path):
    registry = _registry(tmp_path)
    contract = _contract(tmp_path, run_id="run_rebuild_test")
    registry.create_run(contract)
    registry.start_run(contract["run_id"])
    report_path = tmp_path / "report.json"
    report_path.write_text('{"result":"reject"}\n', encoding="utf-8")
    registry.record_artifact(contract["run_id"], "primary_report", report_path)
    registry.complete_run(contract["run_id"])
    before = registry.get_run(contract["run_id"])

    counts = registry.rebuild_index()

    assert counts == {"runs": 1, "events": 2, "artifacts": 2}
    after = registry.get_run(contract["run_id"])
    assert after["status"] == "completed"
    assert after["updated_at_utc"] == before["updated_at_utc"]
    assert len(registry.list_artifacts(contract["run_id"])) == 2


def test_repeated_artifact_registration_is_idempotent(tmp_path):
    registry = _registry(tmp_path)
    contract = _contract(tmp_path, run_id="run_artifact_idempotent_test")
    registry.create_run(contract)
    report_path = tmp_path / "report.json"
    report_path.write_text('{"result":"reject"}\n', encoding="utf-8")

    first = registry.record_artifact(contract["run_id"], "primary_report", report_path)
    second = registry.record_artifact(contract["run_id"], "primary_report", report_path)

    assert first == second
    assert len(registry.list_artifacts(contract["run_id"])) == 2
    assert len(list((tmp_path / "factory_runs" / contract["run_id"] / "artifacts").glob("*.json"))) == 2


def test_mutable_input_snapshot_survives_source_changes_and_index_rebuild(tmp_path):
    registry = _registry(tmp_path)
    contract = _contract(tmp_path, run_id="run_snapshot_test")
    registry.create_run(contract)
    source = tmp_path / "panel_trial_registry.jsonl"
    source.write_text('{"candidate_id":"first"}\n', encoding="utf-8")

    snapshot = registry.snapshot_file(contract["run_id"], "effective_trial_registry_snapshot", source)
    source.write_text('{"candidate_id":"changed_later"}\n', encoding="utf-8")
    counts = registry.rebuild_index()

    assert Path(snapshot["path"]).read_text(encoding="utf-8") == '{"candidate_id":"first"}\n'
    assert snapshot["snapshot_source_exists"] is True
    assert counts["artifacts"] == 2


def test_index_rebuild_fails_closed_when_registered_artifact_changed(tmp_path):
    registry = _registry(tmp_path)
    contract = _contract(tmp_path, run_id="run_artifact_tamper_test")
    registry.create_run(contract)
    registry.start_run(contract["run_id"])
    report_path = tmp_path / "report.json"
    report_path.write_text('{"result":"reject"}\n', encoding="utf-8")
    registry.record_artifact(contract["run_id"], "primary_report", report_path)
    registry.complete_run(contract["run_id"])
    report_path.write_text('{"result":"pass"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="run_artifact_hash_mismatch"):
        registry.rebuild_index()
