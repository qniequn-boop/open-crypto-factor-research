import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cost_and_horizon_policy_is_factory_wide_and_factor_neutral():
    policy = json.loads(
        (ROOT / "ECONOMIC_COST_AND_HORIZON_POLICY_V1.json").read_text(encoding="utf-8")
    )
    scope = policy["scope"]
    neutrality = policy["factor_neutrality"]
    low_vol = policy["frozen_90_day_low_volatility_track"]

    assert scope["system_wide"] is True
    assert scope["factor_specific_calibration"] is False
    assert neutrality[
        "all_factors_use_same_cost_surface_for_same_asset_notional_regime_and_order_type"
    ] is True
    assert neutrality["asset_or_date_selection_may_depend_on_named_factor"] is False
    assert neutrality["cost_assumptions_may_be_tuned_to_make_a_factor_pass"] is False
    assert neutrality["horizon_assumptions_may_be_tuned_to_make_a_factor_pass"] is False
    assert low_vol["is_calibration_target"] is False
    assert low_vol["has_priority_over_other_factors"] is False
    assert low_vol["may_change_signal_or_prospective_contract"] is False


def test_l2_contract_consumes_shared_policy_without_privileging_a_factor():
    contract = json.loads(
        (ROOT / "OKX_L2_REGIME_SAMPLE_V1.json").read_text(encoding="utf-8")
    )
    scope = contract["economic_scope"]

    assert scope["policy_id"] == "factory_wide_economic_cost_and_horizon_v1_20260718"
    assert scope["system_wide_cost_calibration"] is True
    assert scope["factor_specific_calibration"] is False
    assert scope["frozen_90_day_low_volatility_is_calibration_target"] is False
    assert "daily" in scope["horizon_reporting_buckets"]
    assert "weekly" in scope["horizon_reporting_buckets"]
    assert "monthly" in scope["horizon_reporting_buckets"]
