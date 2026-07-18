"""Panel data and robustness substrate audit.

This script answers a deliberately prior question: is the current panel data
good enough to justify another small AI candidate generation batch?
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import config
import panel_factor_research as panel_research
import panel_universe


LOG_DIR = Path(config.LOG_DIR)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _range_payload(index: pd.DatetimeIndex) -> dict[str, Any]:
    if len(index) == 0:
        return {"bars": 0, "start": None, "end": None, "days": 0.0}
    return {
        "bars": int(len(index)),
        "start": str(index.min()),
        "end": str(index.max()),
        "days": float((index.max() - index.min()).total_seconds() / 86400.0),
    }


def _coverage_ratio(frame: pd.DataFrame, index: pd.DatetimeIndex | None = None) -> float:
    view = frame.reindex(index) if index is not None else frame
    denominator = view.size
    if denominator == 0:
        return 0.0
    return float(view.notna().sum().sum() / denominator)


def _masked_coverage(
    frame: pd.DataFrame,
    mask: pd.DataFrame,
    index: pd.DatetimeIndex | None = None,
) -> float:
    view = frame.reindex(index) if index is not None else frame
    eligible = mask.reindex(index) if index is not None else mask
    eligible = eligible.reindex(index=view.index, columns=view.columns).fillna(False)
    denominator = int(eligible.sum().sum())
    if denominator == 0:
        return 0.0
    return float((view.notna() & eligible).sum().sum() / denominator)


def _open_interest_coverage(
    events: pd.DataFrame,
    eligibility: pd.DataFrame,
    index: pd.DatetimeIndex,
) -> dict[str, Any]:
    event_view = events.reindex(index)
    eligible_view = eligibility.reindex(index).fillna(False)
    by_asset = {}
    total_expected = 0
    total_observed = 0
    for inst_id in eligibility.columns:
        eligible_daily = eligible_view[inst_id].resample("1D").max().astype(bool)
        event_daily = event_view[inst_id].resample("1D").last().notna()
        expected = int(eligible_daily.sum())
        observed = int((event_daily & eligible_daily).sum())
        total_expected += expected
        total_observed += observed
        by_asset[inst_id] = {
            "eligible_days": expected,
            "observed_daily_events": observed,
            "coverage": float(observed / expected) if expected else 0.0,
        }
    return {
        "expected_eligible_asset_days": total_expected,
        "observed_eligible_asset_days": total_observed,
        "coverage": float(total_observed / total_expected) if total_expected else 0.0,
        "by_asset": by_asset,
    }


def _asset_audit(
    inst_id: str,
    item: dict[str, Any],
    common_index: pd.DatetimeIndex,
    eligibility: pd.DataFrame,
) -> dict[str, Any]:
    ohlcv = item["ohlcv"].sort_index()
    spot_ohlcv = item.get("spot_ohlcv")
    funding = item.get("funding")
    close = ohlcv["close"]
    vol_quote = ohlcv.get("vol_quote")
    spot_close = spot_ohlcv["close"].sort_index() if spot_ohlcv is not None else pd.Series(dtype=float)
    common_close = close.reindex(common_index)
    common_spot = spot_close.reindex(common_index) if len(spot_close) else pd.Series(index=common_index, dtype=float)
    basis_valid = common_close.notna() & common_spot.notna() & (common_spot > 0)
    funding_events = int(funding.notna().sum()) if funding is not None else 0
    open_interest = item.get("open_interest")
    oi_index = open_interest.index if open_interest is not None else pd.DatetimeIndex([], tz="UTC")
    market_cap = item.get("market_cap")
    market_cap_index = market_cap.index if market_cap is not None else pd.DatetimeIndex([], tz="UTC")
    funding_span_days = 0.0
    if funding is not None and funding_events:
        funding_span_days = float((funding.dropna().index.max() - funding.dropna().index.min()).total_seconds() / 86400.0)
    return {
        "inst_id": inst_id,
        "ohlcv": _range_payload(ohlcv.index),
        "close_coverage_on_common_index": _coverage_ratio(common_close.to_frame()),
        "median_quote_volume": _safe_float(vol_quote.median()) if vol_quote is not None else None,
        "spot": _range_payload(spot_close.index) if len(spot_close) else {"bars": 0, "start": None, "end": None, "days": 0.0},
        "spot_error": item.get("spot_error"),
        "spot_coverage_on_common_index": _coverage_ratio(common_spot.to_frame()),
        "basis_coverage_on_common_index": float(basis_valid.mean()) if len(basis_valid) else 0.0,
        "funding_events": funding_events,
        "funding_span_days": funding_span_days,
        "funding_events_per_day": float(funding_events / funding_span_days) if funding_span_days > 0 else 0.0,
        "open_interest": _range_payload(oi_index),
        "open_interest_error": item.get("open_interest_error"),
        "market_cap": _range_payload(market_cap_index),
        "market_cap_error": item.get("market_cap_error"),
        "instrument": item.get("instrument"),
        "instrument_error": item.get("instrument_error"),
        "asset_label": item.get("asset_label"),
        "eligible_bars": int(eligibility[inst_id].reindex(common_index).fillna(False).sum()),
    }


def _split_coverage(matrices: dict[str, pd.DataFrame], common_index: pd.DatetimeIndex) -> dict[str, Any]:
    split_indexes = panel_research._split_index(common_index)
    basis = matrices["basis"]
    funding_cost = matrices["funding_cost"]
    close = matrices["close"]
    eligibility = matrices["eligibility"]
    open_interest_events = matrices["open_interest_events"]
    market_cap = matrices["market_cap"]
    out = {}
    for split_name, idx in split_indexes.items():
        eligible_counts = eligibility.reindex(idx).sum(axis=1)
        out[split_name] = {
            **_range_payload(idx),
            "median_assets_with_close": int(close.reindex(idx).notna().sum(axis=1).median()) if len(idx) else 0,
            "median_eligible_assets": float(eligible_counts.median()) if len(idx) else 0.0,
            "p10_eligible_assets": float(eligible_counts.quantile(0.10)) if len(idx) else 0.0,
            "median_top_bottom_assets_per_side": int(np.floor(float(eligible_counts.median()) * 0.30)) if len(idx) else 0,
            "basis_coverage": _masked_coverage(basis, eligibility, idx),
            "funding_event_coverage": _coverage_ratio(funding_cost, idx),
            "funding_event_count": int(funding_cost.reindex(idx).notna().sum().sum()) if len(idx) else 0,
            "open_interest": _open_interest_coverage(open_interest_events, eligibility, idx),
            "market_cap_coverage": _masked_coverage(market_cap, eligibility, idx),
        }
    return out


def _large_liquid_subset(matrices: dict[str, pd.DataFrame], common_index: pd.DatetimeIndex, top_n: int = 8) -> dict[str, Any]:
    returns = matrices["returns"].reindex(common_index)
    liquidity = matrices["formula_library"]["liquidity_size"].reindex(common_index)
    eligibility = matrices["eligibility"].reindex(common_index).fillna(False)
    mask = panel_research._large_liquid_mask(liquidity, eligibility, common_index, top_n=top_n)
    active_assets = list(mask.columns[mask.any(axis=0)])
    subset_returns = returns[active_assets].where(mask[active_assets]) if active_assets else pd.DataFrame(index=common_index)
    corr = (
        subset_returns.corr().where(~np.eye(len(active_assets), dtype=bool)).stack()
        if len(active_assets) > 1
        else pd.Series(dtype=float)
    )
    membership = mask.sum(axis=0).sort_values(ascending=False)
    return {
        "top_n": top_n,
        "selection": "point_in_time_lagged_liquidity_top_n",
        "asset_membership_bars": {name: int(value) for name, value in membership.items() if value > 0},
        "median_assets_available": int(mask.sum(axis=1).median()) if len(mask) else 0,
        "min_assets_available": int(mask.sum(axis=1).min()) if len(mask) else 0,
        "basis_coverage": _masked_coverage(matrices["basis"], mask, common_index),
        "funding_event_coverage": _masked_coverage(matrices["funding_cost"], mask, common_index),
        "median_pairwise_return_corr": _safe_float(corr.median()) if len(corr) else None,
    }


def _liquidity_bucket_summary(matrices: dict[str, pd.DataFrame], common_index: pd.DatetimeIndex) -> dict[str, Any]:
    liquidity = matrices["formula_library"]["liquidity_size"].reindex(common_index)
    basis = matrices["basis"].reindex(common_index)
    funding = matrices["funding_cost"].reindex(common_index)
    counts = {"low": [], "mid": [], "high": []}
    basis_cov = {"low": [], "mid": [], "high": []}
    funding_cov = {"low": [], "mid": [], "high": []}
    for ts, row in liquidity.iterrows():
        valid = row.dropna()
        if len(valid) < 6:
            continue
        labels = pd.qcut(valid.rank(method="first"), q=3, labels=["low", "mid", "high"])
        for bucket in ["low", "mid", "high"]:
            members = labels[labels == bucket].index
            counts[bucket].append(len(members))
            basis_cov[bucket].append(float(basis.loc[ts, members].notna().mean()))
            funding_cov[bucket].append(float(funding.loc[ts, members].notna().mean()))
    return {
        bucket: {
            "median_assets": float(np.median(counts[bucket])) if counts[bucket] else 0.0,
            "basis_coverage": float(np.mean(basis_cov[bucket])) if basis_cov[bucket] else 0.0,
            "funding_event_coverage": float(np.mean(funding_cov[bucket])) if funding_cov[bucket] else 0.0,
        }
        for bucket in ["low", "mid", "high"]
    }


def _crash_windows(matrices: dict[str, pd.DataFrame], common_index: pd.DatetimeIndex, n_windows: int = 5) -> list[dict[str, Any]]:
    eligibility = matrices["eligibility"].reindex(common_index).fillna(False)
    returns = matrices["returns"].reindex(common_index).where(eligibility)
    market_ret = returns.mean(axis=1).rolling(24, min_periods=12).sum().dropna()
    if market_ret.empty:
        return []
    candidates = market_ret.nsmallest(max(n_windows * 4, n_windows))
    windows = []
    used = []
    for ts, ret in candidates.items():
        start = ts - pd.Timedelta(days=3)
        end = ts + pd.Timedelta(days=3)
        if any(abs((ts - old).total_seconds()) < 7 * 86400 for old in used):
            continue
        idx = common_index[(common_index >= start) & (common_index <= end)]
        if len(idx) < 24:
            continue
        used.append(ts)
        windows.append(
            {
                "anchor": str(ts),
                "start": str(idx.min()),
                "end": str(idx.max()),
                "bars": int(len(idx)),
                "market_24h_return": float(ret),
                "median_assets_with_close": int(eligibility.reindex(idx).sum(axis=1).median()),
                "basis_coverage": _masked_coverage(matrices["basis"], eligibility, idx),
                "funding_event_count": int(matrices["funding_cost"].reindex(idx).notna().sum().sum()),
            }
        )
        if len(windows) >= n_windows:
            break
    return windows


def _decision(report: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons = []
    min_assets = int(report.get("min_assets") or getattr(config, "PANEL_MIN_ASSETS", 20))
    if report["loaded_asset_count"] < 30:
        reasons.append("loaded_asset_count_below_30")
    if report["point_in_time_universe"]["eligible_asset_union_count"] < 30:
        reasons.append("eligible_asset_union_below_30")
    if report["point_in_time_universe"]["median_eligible_assets"] < min_assets:
        reasons.append("median_eligible_assets_below_min")
    if min(split["median_eligible_assets"] for split in report["split_coverage"].values()) < min_assets:
        reasons.append("split_eligible_assets_below_min")
    if min(split["median_top_bottom_assets_per_side"] for split in report["split_coverage"].values()) < 6:
        reasons.append("top_bottom_side_breadth_below_6")
    if report["global_coverage"]["basis_coverage"] < 0.85:
        reasons.append("basis_coverage_below_85pct")
    if min(split["basis_coverage"] for split in report["split_coverage"].values()) < 0.80:
        reasons.append("split_basis_coverage_below_80pct")
    if report["global_coverage"]["open_interest"]["coverage"] < 0.80:
        reasons.append("open_interest_daily_coverage_below_80pct")
    if min(split["funding_event_count"] for split in report["split_coverage"].values()) <= 0:
        reasons.append("funding_events_missing_in_a_split")
    if report["funding_history"]["insufficient_assets"]:
        reasons.append("funding_history_below_90pct")
    if report["point_in_time_universe"]["missing_instrument_metadata"]:
        reasons.append("instrument_metadata_missing")
    if report["point_in_time_universe"]["missing_asset_labels"]:
        reasons.append("asset_family_labels_missing")
    if report["large_liquid_subset"]["median_assets_available"] < 8:
        reasons.append("large_liquid_subset_too_small")
    if len(report["crash_windows"]) < 3:
        reasons.append("too_few_crash_windows")
    val_mde = report["design_power_proxy"]["splits"]["Val"]["nominal_rank_ic_mde_80pct"]
    if val_mde > 0.15:
        reasons.append("validation_rank_ic_power_proxy_above_0.15")
    return not reasons, reasons


def build_data_audit(
    panel: dict[str, dict],
    failures: list[dict[str, Any]],
    *,
    days: int,
    min_assets: int,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = registry or panel_universe.load_registry()
    matrices = panel_research._build_matrices(
        panel,
        universe_registry=registry,
        build_factors=False,
    )
    close = matrices["close"]
    eligibility = matrices["eligibility"]
    common_index = eligibility.index[eligibility.sum(axis=1) >= min_assets]
    split_coverage = _split_coverage(matrices, common_index)
    split_indexes = panel_research._split_index(common_index)
    universe_summary = panel_universe.summarize_eligibility(matrices["universe"], split_indexes)
    power_proxy = panel_universe.design_power_proxy(matrices["universe"], split_indexes)
    asset_rows = [
        _asset_audit(inst_id, item, common_index, eligibility)
        for inst_id, item in sorted(panel.items())
    ]
    minimum_funding_span_days = float(days) * 0.90
    insufficient_funding_assets = sorted(
        row["inst_id"]
        for row in asset_rows
        if row["eligible_bars"] > 0 and row["funding_span_days"] < minimum_funding_span_days
    )
    funding_history = {
        "minimum_required_span_days": minimum_funding_span_days,
        "insufficient_assets": insufficient_funding_assets,
        "asset_span_days": {row["inst_id"]: row["funding_span_days"] for row in asset_rows},
    }
    global_coverage = {
        "close_coverage": _coverage_ratio(matrices["close"], common_index),
        "spot_coverage": _masked_coverage(matrices["spot_close"], eligibility, common_index),
        "basis_coverage": _masked_coverage(matrices["basis"], eligibility, common_index),
        "funding_event_coverage": _coverage_ratio(matrices["funding_cost"], common_index),
        "funding_event_count": int(matrices["funding_cost"].reindex(common_index).notna().sum().sum()),
        "open_interest": _open_interest_coverage(matrices["open_interest_events"], eligibility, common_index),
        "market_cap_coverage": _masked_coverage(matrices["market_cap"], eligibility, common_index),
    }
    market_cap_ready = bool(
        global_coverage["market_cap_coverage"] >= 0.95
        and min(split["market_cap_coverage"] for split in split_coverage.values()) >= 0.90
    )
    report = {
        "created_at_utc": _stamp(),
        "schema_version": 2,
        "audit_type": "panel_data_substrate_v2",
        "universe_registry_id": registry["registry_id"],
        "days": int(days),
        "bar": config.BAR,
        "min_assets": int(min_assets),
        "requested_assets": panel_universe.registry_inst_ids(registry),
        "loaded_asset_count": len(panel),
        "load_failures": failures,
        "common_index": {
            **_range_payload(common_index),
            "median_assets_with_close": int(close.reindex(common_index).notna().sum(axis=1).median()) if len(common_index) else 0,
            "min_assets_with_close": int(close.reindex(common_index).notna().sum(axis=1).min()) if len(common_index) else 0,
            "median_eligible_assets": float(eligibility.reindex(common_index).sum(axis=1).median()) if len(common_index) else 0.0,
        },
        "global_coverage": global_coverage,
        "funding_history": funding_history,
        "split_coverage": split_coverage,
        "point_in_time_universe": universe_summary,
        "design_power_proxy": power_proxy,
        "assets": asset_rows,
        "large_liquid_subset": _large_liquid_subset(matrices, common_index),
        "liquidity_buckets": _liquidity_bucket_summary(matrices, common_index),
        "crash_windows": _crash_windows(matrices, common_index),
        "canonical_replication_readiness": {
            "market_cap_data_ready": market_cap_ready,
            "market_cap_global_coverage": global_coverage["market_cap_coverage"],
            "minimum_split_market_cap_coverage": min(
                split["market_cap_coverage"] for split in split_coverage.values()
            ),
            "information_lag_days": 1,
            "ready_for_ltw_canonical_momentum": market_cap_ready,
            "note": "Data readiness does not waive survivorship or instrument-market adaptation limits.",
        },
        "missing_next_data_fields": [
            "delisted_instrument_archive",
            "historical_asset_family_labels",
            *([] if market_cap_ready else ["point_in_time_market_cap"]),
        ],
        "interpretation": "Engineering readiness and permission to generate another AI batch are separate decisions.",
    }
    ok, reasons = _decision(report)
    survivorship_complete = bool(registry["construction"].get("survivorship_complete"))
    evidence_policy = panel_universe.evidence_policy(common_index, registry)
    batch_reasons = list(reasons)
    if not evidence_policy["formal_promotion_allowed"]:
        batch_reasons.append("survivorship_archive_incomplete")
    report["data_substrate_v2_pass"] = bool(ok)
    report["technical_failed_reasons"] = reasons
    report["evidence_policy"] = evidence_policy
    report["retrospective_exploration_allowed"] = bool(ok)
    report["formal_promotion_allowed"] = bool(ok and evidence_policy["formal_promotion_allowed"])
    report["batch1_allowed"] = report["formal_promotion_allowed"]
    report["data_audit_pass_for_batch1"] = report["batch1_allowed"]
    report["failed_reasons"] = batch_reasons
    return report


def write_data_audit(report: dict[str, Any], *, log_dir: Path | str = LOG_DIR) -> Path:
    out_dir = Path(log_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"panel_data_audit_{report['created_at_utc']}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "panel_data_audit_latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=getattr(config, "PANEL_HISTORY_DAYS", config.HISTORY_DAYS))
    parser.add_argument("--symbols", default=",".join(getattr(config, "PANEL_INST_IDS", [config.INST_ID])))
    parser.add_argument("--min-assets", type=int, default=getattr(config, "PANEL_MIN_ASSETS", 8))
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    inst_ids = [item.strip() for item in args.symbols.split(",") if item.strip()]
    loaded_panel, failures = panel_research._load_panel(inst_ids, args.days, force_refresh=args.force_refresh)
    report = build_data_audit(loaded_panel, failures, days=args.days, min_assets=args.min_assets)
    out_path = write_data_audit(report)
    print(f"WROTE {out_path}")
    print(
        "DATA_SUBSTRATE_V2",
        "PASS" if report["data_substrate_v2_pass"] else "FAIL",
        f"BATCH1_ALLOWED {report['batch1_allowed']}",
        f"ASSETS {report['loaded_asset_count']}",
        f"ELIGIBLE_MEDIAN {report['point_in_time_universe']['median_eligible_assets']:.1f}",
        f"BASIS {report['global_coverage']['basis_coverage']:.3f}",
        f"OI {report['global_coverage']['open_interest']['coverage']:.3f}",
        f"FUNDING_EVENTS {report['global_coverage']['funding_event_count']}",
        f"CRASH_WINDOWS {len(report['crash_windows'])}",
    )
    if report["failed_reasons"]:
        print("FAILED_REASONS", ",".join(report["failed_reasons"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
