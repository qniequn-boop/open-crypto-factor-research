import copy

import numpy as np
import pandas as pd

import data
import panel_factor_research as panel
import panel_universe


def _registry(asset_count=3, target_size=2):
    registry = copy.deepcopy(panel_universe.load_registry())
    registry["registry_id"] = "unit_test_universe"
    registry["construction"]["candidate_pool_size"] = asset_count
    registry["construction"]["survivorship_complete"] = True
    registry["assets"] = [
        {"inst_id": f"A{i}-USDT-SWAP", "base_asset": f"A{i}", "asset_family": "defi"}
        for i in range(asset_count)
    ]
    registry["point_in_time_rules"].update(
        {
            "target_size": target_size,
            "min_listing_age_days": 3,
            "min_observed_history_days": 1,
            "min_history_coverage_ratio": 0.90,
            "liquidity_lookback_days": 2,
            "liquidity_min_period_days": 1,
            "min_avg_daily_quote_volume_usd": 1,
            "selection_lag_hours": 1,
            "power_block_days": 1,
        }
    )
    return registry


def _panel_and_frames(periods=24 * 10):
    idx = pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC")
    assets = [f"A{i}-USDT-SWAP" for i in range(3)]
    close = pd.DataFrame({asset: 100.0 + i for i, asset in enumerate(assets)}, index=idx)
    vol_quote = pd.DataFrame(
        {
            assets[0]: 100.0,
            assets[1]: 90.0,
            assets[2]: 10.0,
        },
        index=idx,
    )
    old_listing = int(pd.Timestamp("2020-01-01", tz="UTC").timestamp() * 1000)
    items = {
        asset: {"instrument": {"list_time_ms": old_listing}, "asset_label": "defi"}
        for asset in assets
    }
    return idx, assets, items, close, vol_quote


def test_registry_is_valid_and_frozen_at_50_assets():
    registry = panel_universe.load_registry()

    assert panel_universe.validate_registry(registry) == []
    assert len(panel_universe.registry_inst_ids(registry)) == 50
    assert registry["construction"]["survivorship_complete"] is False
    assert registry["construction"]["prospective_start_utc"] == "2026-07-10T00:00:00Z"


def test_survivor_conditioned_history_has_watchlist_ceiling():
    index = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
    registry = _registry()
    registry["construction"]["survivorship_complete"] = False
    registry["construction"]["retrospective_mode"] = "survivor_conditioned_exploration"
    registry["construction"]["prospective_start_utc"] = "2026-07-10T00:00:00Z"

    policy = panel_universe.evidence_policy(index, registry)

    assert policy["mode"] == "survivor_conditioned_exploration"
    assert policy["promotion_ceiling"] == "panel_factor_watchlist"
    assert policy["formal_promotion_allowed"] is False


def test_frozen_universe_becomes_formal_for_prospective_sample():
    registry = _registry()
    registry["construction"]["survivorship_complete"] = False
    registry["construction"]["prospective_start_utc"] = "2026-07-10T00:00:00Z"
    index = pd.date_range("2026-07-11", periods=24, freq="h", tz="UTC")

    policy = panel_universe.evidence_policy(index, registry)

    assert policy["mode"] == "prospective_only"
    assert policy["promotion_ceiling"] == "panel_factor_pass"
    assert policy["formal_promotion_allowed"] is True


def test_point_in_time_liquidity_rank_uses_lagged_values():
    idx, assets, items, close, vol_quote = _panel_and_frames()
    vol_quote.loc[idx[-1], assets[2]] = 1_000_000_000.0

    result = panel_universe.build_point_in_time_eligibility(
        items,
        close,
        vol_quote,
        registry=_registry(),
    )

    assert result["eligibility"].loc[idx[-1], assets[0]]
    assert result["eligibility"].loc[idx[-1], assets[1]]
    assert not result["eligibility"].loc[idx[-1], assets[2]]

    vol_quote.loc[idx[-2], assets[2]] = 1_000_000_000.0
    updated = panel_universe.build_point_in_time_eligibility(
        items,
        close,
        vol_quote,
        registry=_registry(),
    )
    assert updated["eligibility"].loc[idx[-1], assets[2]]


