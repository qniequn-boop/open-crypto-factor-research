import json
from pathlib import Path

import pandas as pd
import pytest

import panel_factor_research as panel
import panel_run_registry


def _one_asset_panel():
    index = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
    ohlcv = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [10.0, 11.0, 12.0],
            "volume_quote": [1000.0, 1111.0, 1224.0],
        },
        index=index,
    )
    return {
        "BTC-USDT-SWAP": {
            "ohlcv": ohlcv,
            "spot_ohlcv": None,
            "funding": pd.Series([0.0, float("nan"), float("nan")], index=index, name="funding"),
            "open_interest": None,
            "market_cap": None,
            "instrument": {"instId": "BTC-USDT-SWAP"},
            "asset_label": "payment",
        }
    }


def _fake_evaluation(*args, **kwargs):
    return {
        "created_at_utc": "20260715T130000Z",
        "factor_count": 0,
        "pass_count": 0,
        "watchlist_count": 0,
        "factors": [],
        "_selection_return_archive": {
            "schema_version": 1,
            "archive_type": "panel_selection_daily_net_returns",
            "selection_policy": "IS_and_Val_only",
            "holdout_included": False,
            "full_trial_count": 0,
            "selection_end": None,
            "observed_path_count": 0,
            "empty_path_count": 0,
            "paths": {},
        },
    }


def test_panel_factor_main_records_completed_run_and_hashed_artifacts(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(panel, "LOG_DIR", log_dir)
    monkeypatch.setattr(panel, "PANEL_SUBSTRATE_DIR", tmp_path / "panel_substrates")
    monkeypatch.setattr(panel, "_load_panel", lambda *args, **kwargs: (_one_asset_panel(), {}))
    monkeypatch.setattr(panel, "_evaluate", _fake_evaluation)

    result = panel.main(
        ["--days", "2", "--symbols", "BTC-USDT-SWAP", "--min-assets", "1"]
    )

    assert result == 0
    registry = panel_run_registry.RunRegistry(
        log_dir / "factory_runs",
        log_dir / "factory_run_index.sqlite3",
    )
    rows = registry.query_runs(status="completed")
    assert len(rows) == 1
    assert rows[0]["run_kind"] == "panel_factor_research"
    assert rows[0]["stage"] == "stage_3_full_historical_audit"
    assert len(rows[0]["data_fingerprint"]) == 64
    artifacts = registry.list_artifacts(rows[0]["run_id"])
    assert {row["role"] for row in artifacts} == {
        "code_snapshot_bundle",
        "effective_trial_registry_snapshot",
        "panel_substrate_manifest",
        "primary_report",
        "selection_return_archive",
    }
    report = json.loads(Path(rows[0]["primary_report_path"]).read_text(encoding="utf-8"))
    assert report["factory_run"]["run_id"] == rows[0]["run_id"]
    assert report["factory_run"]["sqlite_is_rebuildable_index_only"] is True
    assert report["panel_substrate"]["panel_loader_invoked"] is True
    assert report["panel_substrate"]["cache_hit"] is False


def test_panel_factor_main_records_unhandled_failure(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(panel, "LOG_DIR", log_dir)
    monkeypatch.setattr(panel, "PANEL_SUBSTRATE_DIR", tmp_path / "panel_substrates")

    def fail_load(*args, **kwargs):
        raise RuntimeError("synthetic_load_failure")

    monkeypatch.setattr(panel, "_load_panel", fail_load)

    with pytest.raises(RuntimeError, match="synthetic_load_failure"):
        panel.main(["--days", "2", "--symbols", "BTC-USDT-SWAP", "--min-assets", "1"])

    registry = panel_run_registry.RunRegistry(
        log_dir / "factory_runs",
        log_dir / "factory_run_index.sqlite3",
    )
    failures = registry.query_runs(failure_reason="RuntimeError")
    assert len(failures) == 1
    assert failures[0]["status"] == "failed"


def test_explicit_frozen_substrate_never_invokes_panel_loader(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    substrate_dir = tmp_path / "panel_substrates"
    monkeypatch.setattr(panel, "LOG_DIR", log_dir)
    monkeypatch.setattr(panel, "PANEL_SUBSTRATE_DIR", substrate_dir)
    monkeypatch.setattr(panel, "_load_panel", lambda *args, **kwargs: (_one_asset_panel(), {}))
    monkeypatch.setattr(panel, "_evaluate", _fake_evaluation)
    common_args = [
        "--days",
        "2",
        "--symbols",
        "BTC-USDT-SWAP",
        "--min-assets",
        "1",
        "--as-of",
        "2026-01-02T00:00:00Z",
    ]
    assert panel.main(common_args) == 0
    first_report = json.loads((log_dir / "panel_factor_report_latest.json").read_text(encoding="utf-8"))
    manifest_path = first_report["panel_substrate"]["manifest_path"]

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("panel_loader_must_not_run")

    monkeypatch.setattr(panel, "_load_panel", forbidden_loader)
    assert panel.main([*common_args, "--require-cached-substrate"]) == 0
    cached_report = json.loads((log_dir / "panel_factor_report_latest.json").read_text(encoding="utf-8"))
    assert cached_report["panel_substrate"]["mode"] == "automatic_validated_alias"
    assert cached_report["panel_substrate"]["panel_loader_invoked"] is False

    assert panel.main([*common_args, "--substrate-manifest", manifest_path]) == 0

    frozen_report = json.loads((log_dir / "panel_factor_report_latest.json").read_text(encoding="utf-8"))
    assert frozen_report["panel_substrate"]["mode"] == "explicit_frozen_manifest"
    assert frozen_report["panel_substrate"]["panel_loader_invoked"] is False
    assert frozen_report["panel_substrate"]["zero_network_panel_load"] is True
    assert frozen_report["panel_substrate"]["formal_frozen_contract"] is True


def test_required_cached_substrate_miss_fails_before_panel_loader(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(panel, "LOG_DIR", log_dir)
    monkeypatch.setattr(panel, "PANEL_SUBSTRATE_DIR", tmp_path / "empty_substrates")

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("panel_loader_must_not_run_on_required_cache_miss")

    monkeypatch.setattr(panel, "_load_panel", forbidden_loader)

    with pytest.raises(ValueError, match="required_panel_substrate_unavailable:alias_missing"):
        panel.main(
            [
                "--days",
                "2",
                "--symbols",
                "BTC-USDT-SWAP",
                "--min-assets",
                "1",
                "--require-cached-substrate",
            ]
        )
