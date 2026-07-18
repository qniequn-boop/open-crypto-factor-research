"""Append-only daily snapshots for the prospective panel universe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import config
import data
import panel_universe


SNAPSHOT_DIR = Path("prospective_snapshots")
MANIFEST_PATH = SNAPSHOT_DIR / "manifest.jsonl"


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def snapshot_is_formal_evidence(payload: dict[str, Any]) -> bool:
    return bool(payload.get("day_complete", False))


def append_run_event(snapshot_dir: Path | str, event: dict[str, Any]) -> None:
    out_dir = Path(snapshot_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def build_snapshot(
    panel: dict[str, dict[str, Any]],
    *,
    registry: dict[str, Any],
    as_of: pd.Timestamp,
    captured_at: pd.Timestamp,
) -> dict[str, Any]:
    as_of = pd.Timestamp(as_of)
    captured_at = pd.Timestamp(captured_at)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    else:
        as_of = as_of.tz_convert("UTC")
    if captured_at.tzinfo is None:
        captured_at = captured_at.tz_localize("UTC")
    else:
        captured_at = captured_at.tz_convert("UTC")
    prospective_start = pd.Timestamp(registry["construction"]["prospective_start_utc"])
    if prospective_start.tzinfo is None:
        prospective_start = prospective_start.tz_localize("UTC")
    if as_of < prospective_start:
        raise ValueError("snapshot_before_prospective_start")

    close = pd.concat({name: item["ohlcv"]["close"] for name, item in panel.items()}, axis=1).sort_index()
    vol_quote = pd.concat({name: item["ohlcv"]["vol_quote"] for name, item in panel.items()}, axis=1).reindex(close.index)
    usable_index = close.index[close.index <= as_of]
    if not len(usable_index):
        raise ValueError("no_closed_bar_at_or_before_as_of")
    as_of_bar = usable_index.max()
    close = close.loc[:as_of_bar]
    vol_quote = vol_quote.loc[:as_of_bar]
    universe = panel_universe.build_point_in_time_eligibility(panel, close, vol_quote, registry=registry)
    eligibility = universe["eligibility"].loc[as_of_bar]
    base_eligibility = universe["base_eligibility"].loc[as_of_bar]
    liquidity = universe["trailing_avg_daily_quote_volume"].loc[as_of_bar]
    listing_age = universe["listing_age_days"].loc[as_of_bar]
    observed = universe["observed_history_bars"].loc[as_of_bar]
    assets = []
    for inst_id in panel_universe.registry_inst_ids(registry):
        item = panel.get(inst_id, {})
        instrument = item.get("instrument") or {}
        assets.append(
            {
                "inst_id": inst_id,
                "instrument_state": instrument.get("state"),
                "eligible": bool(eligibility.get(inst_id, False)),
                "base_eligible": bool(base_eligibility.get(inst_id, False)),
                "listing_age_days": float(listing_age.get(inst_id)) if pd.notna(listing_age.get(inst_id)) else None,
                "observed_history_bars": int(observed.get(inst_id, 0)),
                "trailing_avg_daily_quote_volume_usd": (
                    float(liquidity.get(inst_id)) if pd.notna(liquidity.get(inst_id)) else None
                ),
                "asset_family": (panel_universe.registry_asset_map(registry).get(inst_id) or {}).get("asset_family"),
            }
        )
    eligible_assets = [row["inst_id"] for row in assets if row["eligible"]]
    expected_day_end = as_of_bar.normalize() + pd.Timedelta(hours=23)
    day_complete = bool(as_of_bar == expected_day_end)
    return {
        "schema_version": 1,
        "snapshot_date_utc": as_of.date().isoformat(),
        "captured_at_utc": captured_at.isoformat(),
        "as_of_bar_utc": as_of_bar.isoformat(),
        "expected_day_end_bar_utc": expected_day_end.isoformat(),
        "day_complete": day_complete,
        "formal_evidence_eligible": day_complete,
        "registry_id": registry["registry_id"],
        "prospective_start_utc": prospective_start.isoformat(),
        "source": "OKX public instruments and confirmed history-candles",
        "rules": dict(registry["point_in_time_rules"]),
        "eligible_count": len(eligible_assets),
        "eligible_assets": eligible_assets,
        "assets": assets,
    }


def write_snapshot_immutable(
    payload: dict[str, Any],
    *,
    snapshot_dir: Path | str = SNAPSHOT_DIR,
) -> tuple[Path, bool]:
    out_dir = Path(snapshot_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{payload['snapshot_date_utc']}.json"
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        manifest_path = out_dir / "manifest.jsonl"
        manifest_rows = [
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ] if manifest_path.exists() else []
        matching = [row for row in manifest_rows if row.get("snapshot_date_utc") == payload["snapshot_date_utc"]]
        if not matching or matching[-1].get("sha256") != payload_sha256(existing):
            raise ValueError(f"snapshot_manifest_integrity_failed:{path}")
        return path, False
    with os.fdopen(fd, "wb") as fh:
        fh.write(encoded)
        fh.flush()
        os.fsync(fh.fileno())
    manifest_path = out_dir / "manifest.jsonl"
    row = {
        "snapshot_date_utc": payload["snapshot_date_utc"],
        "as_of_bar_utc": payload["as_of_bar_utc"],
        "registry_id": payload["registry_id"],
        "eligible_count": payload["eligible_count"],
        "day_complete": bool(payload.get("day_complete", False)),
        "formal_evidence_eligible": snapshot_is_formal_evidence(payload),
        "path": str(path),
        "sha256": payload_sha256(payload),
    }
    with manifest_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return path, True


def collect_live_panel(registry: dict[str, Any], *, days: int) -> tuple[dict[str, Any], list[dict[str, str]]]:
    instruments = data.load_instruments("SWAP", force_refresh=True)
    panel: dict[str, Any] = {}
    failures = []
    asset_map = panel_universe.registry_asset_map(registry)
    for inst_id in panel_universe.registry_inst_ids(registry):
        try:
            ohlcv = data.refresh_ohlcv_cache_incremental(inst_id, config.BAR, days)
            instrument = instruments.loc[inst_id].to_dict() if inst_id in instruments.index else None
            if not instrument or instrument.get("state") != "live":
                raise ValueError("instrument_not_live_in_snapshot")
            panel[inst_id] = {
                "ohlcv": ohlcv,
                "instrument": instrument,
                "asset_label": (asset_map.get(inst_id) or {}).get("asset_family"),
            }
        except Exception as exc:
            failures.append({"inst_id": inst_id, "error": str(exc)})
    return panel, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", help="UTC timestamp; defaults to the last fully closed hourly bar")
    parser.add_argument("--days", type=int, default=config.PANEL_HISTORY_DAYS)
    parser.add_argument("--snapshot-dir", default=str(SNAPSHOT_DIR))
    args = parser.parse_args()
    captured_at = _utc_now()
    as_of = pd.Timestamp(args.as_of) if args.as_of else captured_at.floor("h") - pd.Timedelta(hours=1)
    registry = panel_universe.load_registry()
    panel, failures = collect_live_panel(registry, days=args.days)
    if failures:
        event = {
            "captured_at_utc": captured_at.isoformat(),
            "as_of_utc": as_of.isoformat(),
            "status": "failed",
            "load_failures": failures,
        }
        append_run_event(args.snapshot_dir, event)
        print(json.dumps(event, ensure_ascii=False))
        return 2
    payload = build_snapshot(panel, registry=registry, as_of=as_of, captured_at=captured_at)
    path, created = write_snapshot_immutable(payload, snapshot_dir=args.snapshot_dir)
    append_run_event(
        args.snapshot_dir,
        {
            "captured_at_utc": captured_at.isoformat(),
            "as_of_utc": as_of.isoformat(),
            "status": "created" if created else "already_exists",
            "snapshot_path": str(path),
            "eligible_count": payload["eligible_count"],
        },
    )
    print("SNAPSHOT", "CREATED" if created else "EXISTS", path, "ELIGIBLE", payload["eligible_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
