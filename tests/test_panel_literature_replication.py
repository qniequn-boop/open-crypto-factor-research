import numpy as np
import pandas as pd

import panel_literature_replication as replication
import panel_factor_research as panel


def test_literature_weights_are_30_40_30_value_weighted_and_dollar_neutral():
    ts = pd.DatetimeIndex([pd.Timestamp("2026-01-05T00:00:00Z")])
    columns = [f"A{i}" for i in range(10)]
    signal = pd.DataFrame([range(10)], index=ts, columns=columns, dtype=float)
    caps = pd.DataFrame([np.arange(1, 11)], index=ts, columns=columns, dtype=float)
    mask = pd.DataFrame(True, index=ts, columns=columns)

    weights, coverage = replication._value_weighted_30_40_30_weights(
        signal,
        caps,
        mask,
        min_assets=10,
        side_fraction=0.30,
    )

    row = weights.loc[ts[0]]
    assert (row > 0).sum() == 3
    assert (row < 0).sum() == 3
    assert (row == 0).sum() == 4
    assert abs(row[row > 0].sum() - 0.5) < 1e-12
    assert abs(row[row < 0].sum() + 0.5) < 1e-12
    assert row["A9"] > row["A8"] > row["A7"]
    assert coverage["valid_formation_count"] == 1


def test_weekly_weights_execute_one_bar_late_and_hold_for_one_week():
    index = pd.date_range("2026-01-05", periods=24 * 8, freq="h", tz="UTC")
    formation = pd.DataFrame({"A": [0.5], "B": [-0.5]}, index=index[:1])

    held = replication._execute_and_hold(
        formation,
        index,
        execution_lag_bars=1,
        holding_hours=168,
    )

    assert held.iloc[0].abs().sum() == 0.0
    assert held.iloc[1]["A"] == 0.5
    assert held.iloc[168]["A"] == 0.5
    assert held.iloc[169].abs().sum() == 0.0


def test_above_median_scope_is_point_in_time():
    formation = pd.date_range("2026-01-05", periods=2, freq="7D", tz="UTC")
    columns = ["A", "B", "C", "D"]
    eligibility = pd.DataFrame(True, index=formation, columns=columns)
    caps = pd.DataFrame([[1, 2, 3, 4], [4, 3, 2, 1]], index=formation, columns=columns)

    mask = replication._scope_mask(
        eligibility,
        caps,
        formation,
        "above_median_point_in_time_market_cap_within_registered_panel",
    )

    assert set(mask.columns[mask.iloc[0]]) == {"C", "D"}
    assert set(mask.columns[mask.iloc[1]]) == {"A", "B"}


def test_replication_loader_can_skip_unrequired_spot_and_open_interest(monkeypatch):
    index = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    ohlcv = pd.DataFrame(
        {
            "open": [1.0, 1.0],
            "high": [1.0, 1.0],
            "low": [1.0, 1.0],
            "close": [1.0, 1.0],
            "volume": [1.0, 1.0],
            "vol_quote": [1.0, 1.0],
        },
        index=index,
    )
    funding = pd.Series([0.001], index=index[:1], name="funding_rate")
    market_cap = pd.DataFrame({"market_cap_usd": [100.0]}, index=index[:1])
    instruments = pd.DataFrame(
        {
            "state": ["live"],
            "list_time_ms": [int(pd.Timestamp("2020-01-01", tz="UTC").timestamp() * 1000)],
            "list_time": [pd.Timestamp("2020-01-01", tz="UTC")],
            "settle_ccy": ["USDT"],
            "contract_value": [1.0],
            "contract_value_ccy": ["A"],
            "fetched_at_utc": [pd.Timestamp("2026-01-01", tz="UTC")],
        },
        index=pd.Index(["A-USDT-SWAP"], name="inst_id"),
    )
    monkeypatch.setattr(panel.data_module, "load_instruments", lambda *args, **kwargs: instruments)
    monkeypatch.setattr(panel.data_module, "load_data", lambda *args, **kwargs: ohlcv)
    monkeypatch.setattr(panel.data_module, "load_funding_rates", lambda *args, **kwargs: funding)
    monkeypatch.setattr(panel.data_module, "load_market_cap_history", lambda *args, **kwargs: market_cap)
    monkeypatch.setattr(
        panel.data_module,
        "load_spot_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("spot should not load")),
    )
    monkeypatch.setattr(
        panel.data_module,
        "load_open_interest_history",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OI should not load")),
    )

    loaded, failures = panel._load_panel(
        ["A-USDT-SWAP"],
        730,
        load_spot=False,
        load_open_interest=False,
        load_market_cap=True,
    )

    assert failures == []
    assert loaded["A-USDT-SWAP"]["spot_ohlcv"] is None
    assert loaded["A-USDT-SWAP"]["spot_error"] == "not_requested"
    assert loaded["A-USDT-SWAP"]["open_interest"] is None
    assert loaded["A-USDT-SWAP"]["open_interest_error"] == "not_requested"
    assert loaded["A-USDT-SWAP"]["market_cap"] is market_cap


