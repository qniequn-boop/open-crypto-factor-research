"""Run the frozen multi-regime OKX L2 study with resumable cell outputs."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

import config
import crypto_factor_zoo_method as factor_zoo
import okx_l2_pilot as l2


DEFAULT_CONTRACT = Path("OKX_L2_REGIME_SAMPLE_V1.json")
DEFAULT_AMENDMENT = Path("OKX_L2_REGIME_SAMPLE_V1_BUDGET_AMENDMENT.json")
DEFAULT_METADATA = Path(config.LOG_DIR) / "okx_l2_regime_archive_metadata_v1.json"
DEFAULT_CELL_DIR = Path(config.LOG_DIR) / "okx_l2_regime_cells_v1"
DEFAULT_CACHE_DIR = Path(config.CACHE_DIR) / "okx_l2_regime_v1"
DEFAULT_JSON_REPORT = Path(config.LOG_DIR) / "okx_l2_regime_study_v1_20260718.json"
DEFAULT_MD_REPORT = Path(config.LOG_DIR) / "okx_l2_regime_study_v1_20260718.md"
DEFAULT_PROGRESS = Path(config.LOG_DIR) / "okx_l2_regime_study_progress_v1.jsonl"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_sha256(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _named_source_fingerprint(components: dict[str, Any]) -> dict[str, Any]:
    source_hashes = {
        name: hashlib.sha256(inspect.getsource(value).encode("utf-8")).hexdigest()
        for name, value in components.items()
    }
    digest = hashlib.sha256()
    for name, value in sorted(source_hashes.items()):
        digest.update(name.encode("utf-8"))
        digest.update(value.encode("ascii"))
    return {
        "method": "sha256_of_sorted_callable_name_and_source_sha256_v1",
        "bundle_sha256": digest.hexdigest(),
        "components": source_hashes,
    }


def cell_evaluator_fingerprint() -> dict[str, Any]:
    return _named_source_fingerprint(
        {
            "l2.apply_levels": l2.apply_levels,
            "l2._ordered_levels": l2._ordered_levels,
            "l2._sweep": l2._sweep,
            "l2.book_metrics": l2.book_metrics,
            "l2._summary": l2._summary,
            "l2.load_trades": l2.load_trades,
            "l2._iter_l2_messages": l2._iter_l2_messages,
            "l2.analyze_l2_archive": l2.analyze_l2_archive,
        }
    )


def aggregate_evaluator_fingerprint() -> dict[str, Any]:
    return {
        "method": "sha256_of_aggregate_module_files_v1",
        "bundle_sha256": payload_sha256(
            {
                "okx_l2_regime_study.py": file_sha256(Path(__file__)),
                "crypto_factor_zoo_method.py": file_sha256(Path(factor_zoo.__file__)),
            }
        ),
    }


def load_study_contract(
    contract_path: Path | str = DEFAULT_CONTRACT,
    amendment_path: Path | str = DEFAULT_AMENDMENT,
) -> dict[str, Any]:
    contract_path = Path(contract_path)
    amendment_path = Path(amendment_path)
    contract_hash = file_sha256(contract_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    amendment = json.loads(amendment_path.read_text(encoding="utf-8"))
    if contract.get("schema_version") != 1 or amendment.get("schema_version") != 1:
        raise ValueError("unsupported_l2_regime_contract_schema")
    if amendment.get("base_contract_sha256") != contract_hash:
        raise ValueError("l2_budget_amendment_base_contract_mismatch")
    if bool(amendment.get("outcome_data_accessed")) or bool(
        amendment.get("factor_return_data_accessed")
    ):
        raise ValueError("l2_budget_amendment_used_forbidden_outcomes")
    dates = [str(row["date"]) for row in contract.get("unseen_regime_dates") or []]
    assets = [str(value) for value in contract.get("asset_sample") or []]
    if len(dates) != 5 or len(set(dates)) != 5 or len(assets) != 5 or len(set(assets)) != 5:
        raise ValueError("l2_regime_sample_not_five_by_five")
    return {
        "contract": contract,
        "contract_path": str(contract_path),
        "contract_sha256": contract_hash,
        "amendment": amendment,
        "amendment_path": str(amendment_path),
        "amendment_sha256": file_sha256(amendment_path),
    }


def discover_archive_metadata(
    study: dict[str, Any],
    *,
    discover: Callable[..., dict[str, list[dict[str, Any]]]] = l2.discover_pilot_archives,
) -> dict[str, Any]:
    contract = study["contract"]
    assets = list(contract["asset_sample"])
    rows: dict[str, Any] = {}
    l2_size = 0.0
    trade_size = 0.0
    for date_row in contract["unseen_regime_dates"]:
        date_text = str(date_row["date"])
        discovered = discover(assets, date.fromisoformat(date_text))
        book_rows = discovered.get("l2") or []
        trade_rows = discovered.get("trades") or []
        by_asset = {asset: [row for row in book_rows if row["inst_id"] == asset] for asset in assets}
        if any(len(value) != 1 for value in by_asset.values()):
            raise ValueError(f"l2_metadata_cell_coverage_failed:{date_text}")
        if not set(assets).issubset({row["inst_id"] for row in trade_rows}):
            raise ValueError(f"trade_metadata_cell_coverage_failed:{date_text}")
        l2_size += sum(float(row["size_mb"]) for row in book_rows)
        trade_size += sum(float(row["size_mb"]) for row in trade_rows)
        rows[date_text] = {
            "regime_label": str(date_row["label"]),
            "l2": book_rows,
            "trades": trade_rows,
        }
    budgets = study["amendment"]["amended_download_budget"]
    declared_l2_bytes = int(round(l2_size * 1_000_000.0))
    declared_trade_bytes = int(round(trade_size * 1_000_000.0))
    checks = {
        "all_25_l2_cells_declared": sum(len(row["l2"]) for row in rows.values()) == 25,
        "l2_declared_bytes_within_amended_budget": declared_l2_bytes
        <= int(budgets["maximum_compressed_l2_bytes"]),
        "trade_declared_bytes_within_amended_budget": declared_trade_bytes
        <= int(budgets["maximum_compressed_trade_bytes"]),
    }
    if not all(checks.values()):
        raise ValueError(f"l2_archive_metadata_budget_or_coverage_failed:{checks}")
    return {
        "schema_version": 1,
        "audit_type": "okx_l2_regime_archive_metadata_freeze",
        "created_at_utc": _stamp(),
        "outcome_data_accessed": False,
        "factor_return_data_accessed": False,
        "contract": {
            "path": study["contract_path"],
            "sha256": study["contract_sha256"],
        },
        "budget_amendment": {
            "path": study["amendment_path"],
            "sha256": study["amendment_sha256"],
        },
        "declared_l2_size_mb": float(l2_size),
        "declared_trade_size_mb": float(trade_size),
        "declared_l2_bytes": declared_l2_bytes,
        "declared_trade_bytes": declared_trade_bytes,
        "checks": checks,
        "dates": rows,
    }


def write_json_immutable(payload: dict[str, Any], path: Path | str) -> tuple[Path, bool]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if payload_sha256(existing) != payload_sha256(payload):
            raise ValueError(f"immutable_json_conflict:{path}")
        return path, False
    with os.fdopen(fd, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return path, True


def _append_progress(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _cell_path(cell_dir: Path, date_text: str, inst_id: str) -> Path:
    return cell_dir / f"{date_text}__{inst_id}.json"


def _downloaded_l2_bytes(cache_dir: Path) -> int:
    return sum(path.stat().st_size for path in cache_dir.glob("*-L2orderbook-400lv-*.tar.gz"))


def _downloaded_trade_bytes(cache_dir: Path) -> int:
    return sum(path.stat().st_size for path in cache_dir.glob("*.zip"))


def run_cells(
    study: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    cell_dir: Path = DEFAULT_CELL_DIR,
    progress_path: Path = DEFAULT_PROGRESS,
    max_cells: int | None = None,
) -> dict[str, Any]:
    contract = study["contract"]
    specs = l2.fetch_instrument_specs(contract["asset_sample"])
    sample = contract["sampling_contract"]
    sample_interval_ms = int(sample["sample_interval_seconds"]) * 1000
    budgets = study["amendment"]["amended_download_budget"]
    evaluator = cell_evaluator_fingerprint()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cell_dir.mkdir(parents=True, exist_ok=True)
    completed = 0
    skipped = 0
    for date_row in contract["unseen_regime_dates"]:
        date_text = str(date_row["date"])
        start_ms, end_ms = l2._day_bounds(date.fromisoformat(date_text))
        date_meta = metadata["dates"][date_text]
        for inst_id in contract["asset_sample"]:
            output = _cell_path(cell_dir, date_text, inst_id)
            if output.exists():
                existing = json.loads(output.read_text(encoding="utf-8"))
                if existing.get("contract_sha256") != study["contract_sha256"]:
                    raise ValueError(f"existing_cell_contract_mismatch:{output}")
                if existing.get("cell_evaluator_sha256") != evaluator["bundle_sha256"]:
                    raise ValueError(f"existing_cell_evaluator_mismatch:{output}")
                skipped += 1
                continue
            if max_cells is not None and completed >= int(max_cells):
                return {"completed": completed, "skipped": skipped, "stopped_at_max_cells": True}
            book_rows = [row for row in date_meta["l2"] if row["inst_id"] == inst_id]
            trade_rows = [row for row in date_meta["trades"] if row["inst_id"] == inst_id]
            if len(book_rows) != 1 or not trade_rows:
                raise ValueError(f"cell_archive_metadata_missing:{date_text}:{inst_id}")
            book_destination = cache_dir / book_rows[0]["filename"]
            missing_l2_mb = 0.0 if book_destination.exists() else float(book_rows[0]["size_mb"])
            projected_l2 = _downloaded_l2_bytes(cache_dir) + int(round(missing_l2_mb * 1_000_000.0))
            missing_trade_mb = sum(
                float(row["size_mb"])
                for row in trade_rows
                if not (cache_dir / row["filename"]).exists()
            )
            projected_trade = _downloaded_trade_bytes(cache_dir) + int(round(missing_trade_mb * 1_000_000.0))
            if projected_l2 > int(budgets["maximum_compressed_l2_bytes"]):
                raise ValueError("l2_actual_download_would_exceed_amended_budget")
            if projected_trade > int(budgets["maximum_compressed_trade_bytes"]):
                raise ValueError("trade_actual_download_would_exceed_amended_budget")
            _append_progress(
                progress_path,
                {"at_utc": _stamp(), "status": "cell_started", "date": date_text, "inst_id": inst_id},
            )
            downloaded = l2.download_archives(
                {"l2": book_rows, "trades": trade_rows},
                cache_dir,
            )
            trades = l2.load_trades(
                [Path(row["path"]) for row in downloaded["trades"]],
                inst_id=inst_id,
                start_ms=start_ms,
                end_ms_exclusive=end_ms,
            )
            analysis = l2.analyze_l2_archive(
                Path(downloaded["l2"][0]["path"]),
                spec=specs[inst_id],
                trades=trades,
                start_ms=start_ms,
                end_ms_exclusive=end_ms,
                sample_interval_ms=sample_interval_ms,
                depth_bps=sample["depth_bands_bps"],
                notionals=sample["market_order_notionals_usdt"],
            )
            payload = {
                "schema_version": 1,
                "audit_type": "okx_l2_regime_asset_date_cell",
                "created_at_utc": _stamp(),
                "contract_sha256": study["contract_sha256"],
                "budget_amendment_sha256": study["amendment_sha256"],
                "metadata_sha256": payload_sha256(metadata),
                "cell_evaluator_sha256": evaluator["bundle_sha256"],
                "cell_evaluator_fingerprint": evaluator,
                "date": date_text,
                "regime_label": str(date_row["label"]),
                "inst_id": inst_id,
                "sample_interval_ms": sample_interval_ms,
                "archive_provenance": downloaded,
                "analysis": analysis,
            }
            write_json_immutable(payload, output)
            completed += 1
            _append_progress(
                progress_path,
                {
                    "at_utc": _stamp(),
                    "status": "cell_completed",
                    "date": date_text,
                    "inst_id": inst_id,
                    "cell_path": str(output),
                    "cell_sha256": file_sha256(output),
                    "coverage_fraction": analysis["sampling"]["coverage_fraction"],
                },
            )
    return {"completed": completed, "skipped": skipped, "stopped_at_max_cells": False}


def _proxy_value(inst_id: str, date_text: str, *, days: int = 1095) -> dict[str, Any]:
    source = Path(config.CACHE_DIR) / f"{inst_id}_1H_{int(days)}d.parquet"
    if not source.exists():
        raise FileNotFoundError(f"missing_proxy_hourly_cache:{source}")
    hourly = pd.read_parquet(source)
    if hourly.index.tz is None:
        hourly.index = hourly.index.tz_localize("UTC")
    daily = factor_zoo.aggregate_hourly_ohlcv_to_daily(hourly)
    proxy = factor_zoo.factor_zoo_bidask_spread(daily["high"], daily["low"], daily["close"])
    target = pd.Timestamp(date_text, tz="UTC")
    value = proxy.get(target)
    return {
        "full_spread_bps": None if value is None or pd.isna(value) else float(value) * 10_000.0,
        "source_path": str(source),
        "source_sha256": file_sha256(source),
    }


def _number(summary: dict[str, Any], name: str) -> float | None:
    value = summary.get(name)
    return None if value is None or not math.isfinite(float(value)) else float(value)


def _cell_cost_rows(cell: dict[str, Any], fee_bps: float) -> list[dict[str, Any]]:
    analysis = cell["analysis"]
    rows = []
    for notional, sides in analysis["market_order_impact_bps"].items():
        buy_median = _number(sides["buy"], "median")
        sell_median = _number(sides["sell"], "median")
        buy_p95 = _number(sides["buy"], "p95")
        sell_p95 = _number(sides["sell"], "p95")
        medians = [value for value in (buy_median, sell_median) if value is not None]
        p95s = [value for value in (buy_p95, sell_p95) if value is not None]
        median_one_way = fee_bps + float(np.mean(medians)) if len(medians) == 2 else None
        p95_one_way = fee_bps + max(p95s) if len(p95s) == 2 else None
        rows.append(
            {
                "date": cell["date"],
                "regime_label": cell["regime_label"],
                "inst_id": cell["inst_id"],
                "notional_usdt": float(notional),
                "median_one_way_cost_bps": median_one_way,
                "p95_one_way_cost_bps": p95_one_way,
                "p95_round_trip_cost_bps": None if p95_one_way is None else 2.0 * p95_one_way,
                "buy_fill_fraction": float(sides["buy_fill_fraction"]),
                "sell_fill_fraction": float(sides["sell_fill_fraction"]),
            }
        )
    return rows


def aggregate_study(
    study: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cell_dir: Path = DEFAULT_CELL_DIR,
    proxy_loader: Callable[[str, str], dict[str, Any]] = _proxy_value,
) -> dict[str, Any]:
    contract = study["contract"]
    assets = list(contract["asset_sample"])
    date_rows = list(contract["unseen_regime_dates"])
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    cell_evaluator = cell_evaluator_fingerprint()
    aggregate_evaluator = aggregate_evaluator_fingerprint()
    missing = []
    for date_row in date_rows:
        date_text = str(date_row["date"])
        for inst_id in assets:
            path = _cell_path(cell_dir, date_text, inst_id)
            if not path.exists():
                missing.append({"date": date_text, "inst_id": inst_id})
                continue
            cell = json.loads(path.read_text(encoding="utf-8"))
            if cell.get("contract_sha256") != study["contract_sha256"]:
                raise ValueError(f"aggregate_cell_contract_mismatch:{path}")
            if cell.get("cell_evaluator_sha256") != cell_evaluator["bundle_sha256"]:
                raise ValueError(f"aggregate_cell_evaluator_mismatch:{path}")
            cells[(date_text, inst_id)] = cell

    min_coverage = float(contract["admission_checks"]["minimum_complete_sample_fraction"])
    cell_summaries = []
    cost_rows = []
    complete_by_asset = {asset: 0 for asset in assets}
    complete_by_date = {str(row["date"]): 0 for row in date_rows}
    proxy_rows: dict[str, list[dict[str, Any]]] = {}
    for (date_text, inst_id), cell in cells.items():
        analysis = cell["analysis"]
        coverage = float(analysis["sampling"]["coverage_fraction"])
        complete = bool(
            coverage >= min_coverage
            and analysis["book_integrity"]["snapshot_count"] >= 1
            and analysis["book_integrity"]["monotonic_timestamp_violations"] == 0
        )
        if complete:
            complete_by_asset[inst_id] += 1
            complete_by_date[date_text] += 1
        proxy = proxy_loader(inst_id, date_text)
        l2_quoted = _number(analysis["quoted_spread_bps"], "median")
        proxy_rows.setdefault(date_text, []).append(
            {
                "inst_id": inst_id,
                "complete": complete,
                "proxy_full_spread_bps": proxy["full_spread_bps"],
                "l2_median_quoted_spread_bps": l2_quoted,
                "proxy_source": proxy,
            }
        )
        cell_summaries.append(
            {
                "date": date_text,
                "regime_label": cell["regime_label"],
                "inst_id": inst_id,
                "coverage_fraction": coverage,
                "complete": complete,
                "median_quoted_spread_bps": l2_quoted,
                "weighted_one_way_effective_slippage_bps": analysis["effective_spread_bps"].get(
                    "quote_notional_weighted_one_way_slippage_bps"
                ),
                "maximum_event_gap_ms": analysis["book_integrity"]["maximum_event_gap_ms"],
                "cell_path": str(_cell_path(cell_dir, date_text, inst_id)),
                "cell_sha256": file_sha256(_cell_path(cell_dir, date_text, inst_id)),
            }
        )
        cost_rows.extend(
            _cell_cost_rows(cell, float(contract["sampling_contract"]["fee_bps_one_way"]))
        )

    rank_by_date = {}
    rank_values = []
    for date_row in date_rows:
        date_text = str(date_row["date"])
        frame = pd.DataFrame(proxy_rows.get(date_text) or [])
        if len(frame):
            frame = frame.loc[frame["complete"]].dropna(
                subset=["proxy_full_spread_bps", "l2_median_quoted_spread_bps"]
            )
        spearman = (
            float(frame[["proxy_full_spread_bps", "l2_median_quoted_spread_bps"]].corr(method="spearman").iloc[0, 1])
            if len(frame) >= 4
            else None
        )
        if spearman is not None and math.isfinite(spearman):
            rank_values.append(spearman)
        rank_by_date[date_text] = {
            "regime_label": str(date_row["label"]),
            "asset_count": int(len(frame)),
            "spearman": spearman,
            "positive": bool(spearman is not None and spearman > 0),
            "rows": frame.to_dict(orient="records") if len(frame) else [],
        }

    cost_frame = pd.DataFrame(cost_rows)
    cost_surface = []
    if len(cost_frame):
        for (inst_id, notional), frame in cost_frame.groupby(["inst_id", "notional_usdt"]):
            medians = frame["median_one_way_cost_bps"].dropna()
            p95s = frame["p95_one_way_cost_bps"].dropna()
            observed_stress = float(p95s.max()) if len(p95s) else None
            cost_surface.append(
                {
                    "inst_id": str(inst_id),
                    "notional_usdt": float(notional),
                    "regime_day_count": int(len(frame)),
                    "median_one_way_cost_bps": float(medians.median()) if len(medians) else None,
                    "observed_regime_p95_one_way_cost_bps": observed_stress,
                    "observed_regime_p95_round_trip_cost_bps": None
                    if observed_stress is None
                    else 2.0 * observed_stress,
                    "double_p95_visible_cost_stress_bps_one_way": None
                    if observed_stress is None
                    else 2.0 * observed_stress,
                    "minimum_buy_fill_fraction": float(frame["buy_fill_fraction"].min()),
                    "minimum_sell_fill_fraction": float(frame["sell_fill_fraction"].min()),
                    "break_even_turnover_formula": "gross_alpha_bps / median_one_way_cost_bps",
                    "annual_cost_drag_formula": "median_one_way_cost_bps * realized_turnover_per_rebalance * rebalances_per_year",
                }
            )

    checks_contract = contract["admission_checks"]
    qualifying_dates = sum(value >= 4 for value in complete_by_date.values())
    qualifying_assets = sum(
        value >= int(checks_contract["minimum_unseen_dates_with_data"])
        for value in complete_by_asset.values()
    )
    positive_dates = sum(bool(row["positive"]) for row in rank_by_date.values())
    median_spearman = float(np.median(rank_values)) if rank_values else None
    operational_checks = {
        "all_25_frozen_cells_present": len(cells) == 25 and not missing,
        "all_present_cells_meet_integrity_and_coverage": all(
            row["complete"] for row in cell_summaries
        ),
    }
    checks = {
        "minimum_unseen_dates_with_data": qualifying_dates
        >= int(checks_contract["minimum_unseen_dates_with_data"]),
        "minimum_assets_with_four_unseen_dates": qualifying_assets
        >= int(checks_contract["minimum_assets_with_four_unseen_dates"]),
        "minimum_complete_sample_fraction": operational_checks[
            "all_present_cells_meet_integrity_and_coverage"
        ],
        "minimum_dates_with_positive_proxy_rank": positive_dates
        >= int(checks_contract["minimum_dates_with_positive_cross_sectional_proxy_rank_correlation"]),
        "minimum_median_cross_sectional_spearman": median_spearman is not None
        and median_spearman >= float(checks_contract["minimum_median_cross_sectional_spearman"]),
    }
    authorized = all(checks.values())
    return {
        "schema_version": 1,
        "audit_type": "okx_l2_frozen_multiregime_cost_and_proxy_study",
        "created_at_utc": _stamp(),
        "claim_ceiling": "five_asset_five_regime_okx_visible_book_cost_surface_and_proxy_admission_only",
        "factor_generated": False,
        "parameter_search_performed": False,
        "trial_registry_changed": False,
        "promotion_state_changed": False,
        "contract": {
            "path": study["contract_path"],
            "sha256": study["contract_sha256"],
            "budget_amendment_path": study["amendment_path"],
            "budget_amendment_sha256": study["amendment_sha256"],
            "metadata_sha256": payload_sha256(metadata),
            "cell_evaluator_sha256": cell_evaluator["bundle_sha256"],
            "aggregate_evaluator_sha256": aggregate_evaluator["bundle_sha256"],
        },
        "missing_cells": missing,
        "complete_cells": int(sum(row["complete"] for row in cell_summaries)),
        "complete_by_asset": complete_by_asset,
        "complete_by_date": complete_by_date,
        "cell_summaries": cell_summaries,
        "cost_surface": cost_surface,
        "cost_surface_policy": {
            "same_surface_for_all_factors": True,
            "visible_book_only": True,
            "fee_bps_one_way": float(contract["sampling_contract"]["fee_bps_one_way"]),
            "latency_queue_rejection_buffer": "not_identified_by_historical_archive",
            "production_full_cost_calibration": False,
            "stress_sensitivity": "double the worst frozen-regime p95 visible one-way all-in cost",
        },
        "proxy_rank_by_date": rank_by_date,
        "proxy_rank_summary": {
            "dates_with_positive_spearman": positive_dates,
            "median_spearman": median_spearman,
            "valid_date_count": len(rank_values),
        },
        "operational_checks": operational_checks,
        "admission_checks": checks,
        "decision": {
            "microstructure_source_authorized": authorized,
            "authorized_paths": ["canonical_bidask", "canonical_turnover_volatility"]
            if authorized
            else [],
            "visible_book_cost_surface_supported": checks["minimum_unseen_dates_with_data"]
            and checks["minimum_assets_with_four_unseen_dates"]
            and checks["minimum_complete_sample_fraction"],
            "full_production_cost_model_supported": False,
            "reason": "all preregistered proxy and coverage gates passed"
            if authorized
            else "one or more preregistered proxy or coverage gates failed",
        },
        "limitations": [
            "The surface covers five current OKX perpetuals and five frozen days, not the broad crypto population.",
            "Current contract metadata is applied to historical archives; historical contract-spec changes are not independently reconstructed.",
            "Visible-book sweeps exclude latency, queueing, hidden liquidity, rejects, and outages.",
            "The OHLC proxy may rank liquidity but never calibrates execution-cost magnitude.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    def _fmt(value: Any, pattern: str = ".4f") -> str:
        if value is None:
            return "NA"
        number = float(value)
        return format(number, pattern) if math.isfinite(number) else "NA"

    decision = report["decision"]
    rank = report["proxy_rank_summary"]
    lines = [
        "# OKX Frozen Multi-Regime L2 Study",
        "",
        f"Created: {report['created_at_utc']}",
        "",
        "## Decision",
        "",
        f"- Complete frozen cells: `{report['complete_cells']}/25`",
        f"- Visible-book cost surface supported: `{decision['visible_book_cost_surface_supported']}`",
        f"- Microstructure source authorized: `{decision['microstructure_source_authorized']}`",
        f"- Full production cost model supported: `{decision['full_production_cost_model_supported']}`",
        f"- Positive proxy-rank dates: `{rank['dates_with_positive_spearman']}`",
        f"- Median cross-sectional Spearman: `{rank['median_spearman']}`",
        "",
        "Historical L2 determines spread, visible impact, and capacity. It does",
        "not identify latency, queueing, rejection, hidden-liquidity, or outage cost.",
        "",
        "## Admission Checks",
        "",
    ]
    lines.extend(f"- {name}: `{value}`" for name, value in report["admission_checks"].items())
    lines.extend(
        [
            "",
            "## Factory-Wide Cost Surface",
            "",
            "| Asset | Notional | Median one-way | Worst regime p95 one-way | Worst p95 round trip | Min buy/sell fill |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["cost_surface"]:
        lines.append(
            f"| {row['inst_id']} | {_fmt(row['notional_usdt'], '.0f')} | "
            f"{_fmt(row['median_one_way_cost_bps'])} | "
            f"{_fmt(row['observed_regime_p95_one_way_cost_bps'])} | "
            f"{_fmt(row['observed_regime_p95_round_trip_cost_bps'])} | "
            f"{_fmt(row['minimum_buy_fill_fraction'], '.2%')}/"
            f"{_fmt(row['minimum_sell_fill_fraction'], '.2%')} |"
        )
    lines.extend(["", "## Proxy Rank By Date", ""])
    for date_text, row in report["proxy_rank_by_date"].items():
        lines.append(
            f"- {date_text} ({row['regime_label']}): n={row['asset_count']}, Spearman={row['spearman']}"
        )
    lines.extend(["", "## Limits", "", *[f"- {value}" for value in report["limitations"]]])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--amendment", type=Path, default=DEFAULT_AMENDMENT)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--cell-dir", type=Path, default=DEFAULT_CELL_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument("--md-report", type=Path, default=DEFAULT_MD_REPORT)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--aggregate", action="store_true")
    parser.add_argument("--max-cells", type=int)
    args = parser.parse_args()
    study = load_study_contract(args.contract, args.amendment)
    if args.metadata.exists():
        metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
        if metadata.get("contract", {}).get("sha256") != study["contract_sha256"]:
            raise ValueError("existing_metadata_contract_mismatch")
    else:
        metadata = discover_archive_metadata(study)
        write_json_immutable(metadata, args.metadata)
        print(f"METADATA {args.metadata}")
    if args.metadata_only and not args.execute and not args.aggregate:
        return
    if args.execute:
        state = run_cells(
            study,
            metadata,
            cache_dir=args.cache_dir,
            cell_dir=args.cell_dir,
            progress_path=args.progress,
            max_cells=args.max_cells,
        )
        print("CELL_STATE", json.dumps(state, sort_keys=True))
    if args.aggregate:
        report = aggregate_study(study, metadata, cell_dir=args.cell_dir)
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.md_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(
            json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        args.md_report.write_text(render_markdown(report), encoding="utf-8")
        print(f"JSON_REPORT {args.json_report}")
        print(f"MD_REPORT {args.md_report}")
        print("SOURCE_AUTHORIZED", report["decision"]["microstructure_source_authorized"])


if __name__ == "__main__":
    main()
