import hashlib
import json

import pandas as pd

import panel_factor_research as panel


def test_rank_weights_are_cross_sectional_dollar_neutral():
    idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    factor = pd.DataFrame(
        {
            "A": [1.0, 3.0],
            "B": [2.0, 2.0],
            "C": [3.0, 1.0],
        },
        index=idx,
    )

    weights = panel._rank_weights(factor, min_assets=3)

    assert weights.sum(axis=1).abs().max() < 1e-12
    assert (weights.abs().sum(axis=1).round(12) == 1.0).all()
    assert weights.loc[idx[0], "C"] > 0
    assert weights.loc[idx[0], "A"] < 0
    assert weights.loc[idx[1], "A"] > 0
    assert weights.loc[idx[1], "C"] < 0


def test_top_bottom_weights_are_equal_weighted_by_side():
    idx = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    factor = pd.DataFrame(
        {
            "A": [1.0],
            "B": [2.0],
            "C": [3.0],
            "D": [4.0],
            "E": [5.0],
            "F": [6.0],
            "G": [7.0],
            "H": [8.0],
            "I": [9.0],
            "J": [10.0],
        },
        index=idx,
    )

    weights = panel._top_bottom_weights(factor, min_assets=8, quantile=0.30)

    assert weights.sum(axis=1).abs().max() < 1e-12
    assert (weights.abs().sum(axis=1).round(12) == 1.0).all()
    assert set(weights.loc[idx[0]][weights.loc[idx[0]] > 0].index) == {"H", "I", "J"}
    assert set(weights.loc[idx[0]][weights.loc[idx[0]] < 0].index) == {"A", "B", "C"}
    assert weights.loc[idx[0], "J"] == weights.loc[idx[0], "H"]


def test_rebalance_holds_weights_between_update_buckets():
    idx = pd.date_range("2026-01-01", periods=5, freq="h", tz="UTC")
    weights = pd.DataFrame({"A": [0.5, 0.4, 0.3, 0.2, 0.1], "B": [-0.5, -0.4, -0.3, -0.2, -0.1]}, index=idx)

    held = panel._apply_rebalance(weights, every_hours=2)

    assert held.iloc[0].to_dict() == weights.iloc[0].to_dict()
    assert held.iloc[1].to_dict() == weights.iloc[0].to_dict()
    assert held.iloc[2].to_dict() == weights.iloc[2].to_dict()
    assert held.iloc[3].to_dict() == weights.iloc[2].to_dict()


def test_cross_sectional_residual_removes_linear_exposure():
    idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    x = pd.DataFrame(
        {
            "A": [1.0, 2.0],
            "B": [2.0, 3.0],
            "C": [3.0, 4.0],
            "D": [4.0, 5.0],
        },
        index=idx,
    )
    y = 2.0 * x + pd.DataFrame(
        {
            "A": [0.1, -0.2],
            "B": [-0.1, 0.2],
            "C": [0.1, -0.2],
            "D": [-0.1, 0.2],
        },
        index=idx,
    )

    residual = panel._cross_sectional_residual(y, x, min_assets=4)

    for ts in idx:
        assert abs(residual.loc[ts].mean()) < 1e-12
        assert abs(residual.loc[ts].corr(x.loc[ts])) < 1e-12


def test_pct_change_does_not_pad_missing_prices():
    idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    prices = pd.DataFrame({"A": [100.0, None, 110.0]}, index=idx)

    returns = panel._pct_change(prices)

    assert pd.isna(returns.loc[idx[1], "A"])
    assert pd.isna(returns.loc[idx[2], "A"])


def test_daily_market_cap_events_receive_a_full_day_information_lag_without_gap_fill():
    hourly = pd.date_range("2026-01-01", periods=24 * 4, freq="h", tz="UTC")
    daily = pd.DataFrame(
        {"A": [100.0, 120.0]},
        index=pd.DatetimeIndex([hourly[0], hourly[48]]),
    )

    aligned = panel._lag_daily_events_to_intraday(daily, hourly, lag_days=1)

    assert pd.isna(aligned.loc[hourly[23], "A"])
    assert aligned.loc[hourly[24], "A"] == 100.0
    assert aligned.loc[hourly[47], "A"] == 100.0
    assert pd.isna(aligned.loc[hourly[48], "A"])
    assert aligned.loc[hourly[72], "A"] == 120.0


