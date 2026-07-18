"""Panel-specific multiple-testing audits based on Bailey et al.

The functions in this module accept selection-sample returns only. Callers are
responsible for supplying IS/Val data and must never pass Holdout observations.
"""

from __future__ import annotations

import itertools
import math
from statistics import NormalDist
from typing import Any, Iterable

import numpy as np
import pandas as pd


EULER_MASCHERONI = 0.5772156649015329


def aggregate_daily_returns(returns: pd.Series) -> pd.Series:
    """Aggregate intraday additive PnL to UTC daily observations."""
    clean = returns.replace([np.inf, -np.inf], np.nan).dropna().sort_index()
    if not isinstance(clean.index, pd.DatetimeIndex):
        raise TypeError("returns index must be a DatetimeIndex")
    return clean.resample("1D").sum().dropna()


def unannualized_sharpe(returns: pd.Series) -> float:
    clean = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 2:
        return 0.0
    std = float(clean.std(ddof=1))
    return float(clean.mean() / std) if std > 0.0 else 0.0


def expected_maximum_sharpe(trial_sharpe_std: float, n_trials: int) -> float:
    """Expected maximum Sharpe under independent Normal trials.

    This is the Bailey-Lopez de Prado approximation combining two Normal order
    statistic quantiles. The input Sharpe standard deviation and output use the
    same unannualized frequency.
    """
    n_trials = max(int(n_trials), 1)
    trial_sharpe_std = max(float(trial_sharpe_std), 0.0)
    if n_trials <= 1 or trial_sharpe_std == 0.0:
        return 0.0
    normal = NormalDist()
    q1 = normal.inv_cdf(1.0 - 1.0 / n_trials)
    q2 = normal.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return float(trial_sharpe_std * ((1.0 - EULER_MASCHERONI) * q1 + EULER_MASCHERONI * q2))


