"""Execution-only audit for the frozen 90-day monthly low-volatility factor.

The module reconstructs the frozen spot signal, applies the same target weights
to OKX USDT perpetual returns, and subtracts realized sparse funding events and
predeclared execution costs. It cannot alter factor status or trial accounting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import config
import panel_factor_research as panel
import panel_literature_replication as replication
import panel_universe


ROOT = Path(__file__).resolve().parent
DEFAULT_CONTRACT_PATH = ROOT / "LOW_VOL_EXECUTION_TRANSLATION_CONTRACT_001.json"
DEFAULT_OUTPUT_PATH = ROOT / "logs" / "low_vol_execution_translation_audit_20260716.json"
EPSILON = 1e-12


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _frame_fingerprint(frame: pd.DataFrame) -> str:
    clean = frame.sort_index().sort_index(axis=1)
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(clean, index=True).to_numpy().tobytes())
    digest.update("|".join(map(str, clean.columns)).encode("utf-8"))
    return digest.hexdigest()


def _utc(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _locked_file_hashes(contract: dict[str, Any]) -> dict[str, str]:
    return {
        name: _sha256(ROOT / row["path"])
        for name, row in contract["locked_files"].items()
    }


def _verify_contract(contract: dict[str, Any]) -> dict[str, str]:
    if contract.get("status") != "frozen_before_evaluation":
        raise ValueError("execution_audit_contract_not_frozen")
    if contract.get("source_candidate_id") != "monthly_low_vol_90d__equal_quintile_v1":
        raise ValueError("execution_audit_source_candidate_changed")
    actual = _locked_file_hashes(contract)
    expected = {name: row["sha256"] for name, row in contract["locked_files"].items()}
    if actual != expected:
        raise ValueError(f"execution_audit_locked_file_mismatch:{actual}")
    return actual


def _load_frozen_signal(
    contract: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    batch_path = ROOT / contract["locked_files"]["batch005"]["path"]
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    historical_report = json.loads(
        (ROOT / contract["locked_files"]["batch005_report"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    implementation = batch["frozen_implementation"]
    path = next(
        (row for row in batch["paths"] if row["path_id"] == contract["source_candidate_id"]),
        None,
    )
    if path is None:
        raise ValueError("frozen_low_vol_path_missing")

    signal_contract = contract["signal_contract"]
    expected = {
        "lookback_days": int(path["lookback_days"]),
        "minimum_assets": int(implementation["minimum_assets"]),
        "minimum_lookback_coverage_fraction": float(
            implementation["minimum_lookback_coverage_fraction"]
        ),
        "side_fraction": float(implementation["side_fraction"]),
        "execution_lag_days": int(implementation["execution_lag_days"]),
    }
    for key, value in expected.items():
        if signal_contract.get(key) != value:
            raise ValueError(f"execution_audit_signal_contract_mismatch:{key}")

    inst_ids = panel_universe.registry_inst_ids()
    loaded, failures = replication._load_daily_spot_panel(
        inst_ids,
        bar=str(implementation["bar"]),
        days=int(implementation["history_days"]),
        evaluation_end_utc=contract["evaluation_end_utc"],
    )
    if failures or len(loaded) != len(inst_ids):
        raise ValueError(f"execution_audit_daily_spot_load_incomplete:{failures}")

    close = pd.concat(
        {inst_id: row["spot_ohlcv"]["close"] for inst_id, row in loaded.items()},
        axis=1,
    ).sort_index()
    volume = pd.concat(
        {inst_id: row["spot_ohlcv"]["vol_quote"] for inst_id, row in loaded.items()},
        axis=1,
    ).reindex(close.index)
    universe = panel_universe.build_point_in_time_eligibility(loaded, close, volume)
    eligibility = universe["eligibility"]
    common_index = eligibility.index[
        eligibility.sum(axis=1) >= int(signal_contract["minimum_assets"])
    ]
    formations = replication._month_end_formation_times(common_index)
    signal = replication._trailing_low_vol_signal(
        close,
        formations,
        eligibility,
        lookback_days=int(signal_contract["lookback_days"]),
        minimum_coverage_fraction=float(
            signal_contract["minimum_lookback_coverage_fraction"]
        ),
    )
    scope = eligibility.reindex(formations).fillna(False)
    dummy_caps = pd.DataFrame(1.0, index=formations, columns=close.columns)
    formation_weights, coverage = replication._quintile_long_short_weights(
        signal,
        dummy_caps,
        scope,
        min_assets=int(signal_contract["minimum_assets"]),
        side_fraction=float(signal_contract["side_fraction"]),
        weighting_mode="equal_weighted",
    )
    daily_weights = replication._execute_monthly_targets(
        formation_weights,
        common_index,
        execution_lag_days=int(signal_contract["execution_lag_days"]),
    )
    spot_input_fingerprint = replication._daily_spot_input_fingerprint(loaded)
    if spot_input_fingerprint != historical_report["daily_spot_input_fingerprint"]:
        raise ValueError("execution_audit_batch005_spot_input_fingerprint_mismatch")
    return daily_weights, close.reindex(common_index), {
        "registered_assets": len(inst_ids),
        "daily_start": str(common_index.min()),
        "daily_end": str(common_index.max()),
        "formation_coverage": coverage,
        "spot_input_fingerprint": spot_input_fingerprint,
        "batch005_spot_input_fingerprint_verified": True,
        "signal_fingerprint": _frame_fingerprint(signal),
        "formation_weight_fingerprint": _frame_fingerprint(formation_weights),
    }


def _load_perpetual_panel(
    contract: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, pd.DataFrame], dict[str, Any]]:
    inst_ids = panel_universe.registry_inst_ids()
    loaded, failures = panel._load_panel(
        inst_ids,
        int(contract["perpetual_contract"]["history_days"]),
        load_spot=False,
        load_open_interest=False,
        load_market_cap=False,
    )
    if failures or len(loaded) != len(inst_ids):
        raise ValueError(f"execution_audit_perpetual_load_incomplete:{failures}")
    loaded = panel._truncate_panel_as_of(loaded, contract["evaluation_end_utc"])
    matrices = panel._build_matrices(loaded, build_factors=False)
    close = matrices["close"]
    funding = matrices["funding_cost"]
    return loaded, matrices, {
        "perpetual_close_fingerprint": _frame_fingerprint(close),
        "funding_event_fingerprint": _frame_fingerprint(funding),
        "perpetual_rows": int(len(close)),
        "perpetual_start": str(close.index.min()),
        "perpetual_end": str(close.index.max()),
        "funding_event_count": int(funding.notna().sum().sum()),
    }


def _daily_targets_to_intraday(
    daily_weights: pd.DataFrame,
    intraday_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    if not daily_weights.index.is_monotonic_increasing:
        daily_weights = daily_weights.sort_index()
    return daily_weights.reindex(intraday_index, method="ffill").fillna(0.0)


def _portfolio_metrics(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    funding_events: pd.DataFrame,
    index: pd.DatetimeIndex,
    *,
    one_way_cost_bps: float,
    include_series: bool = False,
) -> dict[str, Any]:
    weights = weights.reindex(index).fillna(0.0)
    raw_returns = returns.reindex(index)
    held = weights.abs().gt(EPSILON)
    missing = held & raw_returns.isna()
    price_pnl = (weights * raw_returns.fillna(0.0)).sum(axis=1)
    funding_by_asset = weights * funding_events.reindex(index).fillna(0.0)
    funding_cost = funding_by_asset.sum(axis=1)
    turnover = panel._turnover_with_initial_entry(weights)
    execution_cost = turnover * float(one_way_cost_bps) / 10000.0
    net = price_pnl - funding_cost - execution_cost
    daily_price = price_pnl.resample("1D").sum(min_count=1).dropna()
    daily_net = net.resample("1D").sum(min_count=1).dropna()
    compounded = float((1.0 + net).prod() - 1.0) if len(net) else 0.0
    result: dict[str, Any] = {
        "bars": int(len(index)),
        "active_bars": int(held.any(axis=1).sum()),
        "arithmetic_net_return": float(net.sum()),
        "compounded_net_return": compounded,
        "gross_price_return": float(price_pnl.sum()),
        "net_funding_cost": float(funding_cost.sum()),
        "funding_paid_by_long_leg": float(
            funding_by_asset.where(weights > EPSILON, 0.0).sum().sum()
        ),
        "funding_paid_by_short_leg": float(
            funding_by_asset.where(weights < -EPSILON, 0.0).sum().sum()
        ),
        "execution_cost_paid": float(execution_cost.sum()),
        "turnover_total": float(turnover.sum()),
        "turnover_mean_per_bar": float(turnover.mean()) if len(turnover) else 0.0,
        "daily_sharpe": float(panel.annualized_sharpe(daily_net, 365)),
        "max_drawdown": float(panel.max_drawdown(net)),
        "average_gross_exposure": float(weights.abs().sum(axis=1).mean()) if len(weights) else 0.0,
        "missing_return_asset_bars_while_held": int(missing.sum().sum()),
        "return_evidence_complete_while_held": bool(not missing.any().any()),
    }
    if include_series:
        result["_hourly_net"] = net
        result["_daily_net"] = daily_net
        result["_daily_price"] = daily_price
    return result


def _funding_coverage_audit(
    weights: pd.DataFrame,
    loaded: dict[str, dict[str, Any]],
    *,
    maximum_event_gap_hours: float,
) -> dict[str, Any]:
    rows = []
    maximum_gap = pd.Timedelta(hours=float(maximum_event_gap_hours))
    for inst_id in weights.columns:
        active = weights.index[weights[inst_id].abs() > EPSILON]
        if not len(active):
            continue
        events = loaded[inst_id]["funding"].dropna().sort_index()
        first_held, last_held = active.min(), active.max()
        relevant = events.loc[
            (events.index >= first_held - maximum_gap)
            & (events.index <= last_held + maximum_gap)
        ]
        gaps = relevant.index.to_series().diff().dropna()
        first_ok = bool(len(relevant) and relevant.index.min() <= first_held + maximum_gap)
        last_ok = bool(len(relevant) and relevant.index.max() >= last_held - maximum_gap)
        gap_ok = bool(not len(gaps) or gaps.max() <= maximum_gap)
        rows.append(
            {
                "inst_id": inst_id,
                "first_held": str(first_held),
                "last_held": str(last_held),
                "event_count_near_held_span": int(len(relevant)),
                "maximum_event_gap_hours": (
                    float(gaps.max().total_seconds() / 3600.0) if len(gaps) else None
                ),
                "complete": bool(first_ok and last_ok and gap_ok),
            }
        )
    return {
        "held_assets": int(len(rows)),
        "complete_assets": int(sum(row["complete"] for row in rows)),
        "complete": bool(rows and all(row["complete"] for row in rows)),
        "maximum_allowed_event_gap_hours": float(maximum_event_gap_hours),
        "assets": rows,
    }


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _minimum_contract_notional(spec: dict[str, Any], price: float) -> tuple[float | None, float | None]:
    contract_value = _number(spec.get("ctVal"))
    minimum_size = _number(spec.get("minSz"))
    if contract_value is None or minimum_size is None or contract_value <= 0 or minimum_size <= 0:
        return None, None
    base = str(spec.get("instId", "")).split("-")[0]
    value_ccy = str(spec.get("ctValCcy", ""))
    if value_ccy == base:
        notional_per_contract = contract_value * float(price)
    elif value_ccy in {"USD", "USDT", "USDC"}:
        notional_per_contract = contract_value
    else:
        return None, None
    return minimum_size * notional_per_contract, notional_per_contract


def _current_order_feasibility(
    weights: pd.Series,
    prices: pd.Series,
    raw_specs: list[dict[str, Any]],
    *,
    capital_usdt: float,
    maximum_notional_error_fraction: float,
) -> dict[str, Any]:
    specs = {str(row.get("instId")): row for row in raw_specs}
    rows = []
    for inst_id, weight in weights.items():
        if abs(float(weight)) <= EPSILON:
            continue
        target = abs(float(weight)) * float(capital_usdt)
        spec = specs.get(inst_id)
        price = _number(prices.get(inst_id))
        if spec is None or price is None or price <= 0:
            rows.append({"inst_id": inst_id, "target_notional_usdt": target, "complete": False})
            continue
        minimum_notional, per_contract = _minimum_contract_notional(spec, price)
        lot_size = _number(spec.get("lotSz"))
        minimum_size = _number(spec.get("minSz"))
        if minimum_notional is None or per_contract is None or lot_size is None or lot_size <= 0:
            rows.append({"inst_id": inst_id, "target_notional_usdt": target, "complete": False})
            continue
        desired_contracts = target / per_contract
        rounded_contracts = round(desired_contracts / lot_size) * lot_size
        rounded_contracts = max(float(minimum_size), rounded_contracts)
        achieved = rounded_contracts * per_contract
        error_fraction = abs(achieved - target) / target if target > 0 else 0.0
        rows.append(
            {
                "inst_id": inst_id,
                "side": "long" if weight > 0 else "short",
                "target_notional_usdt": target,
                "minimum_notional_usdt": minimum_notional,
                "rounded_contracts": rounded_contracts,
                "achieved_notional_usdt": achieved,
                "notional_error_fraction": error_fraction,
                "complete": True,
                "within_error_tolerance": bool(
                    error_fraction <= float(maximum_notional_error_fraction)
                ),
            }
        )
    complete_rows = [row for row in rows if row.get("complete")]
    feasible_rows = [row for row in complete_rows if row.get("within_error_tolerance")]
    return {
        "capital_usdt": float(capital_usdt),
        "active_legs": int(len(rows)),
        "spec_complete_legs": int(len(complete_rows)),
        "legs_within_error_tolerance": int(len(feasible_rows)),
        "feasible_fraction": float(len(feasible_rows) / len(rows)) if rows else 0.0,
        "maximum_notional_error_fraction": float(maximum_notional_error_fraction),
        "current_snapshot_only": True,
        "rows": rows,
    }


def _classify(checks: dict[str, bool]) -> dict[str, Any]:
    hard = [
        "return_evidence_complete",
        "funding_evidence_complete",
        "full_period_net_positive",
    ]
    readiness = [
        "post_source_noncollapse",
        "double_cost_net_positive",
        "drawdown_within_limit",
        "spot_perpetual_tracking_consistent",
        "current_100u_order_feasibility",
    ]
    failed_hard = [name for name in hard if not checks.get(name, False)]
    failed_readiness = [name for name in readiness if not checks.get(name, False)]
    if failed_hard:
        return {
            "status": "execution_translation_reject",
            "failed_checks": failed_hard + failed_readiness,
            "meaning": "The frozen signal lacks complete or positive executable-perpetual evidence.",
        }
    if failed_readiness:
        return {
            "status": "execution_translation_watchlist",
            "failed_checks": failed_readiness,
            "meaning": "Economics are positive, but execution readiness is not robust enough for paper design.",
        }
    return {
        "status": "execution_translation_pass_for_paper_design",
        "failed_checks": [],
        "meaning": "Execution translation may inform later paper design; factor promotion and capital remain prohibited.",
    }


def run_execution_translation_audit(
    contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    locked_hashes = _verify_contract(contract)
    daily_weights, spot_close, signal_summary = _load_frozen_signal(contract)
    loaded, matrices, execution_inputs = _load_perpetual_panel(contract)

    start = _utc(contract["evaluation_start_utc"])
    end = _utc(contract["evaluation_end_utc"])
    execution_index = matrices["returns"].index[
        (matrices["returns"].index >= start) & (matrices["returns"].index <= end)
    ]
    if not len(execution_index):
        raise ValueError("execution_audit_empty_perpetual_window")
    if execution_index.min() != start or execution_index.max() != end:
        raise ValueError(
            "execution_audit_perpetual_window_incomplete:"
            f"{execution_index.min()}:{execution_index.max()}"
        )
    weights = _daily_targets_to_intraday(daily_weights, execution_index)
    weights = weights.reindex(columns=matrices["returns"].columns).fillna(0.0)

    costs = contract["perpetual_contract"]["cost_scenarios_bps_one_way"]
    periods = {
        "full": execution_index,
        "source_overlap": execution_index[execution_index < _utc("2025-12-01T00:00:00Z")],
        "post_source": execution_index[execution_index >= _utc("2025-12-01T00:00:00Z")],
    }
    standard: dict[str, dict[str, Any]] = {}
    internal: dict[str, dict[str, Any]] = {}
    for name, index in periods.items():
        metrics = _portfolio_metrics(
            weights,
            matrices["returns"],
            matrices["funding_cost"],
            index,
            one_way_cost_bps=float(costs["standard"]),
            include_series=True,
        )
        internal[name] = {
            "hourly_net": metrics.pop("_hourly_net"),
            "daily_net": metrics.pop("_daily_net"),
            "daily_price": metrics.pop("_daily_price"),
        }
        standard[name] = metrics
    stress = _portfolio_metrics(
        weights,
        matrices["returns"],
        matrices["funding_cost"],
        execution_index,
        one_way_cost_bps=float(costs["double_cost_stress"]),
    )

    spot_returns = spot_close.pct_change(fill_method=None)
    spot_index = spot_returns.index[(spot_returns.index >= start.normalize()) & (spot_returns.index <= end)]
    spot_weights = daily_weights.reindex(spot_index).fillna(0.0)
    spot_gross = (spot_weights * spot_returns.reindex(spot_index).fillna(0.0)).sum(axis=1)
    tracking = pd.concat(
        [spot_gross.rename("spot"), internal["full"]["daily_price"].rename("perpetual")],
        axis=1,
        join="inner",
    ).dropna()
    tracking_correlation = float(tracking.corr().iloc[0, 1]) if len(tracking) >= 3 else 0.0

    funding_coverage = _funding_coverage_audit(
        weights,
        loaded,
        maximum_event_gap_hours=float(
            contract["perpetual_contract"]["maximum_funding_event_gap_hours"]
        ),
    )
    latest_weights = daily_weights.loc[daily_weights.index <= end].iloc[-1]
    latest_prices = matrices["close"].loc[matrices["close"].index <= end].ffill().iloc[-1]
    try:
        raw_specs = panel.data_module.fetch_okx_instruments("SWAP")
        feasibility = _current_order_feasibility(
            latest_weights,
            latest_prices,
            raw_specs,
            capital_usdt=float(contract["current_order_diagnostic"]["capital_usdt"]),
            maximum_notional_error_fraction=float(
                contract["current_order_diagnostic"]["maximum_notional_error_fraction"]
            ),
        )
        feasibility["fetch_error"] = None
    except Exception as exc:
        feasibility = {
            "capital_usdt": float(contract["current_order_diagnostic"]["capital_usdt"]),
            "active_legs": int((latest_weights.abs() > EPSILON).sum()),
            "spec_complete_legs": 0,
            "legs_within_error_tolerance": 0,
            "feasible_fraction": 0.0,
            "current_snapshot_only": True,
            "rows": [],
            "fetch_error": str(exc),
        }

    thresholds = contract["classification_thresholds"]
    checks = {
        "return_evidence_complete": bool(
            all(row["return_evidence_complete_while_held"] for row in standard.values())
        ),
        "funding_evidence_complete": bool(funding_coverage["complete"]),
        "full_period_net_positive": bool(standard["full"]["arithmetic_net_return"] > 0),
        "post_source_noncollapse": bool(
            standard["post_source"]["arithmetic_net_return"]
            >= float(thresholds["post_source_return_floor"])
        ),
        "double_cost_net_positive": bool(stress["arithmetic_net_return"] > 0),
        "drawdown_within_limit": bool(
            standard["full"]["max_drawdown"] <= float(thresholds["maximum_drawdown"])
        ),
        "spot_perpetual_tracking_consistent": bool(
            tracking_correlation >= float(thresholds["minimum_spot_perpetual_daily_correlation"])
        ),
        "current_100u_order_feasibility": bool(
            feasibility["feasible_fraction"]
            >= float(thresholds["minimum_current_order_feasible_fraction"])
        ),
    }
    classification = _classify(checks)
    return {
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "audit_id": contract["audit_id"],
        "audit_type": "frozen_factor_execution_translation",
        "contract_path": str(contract_path),
        "contract_sha256": _sha256(contract_path),
        "locked_file_hashes_verified": locked_hashes,
        "source_candidate_id": contract["source_candidate_id"],
        "source_factor_status_unchanged": "prospective_shadow_strong",
        "factor_trial_registry_events_written": 0,
        "evaluation_window": {
            "start": str(execution_index.min()),
            "end": str(execution_index.max()),
            "hours": int(len(execution_index)),
        },
        "signal_reconstruction": signal_summary,
        "execution_inputs": execution_inputs,
        "perpetual_standard_cost": standard,
        "perpetual_double_cost_stress": stress,
        "spot_perpetual_tracking": {
            "daily_observations": int(len(tracking)),
            "daily_gross_return_correlation": tracking_correlation,
            "mean_absolute_daily_return_difference": float(
                (tracking["spot"] - tracking["perpetual"]).abs().mean()
            ) if len(tracking) else None,
        },
        "funding_evidence": funding_coverage,
        "current_100u_order_diagnostic": feasibility,
        "spot_margin_borrow_path": {
            "status": "blocked_missing_point_in_time_borrow_evidence",
            "historical_pnl_computed": False,
            "reason": (
                "OKX borrow rates and limits are authenticated, account-specific current data; "
                "interest history describes actual account liabilities, not hypothetical historical availability."
            ),
        },
        "checks": checks,
        "classification": classification,
        "claim_limits": contract["claim_limits"],
        "next_action": (
            "Design a no-order live shadow executor only if the classification passes for paper design; "
            "otherwise retain the factor prospective track and resolve only the named execution failures."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    report = run_execution_translation_audit(args.contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "classification": report["classification"],
        "full": report["perpetual_standard_cost"]["full"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