def test_factor_funding_uses_same_one_x_notional_basis_as_price_returns(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    weights = pd.DataFrame({"A": [1.0]}, index=idx)
    returns = pd.DataFrame({"A": [0.01]}, index=idx)
    funding = pd.DataFrame({"A": [0.001]}, index=idx)
    monkeypatch.setattr(panel.config, "LEVERAGE", 5)
    monkeypatch.setattr(panel.config, "COST_BPS", 0)
    monkeypatch.setattr(panel.config, "SLIPPAGE_BPS", 0)

    metrics = panel._portfolio_metrics_from_weights(weights, returns, funding, idx)

    assert abs(metrics["gross_return"] - 0.01) < 1e-12
    assert abs(metrics["funding_paid"] - 0.001) < 1e-12
    assert abs(metrics["total_return"] - 0.009) < 1e-12
    assert metrics["exposure_accounting"] == "factor_1x_notional_v2"


def test_portfolio_cost_includes_initial_entry(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    weights = pd.DataFrame({"A": [0.5, 0.5], "B": [-0.5, -0.5]}, index=idx)
    returns = pd.DataFrame(0.0, index=idx, columns=weights.columns)
    funding = returns.copy()
    monkeypatch.setattr(panel.config, "COST_BPS", 5)
    monkeypatch.setattr(panel.config, "SLIPPAGE_BPS", 2)

    metrics = panel._portfolio_metrics_from_weights(weights, returns, funding, idx)

    assert metrics["turnover"] == 0.5
    assert metrics["cost_paid"] == 0.0007
    assert metrics["total_return"] == -0.0007


def test_panel_as_of_cutoff_truncates_every_time_indexed_input():
    idx = pd.date_range("2026-01-01", periods=5, freq="h", tz="UTC")
    panel_data = {
        "A": {
            "ohlcv": pd.DataFrame({"close": range(5)}, index=idx),
            "spot_ohlcv": pd.DataFrame({"close": range(5)}, index=idx),
            "open_interest": pd.DataFrame({"open_interest_usd": range(5)}, index=idx),
            "market_cap": pd.DataFrame({"market_cap_usd": range(5)}, index=idx),
            "funding": pd.Series(range(5), index=idx),
            "instrument": {"state": "live"},
        }
    }

    result = panel._truncate_panel_as_of(panel_data, idx[2])

    for key in ("ohlcv", "spot_ohlcv", "open_interest", "market_cap", "funding"):
        assert result["A"][key].index.max() == idx[2]
    assert result["A"]["instrument"] == {"state": "live"}


def test_panel_input_fingerprint_changes_when_one_market_value_changes():
    idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    first = {
        "A": {
            "ohlcv": pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=idx),
            "spot_ohlcv": None,
            "funding": pd.Series([0.0], index=idx[:1]),
            "open_interest": None,
            "instrument": {"state": "live"},
            "asset_label": "l1",
        }
    }
    second = {"A": {**first["A"], "ohlcv": first["A"]["ohlcv"].copy()}}
    second["A"]["ohlcv"].loc[idx[1], "close"] = 2.5

    first_hash = panel._panel_input_fingerprint(first)
    second_hash = panel._panel_input_fingerprint(second)

    assert first_hash["panel_sha256"] != second_hash["panel_sha256"]
    assert first_hash["asset_sha256"]["A"] != second_hash["asset_sha256"]["A"]


def test_versioned_reaudit_contract_fails_closed_when_sample_or_trials_change(tmp_path):
    reference = {
        "created_at_utc": "20260701T000000Z",
        "candidate_batch_id": "batch_1",
        "multiple_testing_trial_count": 10,
        "time_ranges": {
            "IS": {"start": "2026-01-01 00:00:00+00:00", "end": "2026-01-02 00:00:00+00:00", "bars": 25},
            "Val": {"start": "2026-01-02 01:00:00+00:00", "end": "2026-01-03 00:00:00+00:00", "bars": 24},
            "Holdout": {"start": "2026-01-03 01:00:00+00:00", "end": "2026-01-04 00:00:00+00:00", "bars": 24},
        },
        "factors": [{"factor_name": "momentum_7d", "panel_formula": None, "weighting_mode": "rank_linear"}],
    }
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(reference), encoding="utf-8")
    contract = panel._load_reaudit_contract(path)
    current = {
        **reference,
        "multiple_testing_trial_count": 11,
        "time_ranges": {**reference["time_ranges"], "Holdout": {**reference["time_ranges"]["Holdout"], "bars": 23}},
    }

    panel._attach_reaudit_comparability(current, contract)

    audit = current["versioned_reaudit"]
    assert audit["input_contract_comparable"] is False
    assert set(audit["comparability_failures"]) == {
        "multiple_testing_trial_count_changed",
        "split_time_ranges_changed",
    }


