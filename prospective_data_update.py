"""Daily incremental data update and quality audit for the prospective panel."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import config
import data
import panel_universe


LOG_DIR = Path(config.LOG_DIR)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _age_hours(index: pd.DatetimeIndex, now: pd.Timestamp) -> float | None:
    if not len(index):
        return None
    return float((now - index.max()).total_seconds() / 3600.0)


def _span_days(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return 0.0
    return float((index.max() - index.min()).total_seconds() / 86400.0)


def _basis_coverage(perpetual: pd.DataFrame, spot: pd.DataFrame, now: pd.Timestamp) -> float:
    cutoff = now - pd.Timedelta(days=30)
    perp_close = perpetual.loc[perpetual.index >= cutoff, "close"]
    spot_close = spot.loc[spot.index >= cutoff, "close"].reindex(perp_close.index)
    return float((perp_close.notna() & spot_close.notna()).mean()) if len(perp_close) else 0.0


def update_asset(inst_id: str, *, days: int, now: pd.Timestamp) -> dict[str, Any]:
    row: dict[str, Any] = {"inst_id": inst_id, "status": "failed", "checks": {}}
    try:
        perpetual = data.refresh_ohlcv_cache_incremental(inst_id, config.BAR, days)
        spot = data.refresh_ohlcv_cache_incremental(inst_id, config.BAR, days, spot=True)
        funding = data.refresh_funding_cache_incremental(inst_id, days)
        open_interest = data.refresh_open_interest_cache_incremental(inst_id, days, period="1D")
        metrics = {
            "perpetual_rows": int(len(perpetual)),
            "spot_rows": int(len(spot)),
            "funding_event_count": int(len(funding)),
            "open_interest_event_count": int(len(open_interest)),
            "perpetual_age_hours": _age_hours(perpetual.index, now),
            "spot_age_hours": _age_hours(spot.index, now),
            "funding_age_hours": _age_hours(funding.index, now),
            "open_interest_age_hours": _age_hours(open_interest.index, now),
            "perpetual_span_days": _span_days(perpetual.index),
            "spot_span_days": _span_days(spot.index),
            "funding_span_days": _span_days(funding.index),
            "open_interest_span_days": _span_days(open_interest.index),
            "basis_coverage_30d": _basis_coverage(perpetual, spot, now),
        }
        checks = {
            "perpetual_recent": metrics["perpetual_age_hours"] is not None and metrics["perpetual_age_hours"] <= 3.0,
            "spot_recent": metrics["spot_age_hours"] is not None and metrics["spot_age_hours"] <= 3.0,
            "funding_recent": metrics["funding_age_hours"] is not None and metrics["funding_age_hours"] <= 12.0,
            "open_interest_recent": metrics["open_interest_age_hours"] is not None and metrics["open_interest_age_hours"] <= 48.0,
            "perpetual_history_90pct": metrics["perpetual_span_days"] >= days * 0.90,
            "spot_history_90pct": metrics["spot_span_days"] >= days * 0.90,
            "funding_history_90pct": metrics["funding_span_days"] >= days * 0.90,
            "open_interest_history_90pct": metrics["open_interest_span_days"] >= days * 0.90,
            "basis_coverage_30d_95pct": metrics["basis_coverage_30d"] >= 0.95,
        }
        row.update(
            {
                "status": "pass" if all(checks.values()) else "failed",
                "metrics": metrics,
                "checks": checks,
                "failed_checks": [name for name, passed in checks.items() if not passed],
            }
        )
    except Exception as exc:
        row["error"] = str(exc)
        row["failed_checks"] = ["update_exception"]
    return row


def run_update(inst_ids: list[str], *, days: int, now: pd.Timestamp | None = None) -> dict[str, Any]:
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    else:
        now = now.tz_convert("UTC")
    rows = []
    for inst_id in inst_ids:
        row = update_asset(inst_id, days=days, now=now)
        rows.append(row)
        print("UPDATE", inst_id, row["status"].upper(), ",".join(row.get("failed_checks", [])) or "none", flush=True)
    failed_assets = [row["inst_id"] for row in rows if row["status"] != "pass"]
    return {
        "created_at_utc": now.isoformat(),
        "schema_version": 1,
        "audit_type": "prospective_daily_data_update",
        "registry_id": panel_universe.load_registry()["registry_id"],
        "days": int(days),
        "requested_asset_count": len(inst_ids),
        "passed_asset_count": len(rows) - len(failed_assets),
        "failed_asset_count": len(failed_assets),
        "failed_assets": failed_assets,
        "overall_status": "pass" if not failed_assets else "failed",
        "assets": rows,
    }


def write_report(report: dict[str, Any], *, log_dir: Path | str = LOG_DIR) -> Path:
    out_dir = Path(log_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp(report["created_at_utc"]).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"prospective_data_update_{stamp}.json"
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    path.write_text(encoded, encoding="utf-8")
    latest = out_dir / "prospective_data_update_latest.json"
    tmp = latest.with_suffix(".json.tmp")
    tmp.write_text(encoded, encoding="utf-8")
    os.replace(tmp, latest)
    with (out_dir / "prospective_data_update_runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "created_at_utc": report["created_at_utc"],
                    "overall_status": report["overall_status"],
                    "passed_asset_count": report["passed_asset_count"],
                    "failed_asset_count": report["failed_asset_count"],
                    "report_path": str(path),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=config.PANEL_HISTORY_DAYS)
    parser.add_argument("--symbols", help="Comma-separated override")
    args = parser.parse_args()
    inst_ids = (
        [item.strip() for item in args.symbols.split(",") if item.strip()]
        if args.symbols
        else panel_universe.registry_inst_ids()
    )
    report = run_update(inst_ids, days=args.days)
    path = write_report(report)
    print("WROTE", path, "STATUS", report["overall_status"])
    return 0 if report["overall_status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
