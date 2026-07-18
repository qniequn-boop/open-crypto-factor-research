import copy

import pandas as pd
import numpy as np

import panel_data_audit as audit


def _test_registry(asset_count=30, survivorship_complete=True):
    registry = copy.deepcopy(audit.panel_universe.load_registry())
    registry["registry_id"] = "synthetic_test_registry"
    registry["construction"]["candidate_pool_size"] = asset_count
    registry["construction"]["survivorship_complete"] = survivorship_complete
    registry["assets"] = [
        {"inst_id": f"A{i}-USDT-SWAP", "base_asset": f"A{i}", "asset_family": "defi"}
        for i in range(asset_count)
    ]
    registry["point_in_time_rules"].update(
        {
            "target_size": asset_count,
            "min_listing_age_days": 1,
            "min_observed_history_days": 3,
            "min_history_coverage_ratio": 0.90,
            "liquidity_lookback_days": 3,
            "liquidity_min_period_days": 2,
            "min_avg_daily_quote_volume_usd": 1,
            "selection_lag_hours": 1,
            "power_block_days": 1,
        }
    )
    return registry


def _synthetic_panel(asset_count=30, periods=24 * 45, missing_spot=False):
    idx = pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC")
    out = {}
    for i in range(asset_count):
        asset = f"A{i}-USDT-SWAP"
        close = pd.Series(100 + i + 0.02 * np.arange(len(idx)), index=idx, dtype=float)
        if i == 0:
            close.iloc[24 * 20 : 24 * 20 + 24] *= 0.75
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
        spot = None
        if not missing_spot:
            spot = ohlcv.copy()
            spot["close"] = close * 0.999
        funding = pd.Series(0.00001 * (i + 1), index=idx[::8])
        open_interest = pd.DataFrame(
            {
                "open_interest_contracts": 1000 + i,
                "open_interest_ccy": 100 + i,
                "open_interest_usd": 1000000 + 1000 * i,
            },
            index=idx[::24],
        )
        market_cap = pd.DataFrame(
            {"market_cap_usd": 100000000 + 1000000 * i},
            index=idx[::24],
        )
        out[asset] = {
            "ohlcv": ohlcv,
            "funding": funding,
            "spot_ohlcv": spot,
            "spot_error": None,
            "open_interest": open_interest,
            "open_interest_error": None,
            "market_cap": market_cap,
            "market_cap_error": None,
            "instrument": {"list_time_ms": 1577836800000, "state": "live"},
            "instrument_error": None,
            "asset_label": "defi",
        }
    return out


def test_data_audit_reports_complete_coverage_on_synthetic_panel(monkeypatch):
    monkeypatch.setattr(audit.config, "PANEL_MIN_ASSETS", 8)
    report = audit.build_data_audit(
        _synthetic_panel(),
        [],
        days=45,
        min_assets=8,
        registry=_test_registry(),
    )

    assert report["loaded_asset_count"] == 30
    assert report["global_coverage"]["basis_coverage"] > 0.99
    assert report["global_coverage"]["open_interest"]["coverage"] > 0.95
    assert report["canonical_replication_readiness"]["market_cap_data_ready"] is True
    assert report["large_liquid_subset"]["median_assets_available"] == 8
    assert len(report["crash_windows"]) >= 1
    assert report["batch1_allowed"] is False
    assert "survivorship_archive_incomplete" not in report["failed_reasons"]


def test_data_audit_fails_when_basis_missing(monkeypatch):
    monkeypatch.setattr(audit.config, "PANEL_MIN_ASSETS", 8)
    report = audit.build_data_audit(
        _synthetic_panel(missing_spot=True),
        [],
        days=45,
        min_assets=8,
        registry=_test_registry(),
    )

    assert report["global_coverage"]["basis_coverage"] == 0.0
    assert report["data_audit_pass_for_batch1"] is False
    assert "basis_coverage_below_85pct" in report["failed_reasons"]


def test_split_coverage_reports_funding_events(monkeypatch):
    monkeypatch.setattr(audit.config, "PANEL_MIN_ASSETS", 8)
    report = audit.build_data_audit(
        _synthetic_panel(),
        [],
        days=45,
        min_assets=8,
        registry=_test_registry(),
    )

    assert set(report["split_coverage"]) == {"IS", "Val", "Holdout"}
    assert all(split["funding_event_count"] > 0 for split in report["split_coverage"].values())


def test_survivor_conditioned_registry_blocks_batch1(monkeypatch):
    monkeypatch.setattr(audit.config, "PANEL_MIN_ASSETS", 8)
    report = audit.build_data_audit(
        _synthetic_panel(),
        [],
        days=45,
        min_assets=8,
        registry=_test_registry(survivorship_complete=False),
    )

    assert report["batch1_allowed"] is False
    assert report["retrospective_exploration_allowed"] is report["data_substrate_v2_pass"]
    assert report["formal_promotion_allowed"] is False
    assert report["evidence_policy"]["promotion_ceiling"] == "panel_factor_watchlist"
    assert "survivorship_archive_incomplete" in report["failed_reasons"]


def test_data_audit_skips_expensive_factor_construction(monkeypatch):
    monkeypatch.setattr(audit.config, "PANEL_MIN_ASSETS", 8)
    monkeypatch.setattr(
        audit.panel_research,
        "_cross_sectional_residual",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("factor path should not run")),
    )

    report = audit.build_data_audit(
        _synthetic_panel(),
        [],
        days=45,
        min_assets=8,
        registry=_test_registry(),
    )

    assert report["loaded_asset_count"] == 30