def test_listing_age_and_missing_metadata_block_eligibility():
    idx, assets, items, close, vol_quote = _panel_and_frames()
    recent_listing = int((idx[-1] - pd.Timedelta(days=2)).timestamp() * 1000)
    items[assets[1]]["instrument"]["list_time_ms"] = recent_listing
    items[assets[2]]["instrument"] = None

    result = panel_universe.build_point_in_time_eligibility(
        items,
        close,
        vol_quote,
        registry=_registry(target_size=3),
    )

    assert result["eligibility"][assets[0]].iloc[-1]
    assert not result["eligibility"][assets[1]].any()
    assert not result["eligibility"][assets[2]].any()
    assert result["metadata_sources"][assets[2]] == "missing"


def test_open_interest_events_remain_sparse_in_panel_matrices():
    idx, assets, items, close, vol_quote = _panel_and_frames()
    panel_data = {}
    for asset in assets:
        ohlcv = pd.DataFrame(
            {
                "open": close[asset],
                "high": close[asset],
                "low": close[asset],
                "close": close[asset],
                "volume": 1.0,
                "vol_quote": vol_quote[asset],
            },
            index=idx,
        )
        spot = ohlcv.copy()
        oi = pd.DataFrame(
            {
                "open_interest_contracts": [1000.0],
                "open_interest_ccy": [100.0],
                "open_interest_usd": [1_000_000.0],
            },
            index=idx[:1],
        )
        panel_data[asset] = {
            "ohlcv": ohlcv,
            "funding": pd.Series(0.0001, index=idx[::8]),
            "spot_ohlcv": spot,
            "open_interest": oi,
            **items[asset],
        }

    matrices = panel._build_matrices(panel_data, universe_registry=_registry(target_size=3))

    assert int(matrices["open_interest_events"].notna().sum().sum()) == len(assets)
    assert matrices["open_interest"].loc[idx[24], assets[0]] == 1_000_000.0
    assert np.isnan(matrices["open_interest"].loc[idx[25], assets[0]])


def test_oi_factor_waits_for_seven_day_change_plus_publication_lag():
    idx, assets, items, close, vol_quote = _panel_and_frames(periods=24 * 12)
    panel_data = {}
    oi_index = idx[::24]
    for asset_number, asset in enumerate(assets):
        ohlcv = pd.DataFrame(
            {
                "open": close[asset],
                "high": close[asset],
                "low": close[asset],
                "close": close[asset] + np.arange(len(idx)) * (asset_number + 1) * 0.001,
                "volume": 1.0,
                "vol_quote": vol_quote[asset],
            },
            index=idx,
        )
        oi = pd.DataFrame(
            {
                "open_interest_contracts": np.arange(len(oi_index)) + 100.0,
                "open_interest_ccy": np.arange(len(oi_index)) + 10.0,
                "open_interest_usd": (np.arange(len(oi_index)) + 1000.0) * (asset_number + 1),
            },
            index=oi_index,
        )
        panel_data[asset] = {
            "ohlcv": ohlcv,
            "funding": pd.Series(0.0001, index=idx[::8]),
            "spot_ohlcv": ohlcv.copy(),
            "open_interest": oi,
            **items[asset],
        }

    matrices = panel._build_matrices(panel_data, universe_registry=_registry(target_size=3))
    oi_change = matrices["formula_library"]["oi_change_7d"][assets[0]]

    assert oi_change.first_valid_index() >= idx[24 * 8]
    assert pd.isna(oi_change.loc[idx[24 * 7]])


def test_open_interest_parser_sorts_and_deduplicates_without_padding():
    raw = [
        ["2000", "2", "0.2", "20"],
        ["1000", "1", "0.1", "10"],
        ["2000", "3", "0.3", "30"],
    ]

    frame = data._open_interest_to_df(raw)

    assert len(frame) == 2
    assert frame.index.is_monotonic_increasing
    assert frame.iloc[-1]["open_interest_usd"] == 20.0


def test_eligibility_summary_separates_warmup_from_analysis_period():
    idx, _, items, close, vol_quote = _panel_and_frames()
    universe = panel_universe.build_point_in_time_eligibility(
        items,
        close,
        vol_quote,
        registry=_registry(),
    )
    analysis_index = idx[-48:]
    summary = panel_universe.summarize_eligibility(
        universe,
        {"IS": analysis_index[:24], "Val": analysis_index[24:36], "Holdout": analysis_index[36:]},
    )

    assert summary["p10_eligible_assets"] == 2.0
    assert summary["full_timeline_including_warmup"]["zero_eligible_bars"] > 0
