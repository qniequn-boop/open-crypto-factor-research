"""Point-in-time universe rules for the panel factor factory."""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd


REGISTRY_PATH = Path(__file__).with_name("PANEL_UNIVERSE_REGISTRY.json")


def load_registry(path: Path | str = REGISTRY_PATH) -> dict[str, Any]:
    registry = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate_registry(registry)
    if errors:
        raise ValueError("invalid panel universe registry: " + ";".join(errors))
    return registry


def validate_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if registry.get("schema_version") != 1:
        errors.append("schema_version_must_be_1")
    assets = registry.get("assets")
    if not isinstance(assets, list) or not assets:
        return errors + ["assets_must_be_nonempty_list"]
    allowed_families = set(registry.get("asset_families") or [])
    seen: set[str] = set()
    for row in assets:
        inst_id = str(row.get("inst_id") or "")
        if not inst_id.endswith("-USDT-SWAP"):
            errors.append(f"invalid_inst_id:{inst_id}")
        if inst_id in seen:
            errors.append(f"duplicate_inst_id:{inst_id}")
        seen.add(inst_id)
        if row.get("asset_family") not in allowed_families:
            errors.append(f"unknown_asset_family:{inst_id}")
    rules = registry.get("point_in_time_rules") or {}
    for name in (
        "target_size",
        "min_listing_age_days",
        "min_observed_history_days",
        "liquidity_lookback_days",
        "liquidity_min_period_days",
        "min_avg_daily_quote_volume_usd",
        "selection_lag_hours",
    ):
        if float(rules.get(name) or 0) <= 0:
            errors.append(f"invalid_rule:{name}")
    return errors


def registry_inst_ids(registry: dict[str, Any] | None = None) -> list[str]:
    registry = registry or load_registry()
    return [str(row["inst_id"]) for row in registry["assets"]]


def registry_asset_map(registry: dict[str, Any] | None = None) -> dict[str, dict[str, str]]:
    registry = registry or load_registry()
    return {str(row["inst_id"]): dict(row) for row in registry["assets"]}