def test_cache_file_state_requires_requested_history_span(tmp_path):
    cutoff = pd.Timestamp("2024-01-01", tz="UTC")
    ready_path = tmp_path / "ready.parquet"
    short_path = tmp_path / "short.parquet"
    pd.DataFrame({"value": [1.0]}, index=[cutoff + pd.Timedelta(days=6)]).to_parquet(ready_path)
    pd.DataFrame({"value": [1.0]}, index=[cutoff + pd.Timedelta(days=8)]).to_parquet(short_path)

    assert replication._cache_file_state(ready_path, cutoff)["history_ready"] is True
    assert replication._cache_file_state(short_path, cutoff)["history_ready"] is False
    assert replication._cache_file_state(tmp_path / "missing.parquet", cutoff)["exists"] is False


def test_trailing_daily_amihud_requires_full_window_and_excludes_current_day():
    index = pd.date_range("2026-01-01", periods=24 * 6, freq="h", tz="UTC")
    formations = index[index.hour == 0]
    close = pd.DataFrame({"A": np.exp(np.arange(len(index)) * 0.001)}, index=index)
    volume = pd.DataFrame({"A": 1000.0}, index=index)

    amihud = replication._trailing_daily_amihud(
        close,
        volume,
        formations,
        lookback_days=2,
        bars_per_day=24,
        information_lag_days=1,
    )

    assert amihud["A"].first_valid_index() == formations[3]
    changed = close.copy()
    changed.loc[formations[4], "A"] *= 100.0
    changed_amihud = replication._trailing_daily_amihud(
        changed,
        volume,
        formations,
        lookback_days=2,
        bars_per_day=24,
        information_lag_days=1,
    )
    assert changed_amihud.loc[formations[4], "A"] == amihud.loc[formations[4], "A"]


def test_ranked_segment_mask_selects_exact_point_in_time_top_n():
    formations = pd.date_range("2026-01-01", periods=2, freq="D", tz="UTC")
    columns = [f"A{i}" for i in range(6)]
    values = pd.DataFrame([range(6), range(5, -1, -1)], index=formations, columns=columns)
    eligibility = pd.DataFrame(True, index=formations, columns=columns)
    required = pd.DataFrame(1.0, index=formations, columns=columns)

    mask = replication._ranked_segment_mask(
        values,
        eligibility,
        formations,
        segment_assets=3,
        largest=True,
        required_values=required,
    )

    assert list(mask.sum(axis=1)) == [3, 3]
    assert set(mask.columns[mask.iloc[0]]) == {"A3", "A4", "A5"}
    assert set(mask.columns[mask.iloc[1]]) == {"A0", "A1", "A2"}


def test_daily_quintile_weights_are_disjoint_and_support_both_source_weightings():
    ts = pd.DatetimeIndex([pd.Timestamp("2026-01-01T00:00:00Z")])
    columns = [f"A{i:02d}" for i in range(20)]
    signal = pd.DataFrame([range(20)], index=ts, columns=columns, dtype=float)
    caps = pd.DataFrame([np.arange(1, 21)], index=ts, columns=columns, dtype=float)
    mask = pd.DataFrame(True, index=ts, columns=columns)

    equal, equal_coverage = replication._quintile_long_short_weights(
        signal,
        caps,
        mask,
        min_assets=20,
        side_fraction=0.20,
        weighting_mode="equal_weighted",
    )
    value, value_coverage = replication._quintile_long_short_weights(
        signal,
        caps,
        mask,
        min_assets=20,
        side_fraction=0.20,
        weighting_mode="point_in_time_market_cap_value_weighted",
    )

    for row in (equal.iloc[0], value.iloc[0]):
        assert (row > 0).sum() == 4
        assert (row < 0).sum() == 4
        assert abs(row[row > 0].sum() - 0.5) < 1e-12
        assert abs(row[row < 0].sum() + 0.5) < 1e-12
    assert equal.loc[ts[0], "A19"] == equal.loc[ts[0], "A16"]
    assert value.loc[ts[0], "A19"] > value.loc[ts[0], "A16"]
    assert equal_coverage["median_assets_per_side"] == 4.0
    assert value_coverage["valid_formation_count"] == 1


