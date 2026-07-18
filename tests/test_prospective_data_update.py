import json

import pandas as pd

import prospective_data_update as update


def _frames(now):
    hourly = pd.date_range(now - pd.Timedelta(days=700), now - pd.Timedelta(hours=1), freq="12h", tz="UTC")
    hourly = hourly.union(pd.DatetimeIndex([now - pd.Timedelta(hours=1)]))
    perpetual = pd.DataFrame({"close": 100.0, "vol_quote": 1_000_000.0}, index=hourly)
    spot = pd.DataFrame({"close": 99.0, "vol_quote": 900_000.0}, index=hourly)
    funding_index = pd.date_range(now - pd.Timedelta(days=700), now - pd.Timedelta(hours=8), freq="8h", tz="UTC")
    funding = pd.Series(0.0001, index=funding_index)
    oi_index = pd.date_range(now - pd.Timedelta(days=700), now - pd.Timedelta(days=1), freq="D", tz="UTC")
    oi = pd.DataFrame(
        {
            "open_interest_contracts": 1.0,
            "open_interest_ccy": 2.0,
            "open_interest_usd": 3.0,
        },
        index=oi_index,
    )
    return perpetual, spot, funding, oi


def test_update_asset_passes_complete_recent_data(monkeypatch):
    now = pd.Timestamp("2026-07-11T12:00:00Z")
    perpetual, spot_frame, funding, oi = _frames(now)

    def refresh_ohlcv(*args, **kwargs):
        return spot_frame if kwargs.get("spot") else perpetual

    monkeypatch.setattr(update.data, "refresh_ohlcv_cache_incremental", refresh_ohlcv)
    monkeypatch.setattr(update.data, "refresh_funding_cache_incremental", lambda *args, **kwargs: funding)
    monkeypatch.setattr(update.data, "refresh_open_interest_cache_incremental", lambda *args, **kwargs: oi)

    row = update.update_asset("A-USDT-SWAP", days=730, now=now)

    assert row["status"] == "pass"
    assert row["failed_checks"] == []
    assert row["metrics"]["basis_coverage_30d"] == 1.0


def test_update_asset_marks_stale_funding_failed(monkeypatch):
    now = pd.Timestamp("2026-07-11T12:00:00Z")
    perpetual, spot, funding, oi = _frames(now)
    funding = funding.loc[funding.index <= now - pd.Timedelta(days=2)]

    def refresh_ohlcv(*args, **kwargs):
        return spot if kwargs.get("spot") else perpetual

    monkeypatch.setattr(update.data, "refresh_ohlcv_cache_incremental", refresh_ohlcv)
    monkeypatch.setattr(update.data, "refresh_funding_cache_incremental", lambda *args, **kwargs: funding)
    monkeypatch.setattr(update.data, "refresh_open_interest_cache_incremental", lambda *args, **kwargs: oi)

    row = update.update_asset("A-USDT-SWAP", days=730, now=now)

    assert row["status"] == "failed"
    assert "funding_recent" in row["failed_checks"]


def test_run_update_isolates_asset_exceptions(monkeypatch):
    monkeypatch.setattr(
        update,
        "update_asset",
        lambda inst_id, **kwargs: (
            {"inst_id": inst_id, "status": "pass", "checks": {}, "failed_checks": []}
            if inst_id == "A"
            else {"inst_id": inst_id, "status": "failed", "checks": {}, "failed_checks": ["update_exception"]}
        ),
    )

    report = update.run_update(["A", "B"], days=730, now=pd.Timestamp("2026-07-11T12:00:00Z"))

    assert report["passed_asset_count"] == 1
    assert report["failed_assets"] == ["B"]
    assert report["overall_status"] == "failed"


def test_write_report_updates_latest_and_appends_run(tmp_path):
    report = {
        "created_at_utc": "2026-07-11T12:00:00+00:00",
        "overall_status": "pass",
        "passed_asset_count": 2,
        "failed_asset_count": 0,
    }

    path = update.write_report(report, log_dir=tmp_path)

    assert path.exists()
    assert json.loads((tmp_path / "prospective_data_update_latest.json").read_text(encoding="utf-8"))["overall_status"] == "pass"
    run = json.loads((tmp_path / "prospective_data_update_runs.jsonl").read_text(encoding="utf-8").strip())
    assert run["failed_asset_count"] == 0