def evidence_policy(
    index: pd.DatetimeIndex,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the preregistered promotion ceiling for the observed sample."""
    registry = registry or load_registry()
    construction = registry["construction"]
    survivorship_complete = bool(construction.get("survivorship_complete"))
    prospective_raw = construction.get("prospective_start_utc")
    prospective_start = pd.Timestamp(prospective_raw) if prospective_raw else None
    if prospective_start is not None and prospective_start.tzinfo is None:
        prospective_start = prospective_start.tz_localize("UTC")
    sample_start = pd.Timestamp(index.min()) if len(index) else None
    prospective_only = bool(
        sample_start is not None
        and prospective_start is not None
        and sample_start >= prospective_start
    )
    formal_promotion_allowed = bool(survivorship_complete or prospective_only)
    return {
        "mode": (
            "survivorship_complete_retrospective"
            if survivorship_complete
            else "prospective_only"
            if prospective_only
            else str(construction.get("retrospective_mode", "survivor_conditioned_exploration"))
        ),
        "sample_start": str(sample_start) if sample_start is not None else None,
        "prospective_start": str(prospective_start) if prospective_start is not None else None,
        "survivorship_complete": survivorship_complete,
        "prospective_only": prospective_only,
        "formal_promotion_allowed": formal_promotion_allowed,
        "promotion_ceiling": "panel_factor_pass" if formal_promotion_allowed else "panel_factor_watchlist",
    }


def _bar_hours(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return 1.0
    deltas = index.to_series().diff().dropna().dt.total_seconds() / 3600.0
    median = float(deltas.median()) if len(deltas) else 1.0
    return median if median > 0 else 1.0


def _listing_timestamp(item: dict[str, Any]) -> tuple[pd.Timestamp | None, str]:
    meta = item.get("instrument") or {}
    value = meta.get("list_time_ms", meta.get("listTime", meta.get("list_time")))
    if value not in (None, ""):
        try:
            if isinstance(value, (int, float)) or str(value).isdigit():
                return pd.to_datetime(int(value), unit="ms", utc=True), "okx_list_time"
            timestamp = pd.Timestamp(value)
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize("UTC")
            else:
                timestamp = timestamp.tz_convert("UTC")
            return timestamp, "okx_list_time"
        except Exception:
            pass
    return None, "missing"


def top_n_mask(values: pd.DataFrame, base_mask: pd.DataFrame, top_n: int) -> pd.DataFrame:
    ranks = values.where(base_mask).rank(axis=1, ascending=False, method="first")
    return base_mask & ranks.le(int(top_n))


def build_point_in_time_eligibility(
    panel: dict[str, dict[str, Any]],
    close: pd.DataFrame,
    vol_quote: pd.DataFrame,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = registry or load_registry()
    rules = registry["point_in_time_rules"]
    index = close.index
    columns = close.columns
    bar_hours = _bar_hours(index)
    bars_per_day = max(1, int(round(24.0 / bar_hours)))

    listing_age_days = pd.DataFrame(np.nan, index=index, columns=columns)
    metadata_sources: dict[str, str] = {}
    listing_times: dict[str, str | None] = {}
    for inst_id in columns:
        listed_at, source = _listing_timestamp(panel.get(inst_id, {}))
        metadata_sources[inst_id] = source
        listing_times[inst_id] = str(listed_at) if listed_at is not None else None
        if listed_at is not None:
            listing_age_days[inst_id] = (index - listed_at).total_seconds() / 86400.0

    metadata_ok = listing_age_days.notna()
    age_ok = listing_age_days.ge(float(rules["min_listing_age_days"]))

    min_history_bars = max(
        1,
        int(
            math.ceil(
                float(rules["min_observed_history_days"])
                * bars_per_day
                * float(rules.get("min_history_coverage_ratio", 1.0))
            )
        ),
    )
    observed_history_bars = close.notna().cumsum()
    history_ok = observed_history_bars.ge(min_history_bars)

    lookback_bars = max(1, int(round(float(rules["liquidity_lookback_days"]) * bars_per_day)))
    min_liquidity_bars = max(1, int(round(float(rules["liquidity_min_period_days"]) * bars_per_day)))
    lag_bars = max(1, int(round(float(rules["selection_lag_hours"]) / bar_hours)))
    trailing_avg_daily_quote_volume = (
        vol_quote.shift(lag_bars)
        .rolling(lookback_bars, min_periods=min_liquidity_bars)
        .sum()
        / float(rules["liquidity_lookback_days"])
    )
    liquidity_ok = trailing_avg_daily_quote_volume.ge(float(rules["min_avg_daily_quote_volume_usd"]))
    base_mask = close.notna() & metadata_ok & age_ok & history_ok & liquidity_ok
    eligibility = top_n_mask(trailing_avg_daily_quote_volume, base_mask, int(rules["target_size"]))

    asset_map = registry_asset_map(registry)
    labels = {inst_id: (asset_map.get(inst_id) or {}).get("asset_family") for inst_id in columns}
    return {
        "eligibility": eligibility.fillna(False),
        "base_eligibility": base_mask.fillna(False),
        "listing_age_days": listing_age_days,
        "observed_history_bars": observed_history_bars,
        "trailing_avg_daily_quote_volume": trailing_avg_daily_quote_volume,
        "metadata_sources": metadata_sources,
        "listing_times": listing_times,
        "asset_labels": labels,
        "rules": dict(rules),
        "bar_hours": bar_hours,
        "bars_per_day": bars_per_day,
        "min_history_bars": min_history_bars,
        "survivorship": dict(registry["construction"]),
    }


def summarize_eligibility(
    universe: dict[str, Any],
    split_indexes: dict[str, pd.DatetimeIndex],
) -> dict[str, Any]:
    eligibility = universe["eligibility"]
    counts = eligibility.sum(axis=1)
    analysis_index = pd.DatetimeIndex([])
    for index in split_indexes.values():
        analysis_index = analysis_index.union(index)
    analysis_counts = counts.reindex(analysis_index).dropna()
    by_split: dict[str, Any] = {}
    for name, index in split_indexes.items():
        split_counts = counts.reindex(index).dropna()
        median_count = float(split_counts.median()) if len(split_counts) else 0.0
        by_split[name] = {
            "bars": int(len(index)),
            "median_eligible_assets": median_count,
            "p10_eligible_assets": float(split_counts.quantile(0.10)) if len(split_counts) else 0.0,
            "min_eligible_assets": int(split_counts.min()) if len(split_counts) else 0,
            "median_top_bottom_assets_per_side": int(math.floor(median_count * 0.30)),
        }
    missing_metadata = sorted(name for name, source in universe["metadata_sources"].items() if source == "missing")
    missing_labels = sorted(name for name, label in universe["asset_labels"].items() if not label)
    return {
        "rules": universe["rules"],
        "median_eligible_assets": float(analysis_counts.median()) if len(analysis_counts) else 0.0,
        "p10_eligible_assets": float(analysis_counts.quantile(0.10)) if len(analysis_counts) else 0.0,
        "max_eligible_assets": int(analysis_counts.max()) if len(analysis_counts) else 0,
        "full_timeline_including_warmup": {
            "bars": int(len(counts)),
            "median_eligible_assets": float(counts.median()) if len(counts) else 0.0,
            "p10_eligible_assets": float(counts.quantile(0.10)) if len(counts) else 0.0,
            "zero_eligible_bars": int((counts == 0).sum()),
        },
        "eligible_asset_union": sorted(eligibility.columns[eligibility.any(axis=0)]),
        "eligible_asset_union_count": int(eligibility.any(axis=0).sum()),
        "missing_instrument_metadata": missing_metadata,
        "missing_asset_labels": missing_labels,
        "listing_times": universe["listing_times"],
        "by_split": by_split,
        "survivorship": universe["survivorship"],
    }


def design_power_proxy(
    universe: dict[str, Any],
    split_indexes: dict[str, pd.DatetimeIndex],
) -> dict[str, Any]:
    rules = universe["rules"]
    eligibility = universe["eligibility"]
    bars_per_day = int(universe["bars_per_day"])
    trial_budget = int(rules.get("next_batch_trial_budget", 10))
    block_days = int(rules.get("power_block_days", 7))
    alpha = 0.05 / max(trial_budget, 1)
    z_alpha = NormalDist().inv_cdf(1.0 - alpha)
    z_power = NormalDist().inv_cdf(0.80)
    rows: dict[str, Any] = {}
    for name, index in split_indexes.items():
        sampled = index[::bars_per_day]
        counts = eligibility.reindex(sampled).sum(axis=1)
        median_assets = float(counts.median()) if len(counts) else 0.0
        effective_blocks = max(1, int(len(sampled) // max(block_days, 1)))
        denominator = math.sqrt(max((median_assets - 1.0) * effective_blocks, 1.0))
        mde = (z_alpha + z_power) / denominator
        rows[name] = {
            "daily_rebalances": int(len(sampled)),
            "conservative_effective_blocks": effective_blocks,
            "median_eligible_assets": median_assets,
            "sidak_like_alpha_per_trial": alpha,
            "nominal_rank_ic_mde_80pct": float(mde),
        }
    return {
        "method": "conservative_fisher_style_proxy_with_nonoverlapping_time_blocks",
        "warning": "This is a design breadth proxy, not a substitute for block bootstrap or realized IC inference.",
        "trial_budget": trial_budget,
        "block_days": block_days,
        "splits": rows,
    }
