import pandas as pd

import panel_market_cap_audit as audit


def test_market_cap_audit_requires_complete_positive_point_in_time_data(monkeypatch):
    end = pd.Timestamp.now(tz="UTC").floor("D")
    idx = pd.date_range(end - pd.Timedelta(days=10), end, freq="1D", tz="UTC")
    frames = {
        "A-USDT-SWAP": pd.DataFrame({"market_cap_usd": 100.0}, index=idx),
        "B-USDT-SWAP": pd.DataFrame({"market_cap_usd": 200.0}, index=idx),
    }
    monkeypatch.setattr(audit.panel_universe, "registry_inst_ids", lambda: list(frames))

    report = audit.audit_market_cap_frames(frames, [], days=10)

    assert report["market_cap_data_ready"] is True
    assert report["global_coverage"] == 1.0
    assert report["source"]["information_lag_days_in_factor_engine"] == 1


def test_market_cap_audit_fails_on_nonpositive_values(monkeypatch):
    end = pd.Timestamp.now(tz="UTC").floor("D")
    idx = pd.date_range(end - pd.Timedelta(days=2), end, freq="1D", tz="UTC")
    frames = {"A-USDT-SWAP": pd.DataFrame({"market_cap_usd": [100.0, 0.0, 100.0]}, index=idx)}
    monkeypatch.setattr(audit.panel_universe, "registry_inst_ids", lambda: list(frames))

    assert audit.audit_market_cap_frames(frames, [], days=2)["market_cap_data_ready"] is False