def test_portfolio_metrics_expose_missing_returns_while_position_is_held():
    idx = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")
    weights = pd.DataFrame({"A": 0.5, "B": -0.5}, index=idx)
    returns = pd.DataFrame({"A": 0.001, "B": -0.001}, index=idx)
    returns.loc[idx[10], "A"] = float("nan")
    funding = pd.DataFrame(0.0, index=idx, columns=["A", "B"])

    metrics = panel._portfolio_metrics_from_weights(weights, returns, funding, idx)

    assert metrics["missing_return_asset_bars_while_held"] == 1
    assert metrics["missing_return_hours_while_held"] == 1
    assert metrics["weighted_missing_return_exposure_sum"] == 0.5
    assert metrics["weighted_missing_return_exposure_max"] == 0.5
    assert metrics["return_evidence_complete_while_held"] is False
    assert metrics["hourly_sharpe_status"] == "legacy_v1_diagnostic"


def test_portfolio_metrics_report_daily_aggregated_sharpe(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=24 * 10, freq="h", tz="UTC")
    weights = pd.DataFrame({"A": 0.5, "B": -0.5}, index=idx)
    daily_pattern = pd.Series([0.001, -0.0005] * 5, index=pd.date_range("2026-01-01", periods=10, freq="D", tz="UTC"))
    asset_return = daily_pattern.reindex(idx, method="ffill") / 24.0
    returns = pd.DataFrame({"A": asset_return, "B": -asset_return}, index=idx)
    funding = pd.DataFrame(0.0, index=idx, columns=["A", "B"])
    monkeypatch.setattr(panel.config, "COST_BPS", 0)
    monkeypatch.setattr(panel.config, "SLIPPAGE_BPS", 0)

    metrics = panel._portfolio_metrics_from_weights(weights, returns, funding, idx)
    expected_daily = panel.panel_overfit_audit.aggregate_daily_returns(
        (weights * returns).sum(axis=1)
    )

    assert metrics["daily_sharpe"] == panel.annualized_sharpe(expected_daily, 365)
    assert metrics["sharpe_primary_candidate_for_gate_v2"] == "daily_sharpe"


def test_basis_from_prices_does_not_pad_missing_spot():
    idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    perp = pd.DataFrame({"A": [101.0, 102.0, 103.0]}, index=idx)
    spot = pd.DataFrame({"A": [100.0, None, 100.0]}, index=idx)

    basis = panel._basis_from_prices(perp, spot)

    assert abs(basis.loc[idx[0], "A"] - 0.01) < 1e-12
    assert pd.isna(basis.loc[idx[1], "A"])
    assert abs(basis.loc[idx[2], "A"] - 0.03) < 1e-12


