"""Dependence-aware diagnostics and simulation for panel gate calibration."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _mean_tstat(values: pd.Series) -> float:
    clean = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3:
        return 0.0
    std = float(clean.std(ddof=1))
    return float(clean.mean() / (std / math.sqrt(len(clean)))) if std > 0 else 0.0


def newey_west_mean_tstat(values: pd.Series, *, max_lag: int) -> dict[str, Any]:
    clean = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(clean)
    if n < max(8, max_lag + 3):
        return {
            "valid": False,
            "observations": n,
            "max_lag": int(max_lag),
            "mean": float(clean.mean()) if n else 0.0,
            "standard_error": None,
            "tstat": 0.0,
            "reason": "insufficient_daily_observations",
        }
    centered = clean.to_numpy(dtype=float) - float(clean.mean())
    long_run_variance = float(np.dot(centered, centered) / n)
    effective_lag = min(int(max_lag), n - 2)
    for lag in range(1, effective_lag + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / n)
        weight = 1.0 - lag / (effective_lag + 1.0)
        long_run_variance += 2.0 * weight * covariance
    long_run_variance = max(long_run_variance, 0.0)
    standard_error = math.sqrt(long_run_variance / n)
    tstat = float(clean.mean() / standard_error) if standard_error > 0 else 0.0
    return {
        "valid": standard_error > 0,
        "observations": n,
        "max_lag": effective_lag,
        "mean": float(clean.mean()),
        "standard_error": float(standard_error),
        "tstat": tstat,
        "reason": None if standard_error > 0 else "zero_long_run_variance",
    }


def daily_ic_series(ic_series: pd.Series, *, formation_hour_utc: int = 0) -> pd.Series:
    clean = pd.Series(ic_series, dtype=float).replace([np.inf, -np.inf], np.nan).dropna().sort_index()
    if not isinstance(clean.index, pd.DatetimeIndex):
        raise TypeError("ic_series_requires_datetime_index")
    index = clean.index.tz_localize("UTC") if clean.index.tz is None else clean.index.tz_convert("UTC")
    clean.index = index
    selected = clean[clean.index.hour == int(formation_hour_utc)]
    if selected.empty:
        shifted = clean.copy()
        shifted.index = shifted.index - pd.Timedelta(hours=int(formation_hour_utc))
        selected = shifted.resample("1D").first().dropna()
        selected.index = selected.index + pd.Timedelta(hours=int(formation_hour_utc))
    return selected


def ic_inference_diagnostics(
    ic_series: pd.Series,
    *,
    formation_hour_utc: int = 0,
    hac_lag_days: int = 6,
    forward_horizon_hours: int = 24,
) -> dict[str, Any]:
    hourly = pd.Series(ic_series, dtype=float).replace([np.inf, -np.inf], np.nan).dropna().sort_index()
    daily = daily_ic_series(hourly, formation_hour_utc=formation_hour_utc)
    hac = newey_west_mean_tstat(daily, max_lag=hac_lag_days)
    naive = _mean_tstat(hourly)
    daily_iid = _mean_tstat(daily)
    return {
        "method": "daily_formation_rank_ic_with_newey_west_mean_se",
        "forward_horizon_hours": int(forward_horizon_hours),
        "formation_hour_utc": int(formation_hour_utc),
        "hourly_observations": int(len(hourly)),
        "daily_observations": int(len(daily)),
        "overlap_warning": bool(forward_horizon_hours > 1 and len(hourly) > len(daily)),
        "naive_hourly_tstat": float(naive),
        "daily_iid_tstat": float(daily_iid),
        "daily_hac": hac,
        "daily_rank_ic": daily,
        "literature": {
            "overlapping_forecasts": "Hansen and Hodrick (1980)",
            "hac_covariance": "Newey and West (1987)",
        },
    }


def simulate_daily_ic(
    *,
    seed: int,
    days: int,
    asset_count: int,
    mean_ic: float,
    autocorrelation: float = 0.25,
) -> pd.Series:
    if asset_count < 4:
        raise ValueError("asset_count_must_be_at_least_four")
    rng = np.random.default_rng(seed)
    innovation_std = 1.0 / math.sqrt(asset_count - 1.0)
    unconditional_scale = math.sqrt(max(1.0 - autocorrelation**2, 1e-9))
    values = np.zeros(days, dtype=float)
    values[0] = mean_ic + rng.normal(0.0, innovation_std)
    for i in range(1, days):
        values[i] = (
            mean_ic
            + autocorrelation * (values[i - 1] - mean_ic)
            + rng.normal(0.0, innovation_std * unconditional_scale)
        )
    values = np.clip(values, -1.0, 1.0)
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=days, freq="D", tz="UTC"))


def inference_power_simulation(
    *,
    mean_ic: float,
    replications: int = 500,
    days: int = 146,
    asset_count: int = 40,
    trial_count: int = 94,
    autocorrelation: float = 0.25,
    hac_lag_days: int = 6,
) -> dict[str, Any]:
    critical_alpha = 1.0 - (1.0 - 0.05) ** (1.0 / max(trial_count, 1))
    passed = 0
    tstats = []
    for seed in range(replications):
        path = simulate_daily_ic(
            seed=seed,
            days=days,
            asset_count=asset_count,
            mean_ic=mean_ic,
            autocorrelation=autocorrelation,
        )
        audit = newey_west_mean_tstat(path, max_lag=hac_lag_days)
        tstat = float(audit["tstat"])
        one_sided_p = 0.5 * math.erfc(tstat / math.sqrt(2.0))
        passed += int(one_sided_p < critical_alpha)
        tstats.append(tstat)
    return {
        "method": "ar1_daily_rank_ic_hac_sidak_power_simulation",
        "mean_ic": float(mean_ic),
        "replications": int(replications),
        "days": int(days),
        "asset_count": int(asset_count),
        "trial_count": int(trial_count),
        "autocorrelation": float(autocorrelation),
        "per_trial_alpha": float(critical_alpha),
        "pass_rate": float(passed / replications),
        "median_tstat": float(np.median(tstats)),
        "p10_tstat": float(np.quantile(tstats, 0.10)),
        "p90_tstat": float(np.quantile(tstats, 0.90)),
        "warning": "Inference-only calibration; full gate power also requires portfolio, robustness, and cost simulation.",
    }


def simulate_nonoverlapping_block_tstats(
    *,
    mean_ic: float,
    replications: int,
    seed: int,
    days: int = 146,
    asset_count: int = 40,
    autocorrelation: float = 0.25,
    block_days: int = 7,
    batch_size: int = 5000,
) -> np.ndarray:
    if block_days < 1 or days // block_days < 3:
        raise ValueError("at_least_three_nonoverlapping_blocks_required")
    rng = np.random.default_rng(seed)
    innovation_std = 1.0 / math.sqrt(asset_count - 1.0)
    innovation_scale = innovation_std * math.sqrt(max(1.0 - autocorrelation**2, 1e-9))
    usable_days = (days // block_days) * block_days
    outputs = []
    remaining = int(replications)
    while remaining > 0:
        size = min(remaining, int(batch_size))
        values = np.empty((size, days), dtype=float)
        values[:, 0] = mean_ic + rng.normal(0.0, innovation_std, size=size)
        for day in range(1, days):
            values[:, day] = (
                mean_ic
                + autocorrelation * (values[:, day - 1] - mean_ic)
                + rng.normal(0.0, innovation_scale, size=size)
            )
        np.clip(values, -1.0, 1.0, out=values)
        blocks = values[:, :usable_days].reshape(size, usable_days // block_days, block_days).mean(axis=2)
        block_std = blocks.std(axis=1, ddof=1)
        tstats = np.divide(
            blocks.mean(axis=1),
            block_std / math.sqrt(blocks.shape[1]),
            out=np.zeros(size, dtype=float),
            where=block_std > 0,
        )
        outputs.append(tstats)
        remaining -= size
    return np.concatenate(outputs)


def nonoverlapping_block_mean_tstat(
    values: pd.Series,
    *,
    block_days: int = 7,
) -> dict[str, Any]:
    clean = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    usable_observations = (len(clean) // block_days) * block_days
    block_count = usable_observations // block_days
    if block_count < 3:
        return {
            "valid": False,
            "daily_observations": int(len(clean)),
            "usable_daily_observations": int(usable_observations),
            "block_days": int(block_days),
            "block_count": int(block_count),
            "mean": float(clean.mean()) if len(clean) else 0.0,
            "tstat": 0.0,
            "reason": "fewer_than_three_nonoverlapping_blocks",
        }
    blocks = clean.iloc[:usable_observations].to_numpy(dtype=float).reshape(block_count, block_days).mean(axis=1)
    block_std = float(blocks.std(ddof=1))
    tstat = float(blocks.mean() / (block_std / math.sqrt(block_count))) if block_std > 0 else 0.0
    return {
        "valid": block_std > 0,
        "daily_observations": int(len(clean)),
        "usable_daily_observations": int(usable_observations),
        "block_days": int(block_days),
        "block_count": int(block_count),
        "mean": float(clean.mean()),
        "tstat": tstat,
        "reason": None if block_std > 0 else "zero_block_dispersion",
    }


def empirical_block_rank_ic_audit(
    ic_series: pd.Series,
    *,
    trial_count: int,
    asset_count: int,
    formation_hour_utc: int = 0,
    block_days: int = 7,
    autocorrelation: float = 0.25,
    null_replications: int = 50000,
    seed: int = 99991,
) -> dict[str, Any]:
    daily = daily_ic_series(ic_series, formation_hour_utc=formation_hour_utc)
    observed = nonoverlapping_block_mean_tstat(daily, block_days=block_days)
    per_trial_alpha = 1.0 - (1.0 - 0.05) ** (1.0 / max(int(trial_count), 1))
    if not observed["valid"]:
        return {
            **observed,
            "method": "empirical_null_nonoverlapping_block_daily_rank_ic",
            "formation_hour_utc": int(formation_hour_utc),
            "trial_count": int(trial_count),
            "asset_count_assumption": int(asset_count),
            "watchlist_critical_tstat": None,
            "pass_critical_tstat": None,
            "empirical_one_sided_p": None,
            "watchlist_clue": False,
            "multiple_testing_pass": False,
        }
    null_tstats = simulate_nonoverlapping_block_tstats(
        mean_ic=0.0,
        replications=null_replications,
        seed=seed,
        days=len(daily),
        asset_count=max(int(asset_count), 4),
        autocorrelation=autocorrelation,
        block_days=block_days,
    )
    watchlist_critical = float(np.quantile(null_tstats, 0.90, method="higher"))
    pass_critical = float(np.quantile(null_tstats, 1.0 - per_trial_alpha, method="higher"))
    empirical_p = float((1.0 + np.sum(null_tstats >= observed["tstat"])) / (len(null_tstats) + 1.0))
    return {
        **observed,
        "method": "empirical_null_nonoverlapping_block_daily_rank_ic",
        "formation_hour_utc": int(formation_hour_utc),
        "trial_count": int(trial_count),
        "asset_count_assumption": int(asset_count),
        "autocorrelation_assumption": float(autocorrelation),
        "null_replications": int(null_replications),
        "familywise_alpha": 0.05,
        "per_trial_alpha": float(per_trial_alpha),
        "watchlist_null_per_signal_target": 0.10,
        "watchlist_critical_tstat": watchlist_critical,
        "pass_critical_tstat": pass_critical,
        "empirical_one_sided_p": empirical_p,
        "watchlist_clue": bool(observed["tstat"] > watchlist_critical),
        "multiple_testing_pass": bool(observed["tstat"] > pass_critical),
        "holdout_used_for_calibration": False,
        "warning": "Null model assumptions are preregistered calibration inputs, not facts inferred from candidate outcomes.",
    }


def empirical_sidak_power_curve(
    *,
    mean_ics: tuple[float, ...] = (0.0, 0.02, 0.05, 0.10),
    calibration_replications: int = 50000,
    evaluation_replications: int = 10000,
    days: int = 146,
    asset_count: int = 40,
    trial_count: int = 94,
    autocorrelation: float = 0.25,
    block_days: int = 7,
) -> dict[str, Any]:
    per_trial_alpha = 1.0 - (1.0 - 0.05) ** (1.0 / max(trial_count, 1))
    null_calibration = simulate_nonoverlapping_block_tstats(
        mean_ic=0.0,
        replications=calibration_replications,
        seed=104729,
        days=days,
        asset_count=asset_count,
        autocorrelation=autocorrelation,
        block_days=block_days,
    )
    critical_tstat = float(np.quantile(null_calibration, 1.0 - per_trial_alpha, method="higher"))
    rows = []
    for index, mean_ic in enumerate(mean_ics):
        tstats = simulate_nonoverlapping_block_tstats(
            mean_ic=float(mean_ic),
            replications=evaluation_replications,
            seed=130363 + index,
            days=days,
            asset_count=asset_count,
            autocorrelation=autocorrelation,
            block_days=block_days,
        )
        pass_rate = float((tstats > critical_tstat).mean())
        rows.append(
            {
                "mean_ic": float(mean_ic),
                "pass_rate": pass_rate,
                "median_tstat": float(np.median(tstats)),
                "p10_tstat": float(np.quantile(tstats, 0.10)),
                "p90_tstat": float(np.quantile(tstats, 0.90)),
            }
        )
    null_rate = next(row["pass_rate"] for row in rows if row["mean_ic"] == 0.0) if 0.0 in mean_ics else None
    return {
        "method": "empirical_null_calibrated_nonoverlapping_block_rank_ic_sidak",
        "calibration_outcome_blind": True,
        "days": int(days),
        "asset_count": int(asset_count),
        "trial_count": int(trial_count),
        "autocorrelation": float(autocorrelation),
        "block_days": int(block_days),
        "block_count": int(days // block_days),
        "familywise_alpha": 0.05,
        "per_trial_alpha": float(per_trial_alpha),
        "critical_tstat": critical_tstat,
        "calibration_replications": int(calibration_replications),
        "evaluation_replications": int(evaluation_replications),
        "estimated_independent_familywise_null_rate": (
            float(1.0 - (1.0 - null_rate) ** trial_count) if null_rate is not None else None
        ),
        "power_curve": rows,
        "limitations": [
            "Assumes AR(1) daily IC with independent trial paths.",
            "Does not yet simulate portfolio costs, missingness, bucket scope, crash regimes, or correlated candidate families.",
            "Production inference should use archived paths and a preregistered max-stat or block-resampling procedure.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--calibration-replications", type=int, default=50000)
    parser.add_argument("--evaluation-replications", type=int, default=10000)
    parser.add_argument("--days", type=int, default=146)
    parser.add_argument("--asset-count", type=int, default=40)
    parser.add_argument("--trial-count", type=int, default=94)
    args = parser.parse_args()
    report = empirical_sidak_power_curve(
        calibration_replications=args.calibration_replications,
        evaluation_replications=args.evaluation_replications,
        days=args.days,
        asset_count=args.asset_count,
        trial_count=args.trial_count,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        print(f"WROTE {path}")
    else:
        print(encoded.decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
