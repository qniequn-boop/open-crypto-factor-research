"""Fetch and audit point-in-time market-cap data for canonical replications."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import config
import data
import panel_universe


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def audit_market_cap_frames(
    frames: dict[str, pd.DataFrame],
    failures: list[dict[str, str]],
    *,
    days: int,
) -> dict[str, Any]:
    end = pd.Timestamp.now(tz="UTC").floor("D")
    start = end - pd.Timedelta(days=int(days))
    expected_index = pd.date_range(start, end, freq="1D", tz="UTC")
    rows = []
    series = {}
    for inst_id in sorted(frames):
        frame = frames[inst_id].sort_index()
        values = frame["market_cap_usd"].reindex(expected_index)
        observed = int(values.notna().sum())
        positive = int((values.dropna() > 0).sum())
        rows.append(
            {
                "inst_id": inst_id,
                "coin_metrics_asset_id": data.coin_metrics_asset_id(inst_id),
                "observed_days": observed,
                "expected_days": len(expected_index),
                "coverage": float(observed / len(expected_index)),
                "positive_value_days": positive,
                "first_observation": str(frame.index.min()) if len(frame) else None,
                "last_observation": str(frame.index.max()) if len(frame) else None,
            }
        )
        series[inst_id] = values
    matrix = pd.DataFrame(series, index=expected_index)
    total_expected = int(matrix.size)
    total_observed = int(matrix.notna().sum().sum())
    minimum_asset_coverage = min((row["coverage"] for row in rows), default=0.0)
    passed = bool(
        not failures
        and len(rows) == len(panel_universe.registry_inst_ids())
        and total_expected > 0
        and total_observed / total_expected >= 0.95
        and minimum_asset_coverage >= 0.90
        and all(row["positive_value_days"] == row["observed_days"] for row in rows)
    )
    return {
        "created_at_utc": _stamp(),
        "audit_type": "coin_metrics_point_in_time_market_cap",
        "source": {
            "provider": "Coin Metrics Community API",
            "metric": "CapMrktEstUSD",
            "definition": "estimated circulating supply multiplied by Coin Metrics daily USD reference price",
            "documentation": "https://docs.coinmetrics.io/asset-metrics/market/capact1yrusd",
            "information_lag_days_in_factor_engine": 1,
            "no_forward_fill_in_raw_cache": True,
        },
        "days": int(days),
        "expected_start": str(start),
        "expected_end": str(end),
        "loaded_asset_count": len(rows),
        "load_failures": failures,
        "observed_asset_days": total_observed,
        "expected_asset_days": total_expected,
        "global_coverage": float(total_observed / total_expected) if total_expected else 0.0,
        "minimum_asset_coverage": minimum_asset_coverage,
        "assets": rows,
        "market_cap_data_ready": passed,
        "limitations": [
            "Estimated circulating supply may be reported by projects or third-party APIs.",
            "This adds market-cap weighting to the live-survivor perpetual panel; it does not repair survivorship bias.",
            "Canonical spot-universe replication remains distinct from a perpetual-universe adaptation.",
        ],
    }


def run_market_cap_audit(
    inst_ids: list[str],
    *,
    days: int,
    workers: int = 3,
    force_refresh: bool = False,
) -> dict[str, Any]:
    frames: dict[str, pd.DataFrame] = {}
    failures = []
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 3))) as executor:
        futures = {
            executor.submit(data.load_market_cap_history, inst_id, days, force_refresh): inst_id
            for inst_id in inst_ids
        }
        for future in as_completed(futures):
            inst_id = futures[future]
            try:
                frames[inst_id] = future.result()
                print(f"MARKET_CAP {inst_id} OK rows={len(frames[inst_id])}", flush=True)
            except Exception as exc:
                failures.append({"inst_id": inst_id, "error": str(exc)})
                print(f"MARKET_CAP {inst_id} FAILED {exc}", flush=True)
    failures.sort(key=lambda row: row["inst_id"])
    return audit_market_cap_frames(frames, failures, days=days)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=config.PANEL_HISTORY_DAYS)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()
    report = run_market_cap_audit(
        panel_universe.registry_inst_ids(),
        days=args.days,
        workers=args.workers,
        force_refresh=args.force_refresh,
    )
    out = Path(args.out) if args.out else Path(config.LOG_DIR) / f"panel_market_cap_audit_{report['created_at_utc']}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {out}")
    print(
        f"MARKET_CAP_READY {report['market_cap_data_ready']} "
        f"ASSETS {report['loaded_asset_count']} COVERAGE {report['global_coverage']:.4f} "
        f"MIN_ASSET {report['minimum_asset_coverage']:.4f}"
    )
    return 0 if report["market_cap_data_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
