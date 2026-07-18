import copy
import json

import numpy as np
import pandas as pd
import pytest

import panel_universe
import prospective_factor_snapshot as snapshot


def _universe_registry():
    registry = copy.deepcopy(panel_universe.load_registry())
    registry["registry_id"] = "factor_snapshot_test"
    registry["construction"]["candidate_pool_size"] = 4
    registry["assets"] = [
        {"inst_id": f"A{i}-USDT-SWAP", "base_asset": f"A{i}", "asset_family": "defi"}
        for i in range(4)
    ]
    registry["point_in_time_rules"].update(
        {
            "target_size": 4,
            "min_listing_age_days": 1,
            "min_observed_history_days": 1,
            "min_history_coverage_ratio": 0.9,
            "liquidity_lookback_days": 2,
            "liquidity_min_period_days": 1,
            "min_avg_daily_quote_volume_usd": 1,
            "selection_lag_hours": 1,
        }
    )
    return registry


def _panel(include_future=False):
    index = pd.date_range("2026-06-20", periods=24 * 12, freq="h", tz="UTC")
    listed = int(pd.Timestamp("2020-01-01", tz="UTC").timestamp() * 1000)
    panel = {}
    for i in range(4):
        trend = pd.Series(range(len(index)), index=index, dtype=float)
        close = 100.0 + i * 10.0 + trend * (0.01 + i * 0.002)
        ohlcv = pd.DataFrame(
            {
                "open": close.shift(1).bfill(),
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": 1000.0 + i * 100.0,
                "vol_quote": close * (1000.0 + i * 100.0),
            },
            index=index,
        )
        if include_future:
            future_index = pd.date_range(index[-1] + pd.Timedelta(hours=1), periods=24, freq="h", tz="UTC")
            future = pd.DataFrame(
                {
                    "open": 99999.0,
                    "high": 99999.0,
                    "low": 99999.0,
                    "close": 99999.0,
                    "volume": 99999.0,
                    "vol_quote": 99999.0,
                },
                index=future_index,
            )
            ohlcv = pd.concat([ohlcv, future])
        spot = ohlcv.copy()
        spot["close"] = spot["close"] * 0.999
        funding = pd.Series(0.00001 * (i + 1), index=index[::8])
        oi_index = pd.date_range(index[0].normalize(), index[-1].normalize(), freq="D", tz="UTC")
        open_interest = pd.DataFrame(
            {
                "open_interest_contracts": 1000.0 + i,
                "open_interest_ccy": 1000.0 + i,
                "open_interest_usd": 1000000.0 + i * 10000.0,
            },
            index=oi_index,
        )
        panel[f"A{i}-USDT-SWAP"] = {
            "ohlcv": ohlcv,
            "spot_ohlcv": spot,
            "funding": funding,
            "open_interest": open_interest,
            "instrument": {"list_time_ms": listed, "state": "live"},
            "asset_label": "defi",
        }
    return panel


def _daily_spot_panel(include_future=False):
    index = pd.date_range("2026-02-01", "2026-07-17", freq="D", tz="UTC")
    listed = int(pd.Timestamp("2020-01-01", tz="UTC").timestamp() * 1000)
    panel = {}
    for i in range(4):
        increments = pd.Series(
            0.001 + np.sin(np.arange(len(index)) * (0.05 + i * 0.03)) * (0.001 + i * 0.002),
            index=index,
        )
        close = 100.0 * np.exp(increments.cumsum())
        daily = pd.DataFrame(
            {
                "open": close.shift(1).bfill(),
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1000.0 + i * 100.0,
                "vol_quote": close * (1000.0 + i * 100.0),
            },
            index=index,
        )
        if include_future:
            future = daily.iloc[[-1]].copy()
            future.index = pd.DatetimeIndex([index[-1] + pd.Timedelta(days=1)])
            future.loc[:, "close"] = 999999.0 + i
            future.loc[:, "vol_quote"] = 999999999.0
            daily = pd.concat([daily, future])
        panel[f"A{i}-USDT-SWAP"] = {
            "daily_spot_ohlcv": daily,
            "instrument": {"list_time_ms": listed, "state": "live"},
        }
    return panel


def _candidate():
    return {
        "candidate_id": "candidate_momentum_shadow",
        "source_ids": ["CRYPTO_CROSS_SECTIONAL_CORE"],
        "hypothesis": "Momentum continuation shadow path.",
        "family": "momentum",
        "required_fields": ["close"],
        "panel_formula": "momentum_7d",
        "direction": "long",
        "neutralization": "none",
        "bucket_policy": "none",
        "weighting_modes": ["rank_linear"],
        "generated_by": "unit_test",
    }