def test_liquidity_bucket_neutral_signal_demeans_within_bucket():
    idx = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    signal = pd.DataFrame(
        {"A": [1.0], "B": [3.0], "C": [10.0], "D": [14.0], "E": [20.0], "F": [26.0]},
        index=idx,
    )
    liquidity = pd.DataFrame(
        {"A": [1.0], "B": [2.0], "C": [3.0], "D": [4.0], "E": [5.0], "F": [6.0]},
        index=idx,
    )

    neutral = panel._liquidity_bucket_neutral_signal(signal, liquidity, min_assets=6, buckets=3)

    assert neutral.loc[idx[0], ["A", "B"]].sum() == 0.0
    assert neutral.loc[idx[0], ["C", "D"]].sum() == 0.0
    assert neutral.loc[idx[0], ["E", "F"]].sum() == 0.0
    assert neutral.loc[idx[0], "A"] < 0
    assert neutral.loc[idx[0], "F"] > 0


def test_candidate_liquidity_size_neutralization_is_applied():
    idx = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    liquidity = pd.DataFrame({"A": [1.0], "B": [2.0], "C": [3.0], "D": [4.0]}, index=idx)
    signal = 3.0 * liquidity + pd.DataFrame({"A": [0.1], "B": [-0.1], "C": [0.1], "D": [-0.1]}, index=idx)
    eligibility = pd.DataFrame(True, index=idx, columns=liquidity.columns)

    controlled = panel._apply_candidate_controls(
        signal,
        {"neutralization": "liquidity_size", "bucket_policy": "none"},
        eligibility=eligibility,
        liquidity_size=liquidity,
        min_assets=4,
    )

    assert abs(controlled.loc[idx[0]].corr(liquidity.loc[idx[0]])) < 1e-12


def test_candidate_large_liquid_policy_masks_smaller_assets():
    idx = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    columns = [f"A{i}" for i in range(10)]
    liquidity = pd.DataFrame([range(10)], index=idx, columns=columns, dtype=float)
    signal = pd.DataFrame(1.0, index=idx, columns=columns)
    eligibility = pd.DataFrame(True, index=idx, columns=columns)

    controlled = panel._apply_candidate_controls(
        signal,
        {"neutralization": "none", "bucket_policy": "large_liquid_only"},
        eligibility=eligibility,
        liquidity_size=liquidity,
        min_assets=4,
    )

    assert controlled.notna().sum(axis=1).iloc[0] == 8
    assert pd.isna(controlled.loc[idx[0], "A0"])
    assert controlled.loc[idx[0], "A9"] == 1.0


def test_trial_adjustment_penalizes_more_trials():
    few_trials = panel._trial_adjustment(ic_tstat=2.0, trial_count=1)
    many_trials = panel._trial_adjustment(ic_tstat=2.0, trial_count=100)

    assert few_trials["sidak_adjusted_p"] < many_trials["sidak_adjusted_p"]
    assert few_trials["raw_one_sided_p"] == many_trials["raw_one_sided_p"]


def _passing_splits():
    return {
        "IS": {"sharpe": 0.2, "total_return": 0.01, "max_drawdown": 0.05, "turnover": 0.01},
        "Val": {"sharpe": 1.0, "total_return": 0.02, "max_drawdown": 0.05, "turnover": 0.01},
        "Holdout": {"sharpe": 0.2, "total_return": 0.01, "max_drawdown": 0.05, "turnover": 0.01},
    }


def _passing_ic():
    return {
        "IS": {"mean_rank_ic": 0.01},
        "Val": {"mean_rank_ic": 0.03},
        "Holdout": {"mean_rank_ic": 0.01},
    }


def _passing_rolling():
    return {
        "window_count": 5,
        "positive_ic_windows": 4,
        "positive_sharpe_windows": 3,
        "min_rank_ic": -0.02,
        "min_sharpe": -1.0,
    }


