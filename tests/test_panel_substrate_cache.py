from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import panel_factor_research as panel_research
import panel_substrate_cache as substrate


def _panel():
    hourly = pd.date_range("2026-01-01", periods=8, freq="1h", tz="UTC")
    daily = pd.date_range("2026-01-01", periods=2, freq="1D", tz="UTC")
    first_ohlcv = pd.DataFrame(
        {
            "open": range(8),
            "high": range(1, 9),
            "low": range(8),
            "close": range(1, 9),
            "volume": [100.0] * 8,
            "vol_quote": [1000.0] * 8,
        },
        index=hourly,
    ).astype(float)
    second_ohlcv = first_ohlcv.iloc[2:].copy() * 2.0
    return {
        "AAA-USDT-SWAP": {
            "ohlcv": first_ohlcv,
            "spot_ohlcv": first_ohlcv * 0.99,
            "funding": pd.Series([0.001, -0.002], index=hourly[[0, 6]], name="funding_rate"),
            "open_interest": pd.DataFrame({"open_interest_usd": [10.0, 11.0]}, index=daily),
            "market_cap": pd.DataFrame({"market_cap_usd": [100.0, 110.0]}, index=daily),
            "spot_error": None,
            "open_interest_error": None,
            "market_cap_error": None,
            "instrument": {"inst_id": "AAA-USDT-SWAP", "list_time_ms": 1, "contract_value": np.nan},
            "instrument_error": None,
            "asset_label": "payment",
        },
        "BBB-USDT-SWAP": {
            "ohlcv": second_ohlcv,
            "spot_ohlcv": None,
            "funding": pd.Series([0.003], index=hourly[[3]], name="funding_rate"),
            "open_interest": None,
            "market_cap": None,
            "spot_error": "not_available",
            "open_interest_error": "not_available",
            "market_cap_error": "not_available",
            "instrument": {"inst_id": "BBB-USDT-SWAP", "list_time_ms": 2},
            "instrument_error": None,
            "asset_label": "infrastructure",
        },
    }


def _request(tmp_path: Path):
    universe = tmp_path / "universe.json"
    universe.write_text('{"registry_id":"test"}\n', encoding="utf-8")
    loader = tmp_path / "loader.py"
    loader.write_text("VERSION = 1\n", encoding="utf-8")
    return substrate.build_request_contract(
        inst_ids=["AAA-USDT-SWAP", "BBB-USDT-SWAP"],
        days=30,
        bar="1H",
        as_of="2026-01-02T00:00:00Z",
        load_spot=True,
        load_open_interest=True,
        load_market_cap=True,
        universe_registry_path=universe,
        loader_code_paths=[loader],
    )


def _inventory(fingerprint="source_1"):
    return {
        "fingerprint": fingerprint,
        "file_count": 0,
        "existing_file_count": 0,
        "entries": [],
    }


def test_panel_substrate_roundtrip_preserves_exact_panel_fingerprint(tmp_path):
    store = substrate.PanelSubstrateStore(tmp_path / "substrates")
    original = _panel()
    fingerprint = panel_research._panel_input_fingerprint(original)
    manifest = store.write(
        panel=original,
        failures=[{"inst_id": "MISSING", "error": "expected"}],
        request_contract=_request(tmp_path),
        panel_fingerprint=fingerprint,
        source_inventory=_inventory(),
    )

    restored, failures, loaded_manifest = store.load(
        manifest["manifest_path"],
        panel_fingerprint_fn=panel_research._panel_input_fingerprint,
    )

    assert panel_research._panel_input_fingerprint(restored) == fingerprint
    assert failures == [{"inst_id": "MISSING", "error": "expected"}]
    assert restored["BBB-USDT-SWAP"]["spot_ohlcv"] is None
    assert restored["AAA-USDT-SWAP"]["funding"].isna().sum() == 0
    assert len(restored["AAA-USDT-SWAP"]["funding"]) == 2
    assert np.isnan(restored["AAA-USDT-SWAP"]["instrument"]["contract_value"])
    assert loaded_manifest["substrate_id"] == manifest["substrate_id"]


def test_identical_substrate_write_reuses_object_and_blobs(tmp_path):
    store = substrate.PanelSubstrateStore(tmp_path / "substrates")
    original = _panel()
    kwargs = {
        "panel": original,
        "failures": [],
        "request_contract": _request(tmp_path),
        "panel_fingerprint": panel_research._panel_input_fingerprint(original),
        "source_inventory": _inventory(),
    }

    first = store.write(**kwargs)
    first_blob_count = len(list((store.root / "blobs").rglob("*.parquet")))
    second = store.write(**kwargs)

    assert first["substrate_id"] == second["substrate_id"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert len(list((store.root / "objects").glob("*/manifest.json"))) == 1
    assert len(list((store.root / "blobs").rglob("*.parquet"))) == first_blob_count


def test_source_file_reencoding_does_not_change_resolved_substrate_identity(tmp_path):
    store = substrate.PanelSubstrateStore(tmp_path / "substrates")
    original = _panel()
    kwargs = {
        "panel": original,
        "failures": [],
        "request_contract": _request(tmp_path),
        "panel_fingerprint": panel_research._panel_input_fingerprint(original),
    }

    first = store.write(**kwargs, source_inventory=_inventory("raw_encoding_1"))
    second = store.write(**kwargs, source_inventory=_inventory("raw_encoding_2"))

    assert first["substrate_id"] == second["substrate_id"]
    assert len(list((store.root / "objects").glob("*/manifest.json"))) == 1


def test_alias_hit_requires_unchanged_source_inventory(tmp_path):
    store = substrate.PanelSubstrateStore(tmp_path / "substrates")
    original = _panel()
    request = _request(tmp_path)
    store.write(
        panel=original,
        failures=[],
        request_contract=request,
        panel_fingerprint=panel_research._panel_input_fingerprint(original),
        source_inventory=_inventory("same"),
    )

    hit, reason = store.lookup(request, _inventory("same"))
    miss, miss_reason = store.lookup(request, _inventory("changed"))

    assert reason == "hit"
    assert hit is not None
    assert miss is None
    assert miss_reason == "source_inventory_changed"


def test_blob_tampering_fails_closed(tmp_path):
    store = substrate.PanelSubstrateStore(tmp_path / "substrates")
    original = _panel()
    manifest = store.write(
        panel=original,
        failures=[],
        request_contract=_request(tmp_path),
        panel_fingerprint=panel_research._panel_input_fingerprint(original),
        source_inventory=_inventory(),
    )
    blob_path = next((store.root / "blobs").rglob("*.parquet"))
    blob_path.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="panel_substrate_blob_hash_mismatch"):
        store.load(manifest["manifest_path"])


def test_frozen_request_can_allow_loader_change_but_not_data_dimensions(tmp_path):
    frozen = _request(tmp_path)
    requested = dict(frozen)
    requested["loader_code"] = {"sha256": "new", "files": []}
    requested["request_key"] = "new_request_key"

    compatible, failures = substrate.request_compatibility(
        frozen,
        requested,
        allow_loader_code_change=True,
    )
    changed_days = {**requested, "days": 60}
    incompatible, dimension_failures = substrate.request_compatibility(
        frozen,
        changed_days,
        allow_loader_code_change=True,
    )

    assert compatible
    assert failures == []
    assert not incompatible
    assert dimension_failures == ["request_contract_changed:days"]
