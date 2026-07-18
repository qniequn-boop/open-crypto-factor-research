import copy

import pandas as pd
import pytest

import panel_factor_research as panel
import panel_stage_policy


def _synthetic_panel(days: int = 40, asset_count: int = 8):
    index = pd.date_range("2026-01-01", periods=24 * days, freq="h", tz="UTC")
    result = {}
    for asset_number in range(asset_count):
        close = pd.Series(
            [100.0 + asset_number + (0.004 + 0.001 * asset_number) * step for step in range(len(index))],
            index=index,
            dtype=float,
        )
        ohlcv = pd.DataFrame(
            {
                "open": close.shift(1).bfill(),
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": 1000.0 + asset_number,
                "vol_quote": close * (1000.0 + asset_number),
            },
            index=index,
        )
        spot = ohlcv.copy()
        spot["close"] = close * (1.0 - 0.0001 * (asset_number + 1))
        result[f"A{asset_number}-USDT-SWAP"] = {
            "ohlcv": ohlcv,
            "funding": pd.Series(0.00001 * (asset_number + 1), index=index[::8]),
            "spot_ohlcv": spot,
            "spot_error": None,
            "open_interest": None,
            "market_cap": None,
            "asset_label": "synthetic" if asset_number < 4 else "synthetic_alt",
        }
    return result


def _candidate():
    return {
        "candidate_id": "cand_staged_basis_001",
        "source_ids": ["PERP_FUNDING_BASIS"],
        "hypothesis": "Rich basis should predict weaker forward returns after funding costs.",
        "family": "carry",
        "required_fields": ["close", "spot_close", "basis"],
        "panel_formula": "basis_carry",
        "direction": "short",
        "neutralization": "none",
        "bucket_policy": "none",
        "weighting_modes": ["rank_linear"],
        "generated_by": "unit_test",
    }


def _force_full_eligibility(monkeypatch):
    original = panel.panel_universe.build_point_in_time_eligibility

    def build(*args, **kwargs):
        result = original(*args, **kwargs)
        close = args[1]
        result["eligibility"] = close.notna()
        result["base_eligibility"] = close.notna()
        return result

    monkeypatch.setattr(panel.panel_universe, "build_point_in_time_eligibility", build)


def _register_candidate(tmp_path, candidate):
    panel.candidate_registry.append_trial_event(
        candidate,
        event="generated",
        status="accepted",
        log_dir=tmp_path,
    )
    return tmp_path / "panel_trial_registry.jsonl"


def _forced_decision(original, survives):
    def decide(*args, **kwargs):
        result = copy.deepcopy(original(*args, **kwargs))
        result["checks"] = {name: bool(survives) for name in result["checks"]}
        result["failed_checks"] = [] if survives else ["val_ic_positive"]
        if not survives:
            result["checks"]["val_ic_positive"] = False
        result["survives_to_stage_3"] = bool(survives)
        result["decision"] = "advance_to_stage_3" if survives else "reject_before_holdout"
        return result

    return decide


def test_stage_2_policy_rejects_any_holdout_input():
    metrics = {
        "IS": {"sharpe": 0.1, "return_evidence_complete_while_held": True},
        "Val": {
            "sharpe": 0.2,
            "total_return": 0.01,
            "turnover": 0.01,
            "return_evidence_complete_while_held": True,
        },
        "Holdout": {"sharpe": 999.0},
    }
    rank_ic = {"IS": {"mean_rank_ic": 0.01}, "Val": {"mean_rank_ic": 0.02}}

    with pytest.raises(ValueError, match="stage_2_holdout_input_forbidden"):
        panel_stage_policy.evaluate_stage_2(
            metrics,
            rank_ic,
            {"IS": 8, "Val": 8},
            required_min_assets=8,
        )