def _passing_robustness():
    return {
        "large_liquid": {
            "splits": {
                "Val": {"rank_ic": {"observations": 100, "mean_rank_ic": 0.02}},
                "Holdout": {"rank_ic": {"observations": 100, "mean_rank_ic": 0.01}},
            }
        },
        "liquidity_buckets": {
            "buckets": {
                "low": {
                    "Val": {"rank_ic": {"mean_rank_ic": 0.01}},
                    "Holdout": {"rank_ic": {"mean_rank_ic": 0.01}},
                },
                "mid": {
                    "Val": {"rank_ic": {"mean_rank_ic": 0.02}},
                    "Holdout": {"rank_ic": {"mean_rank_ic": 0.02}},
                },
                "high": {
                    "Val": {"rank_ic": {"mean_rank_ic": -0.01}},
                    "Holdout": {"rank_ic": {"mean_rank_ic": -0.01}},
                },
            }
        },
        "asset_family_neutral": {
            "splits": {
                "Val": {"rank_ic": {"observations": 100, "mean_rank_ic": 0.02}},
                "Holdout": {"rank_ic": {"observations": 100, "mean_rank_ic": 0.01}},
            }
        },
        "crash_windows": {
            "window_count": 5,
            "negative_return_windows": 1,
            "worst_total_return": -0.02,
            "worst_max_drawdown": 0.08,
        },
    }


def test_factor_status_requires_robustness_gates_for_watchlist():
    status, checks = panel._factor_pass_status(
        _passing_splits(),
        _passing_ic(),
        {"IS": 8, "Val": 8, "Holdout": 8},
        _passing_rolling(),
        {"pass": False},
        {},
    )

    assert status == "panel_factor_reject"
    assert not checks["robust_large_liquid_val_ic_positive"]
    assert not checks["robust_crash_window_count"]


def test_factor_status_allows_watchlist_when_robustness_gates_pass():
    status, checks = panel._factor_pass_status(
        _passing_splits(),
        _passing_ic(),
        {"IS": 8, "Val": 8, "Holdout": 8},
        _passing_rolling(),
        {"pass": False},
        _passing_robustness(),
    )

    assert status == "panel_factor_watchlist"
    assert checks["robust_large_liquid_val_ic_positive"]
    assert checks["robust_bucket_val_not_single_bucket"]
    assert checks["robust_bucket_holdout_not_single_bucket"]
    assert checks["robust_family_neutral_val_ic_positive"]
    assert checks["robust_crash_loss_contained"]
    assert checks["robust_crash_not_mostly_negative"]


def test_factor_status_uses_registered_subpool_coverage_floor():
    status, checks = panel._factor_pass_status(
        _passing_splits(),
        _passing_ic(),
        {"IS": 8, "Val": 8, "Holdout": 8},
        _passing_rolling(),
        {"pass": False},
        _passing_robustness(),
        required_min_assets=8,
    )

    assert status == "panel_factor_watchlist"
    assert checks["coverage_ok"]


def test_survivor_conditioned_evidence_caps_pass_at_watchlist():
    status, checks = panel._apply_evidence_promotion_ceiling(
        "panel_factor_pass",
        {"val_ic_positive": True},
        {"formal_promotion_allowed": False},
    )

    assert status == "panel_factor_watchlist"
    assert checks["val_ic_positive"] is True
    assert checks["evidence_universe_formal_promotion_allowed"] is False


def test_formal_evidence_keeps_pass_status():
    status, checks = panel._apply_evidence_promotion_ceiling(
        "panel_factor_pass",
        {},
        {"formal_promotion_allowed": True},
    )

    assert status == "panel_factor_pass"
    assert checks["evidence_universe_formal_promotion_allowed"] is True


def test_oi_crowding_formulas_are_lagged_and_registered():
    assert panel.FACTOR_DEFINITIONS["oi_price_crowding_reversal"]["direction"] == -1
    assert panel.FACTOR_DEFINITIONS["oi_funding_crowding_reversal"]["direction"] == -1
    assert panel.FACTOR_DEFINITIONS["oi_change_7d"]["family"] == "open_interest"
    assert panel.FACTOR_DEFINITIONS["oi_price_crowding_reversal"]["deprecated_for_candidates"] is True
    assert panel.FACTOR_DEFINITIONS["oi_price_crowding_reversal_v2"]["candidate_direction"] == "short"


