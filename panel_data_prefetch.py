"""Bounded-concurrency cache prefetch for the registered panel universe."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import data


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def prefetch_asset(
    inst_id: str,
    days: int,
    force_refresh: bool = False,
    include_funding: bool = True,
) -> dict[str, Any]:
    row: dict[str, Any] = {"inst_id": inst_id, "fields": {}, "complete": True}
    loaders = {
        "perpetual_ohlcv": lambda: data.load_data(inst_id, config.BAR, days, force_refresh=force_refresh),
        "spot_ohlcv": lambda: data.load_spot_data(inst_id, config.BAR, days, force_refresh=force_refresh),
        "open_interest_daily": lambda: data.load_open_interest_history(
            inst_id,
            days=days,
            period="1D",
            force_refresh=force_refresh,
        ),
        "market_cap_daily": lambda: data.load_market_cap_history(
            inst_id,
            days=days,
            force_refresh=force_refresh,
        ),
    }
    if include_funding:
        loaders["funding"] = lambda: data.load_funding_rates(inst_id, days, force_refresh=force_refresh)
    for field, loader in loaders.items():
        try:
            value = loader()
            if field in {"perpetual_ohlcv", "spot_ohlcv", "funding", "open_interest_daily", "market_cap_daily"} and len(value):
                span_days = float((value.index.max() - value.index.min()).total_seconds() / 86400.0)
                if span_days < days * 0.90:
                    raise ValueError(
                        f"history coverage below 90%: field={field} span_days={span_days:.1f} requested={days}"
                    )
            row["fields"][field] = {"status": "ok", "rows": int(len(value))}
        except Exception as exc:
            row["fields"][field] = {"status": "failed", "error": str(exc)}
            row["complete"] = False
    return row


def run_prefetch(
    inst_ids: list[str],
    *,
    days: int,
    workers: int,
    force_refresh: bool = False,
    include_funding: bool = True,
) -> dict[str, Any]:
    requested_workers = max(1, int(workers))
    workers = 1 if include_funding else min(requested_workers, 3)
    data.load_instruments("SWAP", force_refresh=force_refresh)
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(prefetch_asset, inst_id, days, force_refresh, include_funding): inst_id
            for inst_id in inst_ids
        }
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            failed = [name for name, value in row["fields"].items() if value["status"] != "ok"]
            print(
                "PREFETCH",
                row["inst_id"],
                "OK" if row["complete"] else "PARTIAL",
                "failed=" + (",".join(failed) if failed else "none"),
                flush=True,
            )
    rows.sort(key=lambda row: inst_ids.index(row["inst_id"]))
    return {
        "created_at_utc": _stamp(),
        "days": int(days),
        "workers": workers,
        "include_funding": include_funding,
        "requested_assets": inst_ids,
        "complete_assets": int(sum(row["complete"] for row in rows)),
        "partial_assets": int(sum(not row["complete"] for row in rows)),
        "assets": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=config.PANEL_HISTORY_DAYS)
    parser.add_argument("--symbols", help="Comma-separated override; defaults to the registered pool")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--skip-funding", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    inst_ids = (
        [item.strip() for item in args.symbols.split(",") if item.strip()]
        if args.symbols
        else list(config.PANEL_INST_IDS)
    )
    inst_ids = inst_ids[max(0, args.offset):]
    if args.limit is not None:
        inst_ids = inst_ids[:max(0, args.limit)]
    report = run_prefetch(
        inst_ids,
        days=args.days,
        workers=args.workers,
        force_refresh=args.force_refresh,
        include_funding=not args.skip_funding,
    )
    out_dir = Path(config.LOG_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"panel_data_prefetch_{report['created_at_utc']}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {out_path}")
    return 0 if report["partial_assets"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