def test_daily_ic_inference_uses_preregistered_hac_lag():
    dates = pd.date_range("2026-01-01", periods=40, freq="D", tz="UTC")
    ic = pd.Series(np.linspace(0.01, 0.08, len(dates)), index=dates)

    result = replication._split_daily_ic_hac(ic, dates, max_lag=7)

    assert result["observations"] == 40
    assert result["newey_west"]["valid"] is True
    assert result["newey_west"]["max_lag"] == 7
    assert result["daily_hac_mean_tstat"] > 0


def test_trailing_realized_funding_excludes_the_current_event():
    index = pd.date_range("2026-01-01", periods=30, freq="h", tz="UTC")
    funding = pd.DataFrame({"A": np.nan}, index=index)
    funding.loc[index[0], "A"] = 0.001
    funding.loc[index[24], "A"] = 0.500

    trailing = replication._trailing_realized_funding(
        funding,
        pd.DatetimeIndex([index[24]]),
        lookback_bars=24,
        information_lag_bars=1,
    )

    assert trailing.loc[index[24], "A"] == 0.001


def test_pair_weights_are_unlevered_and_select_exact_top_n():
    ts = pd.DatetimeIndex([pd.Timestamp("2026-01-01T00:00:00Z")])
    signal = pd.DataFrame([[1.0, 4.0, 3.0, 2.0]], index=ts, columns=list("ABCD"))

    weights, coverage = replication._top_n_pair_weights(
        signal,
        top_n=2,
        pair_gross_exposure=1.0,
    )

    assert set(weights.columns[weights.iloc[0] > 0]) == {"B", "C"}
    assert weights.iloc[0].sum() == 0.5
    assert 2.0 * weights.iloc[0].abs().sum() == 1.0
    assert coverage["valid_formation_count"] == 1


def test_hysteresis_pair_weights_enter_top_ten_and_hold_until_top_twenty():
    dates = pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC")
    columns = [f"A{i:02d}" for i in range(10)]
    first = np.arange(10, dtype=float)
    second = first.copy()
    second[9] = 8.5
    second[8] = 9.5
    third = first.copy()
    third[9] = 0.5
    signal = pd.DataFrame([first, second, third], index=dates, columns=columns)

    weights, coverage = replication._hysteresis_pair_weights(
        signal,
        entry_fraction=0.10,
        hold_fraction=0.20,
        minimum_signal_assets=10,
        pair_gross_exposure=1.0,
    )

    assert set(weights.columns[weights.iloc[0] > 0]) == {"A09"}
    assert set(weights.columns[weights.iloc[1] > 0]) == {"A08", "A09"}
    assert set(weights.columns[weights.iloc[2] > 0]) == {"A08"}
    assert coverage["valid_formation_count"] == 3
    assert coverage["entry_fraction"] == 0.10
    assert coverage["hold_fraction"] == 0.20


def test_pair_forward_return_includes_future_funding_received_by_short():
    index = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
    perp = pd.DataFrame({"A": [100.0, 100.0, 100.0, 100.0]}, index=index)
    spot = perp.copy()
    funding = pd.DataFrame({"A": [np.nan, 0.001, np.nan, np.nan]}, index=index)

    result = replication._pair_forward_return(
        perp,
        spot,
        funding,
        holding_bars=2,
        pair_gross_exposure=1.0,
    )

    assert result.loc[index[0], "A"] == 0.0005


def test_pair_portfolio_metrics_credit_positive_funding_to_short_leg():
    index = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    weights = pd.DataFrame({"A": [0.5, 0.5, 0.5]}, index=index)
    flat = pd.DataFrame({"A": [0.0, 0.0, 0.0]}, index=index)
    funding = pd.DataFrame({"A": [0.001, np.nan, np.nan]}, index=index)

    result = replication._pair_portfolio_metrics_with_daily_hac(
        weights,
        flat,
        flat,
        funding,
        index,
        max_lag=1,
    )

    assert result["funding_received"] == 0.0005
    assert result["funding_paid"] == -0.0005
    assert result["cost_paid"] > 0
    assert result["return_evidence_complete_while_held"] is True