def test_candidate_loader_rejects_formula_direction_mismatch(tmp_path, monkeypatch):
    batch = {
        "batch_id": "direction_test",
        "candidates": [{
            "candidate_id": "wrong_basis_direction",
            "source_ids": ["PERP_FUNDING_BASIS"],
            "hypothesis": "Direction contract test.",
            "family": "carry",
            "required_fields": ["basis"],
            "panel_formula": "basis_carry",
            "direction": "long",
            "neutralization": "none",
            "bucket_policy": "none",
            "weighting_modes": ["rank_linear"],
            "generated_by": "test",
        }],
    }
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(batch), encoding="utf-8")
    monkeypatch.setattr(panel.candidate_registry, "append_trial_event", lambda *args, **kwargs: None)

    accepted, rejected, batch_id = panel._load_candidate_definitions(str(path))

    assert batch_id == "direction_test"
    assert accepted == []
    assert "formula_direction_mismatch:short" in rejected[0]["errors"]
    assert "formula_deprecated_for_candidates" in rejected[0]["errors"]


def test_factor_status_rejects_single_bucket_effect():
    robustness = _passing_robustness()
    for bucket in ("mid", "high"):
        robustness["liquidity_buckets"]["buckets"][bucket]["Val"]["rank_ic"]["mean_rank_ic"] = -0.01

    status, checks = panel._factor_pass_status(
        _passing_splits(),
        _passing_ic(),
        {"IS": 8, "Val": 8, "Holdout": 8},
        _passing_rolling(),
        {"pass": False},
        robustness,
    )

    assert status == "panel_factor_reject"
    assert not checks["robust_bucket_val_not_single_bucket"]


def test_asset_family_neutral_signal_excludes_singletons_and_demeans_groups():
    idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    factor = pd.DataFrame(
        {"A": [1.0, 2.0], "B": [3.0, 4.0], "C": [10.0, 20.0]},
        index=idx,
    )

    neutral, families = panel._asset_family_neutral_signal(
        factor,
        {"A": "l1", "B": "l1", "C": "singleton"},
    )

    assert families == {"l1": ["A", "B"]}
    assert neutral[["A", "B"]].sum(axis=1).abs().max() < 1e-12
    assert neutral["C"].isna().all()


def test_factor_status_rejects_family_driven_effect():
    robustness = _passing_robustness()
    robustness["asset_family_neutral"]["splits"]["Val"]["rank_ic"]["mean_rank_ic"] = -0.01

    status, checks = panel._factor_pass_status(
        _passing_splits(),
        _passing_ic(),
        {"IS": 8, "Val": 8, "Holdout": 8},
        _passing_rolling(),
        {"pass": False},
        robustness,
    )

    assert status == "panel_factor_reject"
    assert not checks["robust_family_neutral_val_ic_positive"]


def test_factor_status_rejects_uncontained_crash_loss():
    robustness = _passing_robustness()
    robustness["crash_windows"] = {
        "window_count": 5,
        "negative_return_windows": 4,
        "worst_total_return": -0.08,
        "worst_max_drawdown": 0.18,
    }

    status, checks = panel._factor_pass_status(
        _passing_splits(),
        _passing_ic(),
        {"IS": 8, "Val": 8, "Holdout": 8},
        _passing_rolling(),
        {"pass": False},
        robustness,
    )

    assert status == "panel_factor_reject"
    assert not checks["robust_crash_loss_contained"]
    assert not checks["robust_crash_not_mostly_negative"]