def test_staged_reject_is_physically_isolated_and_not_sent_to_stage_3(tmp_path, monkeypatch):
    candidate = _candidate()
    original_policy = panel_stage_policy.evaluate_stage_2
    original_stage_3 = panel._evaluate_legacy_full
    captured = {}

    monkeypatch.setattr(panel, "LOG_DIR", tmp_path)
    _force_full_eligibility(monkeypatch)
    trial_registry_path = _register_candidate(tmp_path, candidate)
    monkeypatch.setattr(
        panel_stage_policy,
        "evaluate_stage_2",
        _forced_decision(original_policy, survives=False),
    )

    def capture_stage_3(*args, **kwargs):
        captured["stage_3_candidate_ids"] = [
            row["candidate_id"] for row in kwargs.get("candidate_definitions") or []
        ]
        return original_stage_3(*args, **kwargs)

    monkeypatch.setattr(panel, "_evaluate_legacy_full", capture_stage_3)
    report = panel._evaluate(
        _synthetic_panel(),
        days=40,
        rebalance_hours=24,
        min_assets=8,
        candidate_definitions=[candidate],
        candidate_batch_id="batch_staged_reject",
        factor_scope="candidates_and_baselines",
        trial_registry_path=trial_registry_path,
        evaluation_funnel="staged_v1",
    )

    row = next(item for item in report["factors"] if item.get("candidate_id"))
    assert captured["stage_3_candidate_ids"] == []
    assert row["evaluation_stage"] == "stage_2_reject"
    assert row["holdout_accessed"] is False
    assert row["stage_3"]["executed"] is False
    assert set(row["long_short"]) == {"IS", "Val"}
    assert set(row["rank_ic"]) == {"IS", "Val"}
    assert "best_baseline_holdout_sharpe" not in row["baseline_comparison"]
    assert row["rolling_90d"]["executed"] is False
    assert row["robustness"]["executed"] is False
    assert report["evaluation_funnel_summary"]["stage_2_reject_path_count"] == 1
    assert report["evaluation_funnel_summary"]["stage_3_candidate_path_count"] == 0
    assert report["evaluation_funnel_summary"]["full_trial_count_unchanged_by_early_stop"] is True
    assert report["combo_allowed"] is False
    assert report["overfit_audit"]["observed_unique_val_path_count"] >= 1


def test_staged_survivor_matches_legacy_full_economic_results(tmp_path, monkeypatch):
    candidate = _candidate()
    panel_data = _synthetic_panel()
    original_policy = panel_stage_policy.evaluate_stage_2
    monkeypatch.setattr(panel, "LOG_DIR", tmp_path)
    _force_full_eligibility(monkeypatch)
    trial_registry_path = _register_candidate(tmp_path, candidate)
    monkeypatch.setattr(panel.candidate_registry, "append_trial_event", lambda *args, **kwargs: None)

    legacy = panel._evaluate(
        panel_data,
        days=40,
        rebalance_hours=24,
        min_assets=8,
        candidate_definitions=[candidate],
        candidate_batch_id="batch_legacy",
        factor_scope="candidates_and_baselines",
        trial_registry_path=trial_registry_path,
        evaluation_funnel="legacy_full",
    )
    monkeypatch.setattr(
        panel_stage_policy,
        "evaluate_stage_2",
        _forced_decision(original_policy, survives=True),
    )
    staged = panel._evaluate(
        panel_data,
        days=40,
        rebalance_hours=24,
        min_assets=8,
        candidate_definitions=[candidate],
        candidate_batch_id="batch_staged",
        factor_scope="candidates_and_baselines",
        trial_registry_path=trial_registry_path,
        evaluation_funnel="staged_v1",
    )

    legacy_row = next(item for item in legacy["factors"] if item.get("candidate_id"))
    staged_row = next(item for item in staged["factors"] if item.get("candidate_id"))
    for key in (
        "status",
        "checks",
        "failed_checks",
        "coverage_median_assets",
        "rank_ic",
        "dependence_aware_rank_ic",
        "trial_adjustment",
        "long_short",
        "rolling_90d",
        "robustness",
        "overfit_audit",
    ):
        assert staged_row[key] == legacy_row[key]
    assert staged_row["evaluation_stage"] == "stage_3_complete"
    assert staged_row["holdout_accessed"] is True
    assert staged["multiple_testing_trial_count"] == legacy["multiple_testing_trial_count"]
    assert staged["overfit_audit"] == legacy["overfit_audit"]
    assert staged["_selection_return_archive"] == legacy["_selection_return_archive"]


