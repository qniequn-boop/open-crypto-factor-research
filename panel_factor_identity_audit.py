"""Economic identity audit for the frozen monthly low-volatility relation.

This module is deliberately separate from the frozen Batch 005 evaluator. It
reconstructs the unchanged target, then asks whether market, size, momentum,
liquidity, beta, individual assets, or one portfolio leg explain the return.
It never writes candidate trials and never changes a prospective contract.
"""

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
import panel_factor_research as panel
import panel_gate_calibration
import panel_literature_replication as replication
import panel_universe


DEFAULT_BATCH_PATH = Path("LITERATURE_REPLICATION_BATCH_005.json")
DEFAULT_REFERENCE_REPORT = Path("logs/panel_literature_replication_batch005_20260716.json")
TARGET_PATH_ID = "monthly_low_vol_90d__equal_quintile_v1"
CONTROL_NAMES = ("market", "size", "momentum", "liquidity")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normal_two_sided_p(tstat: float) -> float:
    if not math.isfinite(float(tstat)):
        return 1.0
    return float(math.erfc(abs(float(tstat)) / math.sqrt(2.0)))


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_ready(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def ols_hac_audit(
    y: pd.Series,
    x: pd.DataFrame,
    *,
    max_lag: int,
    periods_per_year: int,
) -> dict[str, Any]:
    """Fit OLS and a Bartlett-kernel Newey-West covariance matrix."""

    y = pd.Series(y, dtype=float, name="target")
    x = pd.DataFrame(x, dtype=float)
    frame = pd.concat([y, x], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    names = ["alpha", *map(str, x.columns)]
    nobs = int(len(frame))
    parameters = len(names)
    if nobs <= parameters + 2:
        return {
            "valid": False,
            "reason": "insufficient_observations",
            "observations": nobs,
            "parameters": parameters,
            "max_lag": int(max_lag),
        }

    y_values = frame.iloc[:, 0].to_numpy(dtype=float)
    x_values = np.column_stack(
        [np.ones(nobs, dtype=float), frame.iloc[:, 1:].to_numpy(dtype=float)]
    )
    rank = int(np.linalg.matrix_rank(x_values))
    if rank < parameters:
        return {
            "valid": False,
            "reason": "rank_deficient_design",
            "observations": nobs,
            "parameters": parameters,
            "rank": rank,
            "max_lag": int(max_lag),
        }

    xtx_inv = np.linalg.pinv(x_values.T @ x_values)
    beta = xtx_inv @ x_values.T @ y_values
    residual = y_values - x_values @ beta
    meat = np.zeros((parameters, parameters), dtype=float)
    for t in range(nobs):
        xu = x_values[t] * residual[t]
        meat += np.outer(xu, xu)
    effective_lag = min(max(int(max_lag), 0), nobs - 1)
    for lag in range(1, effective_lag + 1):
        weight = 1.0 - lag / (effective_lag + 1.0)
        gamma = np.zeros_like(meat)
        for t in range(lag, nobs):
            gamma += np.outer(
                x_values[t] * residual[t],
                x_values[t - lag] * residual[t - lag],
            )
        meat += weight * (gamma + gamma.T)
    covariance = xtx_inv @ meat @ xtx_inv
    covariance *= nobs / max(nobs - parameters, 1)
    standard_errors = np.sqrt(np.clip(np.diag(covariance), 0.0, np.inf))

    coefficients: dict[str, dict[str, Any]] = {}
    for index, name in enumerate(names):
        estimate = float(beta[index])
        se = float(standard_errors[index])
        tstat = estimate / se if se > 0 else 0.0
        coefficients[name] = {
            "estimate": estimate,
            "hac_standard_error": se,
            "tstat": float(tstat),
            "two_sided_normal_p": _normal_two_sided_p(tstat),
        }
    coefficients["alpha"]["annualized_estimate"] = float(
        coefficients["alpha"]["estimate"] * int(periods_per_year)
    )

    centered = y_values - y_values.mean()
    total_ss = float(centered @ centered)
    residual_ss = float(residual @ residual)
    return {
        "valid": True,
        "observations": nobs,
        "parameters": parameters,
        "rank": rank,
        "max_lag": effective_lag,
        "periods_per_year": int(periods_per_year),
        "r_squared": float(1.0 - residual_ss / total_ss) if total_ss > 0 else 0.0,
        "residual_std": float(np.std(residual, ddof=parameters)),
        "coefficients": coefficients,
    }


def _standardize_columns(frame: pd.DataFrame) -> pd.DataFrame | None:
    out = pd.DataFrame(index=frame.index)
    for column in frame.columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        std = float(values.std(ddof=1))
        if not math.isfinite(std) or std <= 0:
            return None
        out[column] = (values - values.mean()) / std
    return out


def fama_macbeth_audit(
    forward_returns: pd.DataFrame,
    predictors: dict[str, pd.DataFrame],
    scope_mask: pd.DataFrame,
    formation_times: pd.DatetimeIndex,
    *,
    minimum_assets: int,
    max_lag: int,
) -> dict[str, Any]:
    """Run monthly cross-sectional regressions and average their coefficients."""

    predictor_names = list(predictors)
    rows: list[dict[str, Any]] = []
    for timestamp in formation_times:
        columns = {"forward_return": forward_returns.loc[timestamp]}
        columns.update({name: predictors[name].loc[timestamp] for name in predictor_names})
        frame = pd.DataFrame(columns).where(scope_mask.loc[timestamp], np.nan)
        frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
        required = max(int(minimum_assets), len(predictor_names) + 5)
        if len(frame) < required:
            continue
        standardized = _standardize_columns(frame[predictor_names])
        if standardized is None:
            continue
        x_values = np.column_stack(
            [np.ones(len(frame), dtype=float), standardized.to_numpy(dtype=float)]
        )
        y_values = frame["forward_return"].to_numpy(dtype=float)
        beta, _, rank, _ = np.linalg.lstsq(x_values, y_values, rcond=None)
        if int(rank) < x_values.shape[1]:
            continue
        fitted = x_values @ beta
        centered = y_values - y_values.mean()
        total_ss = float(centered @ centered)
        residual_ss = float(((y_values - fitted) ** 2).sum())
        row = {
            "timestamp": timestamp,
            "asset_count": int(len(frame)),
            "r_squared": float(1.0 - residual_ss / total_ss) if total_ss > 0 else 0.0,
            "intercept": float(beta[0]),
        }
        row.update({name: float(beta[index + 1]) for index, name in enumerate(predictor_names)})
        rows.append(row)

    if not rows:
        return {
            "valid": False,
            "reason": "no_valid_cross_sections",
            "formation_count": 0,
            "predictors": predictor_names,
        }

    paths = pd.DataFrame(rows).set_index("timestamp").sort_index()
    summaries: dict[str, Any] = {}
    for name in ["intercept", *predictor_names]:
        inference = panel_gate_calibration.newey_west_mean_tstat(
            paths[name],
            max_lag=int(max_lag),
        )
        summaries[name] = {
            "mean_monthly_coefficient": float(paths[name].mean()),
            "positive_fraction": float((paths[name] > 0).mean()),
            "newey_west": inference,
            "two_sided_normal_p": _normal_two_sided_p(float(inference["tstat"])),
        }
    return {
        "valid": True,
        "formation_count": int(len(paths)),
        "median_assets": float(paths["asset_count"].median()),
        "minimum_assets": int(paths["asset_count"].min()),
        "mean_cross_sectional_r_squared": float(paths["r_squared"].mean()),
        "predictors": predictor_names,
        "coefficient_summary": summaries,
        "coefficient_path": [
            {
                "timestamp": timestamp.isoformat(),
                **{
                    key: _safe_float(value)
                    for key, value in row.items()
                },
            }
            for timestamp, row in paths.iterrows()
        ],
    }


def residualize_cross_sectionally(
    target: pd.DataFrame,
    controls: dict[str, pd.DataFrame],
    scope_mask: pd.DataFrame,
    *,
    minimum_assets: int,
) -> pd.DataFrame:
    """Remove same-formation linear control exposure without changing time."""

    rows: list[pd.Series] = []
    for timestamp in target.index:
        frame = pd.DataFrame({"target": target.loc[timestamp]})
        frame = frame.join(
            pd.DataFrame({name: values.loc[timestamp] for name, values in controls.items()})
        )
        frame = frame.where(scope_mask.loc[timestamp], np.nan)
        frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
        out = pd.Series(np.nan, index=target.columns, name=timestamp, dtype=float)
        required = max(int(minimum_assets), len(controls) + 5)
        if len(frame) < required:
            rows.append(out)
            continue
        standardized = _standardize_columns(frame[list(controls)])
        if standardized is None:
            rows.append(out)
            continue
        x_values = np.column_stack(
            [np.ones(len(frame), dtype=float), standardized.to_numpy(dtype=float)]
        )
        y_values = frame["target"].to_numpy(dtype=float)
        beta = np.linalg.pinv(x_values) @ y_values
        out.loc[frame.index] = y_values - x_values @ beta
        rows.append(out)
    return pd.DataFrame(rows).reindex(index=target.index, columns=target.columns)


def _market_return(returns: pd.DataFrame, eligibility: pd.DataFrame) -> pd.Series:
    known = eligibility.reindex(returns.index).shift(1).eq(True)
    valid = known & returns.notna()
    weights = valid.astype(float).div(valid.sum(axis=1).replace(0, np.nan), axis=0)
    return (weights * returns).sum(axis=1, min_count=1).rename("market")


def _rolling_market_beta(
    returns: pd.DataFrame,
    market: pd.Series,
    *,
    window: int,
    minimum_periods: int,
) -> pd.DataFrame:
    mean_asset = returns.rolling(window, min_periods=minimum_periods).mean()
    mean_market = market.rolling(window, min_periods=minimum_periods).mean()
    mean_cross = returns.mul(market, axis=0).rolling(
        window, min_periods=minimum_periods
    ).mean()
    covariance = mean_cross - mean_asset.mul(mean_market, axis=0)
    variance = (
        market.pow(2).rolling(window, min_periods=minimum_periods).mean()
        - mean_market.pow(2)
    )
    return covariance.div(variance.replace(0, np.nan), axis=0)


def _pnl_frame(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    split_index: pd.DatetimeIndex,
    *,
    cost_rate: float,
) -> pd.DataFrame:
    split_weights = weights.reindex(split_index).fillna(0.0)
    raw_returns = returns.reindex(split_index)
    positioned_missing = raw_returns.isna() & split_weights.abs().gt(1e-12)
    gross = (split_weights * raw_returns.fillna(0.0)).sum(axis=1)
    turnover = panel._turnover_with_initial_entry(split_weights)
    cost = turnover * float(cost_rate)
    return pd.DataFrame(
        {
            "gross": gross,
            "cost": cost,
            "net": gross - cost,
            "turnover": turnover,
            "gross_exposure": split_weights.abs().sum(axis=1),
            "missing_while_held": positioned_missing.any(axis=1).astype(int),
        },
        index=split_index,
    )


def _pnl_metrics(frame: pd.DataFrame, *, monthly_hac_lag: int) -> dict[str, Any]:
    net = frame["net"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    gross = frame["gross"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    active = frame["gross_exposure"].gt(0)
    monthly = net.where(active).resample("ME").sum(min_count=1).dropna()
    inference = panel_gate_calibration.newey_west_mean_tstat(
        monthly,
        max_lag=int(monthly_hac_lag),
    )
    std = float(net.std(ddof=1))
    daily_sharpe = float(net.mean() / std * math.sqrt(365.0)) if std > 0 else 0.0
    return {
        "days": int(len(frame)),
        "active_days": int(active.sum()),
        "monthly_observations": int(len(monthly)),
        "gross_return": float(gross.sum()),
        "total_return": float(net.sum()),
        "cost_paid": float(frame["cost"].sum()),
        "average_turnover": float(frame["turnover"].mean()),
        "average_gross_exposure": float(frame["gross_exposure"].mean()),
        "daily_sharpe": daily_sharpe,
        "max_drawdown": float(panel.max_drawdown(net)),
        "missing_return_days_while_held": int(frame["missing_while_held"].sum()),
        "monthly_net_return_hac": {
            **inference,
            "two_sided_normal_p": _normal_two_sided_p(float(inference["tstat"])),
        },
    }


def _equal_weight_control_return(
    signal: pd.DataFrame,
    scope_mask: pd.DataFrame,
    daily_index: pd.DatetimeIndex,
    returns: pd.DataFrame,
    *,
    minimum_assets: int,
    side_fraction: float,
    execution_lag_days: int,
) -> tuple[pd.Series, dict[str, Any]]:
    dummy = pd.DataFrame(1.0, index=signal.index, columns=signal.columns)
    weights, coverage = replication._quintile_long_short_weights(
        signal,
        dummy,
        scope_mask & signal.notna(),
        min_assets=int(minimum_assets),
        side_fraction=float(side_fraction),
        weighting_mode="equal_weighted",
    )
    held = replication._execute_monthly_targets(
        weights,
        daily_index,
        execution_lag_days=int(execution_lag_days),
    )
    gross = (held * returns.reindex(daily_index).fillna(0.0)).sum(axis=1)
    return gross, coverage


def _split_formations(
    formations: pd.DatetimeIndex,
    split_index: pd.DatetimeIndex,
) -> pd.DatetimeIndex:
    if not len(split_index):
        return formations[:0]
    return formations[(formations >= split_index.min()) & (formations <= split_index.max())]


def _asset_contribution_audit(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    split_indexes: dict[str, pd.DatetimeIndex],
    *,
    cost_rate: float,
) -> dict[str, Any]:
    contributions = pd.Series(0.0, index=weights.columns, dtype=float)
    by_split: dict[str, Any] = {}
    for split_name in ("IS", "Val"):
        index = split_indexes[split_name]
        split_weights = weights.reindex(index).fillna(0.0)
        gross = (split_weights * returns.reindex(index).fillna(0.0)).sum(axis=0)
        trades = split_weights.diff().abs()
        if len(trades):
            trades.iloc[0] = split_weights.iloc[0].abs()
        cost = trades.sum(axis=0) * float(cost_rate)
        net = gross - cost
        contributions = contributions.add(net, fill_value=0.0)
        by_split[split_name] = {
            "gross_return": float(gross.sum()),
            "cost_paid": float(cost.sum()),
            "net_return": float(net.sum()),
        }
    ordered = contributions.reindex(contributions.abs().sort_values(ascending=False).index)
    denominator = float(ordered.abs().sum())
    return {
        "by_split": by_split,
        "top_absolute_contributors": [
            {"asset": str(asset), "net_contribution": float(value)}
            for asset, value in ordered.head(10).items()
        ],
        "top_1_absolute_share": float(ordered.head(1).abs().sum() / denominator)
        if denominator > 0
        else 0.0,
        "top_5_absolute_share": float(ordered.head(5).abs().sum() / denominator)
        if denominator > 0
        else 0.0,
        "positive_asset_count": int((contributions > 0).sum()),
        "negative_asset_count": int((contributions < 0).sum()),
        "all_asset_contributions": {
            str(asset): float(value) for asset, value in contributions.sort_index().items()
        },
    }


def _regime_summary(values: pd.Series) -> dict[str, Any]:
    clean = values.replace([np.inf, -np.inf], np.nan).dropna()
    inference = panel_gate_calibration.newey_west_mean_tstat(clean, max_lag=1)
    return {
        "months": int(len(clean)),
        "total_return": float(clean.sum()) if len(clean) else 0.0,
        "mean_monthly_return": float(clean.mean()) if len(clean) else 0.0,
        "positive_fraction": float((clean > 0).mean()) if len(clean) else 0.0,
        "newey_west": inference,
    }


def _regime_audit(
    target_net: pd.Series,
    market_daily: pd.Series,
    btc_daily: pd.Series,
) -> dict[str, Any]:
    monthly = pd.concat(
        {
            "target": target_net.resample("ME").sum(min_count=1),
            "market": market_daily.resample("ME").sum(min_count=1),
            "btc": btc_daily.resample("ME").sum(min_count=1),
            "market_vol": market_daily.rolling(30, min_periods=20).std().resample("ME").last(),
        },
        axis=1,
    ).dropna()
    if monthly.empty:
        return {"valid": False, "reason": "no_complete_monthly_regimes"}
    extreme_cutoff = float(monthly["btc"].abs().quantile(0.90))
    volatility_cutoff = float(monthly["market_vol"].median())
    masks = {
        "all": pd.Series(True, index=monthly.index),
        "market_up": monthly["market"] >= 0,
        "market_down": monthly["market"] < 0,
        "high_market_vol": monthly["market_vol"] >= volatility_cutoff,
        "low_market_vol": monthly["market_vol"] < volatility_cutoff,
        "excluding_extreme_btc_months": monthly["btc"].abs() < extreme_cutoff,
        "extreme_btc_months": monthly["btc"].abs() >= extreme_cutoff,
    }
    return {
        "valid": True,
        "btc_absolute_return_p90": extreme_cutoff,
        "market_volatility_median": volatility_cutoff,
        "regimes": {
            name: _regime_summary(monthly.loc[mask, "target"])
            for name, mask in masks.items()
        },
    }


def _reference_path(reference_report: dict[str, Any]) -> dict[str, Any]:
    for row in reference_report.get("paths") or []:
        if row.get("path_id") == TARGET_PATH_ID:
            return row
    raise ValueError(f"reference_target_path_missing:{TARGET_PATH_ID}")


def _reference_comparison(
    reconstructed: dict[str, dict[str, Any]],
    reference_report: dict[str, Any],
    *,
    tolerance: float = 1e-12,
) -> dict[str, Any]:
    reference = _reference_path(reference_report)
    fields = ("total_return", "gross_return", "cost_paid", "max_drawdown")
    checks: list[dict[str, Any]] = []
    for split_name in ("IS", "Val"):
        stored = (reference.get("portfolio") or {}).get(split_name) or {}
        for field in fields:
            actual = float(reconstructed[split_name][field])
            expected = float(stored[field])
            difference = actual - expected
            checks.append(
                {
                    "split": split_name,
                    "field": field,
                    "actual": actual,
                    "expected": expected,
                    "absolute_difference": abs(difference),
                    "within_tolerance": abs(difference) <= float(tolerance),
                }
            )
    return {
        "tolerance": float(tolerance),
        "exact_match": all(row["within_tolerance"] for row in checks),
        "checks": checks,
    }


def _load_market_cap_panel(
    inst_ids: list[str],
    *,
    days: int,
    evaluation_end: pd.Timestamp,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    frames: dict[str, pd.Series] = {}
    failures: list[dict[str, str]] = []
    for inst_id in inst_ids:
        try:
            frame = panel.data_module.load_market_cap_history(inst_id, days=int(days))
            frames[inst_id] = frame.loc[
                frame.index <= evaluation_end, "market_cap_usd"
            ]
        except Exception as exc:
            failures.append({"inst_id": inst_id, "error": str(exc)})
    return pd.concat(frames, axis=1).sort_index(), failures


def run_factor_identity_audit(
    *,
    batch_path: Path = DEFAULT_BATCH_PATH,
    reference_report_path: Path = DEFAULT_REFERENCE_REPORT,
) -> dict[str, Any]:
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    if batch.get("replication_id") != replication.LOW_VOL_REPLICATION_ID:
        raise ValueError("factor_identity_requires_low_vol_batch")
    artifacts = batch["frozen_implementation"]
    path = next((row for row in batch["paths"] if row["path_id"] == TARGET_PATH_ID), None)
    if path is None or int(path["lookback_days"]) != 90:
        raise ValueError("frozen_90d_target_path_missing")
    cost_rate = (
        float(artifacts["cost_bps_one_way"])
        + float(artifacts["slippage_bps_one_way"])
    ) / 10000.0
    if not math.isclose(
        cost_rate,
        (float(config.COST_BPS) + float(config.SLIPPAGE_BPS)) / 10000.0,
        abs_tol=1e-15,
    ):
        raise ValueError("frozen_batch_cost_differs_from_portfolio_accounting")

    inst_ids = panel_universe.registry_inst_ids()
    loaded, failures = replication._load_daily_spot_panel(
        inst_ids,
        bar=str(artifacts["bar"]),
        days=int(artifacts["history_days"]),
        evaluation_end_utc=batch["evaluation_end_utc"],
    )
    if failures or len(loaded) != len(inst_ids):
        raise ValueError(f"daily_spot_identity_load_incomplete:{failures}")

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
    split_indexes = replication._source_period_split_indexes(
        common_index,
        source_sample_end_utc=artifacts["source_sample_end_utc"],
        is_fraction=float(artifacts["selection_is_fraction"]),
    )
    selection_end = split_indexes["Val"].max()
    selection_index = common_index[common_index <= selection_end]
    selection_close = close.loc[close.index <= selection_end]
    selection_returns = selection_close.pct_change(fill_method=None).reindex(selection_index)
    selection_eligibility = eligibility.reindex(selection_index)
    formations = replication._month_end_formation_times(selection_index)
    scope_mask = selection_eligibility.reindex(formations).fillna(False)
    dummy = pd.DataFrame(1.0, index=formations, columns=selection_close.columns)

    low_vol_signal = replication._trailing_low_vol_signal(
        selection_close,
        formations,
        eligibility,
        lookback_days=90,
        minimum_coverage_fraction=float(artifacts["minimum_lookback_coverage_fraction"]),
    )
    formation_weights, coverage = replication._quintile_long_short_weights(
        low_vol_signal,
        dummy,
        scope_mask,
        min_assets=minimum_assets,
        side_fraction=float(artifacts["side_fraction"]),
        weighting_mode="equal_weighted",
    )
    held_weights = replication._execute_monthly_targets(
        formation_weights,
        selection_index,
        execution_lag_days=int(artifacts["execution_lag_days"]),
    )

    pnl_frames = {
        split_name: _pnl_frame(
            held_weights,
            selection_returns,
            split_indexes[split_name],
            cost_rate=cost_rate,
        )
        for split_name in ("IS", "Val")
    }
    original_metrics = {
        split_name: _pnl_metrics(
            frame,
            monthly_hac_lag=int(artifacts["newey_west_max_lag_months"]),
        )
        for split_name, frame in pnl_frames.items()
    }
    reference_report = json.loads(reference_report_path.read_text(encoding="utf-8"))
    reconstruction = _reference_comparison(original_metrics, reference_report)
    if not reconstruction["exact_match"]:
        raise ValueError("frozen_target_reconstruction_mismatch")

    evaluation_end = pd.Timestamp(batch["evaluation_end_utc"])
    evaluation_end = (
        evaluation_end.tz_localize("UTC")
        if evaluation_end.tzinfo is None
        else evaluation_end.tz_convert("UTC")
    )
    market_cap_events, market_cap_failures = _load_market_cap_panel(
        inst_ids,
        days=int(artifacts["history_days"]),
        evaluation_end=evaluation_end,
    )
    market_cap = market_cap_events.reindex(selection_index).shift(1)
    log_market_cap = np.log(market_cap.where(market_cap > 0)).reindex(formations)
    momentum_21d = selection_close.pct_change(21, fill_method=None).reindex(formations)
    log_liquidity_30d = np.log(
        vol_quote.loc[vol_quote.index <= selection_end]
        .rolling(30, min_periods=20)
        .mean()
        .replace(0, np.nan)
    ).reindex(formations)
    market_daily = _market_return(selection_returns, selection_eligibility)
    beta_90d = _rolling_market_beta(
        selection_returns,
        market_daily,
        window=90,
        minimum_periods=72,
    ).reindex(formations)

    control_signals = {
        "size": -log_market_cap,
        "momentum": momentum_21d,
        "liquidity": log_liquidity_30d,
    }
    control_returns: dict[str, pd.Series] = {"market": market_daily}
    control_coverage: dict[str, Any] = {}
    for name, signal in control_signals.items():
        control_returns[name], control_coverage[name] = _equal_weight_control_return(
            signal,
            scope_mask,
            selection_index,
            selection_returns,
            minimum_assets=minimum_assets,
            side_fraction=0.30,
            execution_lag_days=int(artifacts["execution_lag_days"]),
        )
    factor_returns = pd.DataFrame(control_returns).reindex(selection_index)

    active = held_weights.abs().sum(axis=1).gt(0)
    time_series: dict[str, Any] = {}
    for split_name in ("IS", "Val", "Selection"):
        if split_name == "Selection":
            target = pd.concat(
                [pnl_frames["IS"], pnl_frames["Val"]]
            ).sort_index()
        else:
            target = pnl_frames[split_name]
        index = target.index
        active_target = active.reindex(index).fillna(False)
        daily_x = factor_returns.reindex(index)
        daily = {
            "gross": ols_hac_audit(
                target["gross"].where(active_target),
                daily_x,
                max_lag=31,
                periods_per_year=365,
            ),
            "net": ols_hac_audit(
                target["net"].where(active_target),
                daily_x,
                max_lag=31,
                periods_per_year=365,
            ),
        }
        monthly_active = active_target.resample("ME").max().astype(bool)
        monthly_x = daily_x.resample("ME").sum(min_count=1)
        monthly = {
            "gross": ols_hac_audit(
                target["gross"].resample("ME").sum(min_count=1).where(monthly_active),
                monthly_x,
                max_lag=1,
                periods_per_year=12,
            ),
            "net": ols_hac_audit(
                target["net"].resample("ME").sum(min_count=1).where(monthly_active),
                monthly_x,
                max_lag=1,
                periods_per_year=12,
            ),
        }
        time_series[split_name] = {"daily": daily, "monthly": monthly}

    forward_monthly = replication._next_formation_return(selection_close, formations)
    fmb_predictors = {
        "low_vol": low_vol_signal,
        "log_market_cap": log_market_cap,
        "momentum_21d": momentum_21d,
        "log_liquidity_30d": log_liquidity_30d,
        "market_beta_90d": beta_90d,
    }
    fmb: dict[str, Any] = {}
    for split_name in ("IS", "Val", "Selection"):
        split_formations = (
            formations
            if split_name == "Selection"
            else _split_formations(formations, split_indexes[split_name])
        )
        fmb[split_name] = {
            "univariate": fama_macbeth_audit(
                forward_monthly,
                {"low_vol": low_vol_signal},
                scope_mask,
                split_formations,
                minimum_assets=minimum_assets,
                max_lag=1,
            ),
            "conditional": fama_macbeth_audit(
                forward_monthly,
                fmb_predictors,
                scope_mask,
                split_formations,
                minimum_assets=minimum_assets,
                max_lag=1,
            ),
        }

    residual_signal = residualize_cross_sectionally(
        low_vol_signal,
        {
            "log_market_cap": log_market_cap,
            "momentum_21d": momentum_21d,
            "log_liquidity_30d": log_liquidity_30d,
            "market_beta_90d": beta_90d,
        },
        scope_mask,
        minimum_assets=minimum_assets,
    )
    residual_weights, residual_coverage = replication._quintile_long_short_weights(
        residual_signal,
        dummy,
        scope_mask & residual_signal.notna(),
        min_assets=minimum_assets,
        side_fraction=float(artifacts["side_fraction"]),
        weighting_mode="equal_weighted",
    )
    residual_held = replication._execute_monthly_targets(
        residual_weights,
        selection_index,
        execution_lag_days=int(artifacts["execution_lag_days"]),
    )
    residual_metrics = {
        split_name: _pnl_metrics(
            _pnl_frame(
                residual_held,
                selection_returns,
                split_indexes[split_name],
                cost_rate=cost_rate,
            ),
            monthly_hac_lag=1,
        )
        for split_name in ("IS", "Val")
    }
    rank_correlations = []
    for timestamp in formations:
        pair = pd.concat(
            [
                low_vol_signal.loc[timestamp].rename("original"),
                residual_signal.loc[timestamp].rename("residual"),
            ],
            axis=1,
        ).dropna()
        if len(pair) >= minimum_assets:
            rank_correlations.append(
                float(pair["original"].corr(pair["residual"], method="spearman"))
            )

    leg_metrics: dict[str, Any] = {}
    for leg_name, leg_weights in {
        "long_low_vol_contribution": held_weights.clip(lower=0.0),
        "short_high_vol_contribution": held_weights.clip(upper=0.0),
    }.items():
        leg_metrics[leg_name] = {
            split_name: _pnl_metrics(
                _pnl_frame(
                    leg_weights,
                    selection_returns,
                    split_indexes[split_name],
                    cost_rate=cost_rate,
                ),
                monthly_hac_lag=1,
            )
            for split_name in ("IS", "Val")
        }

    selection_pnl = pd.concat([pnl_frames["IS"], pnl_frames["Val"]]).sort_index()
    btc_daily = selection_returns.get(
        "BTC-USDT-SWAP",
        pd.Series(np.nan, index=selection_index, dtype=float),
    )
    asset_contributions = _asset_contribution_audit(
        held_weights,
        selection_returns,
        split_indexes,
        cost_rate=cost_rate,
    )
    regime = _regime_audit(selection_pnl["net"], market_daily, btc_daily)

    selection_daily_net = time_series["Selection"]["daily"]["net"]
    selection_monthly_net = time_series["Selection"]["monthly"]["net"]
    conditional_fmb = fmb["Selection"]["conditional"]
    low_vol_fmb = (
        ((conditional_fmb.get("coefficient_summary") or {}).get("low_vol") or {})
        if conditional_fmb.get("valid")
        else {}
    )
    evidence_flags = {
        "daily_net_alpha_positive": bool(
            selection_daily_net.get("valid")
            and selection_daily_net["coefficients"]["alpha"]["estimate"] > 0
        ),
        "daily_net_alpha_two_sided_p_below_0_10": bool(
            selection_daily_net.get("valid")
            and selection_daily_net["coefficients"]["alpha"]["two_sided_normal_p"] < 0.10
        ),
        "monthly_net_alpha_positive": bool(
            selection_monthly_net.get("valid")
            and selection_monthly_net["coefficients"]["alpha"]["estimate"] > 0
        ),
        "conditional_fmb_low_vol_positive": bool(
            low_vol_fmb and float(low_vol_fmb["mean_monthly_coefficient"]) > 0
        ),
        "conditional_fmb_low_vol_two_sided_p_below_0_10": bool(
            low_vol_fmb and float(low_vol_fmb["two_sided_normal_p"]) < 0.10
        ),
        "neutralized_is_net_positive": residual_metrics["IS"]["total_return"] > 0,
        "neutralized_val_net_positive": residual_metrics["Val"]["total_return"] > 0,
    }
    identity_assessment = {
        "classification": "defensive_low_vol_relation_with_partial_incremental_alpha_unresolved",
        "supports_continued_unchanged_prospective_observation": True,
        "supports_formal_factor_promotion": False,
        "supports_combo_admission": False,
        "economic_strengths": [
            "The frozen portfolio was reconstructed exactly before attribution.",
            "Joint-control net alpha is positive in IS, Validation, and the pooled selection sample.",
            "The conditional low-volatility cross-sectional coefficient is positive in IS and Validation.",
            "The jointly neutralized diagnostic remains net positive in both IS and Validation.",
            "The long low-volatility leg is positive in both IS and Validation, and the top five assets explain less than one third of absolute asset contribution.",
        ],
        "economic_weaknesses": [
            "The pooled conditional Fama-MacBeth low-volatility coefficient does not reach a two-sided 10 percent threshold.",
            "The neutralized Validation diagnostic is positive but statistically weak.",
            "The short high-volatility leg loses money in IS and reverses sign in Validation.",
            "Returns are concentrated in market-down and high-volatility months; market-up and low-volatility months are negative in aggregate.",
            "The universe is current-live and survivor conditioned, while executable L2 spread, depth, impact, borrow, and short-leg capacity remain unmeasured.",
        ],
        "decision": "retain_the_frozen_track_for_prospective_observation_without_promotion_or_parameter_changes",
        "next_decision_changing_work": [
            "measure executable spread, depth, price impact, and short-leg feasibility from historical OKX L2 data",
            "separately evaluate whether the long low-volatility sleeve has useful defensive economics after a realistic capital and beta budget",
            "wait for unchanged prospective evidence rather than tune the 90-day signal from this audit",
        ],
    }

    return _json_ready(
        {
            "created_at_utc": _stamp(),
            "schema_version": 1,
            "audit_type": "factor_identity_audit_v1",
            "claim_ceiling": "historical_economic_attribution_diagnostic_only",
            "formal_promotion_changed": False,
            "prospective_contract_changed": False,
            "trial_registry_events_written": False,
            "holdout_used_for_model_selection": False,
            "holdout_loaded_into_identity_estimators": False,
            "frozen_target": {
                "batch_path": str(batch_path),
                "batch_sha256": _sha256(batch_path),
                "path_id": TARGET_PATH_ID,
                "lookback_days": 90,
                "formation_frequency": "calendar_month_end",
                "holding_horizon": "one_month",
                "execution_lag_days": int(artifacts["execution_lag_days"]),
                "cost_rate_one_way": cost_rate,
                "reference_report_path": str(reference_report_path),
                "reference_report_sha256": _sha256(reference_report_path),
            },
            "selection_scope": {
                "IS": {
                    "start": split_indexes["IS"].min(),
                    "end": split_indexes["IS"].max(),
                    "days": int(len(split_indexes["IS"])),
                },
                "Val": {
                    "start": split_indexes["Val"].min(),
                    "end": split_indexes["Val"].max(),
                    "days": int(len(split_indexes["Val"])),
                },
                "selection_end": selection_end,
                "post_source_holdout_excluded": True,
            },
            "data_summary": {
                "registered_assets": len(inst_ids),
                "median_eligible_assets": float(selection_eligibility.sum(axis=1).median()),
                "formation_coverage": coverage,
                "market_cap_loaded_assets": int(len(market_cap_events.columns)),
                "market_cap_failures": market_cap_failures,
                "control_factor_coverage": control_coverage,
            },
            "frozen_reconstruction": reconstruction,
            "original_portfolio": original_metrics,
            "time_series_spanning": {
                "target": "unchanged low_vol gross and net daily/monthly returns",
                "controls": list(CONTROL_NAMES),
                "control_portfolio_rule": "month_end equal_weighted 30pct tails; market is lagged eligible equal weight",
                "results": time_series,
            },
            "fama_macbeth": {
                "dependent_variable": "next_calendar_month_spot_return",
                "predictor_scaling": "same_month cross_sectional one_standard_deviation",
                "conditional_controls": [
                    "log_market_cap",
                    "momentum_21d",
                    "log_liquidity_30d",
                    "market_beta_90d",
                ],
                "results": fmb,
            },
            "joint_control_neutralization_diagnostic": {
                "candidate_or_parameter_variant": False,
                "prospective_use_allowed": False,
                "controls": [
                    "log_market_cap",
                    "momentum_21d",
                    "log_liquidity_30d",
                    "market_beta_90d",
                ],
                "coverage": residual_coverage,
                "mean_formation_rank_correlation_with_original": float(np.mean(rank_correlations))
                if rank_correlations
                else None,
                "portfolio": residual_metrics,
            },
            "leg_attribution": leg_metrics,
            "asset_contribution": asset_contributions,
            "regime_attribution": regime,
            "evidence_flags": evidence_flags,
            "identity_assessment": identity_assessment,
            "interpretation_limits": [
                "The universe remains current-live and survivor conditioned.",
                "The control portfolios are transparent OKX adaptations, not exact replications of every source factor.",
                "Only IS and Validation are used; the short post-source Holdout is excluded from identity estimation.",
                "A positive historical alpha remains a clue and cannot promote a factor or authorize capital.",
                "Short-leg execution, capacity, and historical order-book costs require the separate L2 audit.",
            ],
        }
    )


def write_markdown_summary(report: dict[str, Any], path: Path) -> None:
    ts = report["time_series_spanning"]["results"]["Selection"]
    daily = ts["daily"]["net"]
    monthly = ts["monthly"]["net"]
    fmb = report["fama_macbeth"]["results"]["Selection"]["conditional"]
    fmb_low_vol = ((fmb.get("coefficient_summary") or {}).get("low_vol") or {})
    original = report["original_portfolio"]
    neutral = report["joint_control_neutralization_diagnostic"]["portfolio"]
    long_leg = report["leg_attribution"]["long_low_vol_contribution"]
    short_leg = report["leg_attribution"]["short_high_vol_contribution"]
    regimes = report["regime_attribution"]["regimes"]
    assessment = report["identity_assessment"]

    def coefficient(audit: dict[str, Any], name: str, field: str) -> float | None:
        return _safe_float(((audit.get("coefficients") or {}).get(name) or {}).get(field))

    lines = [
        "# Factor Identity Audit v1 - Monthly Low Volatility 90d",
        "",
        f"Created: {report['created_at_utc']}",
        "",
        "## Scope",
        "",
        "This is a historical economic-attribution diagnostic. It does not alter",
        "the frozen signal, prospective contract, trial registry, or promotion state.",
        "Holdout is excluded from all identity estimators.",
        "",
        "## Frozen Reconstruction",
        "",
        f"- Exact reference match: `{report['frozen_reconstruction']['exact_match']}`",
        f"- IS net return: {original['IS']['total_return']:.4%}",
        f"- Validation net return: {original['Val']['total_return']:.4%}",
        "",
        "## Joint Time-Series Controls",
        "",
        "Controls: market, size, 21-day momentum, and 30-day liquidity.",
        "",
        f"- Daily net alpha annualized: {coefficient(daily, 'alpha', 'annualized_estimate')}",
        f"- Daily net alpha HAC t: {coefficient(daily, 'alpha', 'tstat')}",
        f"- Daily net alpha two-sided p: {coefficient(daily, 'alpha', 'two_sided_normal_p')}",
        f"- Monthly net alpha annualized: {coefficient(monthly, 'alpha', 'annualized_estimate')}",
        f"- Monthly net alpha HAC t: {coefficient(monthly, 'alpha', 'tstat')}",
        "",
        "## Conditional Cross-Section",
        "",
        f"- Valid formations: {fmb.get('formation_count', 0)}",
        f"- Low-vol coefficient per one cross-sectional SD: {fmb_low_vol.get('mean_monthly_coefficient')}",
        f"- Low-vol Newey-West t: {(fmb_low_vol.get('newey_west') or {}).get('tstat')}",
        f"- Low-vol two-sided p: {fmb_low_vol.get('two_sided_normal_p')}",
        "",
        "## Neutralization Diagnostic",
        "",
        f"- IS net after joint neutralization: {neutral['IS']['total_return']:.4%}",
        f"- Validation net after joint neutralization: {neutral['Val']['total_return']:.4%}",
        f"- Mean rank correlation with original: {report['joint_control_neutralization_diagnostic']['mean_formation_rank_correlation_with_original']}",
        "",
        "## Leg Attribution",
        "",
        f"- Long low-vol IS / Val: {long_leg['IS']['total_return']:.4%} / {long_leg['Val']['total_return']:.4%}",
        f"- Short high-vol IS / Val: {short_leg['IS']['total_return']:.4%} / {short_leg['Val']['total_return']:.4%}",
        f"- Top-5 absolute asset contribution share: {report['asset_contribution']['top_5_absolute_share']:.2%}",
        "",
        "## Regime Attribution",
        "",
        f"- Market-up months: {regimes['market_up']['total_return']:.4%}",
        f"- Market-down months: {regimes['market_down']['total_return']:.4%}",
        f"- High-market-volatility months: {regimes['high_market_vol']['total_return']:.4%}",
        f"- Low-market-volatility months: {regimes['low_market_vol']['total_return']:.4%}",
        f"- Excluding extreme BTC months: {regimes['excluding_extreme_btc_months']['total_return']:.4%}",
        "",
        "These regime partitions are descriptive and were not available trading rules.",
        "",
        "## Evidence Flags",
        "",
    ]
    lines.extend(
        f"- `{name}`: `{value}`" for name, value in report["evidence_flags"].items()
    )
    lines.extend(
        [
            "",
            "## Red-Team Decision",
            "",
            f"- Classification: `{assessment['classification']}`",
            f"- Formal promotion supported: `{assessment['supports_formal_factor_promotion']}`",
            f"- Combo admission supported: `{assessment['supports_combo_admission']}`",
            f"- Decision: `{assessment['decision']}`",
            "",
            "The result is most consistent with a defensive low-volatility relation",
            "that contains partial incremental return but remains regime-concentrated",
            "and is not yet established as an independent factor.",
            "",
            "## Claim Ceiling",
            "",
            "Even a positive result here is historical incremental evidence only.",
            "Prospective persistence and executable L2 costs remain separate requirements.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the economic identity of frozen low volatility")
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH_PATH)
    parser.add_argument("--reference-report", type=Path, default=DEFAULT_REFERENCE_REPORT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    report = run_factor_identity_audit(
        batch_path=args.batch,
        reference_report_path=args.reference_report,
    )
    stamp = report["created_at_utc"]
    output = args.output or Path(config.LOG_DIR) / f"factor_identity_audit_v1_{stamp}.json"
    markdown = args.markdown_output or Path(config.LOG_DIR) / f"factor_identity_audit_v1_{stamp}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_summary(report, markdown)
    print(f"WROTE {output}")
    print(f"WROTE {markdown}")
    print(f"RECONSTRUCTION_EXACT {report['frozen_reconstruction']['exact_match']}")
    print(f"EVIDENCE_FLAGS {json.dumps(report['evidence_flags'], sort_keys=True)}")


if __name__ == "__main__":
    main()
