import json

import panel_reaudit_compare as compare


def _report(value=1.0):
    split = {
        "bars": 24,
        "sharpe": value,
        "gross_sharpe": value,
        "total_return": value / 100,
        "gross_return": value / 100,
        "max_drawdown": 0.01,
        "turnover": 0.02,
        "cost_paid": 0.001,
        "funding_paid": 0.0,
        "funding_abs_paid": 0.0,
        "avg_gross_exposure": 1.0,
        "active_bars": 24,
    }
    return {
        "candidate_batch_id": "batch",
        "multiple_testing_trial_count": 10,
        "time_ranges": {"IS": {"bars": 1}, "Val": {"bars": 1}, "Holdout": {"bars": 1}},
        "factors": [{
            "name": "candidate__rank_linear",
            "candidate_id": "candidate",
            "factor_name": "candidate",
            "panel_formula": "momentum_7d",
            "weighting_mode": "rank_linear",
            "status": "panel_factor_reject",
            "rank_ic": {"Val": {"mean_rank_ic": 0.01}},
            "long_short": {name: split for name in ("IS", "Val", "Holdout")},
            "rolling_90d": {"window_count": 1, "rows": []},
            "trial_adjustment": {"pass": False},
            "gate_v2_draft": {"classification": {"status": "panel_factor_watchlist"}},
        }],
    }


def test_gate_only_comparison_ignores_new_diagnostic_fields(tmp_path):
    old = _report()
    new = _report()
    new["factors"][0]["long_short"]["Val"]["daily_sharpe"] = 123.0
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(old), encoding="utf-8")
    new_path.write_text(json.dumps(new), encoding="utf-8")

    result = compare.compare_reports(old_path, new_path)

    assert result["structural_contract_match"] is True
    assert result["exact_legacy_economic_output_match"] is True
    assert result["gate_only_reaudit_interpretation_allowed"] is True


def test_gate_only_comparison_fails_when_legacy_economics_change(tmp_path):
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(_report(1.0)), encoding="utf-8")
    new_path.write_text(json.dumps(_report(2.0)), encoding="utf-8")

    result = compare.compare_reports(old_path, new_path)

    assert result["exact_legacy_economic_output_match"] is False
    assert result["changed_legacy_paths"] == ["candidate__rank_linear"]
    assert result["gate_only_reaudit_interpretation_allowed"] is False