def deflated_sharpe_audit(
    returns: pd.Series,
    *,
    n_trials: int,
    observed_trial_sharpes: Iterable[float],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Compute a daily-frequency Deflated Sharpe Ratio audit.

    Sharpe, its cross-trial dispersion, and the expected-maximum benchmark are
    deliberately kept unannualized. Pearson kurtosis is used in the
    non-Normality correction from the Probabilistic Sharpe Ratio.
    """
    clean = returns.replace([np.inf, -np.inf], np.nan).dropna()
    trial_values = np.asarray(
        [float(value) for value in observed_trial_sharpes if np.isfinite(value)],
        dtype=float,
    )
    trial_std = float(np.std(trial_values, ddof=1)) if len(trial_values) > 1 else 0.0
    benchmark = expected_maximum_sharpe(trial_std, n_trials)
    result = {
        "method": "bailey_lopez_de_prado_dsr_daily_selection_sample",
        "selection_sample_only": True,
        "return_frequency": "1D",
        "n_observations": int(len(clean)),
        "n_trials": int(max(n_trials, 1)),
        "observed_trial_sharpe_count": int(len(trial_values)),
        "trial_sharpe_std": trial_std,
        "expected_maximum_sharpe": benchmark,
        "alpha": float(alpha),
        "valid": False,
        "passed": False,
        "dsr_probability": 0.0,
        "p_value": 1.0,
    }
    if len(clean) < 30:
        result["reason"] = "fewer_than_30_daily_observations"
        return result
    std = float(clean.std(ddof=1))
    if std <= 0.0 or not np.isfinite(std):
        result["reason"] = "zero_or_invalid_return_variance"
        return result
    if len(trial_values) < 2:
        result["reason"] = "insufficient_observed_trial_sharpes"
        return result

    sharpe = float(clean.mean() / std)
    skewness = float(clean.skew())
    pearson_kurtosis = float(clean.kurt()) + 3.0
    denominator_term = 1.0 - skewness * sharpe + ((pearson_kurtosis - 1.0) / 4.0) * sharpe**2
    if denominator_term <= 0.0 or not np.isfinite(denominator_term):
        result.update(
            {
                "sharpe": sharpe,
                "skewness": skewness,
                "pearson_kurtosis": pearson_kurtosis,
                "reason": "invalid_non_normality_denominator",
            }
        )
        return result

    z_score = float((sharpe - benchmark) * math.sqrt(len(clean) - 1.0) / math.sqrt(denominator_term))
    probability = float(NormalDist().cdf(z_score))
    p_value = float(1.0 - probability)
    result.update(
        {
            "valid": True,
            "passed": bool(p_value < alpha),
            "sharpe": sharpe,
            "skewness": skewness,
            "pearson_kurtosis": pearson_kurtosis,
            "z_score": z_score,
            "dsr_probability": probability,
            "p_value": p_value,
            "reason": "",
        }
    )
    return result


def _column_sharpes(values: np.ndarray) -> np.ndarray:
    means = np.nanmean(values, axis=0)
    stds = np.nanstd(values, axis=0, ddof=1)
    return np.divide(means, stds, out=np.full_like(means, -np.inf), where=stds > 0.0)


def _average_rank(value: float, population: np.ndarray) -> float:
    finite = population[np.isfinite(population)]
    if not np.isfinite(value) or len(finite) == 0:
        return 0.5
    lower = float(np.sum(finite < value))
    equal = float(np.sum(finite == value))
    return 1.0 + lower + max(equal - 1.0, 0.0) / 2.0


def cscv_pbo_audit(
    daily_return_matrix: pd.DataFrame,
    *,
    n_splits: int = 10,
    pass_threshold: float = 0.20,
) -> dict[str, Any]:
    """Estimate PBO using combinatorially symmetric cross-validation.

    Rows must be ordered daily selection-sample returns and columns must be
    unique strategy paths. Every combination of half the contiguous segments is
    used as a training set, with its complement used out of sample.
    """
    matrix = daily_return_matrix.replace([np.inf, -np.inf], np.nan).dropna(axis=1, how="all").sort_index()
    n_splits = min(int(n_splits), len(matrix) // 10)
    if n_splits % 2:
        n_splits -= 1
    base = {
        "method": "bailey_et_al_cscv_daily_selection_sample",
        "selection_sample_only": True,
        "return_frequency": "1D",
        "n_observations": int(len(matrix)),
        "n_strategies": int(matrix.shape[1]),
        "n_splits": int(max(n_splits, 0)),
        "pass_threshold": float(pass_threshold),
        "valid": False,
        "passed": False,
        "pbo": 1.0,
        "combination_count": 0,
    }
    if matrix.shape[1] < 2:
        base["reason"] = "fewer_than_two_strategy_paths"
        return base
    if n_splits < 4:
        base["reason"] = "insufficient_daily_observations_for_cscv"
        return base

    segments = [np.asarray(part, dtype=int) for part in np.array_split(np.arange(len(matrix)), n_splits)]
    values = matrix.to_numpy(dtype=float)
    logits: list[float] = []
    degradation: list[float] = []
    for train_segments in itertools.combinations(range(n_splits), n_splits // 2):
        train_set = set(train_segments)
        train_idx = np.concatenate([segments[i] for i in range(n_splits) if i in train_set])
        test_idx = np.concatenate([segments[i] for i in range(n_splits) if i not in train_set])
        train_scores = _column_sharpes(values[train_idx])
        test_scores = _column_sharpes(values[test_idx])
        if not np.isfinite(train_scores).any():
            continue
        selected = int(np.nanargmax(train_scores))
        selected_test = float(test_scores[selected])
        rank = _average_rank(selected_test, test_scores)
        omega = min(max(rank / (matrix.shape[1] + 1.0), 1e-12), 1.0 - 1e-12)
        logits.append(float(math.log(omega / (1.0 - omega))))
        if np.isfinite(selected_test) and np.isfinite(train_scores[selected]):
            degradation.append(float(selected_test - train_scores[selected]))

    if not logits:
        base["reason"] = "no_valid_cscv_combinations"
        return base
    pbo = float(np.mean(np.asarray(logits) <= 0.0))
    base.update(
        {
            "valid": True,
            "passed": bool(pbo <= pass_threshold),
            "pbo": pbo,
            "combination_count": int(len(logits)),
            "median_logit": float(np.median(logits)),
            "median_oos_sharpe_degradation": float(np.median(degradation)) if degradation else None,
            "reason": "",
        }
    )
    return base