def _plan():
    return {
        "track_id": "test_shadow",
        "purpose": "operational_shadow_only",
        "activation_date_utc": "2026-07-01",
        "promotion_eligible": False,
        "selection_feedback_allowed": False,
        "candidate_batch_id": "batch_test",
        "candidate_batch_path": "batch.json",
        "candidate_batch_sha256": "abc",
        "baseline_factor_names": ["momentum_7d"],
        "rebalance_hours": 24,
    }


def _contract_plan(
    plan,
    candidates,
    candidate_batch,
    *,
    universe_registry,
    universe_registry_sha256="universe_hash",
    evaluator_bundle_fingerprint=None,
):
    declared = copy.deepcopy(plan)
    contract = snapshot.build_track_contract(
        declared,
        candidates,
        candidate_batch,
        universe_registry=universe_registry,
        universe_registry_sha256=universe_registry_sha256,
        evaluator_bundle_fingerprint=evaluator_bundle_fingerprint,
    )
    declared["track_contract_sha256"] = snapshot.payload_sha256(contract)
    return declared


def _low_vol_candidate():
    return {
        "candidate_id": "monthly_low_vol_90d__equal_quintile_v1",
        "source_ids": ["CRYPTO_LOW_VOLATILITY_MONTHLY"],
        "panel_formula": "monthly_low_vol_90d",
    }


def _low_vol_batch():
    return {
        "batch_id": "literature_replication_005_monthly_low_volatility",
        "replication_id": snapshot.literature_replication.LOW_VOL_REPLICATION_ID,
        "frozen_implementation": {
            "bar": "1Dutc",
            "history_days": 1460,
            "minimum_assets": 4,
            "minimum_lookback_coverage_fraction": 0.8,
            "side_fraction": 0.25,
            "execution_lag_days": 1,
            "cost_bps_one_way": 5,
            "slippage_bps_one_way": 2,
        },
        "paths": [
            {
                "path_id": "monthly_low_vol_90d__equal_quintile_v1",
                "lookback_days": 90,
            }
        ],
    }


def _low_vol_plan():
    return {
        "track_id": "monthly_low_vol_90d_prospective_v1",
        "purpose": "promotion_eligible_factor_shadow",
        "status": "active",
        "evaluator_type": snapshot.LOW_VOL_EVALUATOR_TYPE,
        "activation_date_utc": "2026-07-17",
        "promotion_eligible": True,
        "promotion_policy_id": "policy_test",
        "promotion_policy_path": "policy.json",
        "promotion_policy_sha256": "policy_hash",
        "selection_feedback_allowed": False,
        "candidate_batch_id": "literature_replication_005_monthly_low_volatility",
        "candidate_batch_path": "LITERATURE_REPLICATION_BATCH_005.json",
        "candidate_batch_sha256": "batch_hash",
        "historical_report_path": "logs/report.json",
        "historical_report_sha256": "report_hash",
        "candidate_path_id": "monthly_low_vol_90d__equal_quintile_v1",
    }


def test_active_plans_respect_activation_and_never_enable_feedback():
    registry = {
        "plans": [
            {**_plan(), "status": "active"},
            {**_plan(), "track_id": "disabled", "status": "disabled"},
        ]
    }

    assert snapshot.active_plans(registry, "2026-06-30T23:00:00Z") == []
    assert [row["track_id"] for row in snapshot.active_plans(registry, "2026-07-01T23:00:00Z")] == ["test_shadow"]


def test_tracking_registry_rejects_selection_feedback(tmp_path):
    path = tmp_path / "tracking.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tracking_registry_id": "bad",
                "plans": [{**_plan(), "status": "active", "selection_feedback_allowed": True}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="selection_feedback_must_be_disabled"):
        snapshot.load_tracking_registry(path)


