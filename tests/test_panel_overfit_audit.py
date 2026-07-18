import numpy as np
import pandas as pd

import panel_overfit_audit as audit


def test_aggregate_daily_returns_uses_utc_days():
    idx = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")
    result = audit.aggregate_daily_returns(pd.Series(0.001, index=idx))

    assert len(result) == 2
    assert np.allclose(result.to_numpy(), [0.024, 0.024])


def test_dsr_gets_stricter_as_trial_count_grows():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=500, freq="D", tz="UTC")
    returns = pd.Series(0.001 + rng.normal(0.0, 0.01, len(idx)), index=idx)
    trial_sharpes = [-0.08, -0.03, 0.01, 0.04, 0.09]

    few = audit.deflated_sharpe_audit(returns, n_trials=2, observed_trial_sharpes=trial_sharpes)
    many = audit.deflated_sharpe_audit(returns, n_trials=200, observed_trial_sharpes=trial_sharpes)

    assert few["valid"] and many["valid"]
    assert few["expected_maximum_sharpe"] < many["expected_maximum_sharpe"]
    assert few["p_value"] < many["p_value"]


def test_dsr_rejects_short_or_constant_samples():
    idx = pd.date_range("2026-01-01", periods=20, freq="D", tz="UTC")
    result = audit.deflated_sharpe_audit(
        pd.Series(0.0, index=idx),
        n_trials=10,
        observed_trial_sharpes=[-0.1, 0.1],
    )

    assert not result["valid"]
    assert not result["passed"]


def test_cscv_pbo_detects_regime_selected_winners():
    rng = np.random.default_rng(11)
    idx = pd.date_range("2024-01-01", periods=400, freq="D", tz="UTC")
    values = rng.normal(0.0, 0.01, (len(idx), 8))
    for segment in range(8):
        start = segment * 50
        values[start:start + 50, segment] += 0.004
    matrix = pd.DataFrame(values, index=idx, columns=[f"s{i}" for i in range(8)])

    result = audit.cscv_pbo_audit(matrix, n_splits=8)

    assert result["valid"]
    assert result["combination_count"] == 70
    assert 0.0 <= result["pbo"] <= 1.0
    assert result["pbo"] > 0.20


def test_cscv_never_accepts_one_strategy_as_complete_evidence():
    idx = pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC")
    result = audit.cscv_pbo_audit(pd.DataFrame({"only": np.linspace(-0.01, 0.01, 100)}, index=idx))

    assert not result["valid"]
    assert result["reason"] == "fewer_than_two_strategy_paths"
