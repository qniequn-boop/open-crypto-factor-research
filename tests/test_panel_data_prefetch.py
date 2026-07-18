from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import panel_data_prefetch as prefetch


def test_prefetch_records_each_field_and_partial_failures(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=31, freq="1D", tz="UTC")
    monkeypatch.setattr(prefetch.data, "load_instruments", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(prefetch.data, "load_data", lambda *args, **kwargs: pd.DataFrame(index=idx))
    monkeypatch.setattr(prefetch.data, "load_funding_rates", lambda *args, **kwargs: pd.Series(0.0, index=idx))
    monkeypatch.setattr(
        prefetch.data,
        "load_open_interest_history",
        lambda *args, **kwargs: pd.DataFrame(index=idx),
    )
    monkeypatch.setattr(prefetch.data, "load_market_cap_history", lambda *args, **kwargs: pd.DataFrame(index=idx))

    def load_spot(inst_id, *args, **kwargs):
        if inst_id.startswith("B-"):
            raise ValueError("spot missing")
        return pd.DataFrame(index=idx)

    monkeypatch.setattr(prefetch.data, "load_spot_data", load_spot)
    report = prefetch.run_prefetch(
        ["A-USDT-SWAP", "B-USDT-SWAP"],
        days=30,
        workers=8,
    )

    assert report["workers"] == 1
    assert report["include_funding"] is True
    assert report["complete_assets"] == 1
    assert report["partial_assets"] == 1
    failed = next(row for row in report["assets"] if row["inst_id"] == "B-USDT-SWAP")
    assert failed["fields"]["spot_ohlcv"]["status"] == "failed"


def test_prefetch_allows_bounded_concurrency_when_funding_is_skipped(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=31, freq="1D", tz="UTC")
    monkeypatch.setattr(prefetch.data, "load_instruments", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(prefetch.data, "load_data", lambda *args, **kwargs: pd.DataFrame(index=idx))
    monkeypatch.setattr(prefetch.data, "load_spot_data", lambda *args, **kwargs: pd.DataFrame(index=idx))
    monkeypatch.setattr(
        prefetch.data,
        "load_open_interest_history",
        lambda *args, **kwargs: pd.DataFrame(index=idx),
    )
    monkeypatch.setattr(prefetch.data, "load_market_cap_history", lambda *args, **kwargs: pd.DataFrame(index=idx))

    report = prefetch.run_prefetch(
        ["A-USDT-SWAP", "B-USDT-SWAP"],
        days=30,
        workers=8,
        include_funding=False,
    )

    assert report["workers"] == 3
    assert report["include_funding"] is False
    assert all("funding" not in row["fields"] for row in report["assets"])


def test_funding_loader_rejects_recent_rest_fallback_for_long_request(tmp_path, monkeypatch):
    monkeypatch.setattr(prefetch.data, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(prefetch.data.config, "OKX_RATE_LIMIT", 0)
    monkeypatch.setattr(
        prefetch.data,
        "fetch_okx_historical_funding_links_chunked",
        lambda *args, **kwargs: (_ for _ in ()).throw(IOError("rate limited")),
    )
    calls = {"count": 0}

    def recent_only(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] > 1:
            return []
        ts = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp() * 1000)
        return [{"fundingTime": str(ts), "realizedRate": "0.0001"}]

    monkeypatch.setattr(prefetch.data, "fetch_okx_funding_rate_history", recent_only)

    with pytest.raises(ValueError, match="funding history incomplete"):
        prefetch.data.load_funding_rates("A-USDT-SWAP", days=730, force_refresh=True)
