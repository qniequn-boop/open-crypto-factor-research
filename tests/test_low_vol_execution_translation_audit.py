import numpy as np
import pandas as pd

import low_vol_execution_translation_audit as audit


def test_daily_targets_map_to_intraday_without_changing_the_frozen_lag():
    daily = pd.date_range("2026-01-31", periods=3, freq="D", tz="UTC")
    hourly = pd.date_range("2026-02-01", periods=25, freq="h", tz="UTC")
    weights = pd.DataFrame({"A": [0.0, 0.5, -0.5]}, index=daily)

    translated = audit._daily_targets_to_intraday(weights, hourly)

    assert translated.loc[pd.Timestamp("2026-02-01T00:00:00Z"), "A"] == 0.5
    assert translated.loc[pd.Timestamp("2026-02-01T23:00:00Z"), "A"] == 0.5
    assert translated.loc[pd.Timestamp("2026-02-02T00:00:00Z"), "A"] == -0.5


def test_perpetual_metrics_debit_positive_funding_from_long_and_credit_short():
    index = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    weights = pd.DataFrame({"LONG": 0.5, "SHORT": -0.5}, index=index)
    returns = pd.DataFrame(0.0, index=index, columns=weights.columns)
    funding = pd.DataFrame(np.nan, index=index, columns=weights.columns)
    funding.loc[index[1], "LONG"] = 0.001
    funding.loc[index[1], "SHORT"] = 0.002

    result = audit._portfolio_metrics(
        weights,
        returns,
        funding,
        index,
        one_way_cost_bps=0.0,
    )

    assert result["funding_paid_by_long_leg"] == 0.0005
    assert result["funding_paid_by_short_leg"] == -0.001
    assert result["net_funding_cost"] == -0.0005
    assert result["arithmetic_net_return"] == 0.0005


def test_missing_return_while_held_fails_closed():
    index = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    weights = pd.DataFrame({"A": [0.5, 0.5]}, index=index)
    returns = pd.DataFrame({"A": [0.01, np.nan]}, index=index)
    funding = pd.DataFrame({"A": [np.nan, np.nan]}, index=index)

    result = audit._portfolio_metrics(
        weights,
        returns,
        funding,
        index,
        one_way_cost_bps=0.0,
    )

    assert result["return_evidence_complete_while_held"] is False
    assert result["missing_return_asset_bars_while_held"] == 1


def test_funding_coverage_rejects_a_missing_settlement_gap():
    index = pd.date_range("2026-01-01", periods=25, freq="h", tz="UTC")
    weights = pd.DataFrame({"A": 0.5}, index=index)
    complete_events = pd.Series(
        [0.001, 0.001, 0.001, 0.001],
        index=index[[0, 8, 16, 24]],
        name="funding_rate",
    )
    missing_events = complete_events.drop(index[8])

    complete = audit._funding_coverage_audit(
        weights,
        {"A": {"funding": complete_events}},
        maximum_event_gap_hours=8.0,
    )
    missing = audit._funding_coverage_audit(
        weights,
        {"A": {"funding": missing_events}},
        maximum_event_gap_hours=8.0,
    )

    assert complete["complete"] is True
    assert missing["complete"] is False


def test_classification_preserves_reject_watchlist_and_paper_design_layers():
    all_pass = {
        "return_evidence_complete": True,
        "funding_evidence_complete": True,
        "full_period_net_positive": True,
        "post_source_noncollapse": True,
        "double_cost_net_positive": True,
        "drawdown_within_limit": True,
        "spot_perpetual_tracking_consistent": True,
        "current_100u_order_feasibility": True,
    }
    watch = dict(all_pass, double_cost_net_positive=False)
    reject = dict(all_pass, full_period_net_positive=False)

    assert audit._classify(all_pass)["status"] == "execution_translation_pass_for_paper_design"
    assert audit._classify(watch)["status"] == "execution_translation_watchlist"
    assert audit._classify(reject)["status"] == "execution_translation_reject"


def test_current_100u_order_diagnostic_uses_contract_value_and_lot_size():
    weights = pd.Series({"BTC-USDT-SWAP": 0.5, "ETH-USDT-SWAP": -0.5})
    prices = pd.Series({"BTC-USDT-SWAP": 100000.0, "ETH-USDT-SWAP": 4000.0})
    specs = [
        {
            "instId": "BTC-USDT-SWAP",
            "ctVal": "0.01",
            "ctValCcy": "BTC",
            "minSz": "0.01",
            "lotSz": "0.01",
        },
        {
            "instId": "ETH-USDT-SWAP",
            "ctVal": "0.1",
            "ctValCcy": "ETH",
            "minSz": "0.01",
            "lotSz": "0.01",
        },
    ]

    result = audit._current_order_feasibility(
        weights,
        prices,
        specs,
        capital_usdt=100.0,
        maximum_notional_error_fraction=0.25,
    )

    assert result["active_legs"] == 2
    assert result["spec_complete_legs"] == 2
    assert result["feasible_fraction"] == 1.0
    assert result["current_snapshot_only"] is True
