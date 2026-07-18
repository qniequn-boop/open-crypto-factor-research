import panel_gate_synthetic_calibration as calibration


def test_strong_planted_alpha_can_pass_both_full_and_large_liquid_scopes():
    null_stats = calibration.inference.simulate_nonoverlapping_block_tstats(
        mean_ic=0.0, replications=5000, seed=1
    )
    pass_critical = float(calibration.np.quantile(null_stats, 0.995, method="higher"))
    watch_critical = float(calibration.np.quantile(null_stats, 0.90, method="higher"))

    full = calibration.simulate_gate_decision(
        seed=10,
        target_ic=0.20,
        scope="full_panel",
        pass_critical_tstat=pass_critical,
        watchlist_critical_tstat=watch_critical,
    )
    large = calibration.simulate_gate_decision(
        seed=11,
        target_ic=0.25,
        scope="large_liquid_only",
        pass_critical_tstat=pass_critical,
        watchlist_critical_tstat=watch_critical,
    )

    assert full["draft_status"] in {"panel_factor_watchlist", "panel_factor_pass"}
    assert large["draft_status"] in {"panel_factor_watchlist", "panel_factor_pass"}
    assert full["statistical_clue"] is True
    assert large["statistical_clue"] is True
    assert "deflated_sharpe_pass" in full
    assert "cscv_pbo_pass" in full


def test_small_synthetic_calibration_reports_null_and_planted_rows():
    report = calibration.run_synthetic_calibration(
        replications=4,
        target_ics=(0.0, 0.10),
        scopes=("full_panel",),
        signal_trial_count=10,
        stress_scenarios=(),
    )

    assert len(report["rows"]) == 2
    assert report["rows"][0]["target_ic"] == 0.0
    assert report["rows"][1]["target_ic"] == 0.10
    assert len(report["rows"][0]["screened_watchlist_or_pass_rate_wilson95"]) == 2
    assert "dsr_pass_rate" in report["rows"][0]
    assert "cscv_pbo_pass_rate" in report["rows"][0]
    assert report["overfit_gates_simulated"] == ["deflated_sharpe_pass", "cscv_pbo_pass"]
    assert "calibration_assessment" in report
    assert "gate_blocker_rates" in report["rows"][0]


def test_stress_scenarios_are_reported_separately():
    report = calibration.run_synthetic_calibration(
        replications=2,
        target_ics=(0.05,),
        scopes=("full_panel",),
        signal_trial_count=6,
        stress_scenarios=("regime_decay", "funding_stress", "basis_sparse"),
    )

    assert [row["row_type"] for row in report["rows"]] == ["power_curve", "stress", "stress", "stress"]
    assert {row["scenario"] for row in report["rows"]} == {
        "stationary_complete",
        "regime_decay",
        "funding_stress",
        "basis_sparse",
    }


def test_zero_successes_do_not_claim_zero_upper_false_positive_rate():
    lower, upper = calibration._wilson_interval(0, 100)

    assert lower == 0.0
    assert 0.03 < upper < 0.04