def test_validation_rank_ic_is_independent_of_first_holdout_day(tmp_path, monkeypatch):
    _force_full_eligibility(monkeypatch)
    monkeypatch.setattr(panel, "LOG_DIR", tmp_path / "logs")
    original = _synthetic_panel()
    changed = copy.deepcopy(original)
    index = next(iter(original.values()))["ohlcv"].index
    holdout_index = panel._split_index(index)["Holdout"]
    first_holdout_day = holdout_index[: panel.FORWARD_RETURN_HORIZON_BARS]
    for asset_number, item in enumerate(changed.values()):
        replacement = 100.0 + (len(changed) - asset_number) * 100.0
        item["ohlcv"].loc[first_holdout_day, "close"] = replacement

    common = {
        "days": 40,
        "rebalance_hours": 24,
        "min_assets": 8,
        "candidate_definitions": [],
        "factor_scope": "candidates_and_baselines",
        "evaluation_funnel": "legacy_full",
    }
    original_report = panel._evaluate(original, **common)
    changed_report = panel._evaluate(changed, **common)
    original_rows = {row["name"]: row for row in original_report["factors"]}
    changed_rows = {row["name"]: row for row in changed_report["factors"]}

    assert {
        name: row["rank_ic"]["Val"] for name, row in original_rows.items()
    } == {
        name: row["rank_ic"]["Val"] for name, row in changed_rows.items()
    }
    assert any(
        original_rows[name]["rank_ic"]["Holdout"] != changed_rows[name]["rank_ic"]["Holdout"]
        for name in original_rows
    )


def test_evidence_cache_identity_binds_universe_rules_and_eligibility():
    index = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
    eligibility_three = pd.DataFrame(
        [[True, True, True, False]] * len(index),
        index=index,
        columns=["A", "B", "C", "D"],
    )
    eligibility_four = pd.DataFrame(True, index=index, columns=eligibility_three.columns)
    first_identity = panel._universe_evidence_identity(
        {"rules": {"target_size": 3}, "survivorship": {"mode": "pit"}},
        eligibility_three,
        index,
    )
    second_identity = panel._universe_evidence_identity(
        {"rules": {"target_size": 4}, "survivorship": {"mode": "pit"}},
        eligibility_four,
        index,
    )
    common = {
        "panel_fingerprint": "same-panel",
        "common_index": index,
        "signal_key": ("momentum_7d", "none", "none", 1),
        "weighting_mode": "rank_linear",
        "effective_min_assets": 3,
        "rebalance_hours": 24,
        "code_fingerprint": {"sha256": "same-code"},
    }
    first_request = panel._factor_path_evidence_request(**common, universe_identity=first_identity)
    second_request = panel._factor_path_evidence_request(**common, universe_identity=second_identity)

    assert panel.panel_artifact_cache.PanelArtifactStore.request_key(first_request) != panel.panel_artifact_cache.PanelArtifactStore.request_key(second_request)


def test_factor_path_artifact_cache_reuses_raw_evidence_but_recomputes_classification(tmp_path, monkeypatch):
    panel_data = _synthetic_panel()
    _force_full_eligibility(monkeypatch)
    monkeypatch.setattr(panel, "LOG_DIR", tmp_path / "logs")
    original_robustness = panel._factor_robustness_diagnostics
    call_count = {"value": 0}

    def count_robustness(*args, **kwargs):
        call_count["value"] += 1
        return original_robustness(*args, **kwargs)

    monkeypatch.setattr(panel, "_factor_robustness_diagnostics", count_robustness)
    common = {
        "days": 40,
        "rebalance_hours": 24,
        "min_assets": 8,
        "candidate_definitions": [],
        "factor_scope": "candidates_and_baselines",
        "trial_registry_path": tmp_path / "empty_registry.jsonl",
        "evaluation_funnel": "legacy_full",
        "artifact_cache_dir": tmp_path / "evidence_cache",
        "use_artifact_cache": True,
    }
    first = panel._evaluate(panel_data, **common)
    first_call_count = call_count["value"]
    second = panel._evaluate(panel_data, **common)
    second_call_count = call_count["value"] - first_call_count

    assert first["evidence_artifact_cache"]["hit_count"] == 0
    assert first["evidence_artifact_cache"]["miss_count"] == len(panel.BASELINE_FACTOR_NAMES) * len(panel.WEIGHTING_MODES)
    assert second["evidence_artifact_cache"]["hit_count"] == len(panel.BASELINE_FACTOR_NAMES) * len(panel.WEIGHTING_MODES)
    assert second["evidence_artifact_cache"]["miss_count"] == 0
    assert first_call_count > 0
    assert second_call_count == 0
    assert second["evidence_artifact_cache"]["classification_recomputed_each_run"] is True
    assert second["evidence_artifact_cache"]["trial_count_cached"] is False
    assert second["overfit_audit"] == first["overfit_audit"]
    assert second["_selection_return_archive"] == first["_selection_return_archive"]
    first_rows = {row["name"]: row for row in first["factors"]}
    second_rows = {row["name"]: row for row in second["factors"]}
    assert second_rows == first_rows
