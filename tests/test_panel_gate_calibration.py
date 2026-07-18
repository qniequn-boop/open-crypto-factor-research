import numpy as np
import pandas as pd

import panel_gate_calibration as calibration


def test_daily_ic_inference_does_not_count_overlapping_hours_as_independent():
    rng = np.random.default_rng(7)
    daily_values = rng.normal(0.02, 0.12, size=120)
    hourly_values = np.repeat(daily_values, 24)
    index = pd.date_range("2026-01-01", periods=len(hourly_values), freq="h", tz="UTC")
    series = pd.Series(hourly_values, index=index)

    report = calibration.ic_inference_diagnostics(series)

    assert report["hourly_observations"] == 24 * 120
    assert report["daily_observations"] == 120
    assert report["overlap_warning"] is True
    assert abs(report["naive_hourly_tstat"]) > abs(report["daily_iid_tstat"]) * 4
    assert report["daily_hac"]["valid"] is True


def test_hac_inference_requires_enough_daily_observations():
    series = pd.Series([0.1, 0.2, 0.3], index=pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC"))

    result = calibration.newey_west_mean_tstat(series, max_lag=6)

    assert result["valid"] is False
    assert result["reason"] == "insufficient_daily_observations"


def test_null_simulation_is_far_less_likely_to_pass_than_strong_planted_ic():
    null = calibration.inference_power_simulation(mean_ic=0.0, replications=120)
    strong = calibration.inference_power_simulation(mean_ic=0.10, replications=120)

    assert null["pass_rate"] <= 0.05
    assert strong["pass_rate"] > null["pass_rate"] + 0.50


def test_empirical_block_calibration_controls_null_and_has_strong_signal_power():
    report = calibration.empirical_sidak_power_curve(
        mean_ics=(0.0, 0.10),
        calibration_replications=10000,
        evaluation_replications=4000,
        trial_count=10,
    )
    by_ic = {row["mean_ic"]: row for row in report["power_curve"]}

    assert report["calibration_outcome_blind"] is True
    assert by_ic[0.0]["pass_rate"] <= 0.012
    assert by_ic[0.10]["pass_rate"] >= 0.80
    assert report["critical_tstat"] > 2.0


def test_empirical_block_audit_separates_watchlist_clue_from_trial_adjusted_pass():
    series = calibration.simulate_daily_ic(
        seed=31,
        days=146,
        asset_count=40,
        mean_ic=0.05,
    )

    result = calibration.empirical_block_rank_ic_audit(
        series,
        trial_count=51,
        asset_count=40,
        null_replications=10000,
    )

    assert result["valid"] is True
    assert result["watchlist_critical_tstat"] < result["pass_critical_tstat"]
    assert result["holdout_used_for_calibration"] is False
    assert 0.0 < result["empirical_one_sided_p"] <= 1.0


def test_empirical_block_audit_marks_short_history_insufficient():
    series = pd.Series(
        np.linspace(-0.01, 0.02, 13),
        index=pd.date_range("2026-01-01", periods=13, freq="D", tz="UTC"),
    )

    result = calibration.empirical_block_rank_ic_audit(
        series,
        trial_count=10,
        asset_count=40,
        null_replications=1000,
    )

    assert result["valid"] is False
    assert result["block_count"] == 1
    assert result["reason"] == "fewer_than_three_nonoverlapping_blocks"
