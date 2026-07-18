import panel_failure_analysis as failure_analysis


def test_failure_analysis_blocks_combo_without_panel_pass():
    batch = {
        "batch_id": "batch_unit",
        "candidates": [
            {
                "candidate_id": "ai_basis_001",
                "source_ids": ["PERP_FUNDING_BASIS"],
                "family": "carry",
                "panel_formula": "basis_carry",
                "weighting_modes": ["rank_linear"],
            }
        ],
    }
    report = {
        "created_at_utc": "20260705T000000Z",
        "pass_count": 0,
        "watchlist_count": 0,
        "candidate_factor_definition_count": 1,
        "factor_count": 41,
        "multiple_testing_trial_count": 99,
        "factors": [
            {
                "candidate_id": "ai_basis_001",
                "status": "panel_factor_reject",
                "failed_checks": ["multiple_testing_pass", "rolling_ic_stable"],
            }
        ],
    }
    trial_rows = [
        {"batch_id": "batch_unit", "candidate_id": "ai_basis_001", "event": "generated", "status": "accepted"},
        {
            "batch_id": "batch_unit",
            "candidate_id": "ai_basis_001",
            "event": "evaluated",
            "status": "panel_factor_reject",
        },
    ]

    analysis = failure_analysis.build_failure_analysis(batch=batch, report=report, trial_rows=trial_rows)

    assert analysis["combo_allowed"] is False
    assert analysis["trial_event_counts"]["generated"] == 1
    assert analysis["trial_event_counts"]["evaluated"] == 1
    assert analysis["failed_check_counts"]["multiple_testing_pass"] == 1
    assert "PERP_FUNDING_BASIS" in analysis["source_counts"]


def test_failure_analysis_treats_dsr_and_pbo_as_binding_trial_penalties():
    batch = {
        "batch_id": "overfit_unit",
        "candidates": [{
            "candidate_id": "candidate",
            "source_ids": ["BACKTEST_OVERFITTING_DSR_PBO"],
            "family": "test",
            "panel_formula": "momentum_7d",
            "weighting_modes": ["rank_linear"],
        }],
    }
    report = {
        "factors": [{
            "candidate_id": "candidate",
            "status": "panel_factor_reject",
            "failed_checks": ["deflated_sharpe_pass", "cscv_pbo_pass"],
        }],
    }

    analysis = failure_analysis.build_failure_analysis(batch=batch, report=report, trial_rows=[])

    assert analysis["failed_check_counts"]["deflated_sharpe_pass"] == 1
    assert analysis["recommendations"][0].startswith("keep candidate budget small")
