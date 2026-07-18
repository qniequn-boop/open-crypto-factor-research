import pandas as pd

import data


def test_coin_metrics_symbol_mapping_is_explicit():
    assert data.coin_metrics_asset_id("BTC-USDT-SWAP") == "btc"
    assert data.coin_metrics_asset_id("IOTA-USDT-SWAP") == "miota"


def test_coin_metrics_market_cap_parser_preserves_sparse_daily_events():
    frame = data._coin_metrics_market_cap_to_df(
        [
            {"asset": "btc", "time": "2026-01-01T00:00:00Z", "CapMrktEstUSD": "100.5"},
            {"asset": "btc", "time": "2026-01-03T00:00:00Z", "CapMrktEstUSD": "110.0"},
        ]
    )

    assert list(frame.columns) == ["market_cap_usd"]
    assert len(frame) == 2
    assert frame.index.tz is not None
    assert pd.Timestamp("2026-01-02T00:00:00Z") not in frame.index
