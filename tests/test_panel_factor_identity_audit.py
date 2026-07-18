import numpy as np
import pandas as pd

import panel_factor_identity_audit as identity


def test_ols_hac_audit_recovers_known_alpha_and_market_beta():
    rng = np.random.default_rng(20260717)
    index = pd.date_range("2025-01-01", periods=500, freq="D", tz="UTC")
    market = pd.Series(rng.normal(0.0, 0.012, len(index)), index=index)
    noise = pd.Series(rng.normal(0.0, 0.001, len(index)), index=index)
    target = 0.0004 + 1.35 * market + noise

    report = identity.ols_hac_audit(
        target,
        market.to_frame("market"),
        max_lag=7,
        periods_per_year=365,
    )

    assert report["valid"] is True
    assert abs(report["coefficients"]["market"]["estimate"] - 1.35) < 0.02
    assert abs(report["coefficients"]["alpha"]["estimate"] - 0.0004) < 0.0002
    assert report["r_squared"] > 0.99


def test_fama_macbeth_audit_recovers_conditional_low_vol_slope():
    rng = np.random.default_rng(20260718)
    formation_times = pd.date_range("2023-01-31", periods=24, freq="ME", tz="UTC")
    assets = [f"A{i:02d}" for i in range(30)]
    low_vol = pd.DataFrame(
        rng.normal(size=(len(formation_times), len(assets))),
        index=formation_times,
        columns=assets,
    )
    size = pd.DataFrame(
        rng.normal(size=low_vol.shape),
        index=formation_times,
        columns=assets,
    )
    noise = pd.DataFrame(
        rng.normal(0.0, 0.002, size=low_vol.shape),
        index=formation_times,
        columns=assets,
    )
    forward_returns = 0.025 * low_vol + 0.015 * size + noise
    scope = pd.DataFrame(True, index=formation_times, columns=assets)

    report = identity.fama_macbeth_audit(
        forward_returns,
        {"low_vol": low_vol, "size": size},
        scope,
        formation_times,
        minimum_assets=20,
        max_lag=2,
    )

    assert report["valid"] is True
    assert report["formation_count"] == len(formation_times)
    low_vol_result = report["coefficient_summary"]["low_vol"]
    assert low_vol_result["mean_monthly_coefficient"] > 0.02
    assert low_vol_result["positive_fraction"] == 1.0
    assert low_vol_result["newey_west"]["tstat"] > 10.0


def test_cross_sectional_residualization_removes_control_exposure():
    rng = np.random.default_rng(20260719)
    formation_times = pd.date_range("2025-01-31", periods=6, freq="ME", tz="UTC")
    assets = [f"A{i:02d}" for i in range(30)]
    control = pd.DataFrame(
        rng.normal(size=(len(formation_times), len(assets))),
        index=formation_times,
        columns=assets,
    )
    independent = pd.DataFrame(
        rng.normal(size=control.shape),
        index=formation_times,
        columns=assets,
    )
    target = 2.5 * control + independent
    scope = pd.DataFrame(True, index=formation_times, columns=assets)

    residual = identity.residualize_cross_sectionally(
        target,
        {"size": control},
        scope,
        minimum_assets=20,
    )

    for timestamp in formation_times:
        correlation = residual.loc[timestamp].corr(control.loc[timestamp])
        assert abs(correlation) < 1e-12
        assert abs(float(residual.loc[timestamp].mean())) < 1e-12


def test_pnl_frame_charges_initial_entry_and_rebalance_cost():
    index = pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC")
    weights = pd.DataFrame(
        [[0.5, -0.5], [0.5, -0.5], [-0.5, 0.5]],
        index=index,
        columns=["A", "B"],
    )
    returns = pd.DataFrame(
        [[0.02, -0.01], [0.0, 0.0], [0.01, -0.02]],
        index=index,
        columns=["A", "B"],
    )

    frame = identity._pnl_frame(weights, returns, index, cost_rate=0.001)

    assert frame["turnover"].tolist() == [1.0, 0.0, 2.0]
    assert np.allclose(frame["gross"], [0.015, 0.0, -0.015])
    assert np.allclose(frame["cost"], [0.001, 0.0, 0.002])
    assert np.allclose(frame["net"], [0.014, 0.0, -0.017])
