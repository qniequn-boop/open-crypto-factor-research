"""Materialize a frozen panel substrate from already cached source files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import config
import data as data_module
import panel_factor_research as research
import panel_substrate_cache
import panel_universe


def materialize_cached_substrate(
    *,
    inst_ids: list[str],
    days: int,
    as_of: str,
    store_root: Path | str,
    min_assets: int,
) -> dict:
    inventory_before = panel_substrate_cache.collect_source_inventory(
        data_module,
        inst_ids,
        days,
        config.BAR,
        load_spot=True,
        load_open_interest=True,
        load_market_cap=True,
    )
    missing = [row["role"] for row in inventory_before["entries"] if not row["exists"]]
    if missing:
        raise ValueError("cached_substrate_source_files_missing:" + ",".join(missing[:20]))
    panel, failures = research._load_panel(
        inst_ids,
        days,
        force_refresh=False,
        load_spot=True,
        load_open_interest=True,
        load_market_cap=True,
    )
    panel = research._truncate_panel_as_of(panel, as_of)
    if len(panel) < int(min_assets):
        raise ValueError(f"cached_substrate_min_assets_not_met:{len(panel)}<{min_assets}")
    empty_ohlcv = sorted(
        inst_id
        for inst_id, item in panel.items()
        if item.get("ohlcv") is None or item["ohlcv"].empty
    )
    if empty_ohlcv:
        raise ValueError("cached_substrate_empty_ohlcv:" + ",".join(empty_ohlcv))
    request_contract = panel_substrate_cache.build_request_contract(
        inst_ids=inst_ids,
        days=days,
        bar=config.BAR,
        as_of=as_of,
        load_spot=True,
        load_open_interest=True,
        load_market_cap=True,
        universe_registry_path=config.PANEL_UNIVERSE_REGISTRY,
        loader_code_paths=[
            Path(research.__file__),
            Path(data_module.__file__),
            Path(panel_substrate_cache.__file__),
            Path(panel_universe.__file__),
        ],
    )
    inventory_after = panel_substrate_cache.collect_source_inventory(
        data_module,
        inst_ids,
        days,
        config.BAR,
        load_spot=True,
        load_open_interest=True,
        load_market_cap=True,
    )
    if inventory_after["fingerprint"] != inventory_before["fingerprint"]:
        raise ValueError("cached_substrate_sources_changed_during_materialization")
    store = panel_substrate_cache.PanelSubstrateStore(store_root)
    manifest = store.write(
        panel=panel,
        failures=failures,
        request_contract=request_contract,
        panel_fingerprint=research._panel_input_fingerprint(panel),
        source_inventory=inventory_after,
    )
    store.load(
        manifest["manifest_path"],
        panel_fingerprint_fn=research._panel_input_fingerprint,
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--days", type=int, default=config.PANEL_HISTORY_DAYS)
    parser.add_argument("--symbols", default=",".join(config.PANEL_INST_IDS))
    parser.add_argument("--min-assets", type=int, default=config.PANEL_MIN_ASSETS)
    parser.add_argument(
        "--store-root",
        default=str(Path(config.CACHE_DIR) / "panel_substrates" / "v1"),
    )
    args = parser.parse_args()
    inst_ids = [item.strip() for item in args.symbols.split(",") if item.strip()]
    manifest = materialize_cached_substrate(
        inst_ids=inst_ids,
        days=args.days,
        as_of=args.as_of,
        store_root=args.store_root,
        min_assets=args.min_assets,
    )
    print(f"WROTE {manifest['manifest_path']}")
    print(
        json.dumps(
            {
                "substrate_id": manifest["substrate_id"],
                "asset_count": len(manifest["assets"]),
                "failure_count": len(manifest["failures"]),
                "request_contract": manifest["request_contract"],
                "manifest_sha256": manifest["manifest_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