def test_tracking_registry_rejects_active_plan_without_frozen_contract(tmp_path):
    path = tmp_path / "tracking.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tracking_registry_id": "bad",
                "plans": [{**_plan(), "status": "active"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="active_plan_missing_track_contract_sha256"):
        snapshot.load_tracking_registry(path)


def test_evaluator_bundle_fingerprint_changes_when_any_component_changes(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.json"
    first.write_text("value = 1\n", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    before = snapshot.file_bundle_fingerprint([first, second])
    second.write_text('{"changed": true}', encoding="utf-8")
    after = snapshot.file_bundle_fingerprint([first, second])

    assert before["bundle_sha256"] != after["bundle_sha256"]
    assert before["components"]["first.py"] == after["components"]["first.py"]
    assert before["components"]["second.json"] != after["components"]["second.json"]


def test_low_vol_v2_contract_ignores_unrelated_generic_bundle_changes():
    registry = _universe_registry()
    plan = {
        **_low_vol_plan(),
        "track_id": "monthly_low_vol_90d_prospective_v2",
        "evaluator_type": snapshot.LOW_VOL_EVALUATOR_TYPE_V2,
        "activation_date_utc": "2026-07-18",
    }
    semantic = {
        "method": "sha256_of_sorted_callable_name_and_source_sha256_v2",
        "bundle_sha256": "semantic_hash",
    }
    first = snapshot.build_track_contract(
        plan,
        [_low_vol_candidate()],
        _low_vol_batch(),
        universe_registry=registry,
        universe_registry_sha256="universe_hash",
        evaluator_bundle_fingerprint={"bundle_sha256": "generic_before"},
        low_vol_evaluator_fingerprint=semantic,
    )
    second = snapshot.build_track_contract(
        plan,
        [_low_vol_candidate()],
        _low_vol_batch(),
        universe_registry=registry,
        universe_registry_sha256="universe_hash",
        evaluator_bundle_fingerprint={"bundle_sha256": "generic_after"},
        low_vol_evaluator_fingerprint=semantic,
    )

    assert first == second
    assert first["schema_version"] == 2
    assert first["evaluator_semantic_sha256"] == "semantic_hash"
    assert first["cache_refresh_inside_factor_snapshot"] is True
    assert "evaluator_bundle_sha256" not in first

    changed = snapshot.build_track_contract(
        plan,
        [_low_vol_candidate()],
        _low_vol_batch(),
        universe_registry=registry,
        universe_registry_sha256="universe_hash",
        evaluator_bundle_fingerprint={"bundle_sha256": "generic_after"},
        low_vol_evaluator_fingerprint={**semantic, "bundle_sha256": "changed_semantic_hash"},
    )
    assert snapshot.payload_sha256(first) != snapshot.payload_sha256(changed)


def test_production_low_vol_v2_contract_is_frozen_and_v1_cannot_backfill():
    tracking = snapshot.load_tracking_registry()
    plans = {plan["track_id"]: plan for plan in tracking["plans"]}
    old = plans["monthly_low_vol_90d_prospective_v1"]
    current = plans["monthly_low_vol_90d_prospective_v2"]

    assert old["status"] == "invalidated"
    assert old["promotion_eligible"] is False
    assert old["end_date_utc"] == "2026-07-17"
    assert current["status"] == "active"
    assert current["activation_date_utc"] == "2026-07-18"
    assert current["supersedes_track_id"] == old["track_id"]

    candidates, batch = snapshot.load_plan_candidates(current)
    universe_registry = snapshot.panel_universe.load_registry()
    contract = snapshot.build_track_contract(
        current,
        candidates,
        batch,
        universe_registry=universe_registry,
        universe_registry_sha256=snapshot.file_sha256(snapshot.config.PANEL_UNIVERSE_REGISTRY),
        evaluator_bundle_fingerprint=None,
        low_vol_evaluator_fingerprint=snapshot.low_vol_evaluator_fingerprint(),
    )
    assert snapshot.payload_sha256(contract) == current["track_contract_sha256"]


def test_daily_shadow_snapshot_has_continuous_cost_decomposition_and_no_future_leak(monkeypatch):
    monkeypatch.setattr(snapshot.config, "PANEL_MIN_ASSETS", 3)
    as_of = pd.Timestamp("2026-07-01T23:00:00Z")
    tracking = {"tracking_registry_id": "tracking_test"}
    universe_registry = _universe_registry()
    candidate_batch = {"batch_id": "batch_test"}
    bundle = {"bundle_sha256": "bundle_hash"}
    plan = _contract_plan(
        _plan(),
        [_candidate()],
        candidate_batch,
        universe_registry=universe_registry,
        evaluator_bundle_fingerprint=bundle,
    )
    plan_input = [(plan, [_candidate()], candidate_batch)]
    kwargs = {
        "tracking_registry": tracking,
        "plan_inputs": plan_input,
        "as_of": as_of,
        "captured_at": pd.Timestamp("2026-07-02T00:20:00Z"),
        "universe_registry": universe_registry,
        "tracking_registry_sha256": "tracking_hash",
        "evaluator_code_sha256": "code_hash",
        "evaluator_bundle_fingerprint": bundle,
        "universe_registry_sha256": "universe_hash",
    }

    payload = snapshot.build_snapshot(_panel(), **kwargs)
    payload_with_future = snapshot.build_snapshot(_panel(include_future=True), **kwargs)

    assert payload == payload_with_future
    assert payload["day_complete"] is True
    assert payload["operational_evidence_eligible"] is True
    assert payload["formal_evidence_eligible"] is False
    assert payload["selection_feedback_allowed"] is False
    assert payload["holdout_feedback_allowed"] is False
    assert payload["active_plan_count"] == 1
    plan = payload["plans"][0]
    assert plan["promotion_eligible"] is False
    assert plan["contract_matches_registry"] is True
    assert plan["path_set_matches_contract"] is True
    assert plan["formal_promotion_evidence_eligible"] is False
    assert plan["path_count"] == 3
    for path in plan["paths"]:
        assert path["hour_count"] == 24
        assert path["observation_eligible"] is True
        assert path["return_evidence_complete_while_held"] is True
        assert path["weighted_missing_return_exposure_sum"] == 0.0
        assert len(path["hourly"]) == 24
        components = sum(
            row["gross_return"] - row["transaction_cost"] - row["funding_paid"]
            for row in path["hourly"]
        )
        assert path["daily_net_return"] == pytest.approx(components)
        assert all(row["timestamp_utc"] <= as_of.isoformat() for row in path["hourly"])


def test_factor_snapshot_is_append_only_and_hash_verifiable(tmp_path):
    payload = {
        "schema_version": 1,
        "snapshot_date_utc": "2026-07-01",
        "captured_at_utc": "2026-07-02T00:20:00+00:00",
        "as_of_bar_utc": "2026-07-01T23:00:00+00:00",
        "tracking_registry_id": "tracking_test",
        "active_plan_count": 0,
        "operational_evidence_eligible": False,
        "formal_evidence_eligible": True,
        "plans": [],
    }
    path, created = snapshot.write_snapshot_immutable(payload, snapshot_dir=tmp_path)
    recaptured = dict(payload, captured_at_utc="2026-07-02T00:25:00+00:00")
    same_path, created_again = snapshot.write_snapshot_immutable(recaptured, snapshot_dir=tmp_path)
    changed = dict(payload, active_plan_count=99)
    with pytest.raises(ValueError, match="factor_snapshot_recompute_conflict"):
        snapshot.write_snapshot_immutable(changed, snapshot_dir=tmp_path)

    manifest = json.loads((tmp_path / "manifest.jsonl").read_text(encoding="utf-8").strip())
    assert created is True
    assert created_again is False
    assert same_path == path
    assert (tmp_path / "conflicts.jsonl").exists()
    assert manifest["sha256"] == snapshot.payload_sha256(json.loads(path.read_text(encoding="utf-8")))


def test_shadow_path_invalidates_missing_return_while_position_is_held():
    index = pd.date_range("2026-07-01", periods=48, freq="h", tz="UTC")
    factor = pd.DataFrame({"A": -1.0, "B": 1.0}, index=index)
    returns = pd.DataFrame({"A": 0.001, "B": -0.001}, index=index)
    returns.loc[index[30], "A"] = float("nan")
    funding = pd.DataFrame(0.0, index=index, columns=["A", "B"])

    observation = snapshot._path_observation(
        factor,
        returns,
        funding,
        day_index=index[24:],
        min_assets=2,
        weighting_mode="rank_linear",
        rebalance_hours=24,
    )

    assert observation["active_bars"] == 24
    assert observation["missing_return_hours_while_held"] == 1
    assert observation["weighted_missing_return_exposure_sum"] > 0.0
    assert observation["return_evidence_complete_while_held"] is False
    assert observation["observation_eligible"] is False


def test_shadow_path_requires_full_day_of_active_exposure():
    index = pd.date_range("2026-07-01", periods=48, freq="h", tz="UTC")
    factor = pd.DataFrame({"A": -1.0, "B": 1.0}, index=index)
    factor.loc[index[24], :] = float("nan")
    returns = pd.DataFrame({"A": 0.001, "B": -0.001}, index=index)
    funding = pd.DataFrame(0.0, index=index, columns=["A", "B"])

    observation = snapshot._path_observation(
        factor,
        returns,
        funding,
        day_index=index[24:],
        min_assets=2,
        weighting_mode="rank_linear",
        rebalance_hours=1,
    )

    assert observation["active_bars"] == 23
    assert observation["observation_eligible"] is False


def test_low_vol_plan_loader_requires_a_strong_frozen_historical_path(tmp_path):
    batch = _low_vol_batch()
    batch_path = tmp_path / "batch.json"
    batch_path.write_text(json.dumps(batch), encoding="utf-8")
    candidate = _low_vol_candidate()
    report = {
        "batch_sha256": snapshot.file_sha256(batch_path),
        "paths": [
            {
                "path_id": candidate["candidate_id"],
                "candidate": candidate,
                "classification": {"status": "prospective_shadow_strong"},
                "holdout_accessed": True,
            }
        ],
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps({"schema_version": 1, "policy_id": "policy_test"}), encoding="utf-8")
    plan = {
        **_low_vol_plan(),
        "candidate_batch_path": batch_path.name,
        "candidate_batch_sha256": snapshot.file_sha256(batch_path),
        "historical_report_path": report_path.name,
        "historical_report_sha256": snapshot.file_sha256(report_path),
        "promotion_policy_sha256": snapshot.file_sha256(policy_path),
    }

    candidates, loaded_batch = snapshot.load_plan_candidates(plan, project_dir=tmp_path)

    assert candidates == [candidate]
    assert loaded_batch == batch
    report["paths"][0]["classification"]["status"] = "historical_factor_reject"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    plan["historical_report_sha256"] = snapshot.file_sha256(report_path)
    with pytest.raises(ValueError, match="historical_candidate_not_strong"):
        snapshot.load_plan_candidates(plan, project_dir=tmp_path)


def test_low_vol_plan_loader_rejects_changed_promotion_policy(tmp_path):
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps({"schema_version": 1, "policy_id": "policy_test"}), encoding="utf-8")
    plan = {**_low_vol_plan(), "promotion_policy_sha256": "0" * 64}
    with pytest.raises(ValueError, match="promotion_policy_sha256_mismatch"):
        snapshot.load_plan_candidates(plan, project_dir=tmp_path)


def test_low_vol_prospective_evidence_is_future_blind_and_charges_activation_entry():
    registry = _universe_registry()
    batch = _low_vol_batch()
    candidate = _low_vol_candidate()
    bundle = {"bundle_sha256": "bundle_hash"}
    plan = _contract_plan(
        _low_vol_plan(),
        [candidate],
        batch,
        universe_registry=registry,
        evaluator_bundle_fingerprint=bundle,
    )
    as_of = pd.Timestamp("2026-07-17T23:00:00Z")
    kwargs = {
        "plan": plan,
        "candidates": [candidate],
        "candidate_batch": batch,
        "as_of": as_of,
        "universe_registry": registry,
        "track_contract": snapshot.build_track_contract(
            plan,
            [candidate],
            batch,
            universe_registry=registry,
            universe_registry_sha256="universe_hash",
            evaluator_bundle_fingerprint=bundle,
        ),
    }

    evidence = snapshot.build_plan_evidence(_daily_spot_panel(), **kwargs)
    with_future = snapshot.build_plan_evidence(_daily_spot_panel(include_future=True), **kwargs)

    assert evidence == with_future
    assert evidence["operational_evidence_eligible"] is True
    assert evidence["formal_promotion_evidence_eligible"] is True
    assert evidence["path_set_matches_contract"] is True
    path = evidence["paths"][0]
    assert path["observation_eligible"] is True
    assert path["initial_entry_cost_charged"] is True
    assert path["turnover"] == pytest.approx(1.0)
    assert path["transaction_cost"] == pytest.approx(0.0007)
    assert path["net_return"] == pytest.approx(path["gross_return"] - path["transaction_cost"])
    assert path["execution_claim"] == "spot_return_factor_shadow_only"


def test_shadow_path_invalidates_missing_expected_funding_while_held():
    index = pd.date_range("2026-07-01", periods=48, freq="h", tz="UTC")
    factor = pd.DataFrame({"A": -1.0, "B": 1.0}, index=index)
    returns = pd.DataFrame({"A": 0.001, "B": -0.001}, index=index)
    funding = pd.DataFrame(0.0, index=index, columns=["A", "B"])
    funding.loc[index[32], "A"] = float("nan")

    observation = snapshot._path_observation(
        factor,
        returns,
        funding,
        day_index=index[24:],
        min_assets=2,
        weighting_mode="rank_linear",
        rebalance_hours=24,
    )

    assert observation["missing_expected_funding_asset_bars_while_held"] == 1
    assert observation["funding_evidence_complete_while_held"] is False
    assert observation["observation_eligible"] is False