def test_month_end_formations_exclude_an_incomplete_final_month():
    index = pd.date_range("2025-10-01", "2025-12-11", freq="D", tz="UTC")

    formations = replication._month_end_formation_times(index)

    assert list(formations) == [
        pd.Timestamp("2025-10-31", tz="UTC"),
        pd.Timestamp("2025-11-30", tz="UTC"),
    ]


def test_monthly_low_vol_signal_uses_only_information_at_formation():
    index = pd.date_range("2025-01-01", periods=140, freq="D", tz="UTC")
    formations = replication._month_end_formation_times(index)
    close = pd.DataFrame(
        {
            "A": np.exp(np.arange(len(index)) * 0.001),
            "B": np.exp(np.arange(len(index)) * 0.002),
        },
        index=index,
    )
    eligibility = pd.DataFrame(True, index=index, columns=close.columns)
    original = replication._trailing_low_vol_signal(
        close,
        formations,
        eligibility,
        lookback_days=60,
        minimum_coverage_fraction=0.8,
    )
    changed = close.copy()
    changed.loc[index[-1], "A"] *= 100.0
    revised = replication._trailing_low_vol_signal(
        changed,
        formations,
        eligibility,
        lookback_days=60,
        minimum_coverage_fraction=0.8,
    )

    prior_formation = formations[formations < index[-1]][-1]
    assert revised.loc[prior_formation, "A"] == original.loc[prior_formation, "A"]


def test_monthly_targets_execute_one_day_after_formation():
    index = pd.date_range("2025-01-29", periods=35, freq="D", tz="UTC")
    formations = pd.DatetimeIndex(
        [pd.Timestamp("2025-01-31", tz="UTC"), pd.Timestamp("2025-02-28", tz="UTC")]
    )
    targets = pd.DataFrame(
        {"A": [0.5, -0.5], "B": [-0.5, 0.5]},
        index=formations,
    )

    held = replication._execute_monthly_targets(targets, index, execution_lag_days=1)

    assert held.loc[pd.Timestamp("2025-01-31", tz="UTC")].abs().sum() == 0.0
    assert held.loc[pd.Timestamp("2025-02-01", tz="UTC"), "A"] == 0.5
    assert held.loc[pd.Timestamp("2025-02-28", tz="UTC"), "A"] == 0.5
    assert held.loc[pd.Timestamp("2025-03-01", tz="UTC"), "A"] == -0.5


def test_source_period_split_reserves_every_post_source_day_for_holdout():
    index = pd.date_range("2022-08-01", "2026-02-15", freq="D", tz="UTC")

    splits = replication._source_period_split_indexes(
        index,
        source_sample_end_utc="2025-11-30T00:00:00Z",
        is_fraction=0.67,
    )

    assert splits["IS"].max() < splits["Val"].min()
    assert splits["Val"].max() == pd.Timestamp("2025-11-30", tz="UTC")
    assert splits["Holdout"].min() == pd.Timestamp("2025-12-01", tz="UTC")
    assert not splits["IS"].intersection(splits["Holdout"]).size
    assert not splits["Val"].intersection(splits["Holdout"]).size


def test_monthly_ic_random_control_is_seeded_and_reports_empirical_p_value():
    formations = pd.date_range("2024-01-31", periods=8, freq="ME", tz="UTC")
    columns = [f"A{i:02d}" for i in range(20)]
    signal = pd.DataFrame([np.arange(20)] * len(formations), index=formations, columns=columns)
    forward = signal.copy()
    mask = pd.DataFrame(True, index=formations, columns=columns)

    first = replication._permutation_mean_ic_control(
        signal,
        forward,
        mask,
        formations,
        minimum_assets=20,
        permutations=50,
        seed=42,
    )
    second = replication._permutation_mean_ic_control(
        signal,
        forward,
        mask,
        formations,
        minimum_assets=20,
        permutations=50,
        seed=42,
    )

    assert first == second
    assert first["observed_mean_rank_ic"] == 1.0
    assert first["empirical_one_sided_p"] == 1 / 51