def test_evaluate_includes_preregistered_panel_candidate(tmp_path, monkeypatch):
    idx = pd.date_range("2026-01-01", periods=24 * 40, freq="h", tz="UTC")
    assets = [f"A{i}-USDT-SWAP" for i in range(8)]
    panel_data = {}
    for i, asset in enumerate(assets):
        close = pd.Series([100 + i + 0.01 * step for step in range(len(idx))], index=idx, dtype=float)
        ohlcv = pd.DataFrame(
            {
                "open": close.shift(1).bfill(),
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": 1000 + i,
                "vol_quote": close * (1000 + i),
            },
            index=idx,
        )
        spot = ohlcv.copy()
        spot["close"] = close * (1 - 0.0001 * (i + 1))
        funding = pd.Series(0.00001 * (i + 1), index=idx[::8])
        panel_data[asset] = {"ohlcv": ohlcv, "funding": funding, "spot_ohlcv": spot, "spot_error": None}

    monkeypatch.setattr(panel, "LOG_DIR", tmp_path)
    candidate = {
        "candidate_id": "cand_basis_001",
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
    panel.candidate_registry.append_trial_event(
        candidate,
        event="generated",
        status="accepted",
        log_dir=tmp_path,
    )
    trial_input_path = tmp_path / "panel_trial_registry.jsonl"
    trial_event_output_path = tmp_path / "evaluated_trial_events.jsonl"

    original_build_matrices = panel._build_matrices
    requested_names = {}

    def capture_requested_names(*args, **kwargs):
        requested_names["value"] = kwargs.get("requested_factor_names")
        return original_build_matrices(*args, **kwargs)

    monkeypatch.setattr(panel, "_build_matrices", capture_requested_names)

    report = panel._evaluate(
        panel_data,
        days=40,
        rebalance_hours=24,
        min_assets=8,
        candidate_definitions=[candidate],
        candidate_batch_id="batch_test",
        factor_scope="candidates_and_baselines",
        trial_registry_path=trial_input_path,
        trial_event_registry_path=trial_event_output_path,
    )

    rows = [row for row in report["factors"] if row["candidate_id"] == "cand_basis_001"]
    assert len(rows) == 1
    assert rows[0]["source_ids"] == ["PERP_FUNDING_BASIS"]
    assert rows[0]["panel_formula"] == "basis_carry"
    assert "baseline_comparison" in rows[0]
    assert "robustness" in rows[0]
    assert "large_liquid" in rows[0]["robustness"]
    assert "liquidity_buckets" in rows[0]["robustness"]
    assert "asset_family_neutral" in rows[0]["robustness"]
    assert "crash_windows" in rows[0]["robustness"]
    assert set(rows[0]["robustness"]["liquidity_buckets"]["buckets"]) == {"low", "mid", "high"}
    assert "Val" in rows[0]["robustness"]["large_liquid"]["splits"]
    assert report["candidate_factor_definition_count"] == 1
    assert report["factor_scope"] == "candidates_and_baselines"
    assert requested_names["value"] == set(panel.BASELINE_FACTOR_NAMES)
    assert report["evaluated_factor_definition_count"] == len(panel.BASELINE_FACTOR_NAMES) + 1
    assert report["factor_count"] == len(panel.BASELINE_FACTOR_NAMES) * len(panel.WEIGHTING_MODES) + 1
    assert report["trial_count_breakdown"]["rank_ic_signal_trial_count"] <= report["trial_count_breakdown"]["portfolio_path_trial_count"]
    assert report["trial_count_breakdown"]["v1_sidak_count_used"] == report["multiple_testing_trial_count"]
    assert report["overfit_audit"]["holdout_used_for_selection"] is False
    assert report["gate_policy_draft"]["status"] == "synthetically_calibrated_nonbinding_pending_prospective_evidence"
    archive = report["_selection_return_archive"]
    assert archive["holdout_included"] is False
    archived_dates = [date for path in archive["paths"].values() for date in path["dates"]]
    assert not archived_dates or max(archived_dates) <= archive["selection_end"]
    assert archive["observed_path_count"] == len(archive["paths"])
    assert archive["empty_path_count"] >= 0
    assert rows[0]["overfit_audit"]["holdout_used_for_selection"] is False
    assert rows[0]["checks"]["holdout_sharpe_positive"] is False
    assert rows[0]["checks"]["holdout_ic_positive"] is False
    assert rows[0]["gate_v2_draft"]["binding"] is False
    assert rows[0]["gate_v2_draft"]["classification"]["binding"] is False
    assert "dependence_aware_rank_ic" in rows[0]
    assert "empirical_block_audit" in rows[0]["dependence_aware_rank_ic"]["Val"]
    assert "dependence_aware_val_ic_clue" in rows[0]["gate_v2_draft"]["states"]
    assert "deflated_sharpe_pass" in rows[0]["gate_v2_draft"]["insufficient_evidence"]
    assert "cscv_pbo_pass" in rows[0]["gate_v2_draft"]["insufficient_evidence"]
    assert "deflated_sharpe_pass" in rows[0]["checks"]
    assert "cscv_pbo_pass" in rows[0]["checks"]
    json.dumps(report)
    assert (tmp_path / "panel_trial_registry.jsonl").exists()
    assert [
        json.loads(line)["event"]
        for line in trial_input_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] == ["generated"]
    assert [
        json.loads(line)["event"]
        for line in trial_event_output_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] == ["evaluated"]


def test_panel_overfit_attachment_ignores_holdout_returns(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=90, freq="D", tz="UTC")
    splits = {
        "IS": idx[:30],
        "Val": idx[30:60],
        "Holdout": idx[60:],
    }
    path_key = (("formula", "none", "none", 1), "rank_linear")
    captured = {}

    def fake_dsr(returns, **kwargs):
        captured["dsr"] = returns.copy()
        return {"valid": True, "passed": True}

    def fake_pbo(matrix, **kwargs):
        captured["pbo"] = matrix.copy()
        return {"valid": True, "passed": True, "pbo": 0.0}

    monkeypatch.setattr(panel.panel_overfit_audit, "deflated_sharpe_audit", fake_dsr)
    monkeypatch.setattr(panel.panel_overfit_audit, "cscv_pbo_audit", fake_pbo)
    rows = [{
        "_selection_path_key": path_key,
        "status": "panel_factor_pass",
        "checks": {},
        "failed_checks": [],
    }]
    selection_returns = {
        path_key: {
            "IS": pd.Series(0.001, index=splits["IS"]),
            "Val": pd.Series(0.002, index=splits["Val"]),
            "Holdout": pd.Series(999.0, index=splits["Holdout"]),
        }
    }

    result = panel._attach_panel_overfit_audits(
        rows,
        selection_returns,
        trial_count=10,
        split_indexes=splits,
    )

    assert captured["dsr"].index.max() == splits["Val"].max()
    assert captured["pbo"].index.max() == splits["Val"].max()
    assert captured["pbo"].to_numpy().max() < 999.0
    assert result["holdout_used_for_selection"] is False
    assert result["_selection_return_archive"]["holdout_included"] is False
    assert all("999" not in str(path) for path in result["_selection_return_archive"]["paths"].values())
    assert rows[0]["status"] == "panel_factor_pass"


def test_selection_return_archive_is_written_with_verifiable_hash(tmp_path):
    report = {
        "created_at_utc": "20260713T160000Z",
        "_selection_return_archive": {
            "schema_version": 1,
            "archive_type": "panel_selection_daily_net_returns",
            "selection_policy": "IS_and_Val_only",
            "holdout_included": False,
            "full_trial_count": 12,
            "selection_end": "2026-06-30 00:00:00+00:00",
            "observed_path_count": 1,
            "empty_path_count": 0,
            "paths": {
                "factor|rank_linear": {
                    "dates": ["2026-06-30T00:00:00+00:00"],
                    "net_returns": [0.001],
                }
            },
        },
    }

    archive_path = panel._persist_selection_return_archive(
        report,
        candidate_batch_id="batch_test",
        log_dir=tmp_path,
    )

    archive_bytes = archive_path.read_bytes()
    archive = json.loads(archive_bytes)
    metadata = report["selection_return_archive"]
    assert "_selection_return_archive" not in report
    assert archive["candidate_batch_id"] == "batch_test"
    assert archive["holdout_included"] is False
    assert metadata["path_count"] == 1
    assert metadata["sha256"] == hashlib.sha256(archive_bytes).hexdigest()
