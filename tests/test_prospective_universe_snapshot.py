import copy
import json

import pandas as pd
import pytest

import data
import panel_universe
import prospective_universe_snapshot as snapshot


def _registry():
    registry = copy.deepcopy(panel_universe.load_registry())
    registry["registry_id"] = "prospective_test"
    registry["construction"]["prospective_start_utc"] = "2026-07-10T00:00:00Z"
    registry["construction"]["candidate_pool_size"] = 3
    registry["assets"] = [
        {"inst_id": f"A{i}-USDT-SWAP", "base_asset": f"A{i}", "asset_family": "defi"}
        for i in range(3)
    ]
    registry["point_in_time_rules"].update(
        {
            "target_size": 2,
            "min_listing_age_days": 1,
            "min_observed_history_days": 1,
            "min_history_coverage_ratio": 0.9,
            "liquidity_lookback_days": 2,
            "liquidity_min_period_days": 1,
            "min_avg_daily_quote_volume_usd": 1,
            "selection_lag_hours": 1,
        }
    )
    return registry


def _panel():
    index = pd.date_range("2026-07-09", periods=24 * 4, freq="h", tz="UTC")
    listed = int(pd.Timestamp("2020-01-01", tz="UTC").timestamp() * 1000)
    panel = {}
    for i in range(3):
        panel[f"A{i}-USDT-SWAP"] = {
            "ohlcv": pd.DataFrame(
                {
                    "close": 100.0 + i,
                    "vol_quote": 1000.0 - i * 100.0,
                },
                index=index,
            ),
            "instrument": {"list_time_ms": listed, "state": "live"},
            "asset_label": "defi",
        }
    return panel


def test_build_snapshot_uses_lagged_point_in_time_rules():
    payload = snapshot.build_snapshot(
        _panel(),
        registry=_registry(),
        as_of=pd.Timestamp("2026-07-12T12:30:00Z"),
        captured_at=pd.Timestamp("2026-07-12T12:35:00Z"),
    )

    assert payload["snapshot_date_utc"] == "2026-07-12"
    assert payload["as_of_bar_utc"] == "2026-07-12T12:00:00+00:00"
    assert payload["day_complete"] is False
    assert payload["formal_evidence_eligible"] is False
    assert snapshot.snapshot_is_formal_evidence(payload) is False
    assert payload["eligible_assets"] == ["A0-USDT-SWAP", "A1-USDT-SWAP"]
    assert payload["eligible_count"] == 2


def test_snapshot_before_freeze_is_rejected():
    with pytest.raises(ValueError, match="snapshot_before_prospective_start"):
        snapshot.build_snapshot(
            _panel(),
            registry=_registry(),
            as_of=pd.Timestamp("2026-07-09T23:00:00Z"),
            captured_at=pd.Timestamp("2026-07-10T00:00:00Z"),
        )


def test_end_of_day_snapshot_is_formal_evidence():
    payload = snapshot.build_snapshot(
        _panel(),
        registry=_registry(),
        as_of=pd.Timestamp("2026-07-12T23:30:00Z"),
        captured_at=pd.Timestamp("2026-07-13T00:20:00Z"),
    )

    assert payload["as_of_bar_utc"] == "2026-07-12T23:00:00+00:00"
    assert payload["day_complete"] is True
    assert payload["formal_evidence_eligible"] is True
    assert snapshot.snapshot_is_formal_evidence(payload) is True


def test_snapshot_is_append_only_and_idempotent(tmp_path):
    payload = snapshot.build_snapshot(
        _panel(),
        registry=_registry(),
        as_of=pd.Timestamp("2026-07-12T12:00:00Z"),
        captured_at=pd.Timestamp("2026-07-12T12:05:00Z"),
    )
    path, created = snapshot.write_snapshot_immutable(payload, snapshot_dir=tmp_path)
    changed = dict(payload, captured_at_utc="2026-07-12T23:59:00+00:00")
    same_path, created_again = snapshot.write_snapshot_immutable(changed, snapshot_dir=tmp_path)

    assert created is True
    assert created_again is False
    assert same_path == path
    assert json.loads(path.read_text(encoding="utf-8"))["captured_at_utc"] == payload["captured_at_utc"]
    assert len((tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_incremental_refresh_merges_confirmed_bars(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    index = pd.date_range("2026-07-10", periods=2, freq="h", tz="UTC")
    existing = pd.DataFrame(
        {"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "close": [1.0, 2.0], "volume": [1.0, 1.0], "vol_quote": [10.0, 20.0]},
        index=index,
    )
    existing.to_parquet(tmp_path / "A-USDT-SWAP_1H_730d.parquet")
    raw = [
        [str(int(index[1].timestamp() * 1000)), "2", "2", "2", "2.5", "1", "1", "25", "1"],
        [str(int((index[1] + pd.Timedelta(hours=1)).timestamp() * 1000)), "3", "3", "3", "3", "1", "1", "30", "1"],
        [str(int((index[1] + pd.Timedelta(hours=2)).timestamp() * 1000)), "4", "4", "4", "4", "1", "1", "40", "0"],
    ]
    monkeypatch.setattr(data, "fetch_okx_candles", lambda *args, **kwargs: raw)

    merged = data.refresh_ohlcv_cache_incremental("A-USDT-SWAP", "1H", 730)

    assert len(merged) == 3
    assert merged.loc[index[1], "close"] == 2.5
    assert merged.index.max() == index[1] + pd.Timedelta(hours=1)


def test_run_events_are_append_only(tmp_path):
    snapshot.append_run_event(tmp_path, {"status": "failed", "error": "network"})
    snapshot.append_run_event(tmp_path, {"status": "created", "eligible_count": 2})

    rows = [json.loads(line) for line in (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["status"] for row in rows] == ["failed", "created"]


def test_incremental_funding_remains_sparse(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    now = pd.Timestamp.now(tz="UTC").floor("h")
    old_index = pd.DatetimeIndex([now - pd.Timedelta(hours=16), now - pd.Timedelta(hours=8)])
    pd.DataFrame({"funding_rate": [0.0001, 0.0002]}, index=old_index).to_parquet(
        tmp_path / "A-USDT-SWAP_funding_730d.parquet"
    )
    raw = [
        {"fundingTime": str(int(old_index[-1].timestamp() * 1000)), "realizedRate": "0.0003"},
        {"fundingTime": str(int(now.timestamp() * 1000)), "realizedRate": "0.0004"},
    ]
    monkeypatch.setattr(data, "fetch_okx_funding_rate_history", lambda *args, **kwargs: raw)

    merged = data.refresh_funding_cache_incremental("A-USDT-SWAP", 730)

    assert len(merged) == 3
    assert merged.loc[old_index[-1]] == 0.0003
    assert merged.loc[now] == 0.0004


def test_incremental_open_interest_remains_daily_sparse(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    now = pd.Timestamp.now(tz="UTC").floor("D")
    columns = ["open_interest_contracts", "open_interest_ccy", "open_interest_usd"]
    pd.DataFrame([[1.0, 2.0, 3.0]], columns=columns, index=pd.DatetimeIndex([now - pd.Timedelta(days=1)])).to_parquet(
        tmp_path / "A-USDT-SWAP_open_interest_1D_730d.parquet"
    )
    raw = [[str(int(now.timestamp() * 1000)), "4", "5", "6"]]
    monkeypatch.setattr(data, "fetch_okx_open_interest_history", lambda *args, **kwargs: raw)

    merged = data.refresh_open_interest_cache_incremental("A-USDT-SWAP", 730, "1D")

    assert len(merged) == 2
    assert merged.loc[now, "open_interest_usd"] == 6.0
