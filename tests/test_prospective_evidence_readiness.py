import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import prospective_evidence_readiness as readiness


def _registry():
    return {
        "registry_id": "registry_test",
        "construction": {"prospective_start_utc": "2026-01-01T00:00:00Z"},
    }


def _write_snapshot(root: Path, day: str, *, formal: bool, eligible_count: int = 40):
    snapshot_dir = root / "prospective_snapshots"
    snapshot_dir.mkdir(exist_ok=True)
    payload = {
        "registry_id": "registry_test",
        "snapshot_date_utc": day,
        "as_of_bar_utc": f"{day}T23:00:00+00:00",
        "eligible_count": eligible_count,
        "day_complete": formal,
        "formal_evidence_eligible": formal,
    }
    path = snapshot_dir / f"{day}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    row = {
        "snapshot_date_utc": day,
        "registry_id": "registry_test",
        "path": f"prospective_snapshots/{day}.json",
        "sha256": readiness._payload_sha256(payload),
    }
    with (snapshot_dir / "manifest.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _write_update(root: Path, created_at: str):
    path = root / "update.json"
    path.write_text(
        json.dumps({
            "created_at_utc": created_at,
            "overall_status": "pass",
            "registry_id": "registry_test",
            "failed_asset_count": 0,
        }),
        encoding="utf-8",
    )
    return path


def _write_factor_snapshot(
    root: Path,
    day: str,
    *,
    promotion_eligible: bool = False,
    expected_path_ids=None,
    actual_path_ids=None,
):
    snapshot_dir = root / "prospective_factor_snapshots"
    snapshot_dir.mkdir(exist_ok=True)
    expected_path_ids = expected_path_ids or ["factor__rank"]
    actual_path_ids = actual_path_ids or list(expected_path_ids)
    contract = {
        "schema_version": 1,
        "track_id": "track_test",
        "expected_path_ids": sorted(expected_path_ids),
    }
    contract_sha256 = readiness._payload_sha256(contract)
    payload = {
        "tracking_registry_id": "tracking_test",
        "snapshot_date_utc": day,
        "as_of_bar_utc": f"{day}T23:00:00+00:00",
        "day_complete": True,
        "operational_evidence_eligible": True,
        "formal_evidence_eligible": promotion_eligible,
        "plans": [{
            "track_id": "track_test",
            "promotion_eligible": promotion_eligible,
            "track_contract": contract,
            "track_contract_sha256": contract_sha256,
            "declared_track_contract_sha256": contract_sha256,
            "contract_matches_registry": True,
            "path_set_matches_contract": sorted(actual_path_ids) == sorted(expected_path_ids),
            "operational_evidence_eligible": True,
            "formal_promotion_evidence_eligible": promotion_eligible,
            "path_count": len(actual_path_ids),
            "paths": [
                {"path_id": path_id, "observation_eligible": True}
                for path_id in actual_path_ids
            ],
        }],
    }
    path = snapshot_dir / f"{day}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    row = {
        "snapshot_date_utc": day,
        "tracking_registry_id": "tracking_test",
        "path": f"prospective_factor_snapshots/{day}.json",
        "sha256": readiness._payload_sha256(payload),
    }
    with (snapshot_dir / "manifest.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return contract_sha256


def test_bootstrap_snapshot_is_excluded_from_formal_days(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness.config, "PANEL_MIN_ASSETS", 20)
    _write_snapshot(tmp_path, "2026-01-01", formal=False)
    _write_snapshot(tmp_path, "2026-01-02", formal=True)
    update = _write_update(tmp_path, "2026-01-03T00:00:00+00:00")

    report = readiness.build_readiness_report(
        snapshot_dir=tmp_path / "prospective_snapshots",
        data_update_path=update,
        now_utc=datetime(2026, 1, 3, tzinfo=timezone.utc),
        registry=_registry(),
    )

    assert report["formal_complete_day_count"] == 1
    assert report["bootstrap_or_incomplete_snapshot_count"] == 1
    assert report["automation_action"] == "collect_only"
    assert not report["automated_reaudit_allowed"]


def test_promotion_policy_loader_rejects_invalid_stage_set(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps({"schema_version": 1, "policy_id": "bad", "readiness_stages": {"formal_promotion_audit": {"min_days": 1, "min_coverage": 1.0}}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid_prospective_readiness_stages"):
        readiness.load_promotion_policy(path)


def test_ninety_complete_days_enable_only_non_promotional_reaudit(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness.config, "PANEL_MIN_ASSETS", 20)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for offset in range(90):
        _write_snapshot(tmp_path, (start.date()).fromordinal(start.date().toordinal() + offset).isoformat(), formal=True)
    update = _write_update(tmp_path, "2026-03-31T01:00:00+00:00")

    report = readiness.build_readiness_report(
        snapshot_dir=tmp_path / "prospective_snapshots",
        data_update_path=update,
        now_utc=datetime(2026, 3, 31, 2, tzinfo=timezone.utc),
        registry=_registry(),
    )

    assert report["stages"]["non_promotional_reaudit"]["ready"]
    assert not report["stages"]["formal_promotion_audit"]["ready"]
    assert report["automation_action"] == "non_promotional_reaudit_allowed"


def test_hash_mismatch_blocks_all_stages(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness.config, "PANEL_MIN_ASSETS", 20)
    _write_snapshot(tmp_path, "2026-01-01", formal=True)
    path = tmp_path / "prospective_snapshots" / "2026-01-01.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["eligible_count"] = 39
    path.write_text(json.dumps(payload), encoding="utf-8")
    update = _write_update(tmp_path, "2026-01-02T00:00:00+00:00")

    report = readiness.build_readiness_report(
        snapshot_dir=tmp_path / "prospective_snapshots",
        data_update_path=update,
        now_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
        registry=_registry(),
    )

    assert not report["snapshot_integrity_ok"]
    assert any(error.startswith("sha256_mismatch") for error in report["snapshot_integrity_errors"])
    assert report["automation_action"] == "collect_only"


def test_factor_shadow_days_are_required_and_nonpromotion_plan_cannot_unlock_formal_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness.config, "PANEL_MIN_ASSETS", 20)
    monkeypatch.setattr(
        readiness,
        "STAGES",
        {
            "operational_observation": {"min_days": 1, "min_coverage": 0.9},
            "non_promotional_reaudit": {"min_days": 1, "min_coverage": 0.9},
            "formal_promotion_audit": {"min_days": 1, "min_coverage": 0.9},
        },
    )
    _write_snapshot(tmp_path, "2026-01-01", formal=True)
    contract_sha256 = _write_factor_snapshot(tmp_path, "2026-01-01", promotion_eligible=False)
    update = _write_update(tmp_path, "2026-01-02T00:00:00+00:00")
    tracking = {
        "tracking_registry_id": "tracking_test",
        "plans": [{
            "track_id": "track_test",
            "status": "active",
            "promotion_eligible": False,
            "track_contract_sha256": contract_sha256,
        }],
    }

    report = readiness.build_readiness_report(
        snapshot_dir=tmp_path / "prospective_snapshots",
        data_update_path=update,
        now_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
        registry=_registry(),
        factor_snapshot_dir=tmp_path / "prospective_factor_snapshots",
        tracking_registry=tracking,
    )

    assert report["stages"]["non_promotional_reaudit"]["ready"] is True
    assert report["stages"]["formal_promotion_audit"]["ready"] is False
    assert "no_promotion_eligible_factor_tracking_plan" in report["stages"]["formal_promotion_audit"]["blockers"]
    assert report["factor_shadow"]["tracks"]["track_test"]["operational"]["day_count"] == 1


def test_factor_shadow_does_not_count_incomplete_contract_path_set(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness.config, "PANEL_MIN_ASSETS", 20)
    _write_snapshot(tmp_path, "2026-01-01", formal=True)
    contract_sha256 = _write_factor_snapshot(
        tmp_path,
        "2026-01-01",
        expected_path_ids=["factor__rank", "factor__bucket"],
        actual_path_ids=["factor__rank"],
    )
    tracking = {
        "tracking_registry_id": "tracking_test",
        "plans": [{
            "track_id": "track_test",
            "status": "active",
            "promotion_eligible": False,
            "track_contract_sha256": contract_sha256,
        }],
    }

    report = readiness.build_readiness_report(
        snapshot_dir=tmp_path / "prospective_snapshots",
        now_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
        registry=_registry(),
        factor_snapshot_dir=tmp_path / "prospective_factor_snapshots",
        tracking_registry=tracking,
    )

    assert report["factor_shadow"]["integrity_ok"] is False
    assert report["factor_shadow"]["tracks"]["track_test"]["operational"]["day_count"] == 0
    assert any("factor_path_set_mismatch" in error for error in report["factor_shadow"]["integrity_errors"])


def test_factor_shadow_requires_same_day_formal_universe_evidence(tmp_path):
    _write_snapshot(tmp_path, "2026-01-01", formal=True)
    contract_sha256 = _write_factor_snapshot(tmp_path, "2026-01-02")
    tracking = {
        "tracking_registry_id": "tracking_test",
        "plans": [{
            "track_id": "track_test",
            "status": "active",
            "promotion_eligible": False,
            "track_contract_sha256": contract_sha256,
        }],
    }

    report = readiness.build_readiness_report(
        snapshot_dir=tmp_path / "prospective_snapshots",
        now_utc=datetime(2026, 1, 3, tzinfo=timezone.utc),
        registry=_registry(),
        factor_snapshot_dir=tmp_path / "prospective_factor_snapshots",
        tracking_registry=tracking,
    )

    assert report["factor_shadow"]["tracks"]["track_test"]["operational"]["day_count"] == 0
    assert any("unpaired_factor_universe_date" in error for error in report["factor_shadow"]["integrity_errors"])


def test_deprecated_factor_snapshot_is_retained_without_poisoning_active_track(tmp_path):
    _write_snapshot(tmp_path, "2026-01-01", formal=True)
    deprecated_contract = _write_factor_snapshot(tmp_path, "2026-01-01")
    tracking = {
        "tracking_registry_id": "tracking_test",
        "plans": [
            {
                "track_id": "track_test",
                "status": "deprecated",
                "promotion_eligible": False,
                "track_contract_sha256": deprecated_contract,
            },
            {
                "track_id": "current_track",
                "status": "active",
                "promotion_eligible": True,
                "track_contract_sha256": "current_contract",
            },
        ],
    }

    report = readiness.build_readiness_report(
        snapshot_dir=tmp_path / "prospective_snapshots",
        now_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
        registry=_registry(),
        factor_snapshot_dir=tmp_path / "prospective_factor_snapshots",
        tracking_registry=tracking,
    )

    factor = report["factor_shadow"]
    assert factor["integrity_ok"] is True
    assert factor["ignored_inactive_plan_rows"] == 1
    assert factor["tracks"]["current_track"]["formal"]["day_count"] == 0
