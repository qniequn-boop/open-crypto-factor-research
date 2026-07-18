"""Run frozen, method-faithful literature adaptations on the panel substrate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import config
import panel_candidate_registry
import panel_factor_research as panel
import panel_gate_calibration
import panel_gate_policy_v3
import panel_universe


DEFAULT_BATCH_PATH = Path("LITERATURE_REPLICATION_BATCH_001.json")
PERP_CARRY_REPLICATION_ID = "GORNALL_PERP_BASIS_MECHANISM"
LOW_VOL_REPLICATION_ID = "PYO_JANG_LOW_VOL_MONTHLY"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _locked_input_hashes() -> dict[str, str]:
    return {
        "universe_registry_sha256": _sha256(Path("PANEL_UNIVERSE_REGISTRY.json")),
        "literature_registry_sha256": _sha256(Path("LITERATURE_REPLICATION_REGISTRY.json")),
        "market_cap_audit_sha256": _sha256(Path("logs/panel_market_cap_audit_20260714.json")),
    }


def _locked_code_hashes() -> dict[str, str]:
    return {
        "panel_literature_replication_sha256": _sha256(Path(__file__)),
        "panel_factor_research_sha256": _sha256(Path(panel.__file__)),
        "panel_gate_calibration_sha256": _sha256(Path(panel_gate_calibration.__file__)),
        "panel_gate_policy_v3_sha256": _sha256(Path(panel_gate_policy_v3.__file__)),
    }


def _cache_file_state(path: Path, cutoff: pd.Timestamp) -> dict[str, Any]:
    state: dict[str, Any] = {"path": str(path), "exists": path.exists(), "history_ready": False}
    if not path.exists():
        return state
    try:
        frame = pd.read_parquet(path)
        index = pd.DatetimeIndex(frame.index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")
        oldest = index.min() if len(index) else None
        newest = index.max() if len(index) else None
        state.update(
            {
                "rows": int(len(index)),
                "oldest": str(oldest) if oldest is not None else None,
                "newest": str(newest) if newest is not None else None,
                "history_ready": bool(oldest is not None and oldest <= cutoff + pd.Timedelta(days=7)),
            }
        )
    except Exception as exc:
        state["error"] = str(exc)
    return state


def replication_cache_preflight(
    batch_path: Path = DEFAULT_BATCH_PATH,
    *,
    as_of: pd.Timestamp | None = None,
) -> dict[str, Any]:
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    actual_hashes = _locked_input_hashes()
    batch_as_of = batch.get("evaluation_end_utc")
    now = pd.Timestamp.now(tz="UTC") if as_of is None and not batch_as_of else pd.Timestamp(as_of or batch_as_of)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    if batch.get("replication_id") == LOW_VOL_REPLICATION_ID:
        artifacts = batch["frozen_implementation"]
        days = int(artifacts["history_days"])
        bar = str(artifacts["bar"])
        cutoff = now - pd.Timedelta(days=days)
        rows = []
        for inst_id in panel_universe.registry_inst_ids():
            spot_inst_id = panel.data_module.swap_to_spot_inst_id(inst_id)
            state = _cache_file_state(
                panel.data_module._spot_cache_path(spot_inst_id, bar, days),
                cutoff,
            )
            any_history = bool(state.get("exists") and int(state.get("rows", 0)) > 0)
            rows.append(
                {
                    "inst_id": inst_id,
                    "ready": any_history,
                    "fields": {"spot_daily": state},
                }
            )
        actual_code_hashes = _locked_code_hashes()
        expected_code_hashes = batch.get("locked_code")
        hashes_match = actual_hashes == batch["locked_inputs"]
        code_hashes_match = expected_code_hashes is None or actual_code_hashes == expected_code_hashes
        instrument_cache = panel.data_module._instrument_cache_path("SWAP")
        early_assets = sum(row["fields"]["spot_daily"]["history_ready"] for row in rows)
        any_assets = sum(row["ready"] for row in rows)
        minimum_start_assets = int(artifacts["minimum_assets"])
        ready = (
            hashes_match
            and code_hashes_match
            and instrument_cache.exists()
            and any_assets == len(rows)
            and early_assets >= minimum_start_assets
        )
        return {
            "created_at_utc": _stamp(),
            "audit_type": "frozen_literature_replication_preflight",
            "batch_id": batch["batch_id"],
            "batch_sha256": _sha256(batch_path),
            "hashes_match": hashes_match,
            "expected_locked_input_hashes": batch["locked_inputs"],
            "actual_locked_input_hashes": actual_hashes,
            "expected_locked_code_hashes": expected_code_hashes,
            "actual_locked_code_hashes": actual_code_hashes,
            "code_hashes_match": code_hashes_match,
            "instrument_cache": {"path": str(instrument_cache), "exists": instrument_cache.exists()},
            "required_asset_count": len(rows),
            "required_fields": ["spot_daily"],
            "ready_asset_count": any_assets,
            "ready_field_counts": {"spot_daily": any_assets},
            "start_coverage_asset_count": early_assets,
            "minimum_start_coverage_assets": minimum_start_assets,
            "missing_or_incomplete_assets": {
                "spot_daily": [row["inst_id"] for row in rows if not row["ready"]],
            },
            "assets": rows,
            "replication_ready": ready,
            "network_requests_made": False,
            "trial_registry_events_written": False,
        }
    days = int(config.PANEL_HISTORY_DAYS)
    cutoff = now - pd.Timedelta(days=days)
    requires_spot = batch.get("replication_id") == PERP_CARRY_REPLICATION_ID
    required_fields = ["ohlcv", "funding", "market_cap"]
    if requires_spot:
        required_fields.append("spot")
    rows = []
    for inst_id in panel_universe.registry_inst_ids():
        fields = {
            "ohlcv": _cache_file_state(panel.data_module._cache_path(inst_id, config.BAR, days), cutoff),
            "funding": _cache_file_state(panel.data_module._funding_cache_path(inst_id, days), cutoff),
            "market_cap": _cache_file_state(panel.data_module._market_cap_cache_path(inst_id, days), cutoff),
        }
        if requires_spot:
            spot_inst_id = panel.data_module.swap_to_spot_inst_id(inst_id)
            fields["spot"] = _cache_file_state(
                panel.data_module._spot_cache_path(spot_inst_id, config.BAR, days),
                cutoff,
            )
        rows.append(
            {
                "inst_id": inst_id,
                "ready": all(item["history_ready"] for item in fields.values()),
                "fields": fields,
            }
        )
    counts = {
        field: sum(row["fields"][field]["history_ready"] for row in rows)
        for field in required_fields
    }
    missing = {
        field: [row["inst_id"] for row in rows if not row["fields"][field]["history_ready"]]
        for field in required_fields
    }
    hashes_match = actual_hashes == batch["locked_inputs"]
    actual_code_hashes = _locked_code_hashes()
    expected_code_hashes = batch.get("locked_code")
    code_hashes_match = expected_code_hashes is None or actual_code_hashes == expected_code_hashes
    instrument_cache = panel.data_module._instrument_cache_path("SWAP")
    ready = hashes_match and code_hashes_match and instrument_cache.exists() and all(row["ready"] for row in rows)
    return {
        "created_at_utc": _stamp(),
        "audit_type": "frozen_literature_replication_preflight",
        "batch_id": batch["batch_id"],
        "batch_sha256": _sha256(batch_path),
        "hashes_match": hashes_match,
        "expected_locked_input_hashes": batch["locked_inputs"],
        "actual_locked_input_hashes": actual_hashes,
        "expected_locked_code_hashes": expected_code_hashes,
        "actual_locked_code_hashes": actual_code_hashes,
        "code_hashes_match": code_hashes_match,
        "instrument_cache": {"path": str(instrument_cache), "exists": instrument_cache.exists()},
        "required_asset_count": len(rows),
        "required_fields": required_fields,
        "ready_asset_count": sum(row["ready"] for row in rows),
        "ready_field_counts": counts,
        "missing_or_incomplete_assets": missing,
        "assets": rows,
        "replication_ready": ready,
        "network_requests_made": False,
        "trial_registry_events_written": False,
    }


def _mean_tstat(values: pd.Series) -> float:
    clean = values.replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3 or float(clean.std(ddof=1)) <= 0:
        return 0.0
    return float(clean.mean() / (clean.std(ddof=1) / math.sqrt(len(clean))))


def _normal_sf(value: float) -> float:
    return 0.5 * math.erfc(float(value) / math.sqrt(2.0))


def _load_daily_spot_panel(
    inst_ids: list[str],
    *,
    bar: str,
    days: int,
    evaluation_end_utc: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    instruments = panel.data_module.load_instruments("SWAP")
    evaluation_end = pd.Timestamp(evaluation_end_utc)
    evaluation_end = (
        evaluation_end.tz_localize("UTC")
        if evaluation_end.tzinfo is None
        else evaluation_end.tz_convert("UTC")
    )
    loaded: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    for inst_id in inst_ids:
        try:
            spot = panel.data_module.load_spot_data(inst_id, bar=bar, days=days)
            spot = spot.loc[spot.index <= evaluation_end].copy()
            if spot.empty:
                raise ValueError("no_daily_spot_rows_before_evaluation_end")
            instrument = None
            if inst_id in instruments.index:
                row = instruments.loc[inst_id]
                instrument = {
                    "inst_id": inst_id,
                    "state": row.get("state"),
                    "list_time_ms": (
                        int(row["list_time_ms"])
                        if pd.notna(row.get("list_time_ms"))
                        else None
                    ),
                    "list_time": (
                        str(row.get("list_time"))
                        if pd.notna(row.get("list_time"))
                        else None
                    ),
                }
            loaded[inst_id] = {"spot_ohlcv": spot, "instrument": instrument}
        except Exception as exc:
            failures.append({"inst_id": inst_id, "error": str(exc)})
    return loaded, failures


def _daily_spot_input_fingerprint(loaded: dict[str, dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for inst_id in sorted(loaded):
        frame = loaded[inst_id]["spot_ohlcv"][["close", "vol_quote"]].sort_index()
        digest.update(inst_id.encode("utf-8"))
        digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
    return digest.hexdigest()


def _month_end_formation_times(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index[index.is_month_end]


def _source_period_split_indexes(
    common_index: pd.DatetimeIndex,
    *,
    source_sample_end_utc: str,
    is_fraction: float,
) -> dict[str, pd.DatetimeIndex]:
    source_end = pd.Timestamp(source_sample_end_utc)
    source_end = source_end.tz_localize("UTC") if source_end.tzinfo is None else source_end.tz_convert("UTC")
    selection = common_index[common_index <= source_end]
    holdout = common_index[common_index > source_end]
    formations = _month_end_formation_times(selection)
    if len(formations) < 3:
        raise ValueError("insufficient_monthly_formations_for_source_period_split")
    split_count = min(max(int(math.floor(len(formations) * float(is_fraction))), 1), len(formations) - 1)
    boundary = formations[split_count - 1]
    return {
        "IS": selection[selection <= boundary],
        "Val": selection[selection > boundary],
        "Holdout": holdout,
    }


def _trailing_low_vol_signal(
    close: pd.DataFrame,
    formation_times: pd.DatetimeIndex,
    eligibility: pd.DataFrame,
    *,
    lookback_days: int,
    minimum_coverage_fraction: float,
) -> pd.DataFrame:
    daily_log_return = np.log((close / close.shift(1)).where(close > 0))
    minimum_days = max(3, int(math.ceil(int(lookback_days) * float(minimum_coverage_fraction))))
    realized_volatility = daily_log_return.rolling(
        int(lookback_days),
        min_periods=minimum_days,
    ).std()
    return (-realized_volatility).reindex(formation_times).where(
        eligibility.reindex(formation_times).fillna(False)
    )


def _next_formation_return(
    close: pd.DataFrame,
    formation_times: pd.DatetimeIndex,
) -> pd.DataFrame:
    at_formation = close.reindex(formation_times)
    return at_formation.shift(-1) / at_formation - 1.0


def _execute_monthly_targets(
    formation_weights: pd.DataFrame,
    daily_index: pd.DatetimeIndex,
    *,
    execution_lag_days: int,
) -> pd.DataFrame:
    targets = formation_weights.reindex(daily_index).ffill()
    return targets.shift(int(execution_lag_days)).fillna(0.0)


def _spot_portfolio_metrics_with_monthly_hac(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    split_index: pd.DatetimeIndex,
    *,
    max_lag_months: int,
    include_return_series: bool = False,
) -> dict[str, Any]:
    funding = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    metrics = panel._portfolio_metrics_from_weights(
        weights,
        returns,
        funding,
        split_index,
        include_net_returns=True,
    )
    daily_net = metrics.pop("_net_return_series")
    monthly_net = daily_net.resample("ME").sum(min_count=1).dropna()
    inference = panel_gate_calibration.newey_west_mean_tstat(
        monthly_net,
        max_lag=int(max_lag_months),
    )
    metrics["monthly_observations"] = int(len(monthly_net))
    metrics["monthly_net_return_hac"] = {
        **inference,
        "raw_one_sided_p": (
            _normal_sf(float(inference["tstat"]))
            if inference["valid"]
            else 1.0
        ),
    }
    if include_return_series:
        metrics["_daily_net_return_series"] = daily_net
        metrics["_monthly_net_return_series"] = monthly_net
    return metrics


def _rolling_monthly_return_audit(
    monthly_returns: pd.Series,
    *,
    window_months: int,
) -> dict[str, Any]:
    clean = monthly_returns.replace([np.inf, -np.inf], np.nan).dropna()
    rolling = clean.rolling(int(window_months), min_periods=int(window_months)).sum().dropna()
    return {
        "window_months": int(window_months),
        "window_count": int(len(rolling)),
        "positive_window_count": int((rolling > 0).sum()),
        "positive_window_fraction": float((rolling > 0).mean()) if len(rolling) else 0.0,
        "minimum_window_return": float(rolling.min()) if len(rolling) else 0.0,
    }


def _permutation_mean_ic_control(
    signal: pd.DataFrame,
    forward_returns: pd.DataFrame,
    mask: pd.DataFrame,
    split_index: pd.DatetimeIndex,
    *,
    minimum_assets: int,
    permutations: int,
    seed: int,
) -> dict[str, Any]:
    formations = signal.index[(signal.index >= split_index.min()) & (signal.index <= split_index.max())]
    pairs: list[tuple[np.ndarray, np.ndarray]] = []
    observed_values: list[float] = []
    for ts in formations:
        frame = pd.concat(
            [signal.loc[ts].rename("signal"), forward_returns.loc[ts].rename("forward")],
            axis=1,
        ).where(mask.loc[ts], np.nan).dropna()
        if len(frame) < int(minimum_assets):
            continue
        observed = float(frame["signal"].corr(frame["forward"], method="spearman"))
        observed_values.append(observed)
        pairs.append((frame["signal"].to_numpy(dtype=float), frame["forward"].to_numpy(dtype=float)))
    observed_mean = float(np.mean(observed_values)) if observed_values else 0.0
    rng = np.random.default_rng(int(seed))
    null_means = []
    for _ in range(int(permutations)):
        values = []
        for signal_values, forward_values in pairs:
            permuted = rng.permutation(signal_values)
            values.append(float(pd.Series(permuted).corr(pd.Series(forward_values), method="spearman")))
        null_means.append(float(np.mean(values)) if values else 0.0)
    null = np.asarray(null_means, dtype=float)
    empirical_p = (
        float((1 + int((null >= observed_mean).sum())) / (len(null) + 1))
        if len(null)
        else 1.0
    )
    return {
        "observed_mean_rank_ic": observed_mean,
        "permutations": int(permutations),
        "seed": int(seed),
        "null_median_mean_rank_ic": float(np.median(null)) if len(null) else 0.0,
        "null_p95_mean_rank_ic": float(np.quantile(null, 0.95)) if len(null) else 0.0,
        "empirical_one_sided_p": empirical_p,
    }


def _formation_times(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index[(index.dayofweek == 0) & (index.hour == 0) & (index.minute == 0)]


def _scope_mask(
    eligibility: pd.DataFrame,
    market_cap: pd.DataFrame,
    formation_times: pd.DatetimeIndex,
    scope: str,
) -> pd.DataFrame:
    mask = eligibility.reindex(formation_times).fillna(False) & market_cap.reindex(formation_times).notna()
    if scope == "registered_point_in_time_eligible_panel":
        return mask
    if scope != "above_median_point_in_time_market_cap_within_registered_panel":
        raise ValueError(f"unsupported_replication_scope:{scope}")
    out = pd.DataFrame(False, index=formation_times, columns=eligibility.columns)
    caps = market_cap.reindex(formation_times)
    for ts in formation_times:
        valid = caps.loc[ts].where(mask.loc[ts]).dropna()
        if len(valid):
            out.loc[ts, valid[valid >= valid.median()].index] = True
    return out


def _value_weighted_30_40_30_weights(
    signal: pd.DataFrame,
    market_cap: pd.DataFrame,
    scope_mask: pd.DataFrame,
    *,
    min_assets: int,
    side_fraction: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    weights = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)
    breadth = []
    valid_formations = 0
    for ts in signal.index:
        valid = pd.concat(
            [signal.loc[ts].rename("signal"), market_cap.loc[ts].rename("market_cap")],
            axis=1,
        ).where(scope_mask.loc[ts], np.nan).dropna()
        valid = valid[valid["market_cap"] > 0]
        breadth.append(len(valid))
        if len(valid) < min_assets:
            continue
        side_count = max(1, int(math.floor(len(valid) * float(side_fraction))))
        bottom = valid.nsmallest(side_count, "signal")
        top = valid.nlargest(side_count, "signal")
        if top["market_cap"].sum() <= 0 or bottom["market_cap"].sum() <= 0:
            continue
        weights.loc[ts, top.index] = 0.5 * top["market_cap"] / top["market_cap"].sum()
        weights.loc[ts, bottom.index] = -0.5 * bottom["market_cap"] / bottom["market_cap"].sum()
        valid_formations += 1
    return weights, {
        "formation_count": int(len(signal.index)),
        "valid_formation_count": valid_formations,
        "median_formation_breadth": float(np.median(breadth)) if breadth else 0.0,
        "minimum_formation_breadth": int(min(breadth)) if breadth else 0,
    }


def _execute_and_hold(
    formation_weights: pd.DataFrame,
    intraday_index: pd.DatetimeIndex,
    *,
    execution_lag_bars: int,
    holding_hours: int,
) -> pd.DataFrame:
    held = pd.DataFrame(0.0, index=intraday_index, columns=formation_weights.columns)
    index_positions = {timestamp: position for position, timestamp in enumerate(intraday_index)}
    if len(intraday_index) < 2:
        return held
    median_bar = intraday_index.to_series().diff().median()
    holding_bars = max(int(pd.Timedelta(hours=holding_hours) / median_bar), 1)
    for ts, row in formation_weights.iterrows():
        formation_position = index_positions.get(ts)
        if formation_position is None:
            continue
        start = formation_position + int(execution_lag_bars)
        end = min(start + holding_bars, len(intraday_index))
        if start < len(intraday_index):
            held.iloc[start:end] = row.to_numpy(dtype=float)
    return held


def _weekly_ic(
    signal: pd.DataFrame,
    forward_returns: pd.DataFrame,
    scope_mask: pd.DataFrame,
    *,
    min_assets: int,
) -> pd.Series:
    values = {}
    for ts in signal.index:
        pair = pd.concat(
            [signal.loc[ts].rename("signal"), forward_returns.loc[ts].rename("forward")],
            axis=1,
        ).where(scope_mask.loc[ts], np.nan).dropna()
        values[ts] = float(pair["signal"].corr(pair["forward"], method="spearman")) if len(pair) >= min_assets else np.nan
    return pd.Series(values, dtype=float).sort_index()


def _split_ic(ic: pd.Series, split_index: pd.DatetimeIndex) -> dict[str, Any]:
    if len(split_index):
        clean = ic[(ic.index >= split_index.min()) & (ic.index <= split_index.max())].dropna()
    else:
        clean = pd.Series(dtype=float)
    tstat = _mean_tstat(clean)
    return {
        "observations": int(len(clean)),
        "mean_rank_ic": float(clean.mean()) if len(clean) else 0.0,
        "positive_ic_frac": float((clean > 0).mean()) if len(clean) else 0.0,
        "weekly_mean_tstat": tstat,
        "raw_one_sided_p": _normal_sf(tstat),
    }


def _daily_formation_times(index: pd.DatetimeIndex, *, hour_utc: int) -> pd.DatetimeIndex:
    return index[(index.hour == int(hour_utc)) & (index.minute == 0)]


def _daily_log_return(close: pd.DataFrame, *, periods: int) -> pd.DataFrame:
    ratio = close / close.shift(int(periods))
    return np.log(ratio.where(ratio > 0))


def _trailing_daily_amihud(
    close: pd.DataFrame,
    dollar_volume: pd.DataFrame,
    formation_times: pd.DatetimeIndex,
    *,
    lookback_days: int,
    bars_per_day: int,
    information_lag_days: int,
) -> pd.DataFrame:
    daily_return = _daily_log_return(close, periods=bars_per_day).reindex(formation_times)
    daily_volume = dollar_volume.rolling(bars_per_day, min_periods=bars_per_day).sum().reindex(formation_times)
    daily_illiquidity = daily_return.abs() / daily_volume.where(daily_volume > 0)
    lagged = daily_illiquidity.shift(int(information_lag_days))
    return lagged.rolling(int(lookback_days), min_periods=int(lookback_days)).mean()


def _ranked_segment_mask(
    values: pd.DataFrame,
    eligibility: pd.DataFrame,
    formation_times: pd.DatetimeIndex,
    *,
    segment_assets: int,
    largest: bool,
    required_values: pd.DataFrame | None = None,
) -> pd.DataFrame:
    eligible = eligibility.reindex(formation_times).fillna(False)
    ranked_values = values.reindex(formation_times)
    base = eligible & ranked_values.notna()
    if required_values is not None:
        required = required_values.reindex(formation_times)
        base &= required.notna() & required.gt(0)
    ranks = ranked_values.where(base).rank(axis=1, ascending=not largest, method="first")
    return base & ranks.le(int(segment_assets))


def _quintile_long_short_weights(
    signal: pd.DataFrame,
    market_cap: pd.DataFrame,
    scope_mask: pd.DataFrame,
    *,
    min_assets: int,
    side_fraction: float,
    weighting_mode: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if weighting_mode not in {"equal_weighted", "point_in_time_market_cap_value_weighted"}:
        raise ValueError(f"unsupported_literature_weighting_mode:{weighting_mode}")
    weights = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)
    breadth: list[int] = []
    side_counts: list[int] = []
    valid_formations = 0
    for ts in signal.index:
        valid = pd.concat(
            [signal.loc[ts].rename("signal"), market_cap.loc[ts].rename("market_cap")],
            axis=1,
        ).where(scope_mask.loc[ts], np.nan).dropna()
        valid = valid[valid["market_cap"] > 0]
        breadth.append(len(valid))
        if len(valid) < int(min_assets):
            continue
        side_count = max(1, int(math.floor(len(valid) * float(side_fraction))))
        ordered = valid.sort_values("signal", kind="mergesort")
        bottom = ordered.iloc[:side_count]
        top = ordered.iloc[-side_count:]
        if set(top.index) & set(bottom.index):
            continue
        if weighting_mode == "equal_weighted":
            weights.loc[ts, top.index] = 0.5 / len(top)
            weights.loc[ts, bottom.index] = -0.5 / len(bottom)
        else:
            if top["market_cap"].sum() <= 0 or bottom["market_cap"].sum() <= 0:
                continue
            weights.loc[ts, top.index] = 0.5 * top["market_cap"] / top["market_cap"].sum()
            weights.loc[ts, bottom.index] = -0.5 * bottom["market_cap"] / bottom["market_cap"].sum()
        side_counts.append(side_count)
        valid_formations += 1
    return weights, {
        "formation_count": int(len(signal.index)),
        "valid_formation_count": valid_formations,
        "median_formation_breadth": float(np.median(breadth)) if breadth else 0.0,
        "minimum_formation_breadth": int(min(breadth)) if breadth else 0,
        "median_assets_per_side": float(np.median(side_counts)) if side_counts else 0.0,
    }


def _split_daily_ic_hac(
    ic: pd.Series,
    split_index: pd.DatetimeIndex,
    *,
    max_lag: int,
) -> dict[str, Any]:
    if len(split_index):
        clean = ic[(ic.index >= split_index.min()) & (ic.index <= split_index.max())].dropna()
    else:
        clean = pd.Series(dtype=float)
    inference = panel_gate_calibration.newey_west_mean_tstat(clean, max_lag=int(max_lag))
    tstat = float(inference["tstat"])
    return {
        "observations": int(len(clean)),
        "mean_rank_ic": float(clean.mean()) if len(clean) else 0.0,
        "positive_ic_frac": float((clean > 0).mean()) if len(clean) else 0.0,
        "daily_hac_mean_tstat": tstat,
        "raw_one_sided_p": _normal_sf(tstat) if inference["valid"] else 1.0,
        "newey_west": inference,
    }


def _split_monthly_ic_hac(
    ic: pd.Series,
    split_index: pd.DatetimeIndex,
    *,
    max_lag: int,
) -> dict[str, Any]:
    if len(split_index):
        clean = ic[(ic.index >= split_index.min()) & (ic.index <= split_index.max())].dropna()
    else:
        clean = pd.Series(dtype=float)
    inference = panel_gate_calibration.newey_west_mean_tstat(clean, max_lag=int(max_lag))
    tstat = float(inference["tstat"])
    return {
        "observations": int(len(clean)),
        "mean_rank_ic": float(clean.mean()) if len(clean) else 0.0,
        "positive_ic_frac": float((clean > 0).mean()) if len(clean) else 0.0,
        "monthly_hac_mean_tstat": tstat,
        "raw_one_sided_p": _normal_sf(tstat) if inference["valid"] else 1.0,
        "newey_west": inference,
    }


def _portfolio_metrics_with_daily_hac(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    funding: pd.DataFrame,
    split_index: pd.DatetimeIndex,
    *,
    max_lag: int,
) -> dict[str, Any]:
    metrics = panel._portfolio_metrics_from_weights(
        weights,
        returns,
        funding,
        split_index,
        include_net_returns=True,
    )
    net_returns = metrics.pop("_net_return_series")
    daily_returns = net_returns.resample("1D").sum(min_count=1).dropna()
    inference = panel_gate_calibration.newey_west_mean_tstat(daily_returns, max_lag=int(max_lag))
    metrics["daily_net_return_hac"] = {
        **inference,
        "raw_one_sided_p": _normal_sf(float(inference["tstat"])) if inference["valid"] else 1.0,
    }
    return metrics


def _trailing_realized_funding(
    funding_events: pd.DataFrame,
    formation_times: pd.DatetimeIndex,
    *,
    lookback_bars: int,
    information_lag_bars: int,
) -> pd.DataFrame:
    lagged = funding_events.shift(int(information_lag_bars))
    return lagged.rolling(int(lookback_bars), min_periods=1).sum().reindex(formation_times)


def _perp_carry_signal_frames(
    basis: pd.DataFrame,
    funding_events: pd.DataFrame,
    eligibility: pd.DataFrame,
    formation_times: pd.DatetimeIndex,
    *,
    funding_lookback_bars: int,
    information_lag_bars: int,
) -> dict[str, pd.DataFrame]:
    basis_at_formation = basis.reindex(formation_times)
    eligible = eligibility.reindex(formation_times).fillna(False)
    trailing_funding = _trailing_realized_funding(
        funding_events,
        formation_times,
        lookback_bars=funding_lookback_bars,
        information_lag_bars=information_lag_bars,
    )
    positive_basis = basis_at_formation.where(eligible & basis_at_formation.gt(0))
    positive_funding = trailing_funding.where(eligible & trailing_funding.gt(0))
    aligned = positive_basis.notna() & positive_funding.notna()
    basis_rank = positive_basis.rank(axis=1, pct=True, method="average")
    funding_rank = positive_funding.rank(axis=1, pct=True, method="average")
    return {
        "positive_basis": positive_basis,
        "positive_trailing_funding": positive_funding,
        "basis_funding_alignment": ((basis_rank + funding_rank) / 2.0).where(aligned),
    }


def _top_n_pair_weights(
    signal: pd.DataFrame,
    *,
    top_n: int,
    pair_gross_exposure: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    weights = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)
    breadth: list[int] = []
    valid_formations = 0
    for ts in signal.index:
        valid = signal.loc[ts].replace([np.inf, -np.inf], np.nan).dropna()
        breadth.append(len(valid))
        if len(valid) < int(top_n):
            continue
        selected = valid.nlargest(int(top_n), keep="first")
        weights.loc[ts, selected.index] = float(pair_gross_exposure) / 2.0 / len(selected)
        valid_formations += 1
    return weights, {
        "formation_count": int(len(signal.index)),
        "valid_formation_count": int(valid_formations),
        "median_formation_breadth": float(np.median(breadth)) if breadth else 0.0,
        "minimum_formation_breadth": int(min(breadth)) if breadth else 0,
        "top_n": int(top_n),
        "pair_gross_exposure": float(pair_gross_exposure),
    }


def _hysteresis_pair_weights(
    signal: pd.DataFrame,
    *,
    entry_fraction: float,
    hold_fraction: float,
    minimum_signal_assets: int,
    pair_gross_exposure: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not 0 < float(entry_fraction) <= float(hold_fraction) <= 1:
        raise ValueError("invalid_hysteresis_entry_hold_fractions")
    weights = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)
    current: set[str] = set()
    breadth: list[int] = []
    selected_counts: list[int] = []
    valid_formations = 0
    for ts in signal.index:
        valid = signal.loc[ts].replace([np.inf, -np.inf], np.nan).dropna().sort_values(
            ascending=False,
            kind="mergesort",
        )
        breadth.append(len(valid))
        if len(valid) < int(minimum_signal_assets):
            current = set()
            selected_counts.append(0)
            continue
        entry_count = max(1, int(math.ceil(len(valid) * float(entry_fraction))))
        hold_count = max(entry_count, int(math.ceil(len(valid) * float(hold_fraction))))
        entry_set = set(valid.iloc[:entry_count].index)
        hold_set = set(valid.iloc[:hold_count].index)
        current = (current & hold_set) | entry_set
        if current:
            ordered = [inst_id for inst_id in valid.index if inst_id in current]
            weights.loc[ts, ordered] = float(pair_gross_exposure) / 2.0 / len(ordered)
            valid_formations += 1
        selected_counts.append(len(current))
    return weights, {
        "formation_count": int(len(signal.index)),
        "valid_formation_count": int(valid_formations),
        "median_formation_breadth": float(np.median(breadth)) if breadth else 0.0,
        "minimum_formation_breadth": int(min(breadth)) if breadth else 0,
        "median_selected_pairs": float(np.median(selected_counts)) if selected_counts else 0.0,
        "entry_fraction": float(entry_fraction),
        "hold_fraction": float(hold_fraction),
        "pair_gross_exposure": float(pair_gross_exposure),
    }


def _pair_formation_weights(
    path: dict[str, Any],
    signal: pd.DataFrame,
    artifacts: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    policy = path.get("weighting_policy", "top_n_equal_weighted")
    if policy == "top_n_equal_weighted":
        return _top_n_pair_weights(
            signal,
            top_n=int(path["top_n"]),
            pair_gross_exposure=float(artifacts["pair_gross_exposure"]),
        )
    if policy == "hysteresis_ss":
        return _hysteresis_pair_weights(
            signal,
            entry_fraction=float(path["entry_fraction"]),
            hold_fraction=float(path["hold_fraction"]),
            minimum_signal_assets=int(artifacts["minimum_signal_assets"]),
            pair_gross_exposure=float(artifacts["pair_gross_exposure"]),
        )
    raise ValueError(f"unsupported_pair_weighting_policy:{policy}")


def _formation_coverage_for_split(
    formation_weights: pd.DataFrame,
    signal: pd.DataFrame,
    split_index: pd.DatetimeIndex,
) -> dict[str, Any]:
    formations = signal.index[(signal.index >= split_index.min()) & (signal.index <= split_index.max())]
    split_signal = signal.reindex(formations)
    split_weights = formation_weights.reindex(formations).fillna(0.0)
    breadth = split_signal.notna().sum(axis=1)
    active = split_weights.abs().sum(axis=1).gt(0)
    selected = split_weights.gt(0).sum(axis=1)
    return {
        "formation_count": int(len(formations)),
        "valid_formation_count": int(active.sum()),
        "median_formation_breadth": float(breadth.median()) if len(breadth) else 0.0,
        "minimum_formation_breadth": int(breadth.min()) if len(breadth) else 0,
        "median_selected_pairs": float(selected[active].median()) if active.any() else 0.0,
    }


def _pair_forward_return(
    perp_close: pd.DataFrame,
    spot_close: pd.DataFrame,
    funding_events: pd.DataFrame,
    *,
    holding_bars: int,
    pair_gross_exposure: float,
) -> pd.DataFrame:
    holding_bars = int(holding_bars)
    spot_forward = spot_close.shift(-holding_bars) / spot_close - 1.0
    perp_forward = perp_close.shift(-holding_bars) / perp_close - 1.0
    future_funding = (
        funding_events.fillna(0.0)
        .rolling(holding_bars, min_periods=holding_bars)
        .sum()
        .shift(-holding_bars)
    )
    pair_notional = float(pair_gross_exposure) / 2.0
    valid = spot_forward.notna() & perp_forward.notna()
    return (pair_notional * (spot_forward - perp_forward + future_funding)).where(valid)


def _daily_cross_sectional_ic(
    signal: pd.DataFrame,
    forward_pair_return: pd.DataFrame,
    *,
    min_assets: int,
) -> pd.Series:
    values: dict[pd.Timestamp, float] = {}
    for ts in signal.index:
        pair = pd.concat(
            [signal.loc[ts].rename("signal"), forward_pair_return.loc[ts].rename("forward")],
            axis=1,
        ).replace([np.inf, -np.inf], np.nan).dropna()
        values[ts] = (
            float(pair["signal"].corr(pair["forward"], method="spearman"))
            if len(pair) >= int(min_assets)
            else np.nan
        )
    return pd.Series(values, dtype=float).sort_index()


def _pair_portfolio_metrics_with_daily_hac(
    pair_spot_weights: pd.DataFrame,
    spot_returns: pd.DataFrame,
    perp_returns: pd.DataFrame,
    funding_events: pd.DataFrame,
    split_index: pd.DatetimeIndex,
    *,
    max_lag: int,
    include_net_returns: bool = False,
) -> dict[str, Any]:
    weights = pair_spot_weights.reindex(split_index).fillna(0.0)
    spot = spot_returns.reindex(split_index)
    perp = perp_returns.reindex(split_index)
    funding = funding_events.reindex(split_index).fillna(0.0)
    held = weights.abs().gt(0)
    missing = held & (spot.isna() | perp.isna())
    spot_pnl = (weights * spot.fillna(0.0)).sum(axis=1)
    perp_weights = -weights
    perp_pnl = (perp_weights * perp.fillna(0.0)).sum(axis=1)
    gross_price_pnl = spot_pnl + perp_pnl
    funding_cost = (perp_weights * funding).sum(axis=1)
    spot_turnover = panel._turnover_with_initial_entry(weights)
    perp_turnover = panel._turnover_with_initial_entry(perp_weights)
    turnover = spot_turnover + perp_turnover
    cost = turnover * (config.COST_BPS + config.SLIPPAGE_BPS) / 10000.0
    net = (gross_price_pnl - funding_cost - cost).fillna(0.0)
    daily = net.resample("1D").sum(min_count=1).dropna()
    inference = panel_gate_calibration.newey_west_mean_tstat(daily, max_lag=int(max_lag))
    result: dict[str, Any] = {
        "bars": int(len(net)),
        "daily_observations": int(len(daily)),
        "sharpe": float(panel.annualized_sharpe(net, panel._periods_per_year())),
        "daily_sharpe": float(panel.annualized_sharpe(daily, 365)),
        "total_return": float(net.sum()),
        "gross_price_return": float(gross_price_pnl.sum()),
        "funding_paid": float(funding_cost.sum()),
        "funding_received": float(-funding_cost.sum()),
        "cost_paid": float(cost.sum()),
        "max_drawdown": float(panel.max_drawdown(net)),
        "turnover": float(turnover.mean()) if len(turnover) else 0.0,
        "avg_gross_exposure": float((2.0 * weights.abs().sum(axis=1)).mean()) if len(weights) else 0.0,
        "active_bars": int(held.any(axis=1).sum()),
        "missing_return_asset_bars_while_held": int(missing.sum().sum()),
        "return_evidence_complete_while_held": bool(not missing.any().any()),
        "daily_net_return_hac": {
            **inference,
            "raw_one_sided_p": _normal_sf(float(inference["tstat"])) if inference["valid"] else 1.0,
        },
    }
    if include_net_returns:
        result["_net_return_series"] = net
    return result


def _rolling_pair_audit(
    pair_spot_weights: pd.DataFrame,
    spot_returns: pd.DataFrame,
    perp_returns: pd.DataFrame,
    funding_events: pd.DataFrame,
    common_index: pd.DatetimeIndex,
    *,
    window_days: int,
    max_lag: int,
) -> dict[str, Any]:
    rows = []
    if not len(common_index):
        return {"window_days": int(window_days), "window_count": 0, "positive_sharpe_windows": 0, "rows": []}
    start = common_index.min()
    final = common_index.max()
    while start <= final:
        end = start + pd.Timedelta(days=int(window_days))
        idx = common_index[(common_index >= start) & (common_index < end)]
        if len(idx):
            metrics = _pair_portfolio_metrics_with_daily_hac(
                pair_spot_weights,
                spot_returns,
                perp_returns,
                funding_events,
                idx,
                max_lag=max_lag,
            )
            rows.append(
                {
                    "start": str(idx.min()),
                    "end": str(idx.max()),
                    "daily_sharpe": metrics["daily_sharpe"],
                    "total_return": metrics["total_return"],
                    "funding_received": metrics["funding_received"],
                    "cost_paid": metrics["cost_paid"],
                }
            )
        start = end
    return {
        "window_days": int(window_days),
        "window_count": int(len(rows)),
        "positive_sharpe_windows": int(sum(row["daily_sharpe"] > 0 for row in rows)),
        "rows": rows,
    }


def _run_zaremba_replication(
    batch: dict[str, Any],
    batch_path: Path,
    loaded: dict[str, dict[str, Any]],
    matrices: dict[str, pd.DataFrame],
    common_index: pd.DatetimeIndex,
    split_indexes: dict[str, pd.DatetimeIndex],
    actual_hashes: dict[str, str],
) -> dict[str, Any]:
    artifacts = batch["frozen_implementation"]
    formations = _daily_formation_times(common_index, hour_utc=int(artifacts["formation_hour_utc"]))
    close = matrices["close"]
    market_cap = matrices["market_cap"]
    eligibility = matrices["eligibility"]
    returns = matrices["returns"]
    funding = matrices["funding_cost"]
    dollar_volume = matrices["vol_quote"].where(matrices["vol_quote"] > 0)
    bars_per_day = int(artifacts["bars_per_day"])
    signal = _daily_log_return(close, periods=bars_per_day).reindex(formations)
    forward = _daily_log_return(close.shift(-bars_per_day), periods=bars_per_day).reindex(formations)
    cap_at_formation = market_cap.reindex(formations)
    amihud = _trailing_daily_amihud(
        close,
        dollar_volume,
        formations,
        lookback_days=int(artifacts["amihud_lookback_days"]),
        bars_per_day=bars_per_day,
        information_lag_days=int(artifacts["liquidity_information_lag_days"]),
    )
    segment_masks = {
        "largest_by_point_in_time_market_cap": _ranked_segment_mask(
            cap_at_formation,
            eligibility,
            formations,
            segment_assets=int(artifacts["segment_asset_count"]),
            largest=True,
            required_values=cap_at_formation,
        ),
        "most_liquid_by_lagged_20_week_amihud": _ranked_segment_mask(
            amihud,
            eligibility,
            formations,
            segment_assets=int(artifacts["segment_asset_count"]),
            largest=False,
            required_values=cap_at_formation,
        ),
    }

    candidates = []
    for path in batch["paths"]:
        candidate = {
            "candidate_id": path["path_id"],
            "source_ids": ["CRYPTO_LIQUIDITY_ILLIQUIDITY"],
            "hypothesis": "Prior-day return predicts same-direction next-day return within a preregistered large or liquid cryptocurrency segment.",
            "family": "literature_daily_liquidity_conditional_momentum",
            "required_fields": ["close", "dollar_volume", "market_cap", "point_in_time_eligibility"],
            "panel_formula": "zaremba_prior_day_return_conditional_momentum",
            "direction": "long",
            "neutralization": "condition_within_preregistered_segment",
            "bucket_policy": path["segment"],
            "weighting_modes": [path["weighting_mode"]],
            "generated_by": "human_frozen_literature_adaptation",
        }
        candidates.append(candidate)
        panel_candidate_registry.append_trial_event(
            candidate,
            event="preregistered",
            status="accepted",
            reason="frozen_source_constrained_market_adaptation",
            batch_id=batch["batch_id"],
            variant_count=1,
        )

    path_rows = []
    p_values: dict[str, float] = {}
    for path, candidate in zip(batch["paths"], candidates):
        mask = segment_masks[path["segment"]]
        formation_weights, coverage = _quintile_long_short_weights(
            signal,
            cap_at_formation,
            mask,
            min_assets=int(path["minimum_assets"]),
            side_fraction=float(artifacts["side_fraction"]),
            weighting_mode=path["weighting_mode"],
        )
        held = _execute_and_hold(
            formation_weights,
            common_index,
            execution_lag_bars=int(artifacts["execution_lag_bars"]),
            holding_hours=int(artifacts["holding_hours"]),
        )
        ic = _weekly_ic(signal, forward, mask, min_assets=int(path["minimum_assets"]))
        rank_ic = {
            name: _split_daily_ic_hac(ic, idx, max_lag=int(artifacts["newey_west_max_lag_days"]))
            for name, idx in split_indexes.items()
        }
        metrics = {
            name: _portfolio_metrics_with_daily_hac(
                held,
                returns,
                funding,
                idx,
                max_lag=int(artifacts["newey_west_max_lag_days"]),
            )
            for name, idx in split_indexes.items()
        }
        rolling = panel._rolling_factor_audit(held, returns, funding, ic, common_index)
        checks = {
            "coverage_ok": coverage["valid_formation_count"] >= int(artifacts["minimum_valid_formations"]),
            "return_evidence_complete_while_held": all(
                row["return_evidence_complete_while_held"] for row in metrics.values()
            ),
            "val_ic_positive": rank_ic["Val"]["mean_rank_ic"] > 0,
            "dependence_aware_val_ic_clue": rank_ic["Val"]["raw_one_sided_p"] <= 0.10,
            "val_long_short_positive": metrics["Val"]["total_return"] > 0 and metrics["Val"]["daily_sharpe"] > 0,
            "turnover_reasonable": metrics["Val"]["turnover"] < float(artifacts["maximum_mean_hourly_turnover"]),
            "rolling_ic_stable": rolling["window_count"] > 0
            and rolling["positive_ic_windows"] / rolling["window_count"] >= 0.60,
            "holdout_noncollapse": metrics["Holdout"]["daily_sharpe"] > -0.25
            and metrics["Holdout"]["max_drawdown"] < 0.35,
        }
        p_values[path["path_id"]] = rank_ic["Val"]["raw_one_sided_p"]
        path_rows.append(
            {
                **path,
                "candidate": candidate,
                "coverage": coverage,
                "rank_ic": rank_ic,
                "portfolio": metrics,
                "rolling_90d": rolling,
                "checks": checks,
            }
        )

    fdr = panel_gate_policy_v3.false_discovery_adjustment(p_values)
    by = panel_gate_policy_v3.false_discovery_adjustment(p_values, method="benjamini_yekutieli")
    for row in path_rows:
        path_id = row["path_id"]
        row["family_fdr"] = fdr[path_id]
        row["family_fdr_by_sensitivity"] = by[path_id]
        row["classification"] = panel_gate_policy_v3.classify_historical_discovery(
            row["checks"],
            fdr_state="pass" if fdr[path_id]["passed"] else "fail",
        )
        panel_candidate_registry.append_trial_event(
            row["candidate"],
            event="evaluated",
            status=row["classification"]["status"],
            reason=row["classification"]["reason"],
            batch_id=batch["batch_id"],
            variant_count=1,
        )
    return {
        "created_at_utc": _stamp(),
        "audit_type": "frozen_literature_replication_adaptation",
        "batch": batch,
        "batch_sha256": _sha256(batch_path),
        "actual_locked_input_hashes": actual_hashes,
        "actual_locked_code_hashes": _locked_code_hashes(),
        "panel_input_fingerprint": panel._panel_input_fingerprint(loaded),
        "loaded_fields": ["ohlcv", "funding", "market_cap", "instrument_metadata"],
        "time_ranges": {
            name: {"start": str(idx.min()), "end": str(idx.max()), "bars": int(len(idx))}
            for name, idx in split_indexes.items()
        },
        "source_scope_limitation": "The current top-40 liquid perpetual panel cannot estimate the source paper's illiquid-majority reversal.",
        "family_fdr": fdr,
        "family_fdr_by_sensitivity": by,
        "paths": path_rows,
        "status_counts": {
            status: sum(row["classification"]["status"] == status for row in path_rows)
            for status in {row["classification"]["status"] for row in path_rows}
        },
        "formal_pass_count": 0,
        "note": "Historical adaptation can authorize frozen prospective observation only, never capital deployment.",
    }


def _run_perp_carry_replication(
    batch: dict[str, Any],
    batch_path: Path,
    loaded: dict[str, dict[str, Any]],
    matrices: dict[str, pd.DataFrame],
    common_index: pd.DatetimeIndex,
    split_indexes: dict[str, pd.DatetimeIndex],
    actual_hashes: dict[str, str],
) -> dict[str, Any]:
    artifacts = batch["frozen_implementation"]
    selection_end = split_indexes["Val"].max()
    selection_index = common_index[common_index <= selection_end]
    formations = _daily_formation_times(selection_index, hour_utc=int(artifacts["formation_hour_utc"]))
    basis = matrices["basis"].reindex(selection_index)
    funding = matrices["funding_cost"].reindex(selection_index)
    eligibility = matrices["eligibility"].reindex(selection_index)
    perp_close = matrices["close"].reindex(selection_index)
    spot_close = matrices["spot_close"].reindex(selection_index)
    perp_returns = matrices["returns"].reindex(selection_index)
    spot_returns = matrices["spot_close"].pct_change(fill_method=None).reindex(selection_index)
    signals = _perp_carry_signal_frames(
        basis,
        funding,
        eligibility,
        formations,
        funding_lookback_bars=int(artifacts["funding_lookback_hours"]),
        information_lag_bars=int(artifacts["funding_information_lag_bars"]),
    )
    pair_forward = _pair_forward_return(
        perp_close,
        spot_close,
        funding,
        holding_bars=int(artifacts["holding_hours"]),
        pair_gross_exposure=float(artifacts["pair_gross_exposure"]),
    ).reindex(formations)

    candidates = []
    hypotheses = batch["hypotheses"]
    for path in batch["paths"]:
        weighting_policy = path.get("weighting_policy", "top_n_equal_weighted")
        candidates.append(
            {
                "candidate_id": path["path_id"],
                "source_ids": batch.get("source_ids", ["PERP_FUNDING_BASIS"]),
                "hypothesis": hypotheses[path["signal"]],
                "family": "perp_cash_and_carry",
                "required_fields": ["close", "spot_close", "basis", "funding_cost", "point_in_time_eligibility"],
                "panel_formula": f"perp_pair_{path['signal']}",
                "direction": "neutral",
                "neutralization": "none",
                "bucket_policy": "none",
                "weighting_modes": [f"spot_perp_{weighting_policy}"],
                "generated_by": "human_frozen_literature_mechanism",
            }
        )
    for candidate in candidates:
        panel_candidate_registry.append_trial_event(
            candidate,
            event="preregistered",
            status="accepted",
            reason="frozen_spot_perp_mechanism_adaptation",
            batch_id=batch["batch_id"],
            variant_count=1,
        )

    path_rows = []
    p_values = {}
    for path, candidate in zip(batch["paths"], candidates):
        signal = signals[path["signal"]]
        formation_weights, coverage = _pair_formation_weights(path, signal, artifacts)
        split_coverage = {
            split_name: _formation_coverage_for_split(formation_weights, signal, split_indexes[split_name])
            for split_name in ("IS", "Val")
        }
        held = _execute_and_hold(
            formation_weights,
            selection_index,
            execution_lag_bars=int(artifacts["execution_lag_bars"]),
            holding_hours=int(artifacts["holding_hours"]),
        )
        ic = _daily_cross_sectional_ic(
            signal,
            pair_forward,
            min_assets=int(artifacts["minimum_ic_assets"]),
        )
        rank_ic = {
            name: _split_daily_ic_hac(ic, split_indexes[name], max_lag=int(artifacts["newey_west_max_lag_days"]))
            for name in ("IS", "Val")
        }
        metrics = {
            name: _pair_portfolio_metrics_with_daily_hac(
                held,
                spot_returns,
                perp_returns,
                funding,
                split_indexes[name],
                max_lag=int(artifacts["newey_west_max_lag_days"]),
            )
            for name in ("IS", "Val")
        }
        rolling = _rolling_pair_audit(
            held,
            spot_returns,
            perp_returns,
            funding,
            selection_index,
            window_days=int(artifacts["rolling_window_days"]),
            max_lag=int(artifacts["newey_west_max_lag_days"]),
        )
        checks = {
            "is_coverage_ok": split_coverage["IS"]["valid_formation_count"]
            >= int(artifacts["minimum_is_valid_formations"]),
            "val_coverage_ok": split_coverage["Val"]["valid_formation_count"]
            >= int(artifacts["minimum_val_valid_formations"]),
            "return_evidence_complete_while_held": all(
                row["return_evidence_complete_while_held"] for row in metrics.values()
            ),
            "is_net_positive": metrics["IS"]["total_return"] > 0,
            "val_net_positive": metrics["Val"]["total_return"] > 0 and metrics["Val"]["daily_sharpe"] > 0,
            "val_ic_positive": rank_ic["Val"]["mean_rank_ic"] > 0,
            "val_hac_clue": metrics["Val"]["daily_net_return_hac"]["raw_one_sided_p"] <= 0.10,
            "turnover_reasonable": metrics["Val"]["turnover"]
            <= float(artifacts["maximum_mean_hourly_two_leg_turnover"]),
            "rolling_not_single_window": rolling["window_count"] >= 3,
        }
        p_values[path["path_id"]] = metrics["Val"]["daily_net_return_hac"]["raw_one_sided_p"]
        path_rows.append(
            {
                **path,
                "candidate": candidate,
                "coverage": coverage,
                "split_coverage": split_coverage,
                "rank_ic": rank_ic,
                "portfolio": metrics,
                "rolling_90d": rolling,
                "checks": checks,
                "holdout_accessed": False,
                "holdout": {"executed": False, "reason": "awaiting_selection_strength"},
            }
        )

    fdr = panel_gate_policy_v3.false_discovery_adjustment(p_values)
    by = panel_gate_policy_v3.false_discovery_adjustment(p_values, method="benjamini_yekutieli")
    full_signals: dict[str, pd.DataFrame] | None = None
    full_spot_returns: pd.DataFrame | None = None
    full_pair_forward: pd.DataFrame | None = None
    for row in path_rows:
        path_id = row["path_id"]
        row["family_fdr"] = fdr[path_id]
        row["family_fdr_by_sensitivity"] = by[path_id]
        checks = row["checks"]
        clue = all(
            checks[name]
            for name in (
                "is_coverage_ok",
                "val_coverage_ok",
                "return_evidence_complete_while_held",
                "is_net_positive",
                "val_net_positive",
                "val_ic_positive",
                "turnover_reasonable",
            )
        )
        rolling = row["rolling_90d"]
        rolling_fraction = (
            rolling["positive_sharpe_windows"] / rolling["window_count"] if rolling["window_count"] else 0.0
        )
        strong = (
            clue
            and checks["val_hac_clue"]
            and bool(fdr[path_id]["passed"])
            and checks["rolling_not_single_window"]
            and rolling_fraction >= float(artifacts["minimum_positive_rolling_fraction"])
        )
        if not clue:
            status = "historical_mechanism_reject"
            reason = "failed_is_or_validation_economic_clue_gate"
        elif not strong:
            status = "prospective_shadow_clue"
            reason = "positive_is_validation_clue_without_strong_fdr_evidence;holdout_remains_sealed"
        else:
            if full_signals is None:
                full_formations = _daily_formation_times(
                    common_index,
                    hour_utc=int(artifacts["formation_hour_utc"]),
                )
                full_signals = _perp_carry_signal_frames(
                    matrices["basis"].reindex(common_index),
                    matrices["funding_cost"].reindex(common_index),
                    matrices["eligibility"].reindex(common_index),
                    full_formations,
                    funding_lookback_bars=int(artifacts["funding_lookback_hours"]),
                    information_lag_bars=int(artifacts["funding_information_lag_bars"]),
                )
                full_spot_returns = matrices["spot_close"].pct_change(fill_method=None).reindex(common_index)
                full_pair_forward = _pair_forward_return(
                    matrices["close"].reindex(common_index),
                    matrices["spot_close"].reindex(common_index),
                    matrices["funding_cost"].reindex(common_index),
                    holding_bars=int(artifacts["holding_hours"]),
                    pair_gross_exposure=float(artifacts["pair_gross_exposure"]),
                ).reindex(full_formations)
            full_signal = full_signals[row["signal"]]
            full_formation_weights, _ = _pair_formation_weights(row, full_signal, artifacts)
            full_held = _execute_and_hold(
                full_formation_weights,
                common_index,
                execution_lag_bars=int(artifacts["execution_lag_bars"]),
                holding_hours=int(artifacts["holding_hours"]),
            )
            holdout_metrics = _pair_portfolio_metrics_with_daily_hac(
                full_held,
                full_spot_returns,
                matrices["returns"].reindex(common_index),
                matrices["funding_cost"].reindex(common_index),
                split_indexes["Holdout"],
                max_lag=int(artifacts["newey_west_max_lag_days"]),
            )
            holdout_ic_series = _daily_cross_sectional_ic(
                full_signal,
                full_pair_forward,
                min_assets=int(artifacts["minimum_ic_assets"]),
            )
            holdout_ic = _split_daily_ic_hac(
                holdout_ic_series,
                split_indexes["Holdout"],
                max_lag=int(artifacts["newey_west_max_lag_days"]),
            )
            noncollapse = (
                holdout_metrics["daily_sharpe"] >= float(artifacts["holdout_daily_sharpe_floor"])
                and holdout_metrics["max_drawdown"] <= float(artifacts["holdout_max_drawdown"])
                and holdout_metrics["return_evidence_complete_while_held"]
            )
            row["holdout_accessed"] = True
            row["holdout"] = {
                "executed": True,
                "portfolio": holdout_metrics,
                "rank_ic": holdout_ic,
                "noncollapse": bool(noncollapse),
            }
            if noncollapse:
                status = "prospective_shadow_strong"
                reason = "strong_is_validation_evidence_and_holdout_noncollapse;capital_still_prohibited"
            else:
                status = "historical_mechanism_reject"
                reason = "strong_selection_evidence_but_holdout_collapsed"
        row["classification"] = {
            "status": status,
            "reason": reason,
            "formal_promotion": False,
            "capital_deployment_allowed": False,
        }
        panel_candidate_registry.append_trial_event(
            row["candidate"],
            event="evaluated",
            status=status,
            reason=reason,
            batch_id=batch["batch_id"],
            variant_count=1,
        )

    statuses = {row["classification"]["status"] for row in path_rows}
    return {
        "created_at_utc": _stamp(),
        "audit_type": "frozen_perp_basis_funding_mechanism_adaptation",
        "batch": batch,
        "batch_sha256": _sha256(batch_path),
        "actual_locked_input_hashes": actual_hashes,
        "actual_locked_code_hashes": _locked_code_hashes(),
        "panel_input_fingerprint": panel._panel_input_fingerprint(loaded),
        "loaded_fields": ["perp_ohlcv", "spot_ohlcv", "sparse_real_funding", "market_cap", "instrument_metadata"],
        "selection_scope": {
            "splits": ["IS", "Val"],
            "selection_end": str(selection_end),
            "holdout_isolated_until_strong_selection_evidence": True,
        },
        "time_ranges": {
            name: {"start": str(idx.min()), "end": str(idx.max()), "bars": int(len(idx))}
            for name, idx in split_indexes.items()
        },
        "family_fdr": fdr,
        "family_fdr_by_sensitivity": by,
        "paths": path_rows,
        "status_counts": {
            status: sum(row["classification"]["status"] == status for row in path_rows)
            for status in statuses
        },
        "holdout_accessed_path_count": int(sum(row["holdout_accessed"] for row in path_rows)),
        "prospective_shadow_count": int(
            sum(row["classification"]["status"].startswith("prospective_shadow") for row in path_rows)
        ),
        "formal_pass_count": 0,
        "note": "This is a two-leg mechanism audit, not an outright perpetual-return factor or permission to deploy capital.",
    }


def _run_low_vol_replication(
    batch: dict[str, Any],
    batch_path: Path,
    actual_hashes: dict[str, str],
) -> dict[str, Any]:
    artifacts = batch["frozen_implementation"]
    inst_ids = panel_universe.registry_inst_ids()
    loaded, failures = _load_daily_spot_panel(
        inst_ids,
        bar=str(artifacts["bar"]),
        days=int(artifacts["history_days"]),
        evaluation_end_utc=batch["evaluation_end_utc"],
    )
    if failures or len(loaded) != len(inst_ids):
        raise ValueError(f"daily_spot_replication_load_incomplete:{failures}")

    close = pd.concat(
        {inst_id: row["spot_ohlcv"]["close"] for inst_id, row in loaded.items()},
        axis=1,
    ).sort_index()
    vol_quote = pd.concat(
        {inst_id: row["spot_ohlcv"]["vol_quote"] for inst_id, row in loaded.items()},
        axis=1,
    ).reindex(close.index)
    universe = panel_universe.build_point_in_time_eligibility(
        loaded,
        close,
        vol_quote,
    )
    eligibility = universe["eligibility"]
    minimum_assets = int(artifacts["minimum_assets"])
    common_index = eligibility.index[eligibility.sum(axis=1) >= minimum_assets]
    split_indexes = _source_period_split_indexes(
        common_index,
        source_sample_end_utc=artifacts["source_sample_end_utc"],
        is_fraction=float(artifacts["selection_is_fraction"]),
    )
    selection_end = split_indexes["Val"].max()
    selection_index = common_index[common_index <= selection_end]
    selection_close = close.loc[close.index <= selection_end]
    selection_returns = selection_close.pct_change(fill_method=None).reindex(selection_index)
    selection_eligibility = eligibility.reindex(selection_index)
    selection_formations = _month_end_formation_times(selection_index)
    dummy_caps = pd.DataFrame(1.0, index=selection_formations, columns=close.columns)
    scope_mask = selection_eligibility.reindex(selection_formations).fillna(False)
    liquidity_at_formation = universe["trailing_avg_daily_quote_volume"].reindex(selection_formations)
    liquid_ranks = liquidity_at_formation.where(scope_mask).rank(
        axis=1,
        ascending=False,
        method="first",
    )
    liquid_scope_mask = scope_mask & liquid_ranks.le(int(artifacts["liquid_robustness_assets"]))

    candidates = []
    for path in batch["paths"]:
        candidate = {
            "candidate_id": path["path_id"],
            "source_ids": ["CRYPTO_LOW_VOLATILITY_MONTHLY"],
            "hypothesis": (
                "Lower realized spot volatility over the source-specified formation window "
                "predicts higher next-month cross-sectional return in the mature cryptocurrency market."
            ),
            "family": "literature_monthly_low_volatility",
            "required_fields": [
                "spot_close",
                "spot_vol_quote",
                "listing_time",
                "point_in_time_eligibility",
            ],
            "panel_formula": f"monthly_low_vol_{int(path['lookback_days'])}d",
            "direction": "long",
            "neutralization": "none",
            "bucket_policy": "lowest_minus_highest_volatility_quintile",
            "weighting_modes": ["monthly_equal_weighted_quintiles"],
            "generated_by": "human_frozen_literature_adaptation",
        }
        candidates.append(candidate)
        panel_candidate_registry.append_trial_event(
            candidate,
            event="preregistered",
            status="accepted",
            reason="frozen_source_constrained_low_volatility_adaptation",
            batch_id=batch["batch_id"],
            variant_count=1,
        )

    path_rows = []
    p_values: dict[str, float] = {}
    internal_series: dict[str, dict[str, pd.Series]] = {}
    for path, candidate in zip(batch["paths"], candidates):
        signal = _trailing_low_vol_signal(
            selection_close,
            selection_formations,
            eligibility,
            lookback_days=int(path["lookback_days"]),
            minimum_coverage_fraction=float(artifacts["minimum_lookback_coverage_fraction"]),
        )
        forward = _next_formation_return(selection_close, selection_formations)
        formation_weights, coverage = _quintile_long_short_weights(
            signal,
            dummy_caps,
            scope_mask,
            min_assets=minimum_assets,
            side_fraction=float(artifacts["side_fraction"]),
            weighting_mode="equal_weighted",
        )
        held = _execute_monthly_targets(
            formation_weights,
            selection_index,
            execution_lag_days=int(artifacts["execution_lag_days"]),
        )
        ic = _weekly_ic(signal, forward, scope_mask, min_assets=minimum_assets)
        rank_ic = {
            name: _split_monthly_ic_hac(
                ic,
                split_indexes[name],
                max_lag=int(artifacts["newey_west_max_lag_months"]),
            )
            for name in ("IS", "Val")
        }
        metrics = {
            name: _spot_portfolio_metrics_with_monthly_hac(
                held,
                selection_returns,
                split_indexes[name],
                max_lag_months=int(artifacts["newey_west_max_lag_months"]),
                include_return_series=True,
            )
            for name in ("IS", "Val")
        }
        monthly_selection = pd.concat(
            [metrics["IS"]["_monthly_net_return_series"], metrics["Val"]["_monthly_net_return_series"]]
        ).sort_index()
        rolling = _rolling_monthly_return_audit(
            monthly_selection,
            window_months=int(artifacts["rolling_window_months"]),
        )
        daily_val = metrics["Val"]["_daily_net_return_series"]
        market_val = selection_returns.where(selection_eligibility).mean(axis=1).reindex(daily_val.index)
        crash_threshold = float(market_val.quantile(float(artifacts["crash_day_quantile"])))
        crash_days = market_val[market_val <= crash_threshold].index
        crash_audit = {
            "quantile": float(artifacts["crash_day_quantile"]),
            "threshold": crash_threshold,
            "days": int(len(crash_days)),
            "factor_net_return": float(daily_val.reindex(crash_days).sum()),
            "eligible_market_return": float(market_val.reindex(crash_days).sum()),
        }
        internal_series[path["path_id"]] = {
            "is_monthly": metrics["IS"].pop("_monthly_net_return_series"),
            "val_monthly": metrics["Val"].pop("_monthly_net_return_series"),
        }
        metrics["IS"].pop("_daily_net_return_series")
        metrics["Val"].pop("_daily_net_return_series")

        liquid_weights, liquid_coverage = _quintile_long_short_weights(
            signal,
            dummy_caps,
            liquid_scope_mask,
            min_assets=int(artifacts["liquid_robustness_minimum_assets"]),
            side_fraction=float(artifacts["side_fraction"]),
            weighting_mode="equal_weighted",
        )
        liquid_held = _execute_monthly_targets(
            liquid_weights,
            selection_index,
            execution_lag_days=int(artifacts["execution_lag_days"]),
        )
        liquid_metrics = {
            name: _spot_portfolio_metrics_with_monthly_hac(
                liquid_held,
                selection_returns,
                split_indexes[name],
                max_lag_months=int(artifacts["newey_west_max_lag_months"]),
            )
            for name in ("IS", "Val")
        }
        random_control = _permutation_mean_ic_control(
            signal,
            forward,
            scope_mask,
            split_indexes["Val"],
            minimum_assets=minimum_assets,
            permutations=int(artifacts["random_control_permutations"]),
            seed=int(artifacts["random_seed"]) + int(path["lookback_days"]),
        )
        split_coverage = {
            name: _formation_coverage_for_split(
                formation_weights,
                signal,
                split_indexes[name],
            )
            for name in ("IS", "Val")
        }
        checks = {
            "is_coverage_ok": split_coverage["IS"]["valid_formation_count"]
            >= int(artifacts["minimum_is_valid_formations"]),
            "val_coverage_ok": split_coverage["Val"]["valid_formation_count"]
            >= int(artifacts["minimum_val_valid_formations"]),
            "return_evidence_complete_while_held": all(
                row["return_evidence_complete_while_held"] for row in metrics.values()
            ),
            "is_net_positive": metrics["IS"]["total_return"] > 0,
            "val_net_positive": metrics["Val"]["total_return"] > 0,
            "val_ic_positive": rank_ic["Val"]["mean_rank_ic"] > 0,
            "val_monthly_hac_clue": metrics["Val"]["monthly_net_return_hac"]["raw_one_sided_p"]
            <= float(artifacts["selection_alpha"]),
            "large_liquid_val_nonnegative": liquid_metrics["Val"]["total_return"] >= 0,
            "rolling_not_single_window": rolling["window_count"]
            >= int(artifacts["minimum_rolling_windows"]),
            "rolling_positive_fraction": rolling["positive_window_fraction"]
            >= float(artifacts["minimum_positive_rolling_fraction"]),
            "beats_random_ic_control": random_control["empirical_one_sided_p"]
            <= float(artifacts["selection_alpha"]),
        }
        p_values[path["path_id"]] = metrics["Val"]["monthly_net_return_hac"]["raw_one_sided_p"]
        path_rows.append(
            {
                **path,
                "candidate": candidate,
                "coverage": coverage,
                "split_coverage": split_coverage,
                "rank_ic": rank_ic,
                "portfolio": metrics,
                "rolling_monthly": rolling,
                "large_liquid_only": {
                    "asset_count": int(artifacts["liquid_robustness_assets"]),
                    "coverage": liquid_coverage,
                    "portfolio": liquid_metrics,
                },
                "crash_day_audit": crash_audit,
                "random_control": random_control,
                "baseline_comparison": {
                    "zero_return_val_gap": metrics["Val"]["total_return"],
                    "opposite_high_minus_low_val_return": -metrics["Val"]["total_return"],
                    "legacy_7d_perpetual_low_vol_status": "panel_factor_reject",
                    "legacy_report": "logs/panel_factor_report_20260704T170249Z.json",
                },
                "checks": checks,
                "holdout_accessed": False,
                "holdout": {"executed": False, "reason": "awaiting_strong_is_validation_evidence"},
            }
        )

    fdr = panel_gate_policy_v3.false_discovery_adjustment(p_values)
    by = panel_gate_policy_v3.false_discovery_adjustment(p_values, method="benjamini_yekutieli")
    full_cache: dict[int, dict[str, Any]] = {}
    full_returns = close.pct_change(fill_method=None).reindex(common_index)
    full_formations = _month_end_formation_times(common_index)
    full_scope = eligibility.reindex(full_formations).fillna(False)
    full_dummy_caps = pd.DataFrame(1.0, index=full_formations, columns=close.columns)
    for row in path_rows:
        path_id = row["path_id"]
        row["family_fdr"] = fdr[path_id]
        row["family_fdr_by_sensitivity"] = by[path_id]
        checks = row["checks"]
        clue = all(
            checks[name]
            for name in (
                "is_coverage_ok",
                "val_coverage_ok",
                "return_evidence_complete_while_held",
                "is_net_positive",
                "val_net_positive",
                "val_ic_positive",
            )
        )
        strong = (
            clue
            and checks["val_monthly_hac_clue"]
            and bool(fdr[path_id]["passed"])
            and checks["large_liquid_val_nonnegative"]
            and checks["rolling_not_single_window"]
            and checks["rolling_positive_fraction"]
            and checks["beats_random_ic_control"]
        )
        if not clue:
            status = "historical_factor_reject"
            reason = "failed_is_or_validation_low_volatility_clue_gate"
        elif not strong:
            status = "prospective_shadow_clue"
            reason = "positive_is_validation_clue_without_strong_fdr_robustness;holdout_remains_sealed"
        else:
            lookback = int(row["lookback_days"])
            if lookback not in full_cache:
                full_signal = _trailing_low_vol_signal(
                    close,
                    full_formations,
                    eligibility,
                    lookback_days=lookback,
                    minimum_coverage_fraction=float(artifacts["minimum_lookback_coverage_fraction"]),
                )
                full_forward = _next_formation_return(close, full_formations)
                full_weights, _ = _quintile_long_short_weights(
                    full_signal,
                    full_dummy_caps,
                    full_scope,
                    min_assets=minimum_assets,
                    side_fraction=float(artifacts["side_fraction"]),
                    weighting_mode="equal_weighted",
                )
                full_held = _execute_monthly_targets(
                    full_weights,
                    common_index,
                    execution_lag_days=int(artifacts["execution_lag_days"]),
                )
                full_ic = _weekly_ic(
                    full_signal,
                    full_forward,
                    full_scope,
                    min_assets=minimum_assets,
                )
                full_cache[lookback] = {"held": full_held, "ic": full_ic}
            holdout_metrics = _spot_portfolio_metrics_with_monthly_hac(
                full_cache[lookback]["held"],
                full_returns,
                split_indexes["Holdout"],
                max_lag_months=int(artifacts["newey_west_max_lag_months"]),
            )
            holdout_ic = _split_monthly_ic_hac(
                full_cache[lookback]["ic"],
                split_indexes["Holdout"],
                max_lag=int(artifacts["newey_west_max_lag_months"]),
            )
            noncollapse = (
                holdout_metrics["total_return"] >= float(artifacts["holdout_total_return_floor"])
                and holdout_metrics["max_drawdown"] <= float(artifacts["holdout_max_drawdown"])
                and holdout_metrics["return_evidence_complete_while_held"]
            )
            row["holdout_accessed"] = True
            row["holdout"] = {
                "executed": True,
                "portfolio": holdout_metrics,
                "rank_ic": holdout_ic,
                "noncollapse": bool(noncollapse),
                "source_out_of_sample_months": holdout_metrics["monthly_observations"],
            }
            if noncollapse:
                status = "prospective_shadow_strong"
                reason = "strong_selection_evidence_and_short_source_out_of_sample_noncollapse;formal_promotion_prohibited"
            else:
                status = "historical_factor_reject"
                reason = "strong_selection_evidence_but_source_out_of_sample_audit_collapsed"
        row["classification"] = {
            "status": status,
            "reason": reason,
            "formal_promotion": False,
            "capital_deployment_allowed": False,
        }
        panel_candidate_registry.append_trial_event(
            row["candidate"],
            event="evaluated",
            status=status,
            reason=reason,
            batch_id=batch["batch_id"],
            variant_count=1,
        )

    statuses = {row["classification"]["status"] for row in path_rows}
    return {
        "created_at_utc": _stamp(),
        "audit_type": "frozen_monthly_low_volatility_spot_adaptation",
        "batch": batch,
        "batch_sha256": _sha256(batch_path),
        "actual_locked_input_hashes": actual_hashes,
        "actual_locked_code_hashes": _locked_code_hashes(),
        "daily_spot_input_fingerprint": _daily_spot_input_fingerprint(loaded),
        "loaded_fields": ["daily_spot_ohlcv", "swap_listing_metadata"],
        "selection_scope": {
            "splits": ["IS", "Val"],
            "selection_end": str(selection_end),
            "source_sample_end": artifacts["source_sample_end_utc"],
            "holdout_is_source_out_of_sample": True,
            "holdout_isolated_until_strong_selection_evidence": True,
        },
        "universe_summary": {
            "registered_assets": int(len(inst_ids)),
            "common_start": str(common_index.min()),
            "common_end": str(common_index.max()),
            "median_eligible_assets": float(eligibility.reindex(common_index).sum(axis=1).median()),
            "monthly_formations": int(len(full_formations)),
            "survivorship_complete": False,
        },
        "time_ranges": {
            name: {"start": str(idx.min()), "end": str(idx.max()), "bars": int(len(idx))}
            for name, idx in split_indexes.items()
        },
        "family_fdr": fdr,
        "family_fdr_by_sensitivity": by,
        "paths": path_rows,
        "status_counts": {
            status: sum(row["classification"]["status"] == status for row in path_rows)
            for status in statuses
        },
        "holdout_accessed_path_count": int(sum(row["holdout_accessed"] for row in path_rows)),
        "prospective_shadow_count": int(
            sum(row["classification"]["status"].startswith("prospective_shadow") for row in path_rows)
        ),
        "formal_pass_count": 0,
        "note": (
            "This is a survivor-conditioned OKX adaptation of a broader Binance spot result. "
            "Even a positive result can authorize only frozen prospective observation, not capital."
        ),
    }


def run_frozen_replication(batch_path: Path = DEFAULT_BATCH_PATH) -> dict[str, Any]:
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    locked = batch["locked_inputs"]
    actual_hashes = _locked_input_hashes()
    if actual_hashes != locked:
        raise ValueError(f"frozen_replication_input_hash_mismatch:{actual_hashes}")
    expected_code_hashes = batch.get("locked_code")
    actual_code_hashes = _locked_code_hashes()
    if expected_code_hashes is not None and actual_code_hashes != expected_code_hashes:
        raise ValueError(f"frozen_replication_code_hash_mismatch:{actual_code_hashes}")
    replication_id = batch.get("replication_id")
    if replication_id == LOW_VOL_REPLICATION_ID:
        return _run_low_vol_replication(batch, batch_path, actual_hashes)
    inst_ids = panel_universe.registry_inst_ids()
    loaded, failures = panel._load_panel(
        inst_ids,
        config.PANEL_HISTORY_DAYS,
        load_spot=replication_id == PERP_CARRY_REPLICATION_ID,
        load_open_interest=False,
        load_market_cap=True,
    )
    if failures or len(loaded) != len(inst_ids):
        raise ValueError(f"replication_panel_load_incomplete:{failures}")
    if batch.get("evaluation_end_utc"):
        loaded = panel._truncate_panel_as_of(loaded, batch["evaluation_end_utc"])
    matrices = panel._build_matrices(loaded, build_factors=False)
    eligibility = matrices["eligibility"]
    close = matrices["close"]
    market_cap = matrices["market_cap"]
    returns = matrices["returns"]
    funding = matrices["funding_cost"]
    common_index = eligibility.index[eligibility.sum(axis=1) >= config.PANEL_MIN_ASSETS]
    split_indexes = panel._split_index(common_index)
    if replication_id == PERP_CARRY_REPLICATION_ID:
        return _run_perp_carry_replication(
            batch,
            batch_path,
            loaded,
            matrices,
            common_index,
            split_indexes,
            actual_hashes,
        )
    if replication_id == "ZAREMBA_DAILY_LIQUIDITY_CONDITIONAL":
        return _run_zaremba_replication(
            batch,
            batch_path,
            loaded,
            matrices,
            common_index,
            split_indexes,
            actual_hashes,
        )
    if replication_id != "LTW_CMOM_3W_WEEKLY":
        raise ValueError(f"unsupported_frozen_replication:{replication_id}")
    formations = _formation_times(common_index)
    momentum = panel._pct_change(close, periods=batch["frozen_implementation"]["signal_lookback_hours"]).reindex(formations)
    forward = panel._pct_change(close, periods=batch["frozen_implementation"]["holding_hours"]).shift(
        -batch["frozen_implementation"]["holding_hours"]
    ).reindex(formations)
    cap_at_formation = market_cap.reindex(formations)

    prereg_candidates = []
    for path in batch["paths"]:
        prereg_candidates.append(
            {
                "candidate_id": path["path_id"],
                "source_ids": ["CRYPTO_MARKET_SIZE_MOMENTUM"],
                "hypothesis": "Three-week cryptocurrency momentum under the source paper's weekly 30/40/30 value-weighted construction.",
                "family": "canonical_momentum_replication",
                "required_fields": ["close", "market_cap", "point_in_time_eligibility"],
                "panel_formula": "ltw_cmom_3w_weekly",
                "direction": "long",
                "neutralization": "none",
                "bucket_policy": path["scope"],
                "weighting_modes": ["literature_value_weighted_30_40_30"],
                "generated_by": "human_frozen_literature_replication",
            }
        )
    for candidate in prereg_candidates:
        panel_candidate_registry.append_trial_event(
            candidate,
            event="preregistered",
            status="accepted",
            reason="frozen_method_faithful_literature_adaptation",
            batch_id=batch["batch_id"],
            variant_count=1,
        )

    path_rows = []
    p_values = {}
    artifacts = batch["frozen_implementation"]
    for path, candidate in zip(batch["paths"], prereg_candidates):
        mask = _scope_mask(eligibility, market_cap, formations, path["scope"])
        formation_weights, coverage = _value_weighted_30_40_30_weights(
            momentum,
            cap_at_formation,
            mask,
            min_assets=int(path["minimum_assets"]),
            side_fraction=float(artifacts["side_fraction"]),
        )
        held = _execute_and_hold(
            formation_weights,
            common_index,
            execution_lag_bars=int(artifacts["execution_lag_bars"]),
            holding_hours=int(artifacts["holding_hours"]),
        )
        ic = _weekly_ic(momentum, forward, mask, min_assets=int(path["minimum_assets"]))
        rank_ic = {name: _split_ic(ic, idx) for name, idx in split_indexes.items()}
        metrics = {
            name: panel._portfolio_metrics_from_weights(
                held,
                returns,
                funding,
                idx,
                include_net_returns=False,
            )
            for name, idx in split_indexes.items()
        }
        rolling = panel._rolling_factor_audit(held, returns, funding, ic, common_index)
        checks = {
            "coverage_ok": coverage["valid_formation_count"] >= 20,
            "return_evidence_complete_while_held": all(
                row["return_evidence_complete_while_held"] for row in metrics.values()
            ),
            "val_ic_positive": rank_ic["Val"]["mean_rank_ic"] > 0,
            "dependence_aware_val_ic_clue": rank_ic["Val"]["raw_one_sided_p"] <= 0.10,
            "val_long_short_positive": metrics["Val"]["total_return"] > 0 and metrics["Val"]["daily_sharpe"] > 0,
            "turnover_reasonable": metrics["Val"]["turnover"] < 0.08,
            "rolling_ic_stable": rolling["window_count"] > 0
            and rolling["positive_ic_windows"] / rolling["window_count"] >= 0.60,
            "holdout_noncollapse": metrics["Holdout"]["daily_sharpe"] > -0.25
            and metrics["Holdout"]["max_drawdown"] < 0.35,
        }
        p_values[path["path_id"]] = rank_ic["Val"]["raw_one_sided_p"]
        path_rows.append(
            {
                **path,
                "candidate": candidate,
                "coverage": coverage,
                "rank_ic": rank_ic,
                "portfolio": metrics,
                "rolling_90d": rolling,
                "checks": checks,
            }
        )
    fdr = panel_gate_policy_v3.false_discovery_adjustment(p_values)
    by = panel_gate_policy_v3.false_discovery_adjustment(p_values, method="benjamini_yekutieli")
    for row in path_rows:
        path_id = row["path_id"]
        fdr_state = "pass" if fdr[path_id]["passed"] else "fail"
        row["family_fdr"] = fdr[path_id]
        row["family_fdr_by_sensitivity"] = by[path_id]
        row["classification"] = panel_gate_policy_v3.classify_historical_discovery(
            row["checks"],
            fdr_state=fdr_state,
        )
        panel_candidate_registry.append_trial_event(
            row["candidate"],
            event="evaluated",
            status=row["classification"]["status"],
            reason=row["classification"]["reason"],
            batch_id=batch["batch_id"],
            variant_count=1,
        )
    return {
        "created_at_utc": _stamp(),
        "audit_type": "frozen_literature_replication_adaptation",
        "batch": batch,
        "batch_sha256": _sha256(batch_path),
        "actual_locked_input_hashes": actual_hashes,
        "actual_locked_code_hashes": actual_code_hashes,
        "panel_input_fingerprint": panel._panel_input_fingerprint(loaded),
        "loaded_fields": ["ohlcv", "funding", "market_cap", "instrument_metadata"],
        "time_ranges": {
            name: {"start": str(idx.min()), "end": str(idx.max()), "bars": int(len(idx))}
            for name, idx in split_indexes.items()
        },
        "family_fdr": fdr,
        "family_fdr_by_sensitivity": by,
        "paths": path_rows,
        "status_counts": {
            status: sum(row["classification"]["status"] == status for row in path_rows)
            for status in {row["classification"]["status"] for row in path_rows}
        },
        "formal_pass_count": 0,
        "note": "Historical adaptation can authorize frozen prospective observation only, never capital deployment.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", default=str(DEFAULT_BATCH_PATH))
    parser.add_argument("--out")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        report = replication_cache_preflight(Path(args.batch))
        out = Path(args.out) if args.out else Path(config.LOG_DIR) / f"panel_literature_preflight_{report['created_at_utc']}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(f"WROTE {out}")
        print(
            "PREFLIGHT",
            f"ready={report['replication_ready']}",
            f"assets={report['ready_asset_count']}/{report['required_asset_count']}",
            f"fields={report['ready_field_counts']}",
        )
        return 0 if report["replication_ready"] else 2
    report = run_frozen_replication(Path(args.batch))
    out = Path(args.out) if args.out else Path(config.LOG_DIR) / f"panel_literature_replication_{report['created_at_utc']}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"WROTE {out}")
    print(json.dumps(report["status_counts"], sort_keys=True))
    for row in report["paths"]:
        holdout = row.get("portfolio", {}).get("Holdout")
        if holdout is None:
            holdout = row.get("holdout", {}).get("portfolio")
        holdout_summary = (
            f"HoldDailySR={holdout['daily_sharpe']:.2f}" if holdout is not None else "Holdout=sealed"
        )
        print(
            row["path_id"],
            row["classification"]["status"],
            f"ValIC={row['rank_ic']['Val']['mean_rank_ic']:.4f}",
            f"ValDailySR={row['portfolio']['Val']['daily_sharpe']:.2f}",
            holdout_summary,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
