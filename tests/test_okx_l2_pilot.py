import io
import json
import tarfile

import numpy as np
import pytest

import okx_l2_pilot as l2


def _spec():
    return {
        "inst_id": "TEST-USDT-SWAP",
        "contract_value_base": 1.0,
        "contract_value_ccy": "TEST",
        "contract_type": "linear",
        "lot_size_contracts": 1.0,
        "minimum_size_contracts": 1.0,
        "tick_size": 1.0,
        "state": "live",
    }


def _write_l2_archive(path, messages):
    payload = "".join(json.dumps(message) + "\n" for message in messages).encode()
    info = tarfile.TarInfo("TEST-USDT-SWAP-L2orderbook-400lv.data")
    info.size = len(payload)
    with tarfile.open(path, mode="w:gz") as archive:
        archive.addfile(info, io.BytesIO(payload))


def test_apply_levels_updates_and_deletes_prices():
    book = {99.0: 2.0, 98.0: 3.0}

    l2.apply_levels(book, [[99, 4, 1], [98, 0, 0], [97, 5, 2]])

    assert book == {99.0: 4.0, 97.0: 5.0}


def test_book_metrics_convert_contracts_to_quote_depth_and_sweep_impact():
    bids = {99.0: 10.0, 98.0: 10.0}
    asks = {101.0: 10.0, 102.0: 10.0}

    metrics = l2.book_metrics(
        bids,
        asks,
        _spec(),
        depth_bps=(200.0,),
        notionals=(100.0, 1_500.0),
    )

    assert metrics is not None
    assert metrics["mid"] == 100.0
    assert metrics["quoted_spread_bps"] == 200.0
    assert metrics["depth_usdt"]["200"]["bid_usdt"] == 1_970.0
    assert metrics["depth_usdt"]["200"]["ask_usdt"] == 2_030.0
    assert metrics["impact"]["100"]["buy"]["impact_bps"] == 100.0
    assert metrics["impact"]["1500"]["buy"]["impact_bps"] > 100.0


def test_analyzer_reconstructs_updates_and_matches_preceding_quote(tmp_path):
    start = 1_000_000
    archive = tmp_path / "book.tar.gz"
    _write_l2_archive(
        archive,
        [
            {
                "instId": "TEST-USDT-SWAP",
                "action": "snapshot",
                "ts": str(start + 10),
                "bids": [["99", "10", "1"]],
                "asks": [["101", "10", "1"]],
            },
            {
                "instId": "TEST-USDT-SWAP",
                "action": "update",
                "ts": str(start + 2_000),
                "bids": [],
                "asks": [["101", "0", "0"], ["100.5", "10", "1"]],
            },
        ],
    )
    trades = [
        {
            "timestamp_ms": start + 1_000,
            "trade_id": "1",
            "side": "buy",
            "price": 101.0,
            "size_contracts": 1.0,
        }
    ]

    report = l2.analyze_l2_archive(
        archive,
        spec=_spec(),
        trades=trades,
        start_ms=start,
        end_ms_exclusive=start + 4_000,
        sample_interval_ms=1_000,
        depth_bps=(200.0,),
        notionals=(100.0,),
    )

    assert report["book_integrity"]["snapshot_count"] == 1
    assert report["book_integrity"]["update_count"] == 1
    assert report["book_integrity"]["monotonic_timestamp_violations"] == 0
    assert report["sampling"]["valid_samples"] == 4
    assert report["effective_spread_bps"]["matched_trade_fraction"] == 1.0
    assert abs(report["effective_spread_bps"]["median"] - 200.0) < 1e-12
    assert report["effective_spread_bps"]["quote_notional_weighted_one_way_slippage_bps"] == 100.0
    assert report["quoted_spread_bps"]["minimum"] < 200.0
    assert (
        report["market_order_impact_bps"]["100"]["buy"][
            "fraction_above_current_fixed_slippage"
        ]
        == 1.0
    )


def test_l2_archive_stream_reader_rejects_multiple_file_members(tmp_path):
    archive_path = tmp_path / "multiple.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        for name in ("first.data", "second.data"):
            payload = b'{}\n'
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    with pytest.raises(ValueError, match="unexpected_l2_archive_members"):
        list(l2._iter_l2_messages(archive_path))


def test_download_link_request_uses_derivative_family_not_instrument_id():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": "0",
                "data": {
                    "details": [
                        {
                            "instFamily": "BTC-USDT",
                            "groupDetails": [
                                {
                                    "dateTs": "1000",
                                    "filename": "book.tar.gz",
                                    "sizeMB": "1.5",
                                    "url": "https://static.okx.com/path/book.tar.gz",
                                }
                            ],
                        }
                    ]
                },
            }

    class Session:
        def __init__(self):
            self.payload = None

        def post(self, url, **kwargs):
            self.payload = kwargs["json"]
            return Response()

    session = Session()
    rows = l2.request_download_links(
        ["BTC-USDT-SWAP"],
        module=l2.L2_400_MODULE,
        begin_ms=1_000,
        end_ms_exclusive=2_000,
        session=session,
    )

    assert session.payload["instQueryParam"] == {"instFamilyList": ["BTC-USDT"]}
    assert "instIdList" not in session.payload["instQueryParam"]
    assert rows[0]["inst_id"] == "BTC-USDT-SWAP"
    assert np.isclose(rows[0]["size_mb"], 1.5)
