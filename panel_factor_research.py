"""Multi-asset crypto factor research diagnostics.

This is the next-stage research layer after the single-BTC strategy grid. It
tests pre-declared cross-sectional factors on an OKX perpetual panel before any
factor is allowed to become a tradable strategy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import config
import data as data_module
import panel_artifact_cache
import panel_candidate_registry as candidate_registry
import panel_critic_contract
import panel_gate_calibration
import panel_gate_policy
import panel_gate_policy_v3
import panel_overfit_audit
import panel_run_registry
import panel_stage_policy
import panel_substrate_cache
import panel_universe
from backtest import annualized_sharpe, max_drawdown


LOG_DIR = Path(config.LOG_DIR)
FACTORY_RUN_STAGE = "stage_3_full_historical_audit"
PANEL_SUBSTRATE_DIR = Path(config.CACHE_DIR) / "panel_substrates" / "v1"
PANEL_ARTIFACT_CACHE_DIR = Path(config.CACHE_DIR) / "panel_evidence_artifacts" / "v1"
SPLIT_NAMES = ["IS", "Val", "Holdout"]
FORWARD_RETURN_HORIZON_BARS = 24
BASELINE_FACTOR_NAMES = {
    "momentum_7d",
    "short_reversal_24h",
    "liquidity_size",
    "amihud_illiquidity_7d",
    "funding_carry",
    "basis_carry",
}

FACTOR_DEFINITIONS = {
    "momentum_24h": {
        "family": "momentum",
        "direction": 1,
        "logic": "Recent 24h continuation, tested cross-sectionally instead of as BTC timing.",
    },
    "momentum_7d": {
        "family": "momentum",
        "direction": 1,
        "logic": "Medium-horizon continuation across liquid perpetuals.",
    },
    "short_reversal_24h": {
        "family": "reversal",
        "direction": -1,
        "logic": "One-day reversal after crowded short-term moves.",
    },
    "low_vol_7d": {
        "family": "risk",
        "direction": -1,
        "logic": "Lower realized volatility assets may have better risk-adjusted carry.",
    },
    "liquidity_size": {
        "family": "liquidity",
        "direction": 1,
        "logic": "Liquid assets may have lower trading frictions and more persistent flows.",
    },
    "liquidity_change_7d": {
        "family": "liquidity",
        "direction": 1,
        "logic": "Improving liquidity can indicate broadening participation before price response.",
    },
    "amihud_illiquidity_7d": {
        "family": "liquidity",
        "direction": -1,
        "logic": "Lower price impact per dollar volume is preferred; high illiquidity is penalized.",
    },
    "volume_shock_24h": {
        "family": "liquidity",
        "direction": 1,
        "logic": "Participation shock as a flow confirmation signal.",
    },
    "funding_carry": {
        "family": "carry",
        "direction": -1,
        "deprecated_for_candidates": True,
        "logic": "Legacy directional diagnostic only; funding does not authorize a standalone perp-return sign.",
    },
    "funding_extreme_reversal": {
        "family": "carry_reversal",
        "direction": -1,
        "deprecated_for_candidates": True,
        "logic": "Legacy directional diagnostic only; extreme funding requires a separately sourced return mechanism.",
    },
    "trend_carry_aligned": {
        "family": "composite",
        "direction": 1,
        "deprecated_for_candidates": True,
        "logic": "Legacy directional diagnostic only; the funding interaction is not source-authorized for AI search.",
    },
    "liquidity_neutral_momentum_7d": {
        "family": "momentum",
        "direction": 1,
        "logic": "Residual 7d momentum after removing same-timestamp liquidity-size exposure.",
    },
    "liquidity_neutral_funding_carry": {
        "family": "carry",
        "direction": -1,
        "deprecated_for_candidates": True,
        "logic": "Legacy directional diagnostic only; neutralization does not supply a funding return sign.",
    },
    "basis_carry": {
        "family": "carry",
        "direction": -1,
        "deprecated_for_candidates": True,
        "logic": "Legacy directional diagnostic only; perpetual basis is not dated-futures basis and has no standalone perp-return sign.",
    },
    "funding_persistence": {
        "family": "carry",
        "direction": -1,
        "deprecated_for_candidates": True,
        "logic": "Legacy directional diagnostic only; persistence belongs in a spot-perp carry construction first.",
    },
    "basis_funding_dislocation": {
        "family": "carry",
        "direction": -1,
        "deprecated_for_candidates": True,
        "logic": "Legacy directional diagnostic only; dislocation evidence does not identify the outright perp direction.",
    },
    "liquidity_bucket_momentum": {
        "family": "momentum",
        "direction": 1,
        "logic": "Seven-day momentum is compared only within same-timestamp liquidity buckets.",
    },
    "liquidity_bucket_reversal": {
        "family": "reversal",
        "direction": -1,
        "logic": "One-day reversal is compared only within same-timestamp liquidity buckets.",
    },
    "vol_managed_funding_carry": {
        "family": "carry",
        "direction": -1,
        "candidate_direction": "short",
        "deprecated_for_candidates": True,
        "logic": "Legacy directional diagnostic only; volatility scaling cannot repair an unsupported funding sign.",
    },
    "vol_managed_momentum": {
        "family": "momentum",
        "direction": 1,
        "candidate_direction": "long",
        "logic": "Seven-day momentum is scaled by realized volatility to penalize unstable trend.",
    },
    "oi_change_7d": {
        "family": "open_interest",
        "direction": 1,
        "logic": "Lagged seven-day OI growth is an audit baseline without standalone directional interpretation.",
    },
    "oi_price_crowding_reversal": {
        "family": "open_interest_crowding",
        "direction": -1,
        "candidate_direction": "short",
        "deprecated_for_candidates": True,
        "logic": "Price direction is faded when 24-hour-lagged OI growth indicates leveraged crowding.",
    },
    "oi_funding_crowding_reversal": {
        "family": "open_interest_crowding",
        "direction": -1,
        "candidate_direction": "short",
        "deprecated_for_candidates": True,
        "logic": "Funding-side crowding is faded when 24-hour-lagged OI growth confirms leverage build-up.",
    },
    "oi_price_crowding_reversal_v2": {
        "family": "open_interest_crowding",
        "direction": -1,
        "candidate_direction": "short",
        "logic": "Versioned preregistration: fade price direction when lagged OI growth indicates leveraged crowding.",
    },
    "oi_funding_crowding_reversal_v2": {
        "family": "open_interest_crowding",
        "direction": -1,
        "candidate_direction": "short",
        "logic": "Versioned preregistration: fade funding-side crowding when lagged OI growth confirms leverage build-up.",
    },
}

WEIGHTING_MODES = {
    "rank_linear": {
        "logic": "Dollar-neutral linear rank portfolio across all valid assets.",
    },
    "top_bottom_30": {
        "logic": "Dollar-neutral top/bottom 30 percent portfolio, equal weighted within each side.",
    },
}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _declared_candidate_batch_id(batch_path: str | None) -> str | None:
    if not batch_path:
        return None
    try:
        payload = json.loads(Path(batch_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("batch_id")
    return str(value) if value is not None else None


def _factor_run_code_references() -> list[dict[str, Any]]:
    modules = [
        config,
        data_module,
        panel_artifact_cache,
        candidate_registry,
        panel_critic_contract,
        panel_gate_calibration,
        panel_gate_policy,
        panel_gate_policy_v3,
        panel_overfit_audit,
        panel_run_registry,
        panel_stage_policy,
        panel_substrate_cache,
        panel_universe,
    ]
    references = [panel_run_registry.file_reference(Path(__file__), "panel_factor_research_code")]
    for module in modules:
        module_path = getattr(module, "__file__", None)
        if module_path:
            references.append(panel_run_registry.file_reference(module_path, f"code:{module.__name__}"))
    backtest_path = Path(__file__).with_name("backtest.py")
    references.append(panel_run_registry.file_reference(backtest_path, "code:backtest"))
    return references


def _factor_run_input_references(args: argparse.Namespace) -> list[dict[str, Any]]:
    project_dir = Path(__file__).resolve().parent
    declared = [
        ("panel_universe_registry", getattr(config, "PANEL_UNIVERSE_REGISTRY", project_dir / "PANEL_UNIVERSE_REGISTRY.json")),
        ("literature_hypothesis_registry", args.hypothesis_registry),
        ("trial_registry_source", args.trial_registry),
    ]
    if args.candidate_batch:
        declared.append(("candidate_batch", args.candidate_batch))
    if args.critic_report:
        declared.append(("independent_critic_report", args.critic_report))
        critic_payload = json.loads(Path(args.critic_report).read_text(encoding="utf-8"))
        formula_path = (((critic_payload.get("inputs") or {}).get("formula_audit_report") or {}).get("path"))
        if formula_path:
            declared.append(("differential_formula_audit_report", formula_path))
    if args.reference_report:
        declared.append(("reference_report", args.reference_report))
    if args.substrate_manifest:
        declared.append(("panel_substrate_manifest", args.substrate_manifest))
    return [panel_run_registry.file_reference(path, role) for role, path in declared]


def _build_factor_run_contract(args: argparse.Namespace, factor_scope: str) -> dict[str, Any]:
    return panel_run_registry.build_run_contract(
        run_kind="panel_factor_research",
        stage=FACTORY_RUN_STAGE,
        batch_id=_declared_candidate_batch_id(args.candidate_batch),
        parameters={
            "days": int(args.days),
            "symbols": [item.strip() for item in args.symbols.split(",") if item.strip()],
            "min_assets": int(args.min_assets),
            "rebalance_hours": int(args.rebalance_hours),
            "candidate_batch": str(Path(args.candidate_batch).resolve()) if args.candidate_batch else None,
            "critic_report": str(Path(args.critic_report).resolve()) if args.critic_report else None,
            "trial_registry": str(Path(args.trial_registry).resolve()),
            "trial_event_registry": str(Path(args.trial_event_registry).resolve()),
            "hypothesis_registry": str(Path(args.hypothesis_registry).resolve()),
            "factor_scope": factor_scope,
            "evaluation_funnel": args.evaluation_funnel,
            "force_refresh": bool(args.force_refresh),
            "declared_as_of_utc": args.as_of,
            "reference_report": str(Path(args.reference_report).resolve()) if args.reference_report else None,
            "substrate_manifest": str(Path(args.substrate_manifest).resolve()) if args.substrate_manifest else None,
            "require_cached_substrate": bool(args.require_cached_substrate),
            "substrate_cache_dir": str(Path(args.substrate_cache_dir).resolve()),
            "evidence_cache_enabled": not bool(args.disable_evidence_cache),
            "evidence_cache_dir": str(Path(args.evidence_cache_dir).resolve()),
            "cost_bps": float(config.COST_BPS),
            "slippage_bps": float(config.SLIPPAGE_BPS),
            "split_ratios": list(config.SPLIT_RATIOS),
            "numpy_version": np.__version__,
            "pandas_version": pd.__version__,
        },
        input_artifacts=_factor_run_input_references(args),
        code_artifacts=_factor_run_code_references(),
        policies={
            "holdout_access": "stage_3_audit_only",
            "stage_2_policy_version": panel_stage_policy.STAGE_POLICY_VERSION,
            "holdout_feedback_to_ai": False,
            "candidate_evaluation_requires_independent_critic_approval": True,
            "network_access": (
                "forbidden_panel_substrate_only"
                if args.substrate_manifest or args.require_cached_substrate
                else "cache_preferred_but_missing_inputs_may_fetch"
            ),
            "sqlite_is_evidence_authority": False,
            "immutable_run_evidence_required": True,
            "raw_path_evidence_cache_may_be_reused": not bool(args.disable_evidence_cache),
            "multiplicity_and_classification_recomputed_each_run": True,
        },
    )


def _attach_factory_run_metadata(
    report: dict[str, Any],
    *,
    contract: dict[str, Any],
    contract_path: Path,
    registry: panel_run_registry.RunRegistry,
) -> None:
    report["factory_run"] = {
        "run_id": contract["run_id"],
        "run_kind": contract["run_kind"],
        "stage": contract["stage"],
        "contract_sha256": contract["contract_sha256"],
        "contract_path": str(contract_path),
        "sqlite_index_path": str(registry.index_path),
        "sqlite_is_rebuildable_index_only": True,
    }


def _periods_per_year() -> int:
    if config.BAR == "15m":
        return 365 * 24 * 4
    if config.BAR == "4H":
        return 365 * 6
    return 365 * 24


def _pct_change(frame: pd.DataFrame, periods: int = 1) -> pd.DataFrame:
    return frame.pct_change(periods=periods, fill_method=None)


def _lag_daily_events_to_intraday(
    daily_events: pd.DataFrame,
    intraday_index: pd.DatetimeIndex,
    *,
    lag_days: int = 1,
) -> pd.DataFrame:
    """Align daily third-party observations with an explicit information lag."""
    lagged = daily_events.sort_index().copy()
    if len(lagged):
        lagged.index = lagged.index + pd.Timedelta(days=int(lag_days))
    median_bar = intraday_index.to_series().diff().median() if len(intraday_index) > 1 else pd.Timedelta(hours=1)
    bars_per_day = max(int(pd.Timedelta(days=1) / median_bar), 1) if median_bar > pd.Timedelta(0) else 24
    return lagged.reindex(intraday_index).ffill(limit=max(bars_per_day - 1, 0))


def _normal_sf(value: float) -> float:
    return 0.5 * math.erfc(value / math.sqrt(2.0))


def _split_index(index: pd.DatetimeIndex, ratios: tuple[float, float, float] | None = None) -> dict[str, pd.DatetimeIndex]:
    ratios = ratios or config.SPLIT_RATIOS
    n = len(index)
    is_end = int(n * ratios[0])
    val_end = int(n * (ratios[0] + ratios[1]))
    return {
        "IS": index[:is_end],
        "Val": index[is_end:val_end],
        "Holdout": index[val_end:],
    }


def _purge_forward_returns_at_split_boundaries(
    fwd_returns: pd.DataFrame,
    split_indexes: dict[str, pd.DatetimeIndex],
    *,
    horizon_bars: int = FORWARD_RETURN_HORIZON_BARS,
) -> pd.DataFrame:
    purged = fwd_returns.copy()
    if horizon_bars <= 0 or purged.empty:
        return purged
    for split_name, split_index in split_indexes.items():
        if len(split_index) == 0:
            continue
        source_positions = purged.index.get_indexer(split_index)
        invalid = source_positions < 0
        target_positions = source_positions + int(horizon_bars)
        invalid |= target_positions >= len(purged.index)
        valid_locations = np.flatnonzero(~invalid)
        if len(valid_locations):
            target_times = purged.index[target_positions[valid_locations]]
            invalid[valid_locations] |= target_times > split_index.max()
        invalid_index = split_index[invalid]
        if len(invalid_index):
            purged.loc[invalid_index] = np.nan
    return purged


def _spearman_by_time(factor: pd.DataFrame, fwd_ret: pd.DataFrame, min_assets: int) -> pd.Series:
    common_index = factor.index.intersection(fwd_ret.index)
    x = factor.reindex(common_index)
    y = fwd_ret.reindex(common_index)
    valid_counts = (x.notna() & y.notna()).sum(axis=1)
    ic = x.rank(axis=1).corrwith(y.rank(axis=1), axis=1)
    ic[valid_counts < min_assets] = np.nan
    return ic.sort_index()


def _rank_weights(factor: pd.DataFrame, min_assets: int) -> pd.DataFrame:
    ranks = factor.rank(axis=1, pct=True)
    weights = ranks - 0.5
    counts = factor.notna().sum(axis=1)
    weights[counts < min_assets] = np.nan
    weights = weights.sub(weights.mean(axis=1), axis=0)
    gross = weights.abs().sum(axis=1).replace(0, np.nan)
    return weights.div(gross, axis=0).fillna(0.0)


def _top_bottom_weights(factor: pd.DataFrame, min_assets: int, quantile: float = 0.30) -> pd.DataFrame:
    rows = []
    for ts, values in factor.iterrows():
        valid = values.dropna()
        out = pd.Series(0.0, index=factor.columns, name=ts)
        if len(valid) < min_assets:
            rows.append(out)
            continue
        side_count = max(1, int(len(valid) * quantile))
        bottom = valid.nsmallest(side_count).index
        top = valid.nlargest(side_count).index
        out.loc[top] = 0.5 / len(top)
        out.loc[bottom] = -0.5 / len(bottom)
        rows.append(out)
    return pd.DataFrame(rows).reindex(factor.index).fillna(0.0)


def _factor_weights(factor: pd.DataFrame, min_assets: int, weighting_mode: str) -> pd.DataFrame:
    if weighting_mode == "rank_linear":
        return _rank_weights(factor, min_assets)
    if weighting_mode == "top_bottom_30":
        return _top_bottom_weights(factor, min_assets, quantile=0.30)
    raise ValueError(f"unknown weighting mode: {weighting_mode}")


def _apply_rebalance(weights: pd.DataFrame, every_hours: int) -> pd.DataFrame:
    if every_hours <= 1:
        return weights
    marker = pd.Series(weights.index, index=weights.index).dt.floor(f"{every_hours}h")
    update = marker.ne(marker.shift(1)).fillna(True)
    held = weights.where(update, np.nan).ffill().fillna(0.0)
    return held


def _held_weights(factor: pd.DataFrame, min_assets: int, rebalance_hours: int, weighting_mode: str) -> pd.DataFrame:
    raw_weights = _factor_weights(factor, min_assets, weighting_mode)
    return _apply_rebalance(raw_weights, rebalance_hours).shift(1).fillna(0.0)


def _cross_sectional_residual(y: pd.DataFrame, x: pd.DataFrame, min_assets: int) -> pd.DataFrame:
    rows = []
    index = y.index.intersection(x.index)
    for ts in index:
        yy = y.loc[ts]
        xx = x.loc[ts]
        valid = yy.notna() & xx.notna()
        if int(valid.sum()) < min_assets:
            rows.append(pd.Series(np.nan, index=y.columns, name=ts))
            continue
        x_vals = xx[valid].astype(float)
        y_vals = yy[valid].astype(float)
        x_centered = x_vals - x_vals.mean()
        denom = float((x_centered * x_centered).sum())
        out = pd.Series(np.nan, index=y.columns, name=ts)
        if denom <= 0:
            out.loc[valid] = y_vals - y_vals.mean()
        else:
            beta = float(((y_vals - y_vals.mean()) * x_centered).sum() / denom)
            fitted = y_vals.mean() + beta * x_centered
            out.loc[valid] = y_vals - fitted
        rows.append(out)
    return pd.DataFrame(rows).reindex(y.index)


def _basis_from_prices(perp_close: pd.DataFrame, spot_close: pd.DataFrame) -> pd.DataFrame:
    spot_aligned = spot_close.reindex(perp_close.index)
    basis = perp_close / spot_aligned - 1.0
    valid = perp_close.notna() & spot_aligned.notna() & (spot_aligned > 0)
    return basis.where(valid)


def _liquidity_bucket_neutral_signal(
    signal: pd.DataFrame,
    liquidity_size: pd.DataFrame,
    min_assets: int,
    buckets: int = 3,
) -> pd.DataFrame:
    rows = []
    index = signal.index.intersection(liquidity_size.index)
    for ts in index:
        yy = signal.loc[ts]
        liq = liquidity_size.loc[ts]
        valid = yy.notna() & liq.notna()
        out = pd.Series(np.nan, index=signal.columns, name=ts)
        if int(valid.sum()) < min_assets:
            rows.append(out)
            continue
        valid_liq = liq[valid].astype(float)
        valid_signal = yy[valid].astype(float)
        try:
            bucket_labels = pd.qcut(valid_liq.rank(method="first"), q=min(buckets, int(valid.sum())), labels=False)
        except ValueError:
            out.loc[valid] = valid_signal - valid_signal.mean()
            rows.append(out)
            continue
        for bucket in sorted(pd.Series(bucket_labels).dropna().unique()):
            members = bucket_labels == bucket
            if int(members.sum()) <= 1:
                continue
            bucket_values = valid_signal[members]
            out.loc[bucket_values.index] = bucket_values - bucket_values.mean()
        rows.append(out)
    return pd.DataFrame(rows).reindex(signal.index)


def _candidate_direction_multiplier(direction: str) -> int:
    if (direction or "").lower() == "short":
        return -1
    return 1


def _formula_candidate_direction(formula_spec: dict[str, Any]) -> str | None:
    explicit = formula_spec.get("candidate_direction")
    if explicit:
        return str(explicit)
    direction = formula_spec.get("direction")
    if direction == 1:
        return "long"
    if direction == -1:
        return "short"
    return None


def _apply_candidate_controls(
    signal: pd.DataFrame,
    candidate: dict[str, Any],
    *,
    eligibility: pd.DataFrame,
    liquidity_size: pd.DataFrame,
    min_assets: int,
) -> pd.DataFrame:
    controlled = signal.where(eligibility)
    neutralization = str(candidate.get("neutralization", "none"))
    bucket_policy = str(candidate.get("bucket_policy", "none"))
    if neutralization == "liquidity_size":
        controlled = _cross_sectional_residual(
            controlled,
            liquidity_size.where(eligibility),
            min_assets,
        )
    elif neutralization == "liquidity_bucket":
        controlled = _liquidity_bucket_neutral_signal(
            controlled,
            liquidity_size.where(eligibility),
            min_assets,
        )
    if bucket_policy == "liquidity_tercile":
        controlled = _liquidity_bucket_neutral_signal(
            controlled,
            liquidity_size.where(eligibility),
            min_assets,
        )
    elif bucket_policy == "large_liquid_only":
        large_mask = panel_universe.top_n_mask(
            liquidity_size,
            eligibility,
            min(8, max(2, len(liquidity_size.columns))),
        )
        controlled = controlled.where(large_mask)
    return controlled


def _load_candidate_definitions(
    batch_path: str | None,
    literature_registry_path: Path | str = candidate_registry.REGISTRY_PATH,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    if not batch_path:
        return [], [], None
    payload = candidate_registry.load_candidate_batch(batch_path)
    candidates = payload.get("candidates", [])
    source_ids = candidate_registry.load_literature_source_ids(literature_registry_path)
    accepted = []
    rejected = []
    known_formulas = set(FACTOR_DEFINITIONS)
    for candidate in candidates:
        ok, errors = candidate_registry.validate_candidate(
            candidate,
            literature_source_ids=source_ids,
            known_formulas=known_formulas,
            allowed_weighting_modes=set(WEIGHTING_MODES),
        )
        formula_spec = FACTOR_DEFINITIONS.get(str(candidate.get("panel_formula")), {})
        expected_direction = _formula_candidate_direction(formula_spec)
        if expected_direction and str(candidate.get("direction", "")).lower() != expected_direction:
            errors.append(f"formula_direction_mismatch:{expected_direction}")
            ok = False
        if formula_spec.get("deprecated_for_candidates"):
            errors.append("formula_deprecated_for_candidates")
            ok = False
        if ok:
            accepted.append(candidate_registry.normalize_candidate(candidate))
        else:
            rejected.append({"candidate": candidate, "errors": errors})
            candidate_registry.append_trial_event(
                candidate,
                event="schema_rejected",
                status="rejected",
                reason=";".join(errors),
                batch_id=payload.get("batch_id"),
            )
    return accepted, rejected, payload.get("batch_id")


def _truncate_panel_as_of(panel: dict[str, dict[str, Any]], as_of: Any) -> dict[str, dict[str, Any]]:
    cutoff = pd.Timestamp(as_of)
    cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
    truncated = {}
    for inst_id, item in panel.items():
        clean = dict(item)
        for key in ("ohlcv", "spot_ohlcv", "open_interest", "market_cap"):
            value = clean.get(key)
            if value is not None:
                clean[key] = value.loc[value.index <= cutoff].copy()
        funding = clean.get("funding")
        if funding is not None:
            clean["funding"] = funding.loc[funding.index <= cutoff].copy()
        truncated[inst_id] = clean
    return truncated


def _panel_substrate_request(
    args: argparse.Namespace,
    inst_ids: list[str],
    as_of: Any | None,
) -> dict[str, Any]:
    return panel_substrate_cache.build_request_contract(
        inst_ids=inst_ids,
        days=args.days,
        bar=config.BAR,
        as_of=as_of,
        load_spot=True,
        load_open_interest=True,
        load_market_cap=True,
        universe_registry_path=config.PANEL_UNIVERSE_REGISTRY,
        loader_code_paths=[
            Path(__file__),
            Path(data_module.__file__),
            Path(panel_substrate_cache.__file__),
            Path(panel_universe.__file__),
        ],
    )


def _source_inventory(inst_ids: list[str], days: int) -> dict[str, Any]:
    return panel_substrate_cache.collect_source_inventory(
        data_module,
        inst_ids,
        days,
        config.BAR,
        load_spot=True,
        load_open_interest=True,
        load_market_cap=True,
    )


def _resolve_panel_substrate(
    args: argparse.Namespace,
    inst_ids: list[str],
    as_of: Any | None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    store = panel_substrate_cache.PanelSubstrateStore(args.substrate_cache_dir)
    request_contract = _panel_substrate_request(args, inst_ids, as_of)
    if args.substrate_manifest:
        explicit_path = Path(args.substrate_manifest).expanduser().resolve(strict=True)
        if explicit_path.name != "manifest.json" or explicit_path.parent.parent.name != "objects":
            raise ValueError("panel_substrate_manifest_path_layout_invalid")
        store = panel_substrate_cache.PanelSubstrateStore(explicit_path.parents[2])
        manifest = store.read_manifest(explicit_path)
        compatible, failures = panel_substrate_cache.request_compatibility(
            manifest["request_contract"],
            request_contract,
            allow_loader_code_change=True,
        )
        if not compatible:
            raise ValueError(f"frozen_panel_substrate_request_mismatch:{failures}")
        panel, load_failures, manifest = store.load(
            explicit_path,
            panel_fingerprint_fn=_panel_input_fingerprint,
        )
        input_fingerprint = _panel_input_fingerprint(panel)
        return panel, load_failures, input_fingerprint, {
            "mode": "explicit_frozen_manifest",
            "cache_hit": True,
            "cache_reason": "explicit_manifest",
            "panel_loader_invoked": False,
            "zero_network_panel_load": True,
            "formal_frozen_contract": manifest["request_contract"]["cutoff"]["mode"] == "explicit_as_of",
            "request_key": manifest["request_contract"]["request_key"],
            "substrate_id": manifest["substrate_id"],
            "manifest_path": manifest["manifest_path"],
            "manifest_sha256": manifest["manifest_sha256"],
            "source_inventory_fingerprint": manifest["source_inventory"]["fingerprint"],
        }

    inventory_before = _source_inventory(inst_ids, args.days)
    cache_reason = "force_refresh"
    if not args.force_refresh:
        hit, cache_reason = store.lookup(request_contract, inventory_before)
        if hit is not None:
            panel, load_failures, manifest = store.load(
                hit["manifest_path"],
                panel_fingerprint_fn=_panel_input_fingerprint,
            )
            input_fingerprint = _panel_input_fingerprint(panel)
            return panel, load_failures, input_fingerprint, {
                "mode": "automatic_validated_alias",
                "cache_hit": True,
                "cache_reason": cache_reason,
                "panel_loader_invoked": False,
                "zero_network_panel_load": True,
                "formal_frozen_contract": False,
                "request_key": request_contract["request_key"],
                "substrate_id": manifest["substrate_id"],
                "manifest_path": manifest["manifest_path"],
                "manifest_sha256": manifest["manifest_sha256"],
                "source_inventory_fingerprint": inventory_before["fingerprint"],
            }
    if args.require_cached_substrate:
        raise ValueError(f"required_panel_substrate_unavailable:{cache_reason}")

    panel, load_failures = _load_panel(inst_ids, args.days, force_refresh=args.force_refresh)
    if as_of:
        panel = _truncate_panel_as_of(panel, as_of)
    input_fingerprint = _panel_input_fingerprint(panel)
    inventory_after = _source_inventory(inst_ids, args.days)
    manifest = store.write(
        panel=panel,
        failures=load_failures,
        request_contract=request_contract,
        panel_fingerprint=input_fingerprint,
        source_inventory=inventory_after,
    )
    return panel, load_failures, input_fingerprint, {
        "mode": "materialized_from_source_loaders",
        "cache_hit": False,
        "cache_reason": cache_reason,
        "panel_loader_invoked": True,
        "zero_network_panel_load": False,
        "formal_frozen_contract": False,
        "request_key": request_contract["request_key"],
        "substrate_id": manifest["substrate_id"],
        "manifest_path": manifest["manifest_path"],
        "manifest_sha256": manifest["manifest_sha256"],
        "source_inventory_fingerprint": inventory_after["fingerprint"],
    }


def _panel_input_fingerprint(panel: dict[str, dict[str, Any]]) -> dict[str, Any]:
    asset_hashes = {}
    for inst_id in sorted(panel):
        digest = hashlib.sha256()
        item = panel[inst_id]
        for key in ("ohlcv", "spot_ohlcv", "funding", "open_interest", "market_cap"):
            value = item.get(key)
            digest.update(key.encode("utf-8"))
            if value is None:
                digest.update(b"<missing>")
                continue
            frame = value.to_frame(name=value.name or "value") if isinstance(value, pd.Series) else value
            digest.update(json.dumps([str(column) for column in frame.columns]).encode("utf-8"))
            digest.update(np.asarray(frame.index.asi8, dtype="<i8").tobytes())
            for column in frame.columns:
                series = frame[column]
                digest.update(str(series.dtype).encode("utf-8"))
                if pd.api.types.is_numeric_dtype(series.dtype):
                    digest.update(np.ascontiguousarray(series.to_numpy()).tobytes())
                else:
                    digest.update(
                        json.dumps(series.astype(object).where(series.notna(), None).tolist(), default=str).encode("utf-8")
                    )
        metadata = {
            "instrument": item.get("instrument"),
            "asset_label": item.get("asset_label"),
        }
        digest.update(json.dumps(metadata, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8"))
        asset_hashes[inst_id] = digest.hexdigest()
    panel_digest = hashlib.sha256()
    for inst_id, value in asset_hashes.items():
        panel_digest.update(inst_id.encode("utf-8"))
        panel_digest.update(value.encode("ascii"))
    return {
        "method": "sha256_index_int64_column_dtype_raw_values_and_metadata_v1",
        "asset_count": len(asset_hashes),
        "panel_sha256": panel_digest.hexdigest(),
        "asset_sha256": asset_hashes,
    }


def _load_reaudit_contract(path: Path | str) -> dict[str, Any]:
    reference_path = Path(path)
    raw = reference_path.read_bytes()
    report = json.loads(raw)
    time_ranges = report.get("time_ranges") or {}
    if any(not (time_ranges.get(name) or {}).get("start") or not (time_ranges.get(name) or {}).get("end") for name in SPLIT_NAMES):
        raise ValueError("reference_report_missing_complete_time_ranges")
    identities = sorted(
        (
            str(row.get("candidate_id") or row.get("factor_name") or ""),
            str(row.get("panel_formula") or row.get("factor_name") or ""),
            str(row.get("weighting_mode") or ""),
        )
        for row in report.get("factors") or []
    )
    return {
        "path": str(reference_path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "created_at_utc": report.get("created_at_utc"),
        "candidate_batch_id": report.get("candidate_batch_id"),
        "multiple_testing_trial_count": int(report.get("multiple_testing_trial_count") or 0),
        "time_ranges": time_ranges,
        "evaluation_start_utc": time_ranges["IS"]["start"],
        "evaluation_end_utc": time_ranges["Holdout"]["end"],
        "path_identities": identities,
    }


def _attach_reaudit_comparability(report: dict[str, Any], contract: dict[str, Any]) -> None:
    reasons = []
    if report.get("candidate_batch_id") != contract.get("candidate_batch_id"):
        reasons.append("candidate_batch_id_changed")
    if int(report.get("multiple_testing_trial_count") or 0) != int(contract.get("multiple_testing_trial_count") or 0):
        reasons.append("multiple_testing_trial_count_changed")
    if report.get("time_ranges") != contract.get("time_ranges"):
        reasons.append("split_time_ranges_changed")
    identities = sorted(
        (
            str(row.get("candidate_id") or row.get("factor_name") or ""),
            str(row.get("panel_formula") or row.get("factor_name") or ""),
            str(row.get("weighting_mode") or ""),
        )
        for row in report.get("factors") or []
    )
    if identities != contract.get("path_identities"):
        reasons.append("evaluated_path_identities_changed")
    report["versioned_reaudit"] = {
        "reference_report_path": contract["path"],
        "reference_report_sha256": contract["sha256"],
        "reference_created_at_utc": contract["created_at_utc"],
        "input_contract_comparable": not reasons,
        "comparability_failures": reasons,
        "locked_dimensions": [
            "candidate_batch_id",
            "multiple_testing_trial_count",
            "split_time_ranges",
            "evaluated_path_identities",
        ],
    }


def _turnover_with_initial_entry(weights: pd.DataFrame) -> pd.Series:
    if weights.empty:
        return pd.Series(0.0, index=weights.index, dtype=float)
    turnover = weights.diff().abs().sum(axis=1)
    turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    return turnover


def _portfolio_metrics_from_weights(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    funding: pd.DataFrame,
    split_index: pd.DatetimeIndex,
    *,
    include_net_returns: bool = False,
) -> dict[str, Any]:
    weights = weights.reindex(split_index).fillna(0.0)
    raw_split_returns = returns.reindex(split_index)
    positioned_missing = raw_split_returns.isna() & weights.abs().gt(1e-12)
    weighted_missing_exposure = weights.abs().where(positioned_missing, 0.0).sum(axis=1)
    split_returns = raw_split_returns.fillna(0.0)
    split_funding = funding.reindex(split_index).fillna(0.0)
    gross_pnl = (weights * split_returns).sum(axis=1)
    turnover = _turnover_with_initial_entry(weights)
    cost = turnover * (config.COST_BPS + config.SLIPPAGE_BPS) / 10000.0
    # Factor weights are 1x notional fractions. Strategy leverage, if any, must
    # scale price PnL, costs, and funding together at the strategy layer.
    funding_cost = (weights * split_funding).sum(axis=1)
    net_pnl = (gross_pnl - cost - funding_cost).fillna(0.0)
    daily_net_pnl = panel_overfit_audit.aggregate_daily_returns(net_pnl)
    result = {
        "bars": int(len(net_pnl)),
        "sharpe": float(annualized_sharpe(net_pnl, _periods_per_year())),
        "daily_sharpe": float(annualized_sharpe(daily_net_pnl, 365)),
        "sharpe_primary_candidate_for_gate_v2": "daily_sharpe",
        "hourly_sharpe_status": "legacy_v1_diagnostic",
        "gross_sharpe": float(annualized_sharpe(gross_pnl.fillna(0.0), _periods_per_year())),
        "total_return": float(net_pnl.sum()),
        "gross_return": float(gross_pnl.sum()),
        "max_drawdown": float(max_drawdown(net_pnl)),
        "turnover": float(turnover.mean()),
        "cost_paid": float(cost.sum()),
        "funding_paid": float(funding_cost.sum()),
        "funding_abs_paid": float(funding_cost.abs().sum()),
        "avg_gross_exposure": float(weights.abs().sum(axis=1).mean()),
        "active_bars": int((weights.abs().sum(axis=1) > 0).sum()),
        "missing_return_asset_bars_while_held": int(positioned_missing.sum().sum()),
        "missing_return_hours_while_held": int(positioned_missing.any(axis=1).sum()),
        "weighted_missing_return_exposure_sum": float(weighted_missing_exposure.sum()),
        "weighted_missing_return_exposure_max": float(weighted_missing_exposure.max()) if len(weighted_missing_exposure) else 0.0,
        "return_evidence_complete_while_held": bool(not positioned_missing.any().any()),
        "exposure_accounting": "factor_1x_notional_v2",
    }
    if include_net_returns:
        result["_net_return_series"] = net_pnl
    return result


def _portfolio_metrics(
    factor: pd.DataFrame,
    returns: pd.DataFrame,
    funding: pd.DataFrame,
    split_index: pd.DatetimeIndex,
    min_assets: int,
    rebalance_hours: int,
    weighting_mode: str,
) -> dict[str, Any]:
    weights = _held_weights(factor, min_assets, rebalance_hours, weighting_mode)
    return _portfolio_metrics_from_weights(weights, returns, funding, split_index)


def _rolling_windows(index: pd.DatetimeIndex, days: int = 90) -> list[pd.DatetimeIndex]:
    windows = []
    current = index.min()
    end = index.max()
    while current < end:
        next_time = current + pd.Timedelta(days=days)
        part = index[(index >= current) & (index < next_time)]
        if len(part) > 24 * 14:
            windows.append(part)
        current = next_time
    return windows


def _rolling_factor_audit(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    funding: pd.DataFrame,
    ic_series: pd.Series,
    index: pd.DatetimeIndex,
) -> dict[str, Any]:
    rows = []
    for window_index in _rolling_windows(index, days=90):
        ic = ic_series.reindex(window_index).dropna()
        metrics = _portfolio_metrics_from_weights(
            weights,
            returns,
            funding,
            window_index,
        )
        rows.append(
            {
                "start": str(window_index[0]),
                "end": str(window_index[-1]),
                "bars": int(len(window_index)),
                "mean_rank_ic": float(ic.mean()) if len(ic) else 0.0,
                "sharpe": metrics["sharpe"],
                "total_return": metrics["total_return"],
                "max_drawdown": metrics["max_drawdown"],
                "turnover": metrics["turnover"],
            }
        )
    ic_values = [row["mean_rank_ic"] for row in rows]
    sharpe_values = [row["sharpe"] for row in rows]
    return {
        "window_days": 90,
        "window_count": len(rows),
        "positive_ic_windows": int(sum(value > 0 for value in ic_values)),
        "positive_sharpe_windows": int(sum(value > 0 for value in sharpe_values)),
        "min_rank_ic": float(min(ic_values)) if ic_values else 0.0,
        "min_sharpe": float(min(sharpe_values)) if sharpe_values else 0.0,
        "rows": rows,
    }


def _ic_summary(ic_series: pd.Series, index: pd.DatetimeIndex) -> dict[str, Any]:
    split_ic = ic_series.reindex(index).dropna()
    return {
        "observations": int(len(split_ic)),
        "mean_rank_ic": float(split_ic.mean()) if len(split_ic) else 0.0,
        "positive_ic_frac": float((split_ic > 0).mean()) if len(split_ic) else 0.0,
    }


def _large_liquid_mask(
    liquidity_size: pd.DataFrame,
    eligibility: pd.DataFrame,
    common_index: pd.DatetimeIndex,
    top_n: int = 8,
) -> pd.DataFrame:
    values = liquidity_size.reindex(common_index)
    eligible = eligibility.reindex(common_index).fillna(False)
    return panel_universe.top_n_mask(values, eligible, top_n)


def _liquidity_bucket_masks(
    liquidity_size: pd.DataFrame,
    common_index: pd.DatetimeIndex,
    min_assets: int,
) -> dict[str, pd.DataFrame]:
    labels = ["low", "mid", "high"]
    masks = {label: pd.DataFrame(False, index=common_index, columns=liquidity_size.columns) for label in labels}
    liquidity = liquidity_size.reindex(common_index)
    for ts, row in liquidity.iterrows():
        valid = row.dropna()
        if len(valid) < min_assets:
            continue
        bucket_labels = pd.qcut(valid.rank(method="first"), q=3, labels=labels)
        for label in labels:
            masks[label].loc[ts, bucket_labels[bucket_labels == label].index] = True
    return masks


def _crash_window_indexes(
    returns: pd.DataFrame,
    common_index: pd.DatetimeIndex,
    n_windows: int = 5,
) -> list[pd.DatetimeIndex]:
    market_ret = returns.reindex(common_index).mean(axis=1).rolling(24, min_periods=12).sum().dropna()
    if market_ret.empty:
        return []
    candidates = market_ret.nsmallest(max(n_windows * 4, n_windows))
    windows = []
    used = []
    for ts, _ in candidates.items():
        if any(abs((ts - old).total_seconds()) < 7 * 86400 for old in used):
            continue
        idx = common_index[(common_index >= ts - pd.Timedelta(days=3)) & (common_index <= ts + pd.Timedelta(days=3))]
        if len(idx) < 24:
            continue
        used.append(ts)
        windows.append(idx)
        if len(windows) >= n_windows:
            break
    return windows


def _robustness_split_diagnostics(
    factor: pd.DataFrame,
    returns: pd.DataFrame,
    fwd_returns: pd.DataFrame,
    funding: pd.DataFrame,
    split_indexes: dict[str, pd.DatetimeIndex],
    *,
    min_assets: int,
    rebalance_hours: int,
    weighting_mode: str,
    include_long_short: bool = True,
) -> dict[str, Any]:
    weights = _held_weights(factor, min_assets, rebalance_hours, weighting_mode) if include_long_short else None
    rank_ic_sample_hours = 1
    if include_long_short:
        ic_factor = factor
        ic_fwd_returns = fwd_returns.reindex(factor.index)
    else:
        rank_ic_sample_hours = 24
        sampled_index = factor.index[::24]
        ic_factor = factor.reindex(sampled_index)
        ic_fwd_returns = fwd_returns.reindex(sampled_index)
    ic_series = _spearman_by_time(ic_factor, ic_fwd_returns, min_assets)
    by_split = {}
    for split_name, idx in split_indexes.items():
        row = {
            "rank_ic": _ic_summary(ic_series, idx),
            "rank_ic_sample_hours": rank_ic_sample_hours,
            "coverage_median_assets": int(factor.reindex(idx).notna().sum(axis=1).median()) if len(idx) else 0,
        }
        if include_long_short:
            row["long_short"] = _portfolio_metrics_from_weights(weights, returns, funding, idx)
        by_split[split_name] = row
    return by_split


def _robustness_crash_diagnostics(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    funding: pd.DataFrame,
    ic_series: pd.Series,
    crash_windows: list[pd.DatetimeIndex],
) -> dict[str, Any]:
    rows = []
    for idx in crash_windows:
        ic = ic_series.reindex(idx).dropna()
        metrics = _portfolio_metrics_from_weights(weights, returns, funding, idx)
        rows.append(
            {
                "start": str(idx[0]),
                "end": str(idx[-1]),
                "bars": int(len(idx)),
                "mean_rank_ic": float(ic.mean()) if len(ic) else 0.0,
                "total_return": metrics["total_return"],
                "sharpe": metrics["sharpe"],
                "max_drawdown": metrics["max_drawdown"],
                "funding_paid": metrics["funding_paid"],
                "active_bars": metrics["active_bars"],
            }
        )
    returns_ = [row["total_return"] for row in rows]
    drawdowns = [row["max_drawdown"] for row in rows]
    return {
        "window_count": len(rows),
        "negative_return_windows": int(sum(value < 0 for value in returns_)),
        "worst_total_return": float(min(returns_)) if returns_ else 0.0,
        "worst_max_drawdown": float(max(drawdowns)) if drawdowns else 0.0,
        "rows": rows,
    }


def _asset_family_neutral_signal(
    factor: pd.DataFrame,
    asset_families: dict[str, str],
    *,
    min_family_size: int = 2,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Remove same-timestamp family means, excluding singleton families."""
    family_members: dict[str, list[str]] = {}
    for asset in factor.columns:
        family = asset_families.get(str(asset))
        if family:
            family_members.setdefault(str(family), []).append(asset)

    eligible_families = {
        family: members
        for family, members in family_members.items()
        if len(members) >= min_family_size
    }
    neutral = pd.DataFrame(np.nan, index=factor.index, columns=factor.columns)
    for members in eligible_families.values():
        values = factor.loc[:, members]
        neutral.loc[:, members] = values.sub(values.mean(axis=1), axis=0)
    return neutral, eligible_families


def _factor_robustness_diagnostics(
    factor: pd.DataFrame,
    weights: pd.DataFrame,
    ic_series: pd.Series,
    matrices: dict[str, pd.DataFrame],
    split_indexes: dict[str, pd.DatetimeIndex],
    common_index: pd.DatetimeIndex,
    *,
    min_assets: int,
    rebalance_hours: int,
    weighting_mode: str,
    large_mask: pd.DataFrame,
    large_top_n: int,
    bucket_masks: dict[str, pd.DataFrame],
    crash_windows: list[pd.DatetimeIndex],
    asset_families: dict[str, str],
    cross_sectional: dict[str, Any] | None = None,
) -> dict[str, Any]:
    returns = matrices["returns"]
    fwd_returns = matrices["fwd_returns"]
    funding = matrices["funding_cost"]

    if cross_sectional is None:
        large_min_assets = min(min_assets, large_top_n)
        large_factor = factor.reindex(common_index).where(large_mask.reindex(common_index))
        large_liquid = _robustness_split_diagnostics(
            large_factor,
            returns,
            fwd_returns,
            funding,
            split_indexes,
            min_assets=large_min_assets,
            rebalance_hours=rebalance_hours,
            weighting_mode=weighting_mode,
            include_long_short=False,
        )
        membership_bars = large_mask.sum(axis=0).sort_values(ascending=False)

        bucket_min_assets = max(2, min(4, min_assets // 2))
        bucket_reports = {}
        for bucket_name, mask in bucket_masks.items():
            bucket_factor = factor.reindex(common_index).where(mask.reindex(common_index))
            bucket_reports[bucket_name] = _robustness_split_diagnostics(
                bucket_factor,
                returns,
                fwd_returns,
                funding,
                split_indexes,
                min_assets=bucket_min_assets,
                rebalance_hours=rebalance_hours,
                weighting_mode=weighting_mode,
                include_long_short=False,
            )

        family_factor, eligible_families = _asset_family_neutral_signal(
            factor.reindex(common_index),
            asset_families,
        )
        family_min_assets = max(2, min(min_assets, sum(len(v) for v in eligible_families.values())))
        family_neutral = _robustness_split_diagnostics(
            family_factor,
            returns,
            fwd_returns,
            funding,
            split_indexes,
            min_assets=family_min_assets,
            rebalance_hours=rebalance_hours,
            weighting_mode=weighting_mode,
            include_long_short=False,
        )
        cross_sectional = {
            "large_liquid": {
                "selection": "point_in_time_lagged_liquidity_top_n",
                "top_n": large_top_n,
                "asset_membership_bars": {name: int(value) for name, value in membership_bars.items() if value > 0},
                "min_assets": large_min_assets,
                "splits": large_liquid,
            },
            "liquidity_buckets": {
                "min_assets": bucket_min_assets,
                "buckets": bucket_reports,
            },
            "asset_family_neutral": {
                "method": "same_timestamp_within_family_demean",
                "min_family_size": 2,
                "families": eligible_families,
                "min_assets": family_min_assets,
                "splits": family_neutral,
            },
        }

    return {
        **cross_sectional,
        "crash_windows": _robustness_crash_diagnostics(
            weights,
            returns,
            funding,
            ic_series,
            crash_windows,
        ),
        "note": "Robustness diagnostics are audit evidence and are not used to tune candidate formulas.",
    }


def _robustness_quality_checks(robustness: dict[str, Any]) -> dict[str, bool]:
    large_splits = ((robustness.get("large_liquid") or {}).get("splits") or {})
    large_val_ic = (((large_splits.get("Val") or {}).get("rank_ic") or {}).get("mean_rank_ic") or 0.0)
    large_hold_ic = (((large_splits.get("Holdout") or {}).get("rank_ic") or {}).get("mean_rank_ic") or 0.0)
    large_val_obs = int((((large_splits.get("Val") or {}).get("rank_ic") or {}).get("observations") or 0))
    large_hold_obs = int((((large_splits.get("Holdout") or {}).get("rank_ic") or {}).get("observations") or 0))

    bucket_splits = ((robustness.get("liquidity_buckets") or {}).get("buckets") or {})
    bucket_val_ics = []
    bucket_hold_ics = []
    for bucket in ("low", "mid", "high"):
        splits = bucket_splits.get(bucket) or {}
        bucket_val_ics.append((((splits.get("Val") or {}).get("rank_ic") or {}).get("mean_rank_ic") or 0.0))
        bucket_hold_ics.append((((splits.get("Holdout") or {}).get("rank_ic") or {}).get("mean_rank_ic") or 0.0))
    positive_val_buckets = sum(value > 0.0 for value in bucket_val_ics)
    positive_hold_buckets = sum(value > 0.0 for value in bucket_hold_ics)

    family_splits = ((robustness.get("asset_family_neutral") or {}).get("splits") or {})
    family_val_ic = (((family_splits.get("Val") or {}).get("rank_ic") or {}).get("mean_rank_ic") or 0.0)
    family_hold_ic = (((family_splits.get("Holdout") or {}).get("rank_ic") or {}).get("mean_rank_ic") or 0.0)
    family_val_obs = int((((family_splits.get("Val") or {}).get("rank_ic") or {}).get("observations") or 0))
    family_hold_obs = int((((family_splits.get("Holdout") or {}).get("rank_ic") or {}).get("observations") or 0))

    crash = robustness.get("crash_windows") or {}
    crash_count = int(crash.get("window_count") or 0)
    negative_crash_windows = int(crash.get("negative_return_windows") or 0)
    worst_crash_return = float(crash.get("worst_total_return") or 0.0)
    worst_crash_drawdown = float(crash.get("worst_max_drawdown") or 0.0)

    return {
        "robust_large_liquid_val_ic_positive": large_val_obs > 20 and large_val_ic > 0.0,
        "robust_large_liquid_holdout_nonnegative": large_hold_obs > 20 and large_hold_ic >= 0.0,
        "robust_bucket_val_not_single_bucket": positive_val_buckets >= 2,
        "robust_bucket_holdout_not_single_bucket": positive_hold_buckets >= 2,
        "robust_family_neutral_val_ic_positive": family_val_obs > 20 and family_val_ic > 0.0,
        "robust_family_neutral_holdout_nonnegative": family_hold_obs > 20 and family_hold_ic >= 0.0,
        "robust_crash_window_count": crash_count >= 3,
        "robust_crash_loss_contained": worst_crash_return > -0.05 and worst_crash_drawdown < 0.12,
        "robust_crash_not_mostly_negative": crash_count > 0 and negative_crash_windows / crash_count <= 0.40,
    }


def _trial_adjustment(ic_tstat: float, trial_count: int) -> dict[str, Any]:
    raw_p = _normal_sf(ic_tstat)
    adjusted_p = 1.0 - (1.0 - raw_p) ** max(trial_count, 1)
    return {
        "method": "sidak_one_sided_normal_approx_on_val_rank_ic_tstat",
        "trial_count": int(trial_count),
        "raw_one_sided_p": float(raw_p),
        "sidak_adjusted_p": float(adjusted_p),
        "pass": bool(adjusted_p < 0.05),
        "alpha": 0.05,
    }


def _attach_panel_overfit_audits(
    factor_reports: list[dict[str, Any]],
    selection_returns: dict[tuple[Any, ...], dict[str, pd.Series]],
    *,
    trial_count: int,
    split_indexes: dict[str, pd.DatetimeIndex],
) -> dict[str, Any]:
    daily_val: dict[tuple[Any, ...], pd.Series] = {}
    daily_selection: dict[str, pd.Series] = {}
    for path_key, by_split in selection_returns.items():
        if "Val" in by_split:
            daily_val[path_key] = panel_overfit_audit.aggregate_daily_returns(by_split["Val"])
        parts = [by_split[name] for name in ("IS", "Val") if name in by_split]
        if parts:
            label = "|".join(str(item) for item in path_key)
            combined = pd.concat(parts).sort_index()
            daily_selection[label] = panel_overfit_audit.aggregate_daily_returns(combined)

    archived_paths: dict[str, dict[str, list[Any]]] = {}
    empty_selection_path_count = 0
    for label, path in daily_selection.items():
        clean_path = path.replace([np.inf, -np.inf], np.nan).dropna().sort_index()
        if clean_path.empty:
            empty_selection_path_count += 1
            continue
        archived_paths[label] = {
            "dates": [timestamp.isoformat() for timestamp in clean_path.index],
            "net_returns": [float(value) for value in clean_path.to_numpy()],
        }

    trial_sharpes = [panel_overfit_audit.unannualized_sharpe(path) for path in daily_val.values()]
    selection_matrix = pd.concat(daily_selection, axis=1) if daily_selection else pd.DataFrame()
    pbo = panel_overfit_audit.cscv_pbo_audit(selection_matrix, n_splits=10, pass_threshold=0.20)
    pbo.update(
        {
            "strategy_path_scope": "current_run_unique_signal_and_weighting_paths",
            "full_trial_count": int(trial_count),
            "holdout_observation_count": 0,
            "selection_end": str(split_indexes["Val"][-1]) if len(split_indexes.get("Val", [])) else None,
            "holdout_start": str(split_indexes["Holdout"][0]) if len(split_indexes.get("Holdout", [])) else None,
        }
    )

    for row in factor_reports:
        path_key = row.pop("_selection_path_key")
        dsr = panel_overfit_audit.deflated_sharpe_audit(
            daily_val.get(path_key, pd.Series(dtype=float)),
            n_trials=trial_count,
            observed_trial_sharpes=trial_sharpes,
        )
        row["overfit_audit"] = {
            "deflated_sharpe": dsr,
            "cscv_pbo": pbo,
            "holdout_used_for_selection": False,
        }
        row["checks"]["deflated_sharpe_pass"] = bool(dsr.get("valid") and dsr.get("passed"))
        row["checks"]["cscv_pbo_pass"] = bool(pbo.get("valid") and pbo.get("passed"))
        if row["status"] == "panel_factor_pass" and not (
            row["checks"]["deflated_sharpe_pass"] and row["checks"]["cscv_pbo_pass"]
        ):
            row["status"] = "panel_factor_watchlist"
        row["failed_checks"] = [name for name, passed in row["checks"].items() if not passed]

    return {
        "selection_policy": "IS_and_Val_daily_net_returns_only",
        "holdout_used_for_selection": False,
        "full_trial_count": int(trial_count),
        "observed_unique_val_path_count": int(len(daily_val)),
        "observed_trial_sharpe_std": float(np.std(trial_sharpes, ddof=1)) if len(trial_sharpes) > 1 else 0.0,
        "cscv_pbo": pbo,
        "literature": {
            "dsr": "Bailey and Lopez de Prado (2014), The Deflated Sharpe Ratio",
            "pbo": "Bailey et al. (2015), The Probability of Backtest Overfitting",
        },
        "_selection_return_archive": {
            "schema_version": 1,
            "archive_type": "panel_selection_daily_net_returns",
            "selection_policy": "IS_and_Val_only",
            "holdout_included": False,
            "full_trial_count": int(trial_count),
            "selection_end": str(split_indexes["Val"][-1]) if len(split_indexes.get("Val", [])) else None,
            "observed_path_count": len(archived_paths),
            "empty_path_count": empty_selection_path_count,
            "paths": archived_paths,
        },
    }


def _attach_baseline_comparisons(factor_reports: list[dict[str, Any]]) -> None:
    baseline_rows = [
        row for row in factor_reports
        if row.get("factor_name") in BASELINE_FACTOR_NAMES
    ]
    best_val_sharpe = max(
        (float((row.get("long_short") or {}).get("Val", {}).get("sharpe", 0.0)) for row in baseline_rows),
        default=0.0,
    )
    best_holdout_sharpe = max(
        (float((row.get("long_short") or {}).get("Holdout", {}).get("sharpe", 0.0)) for row in baseline_rows),
        default=0.0,
    )
    for row in factor_reports:
        val_sharpe = float((row.get("long_short") or {}).get("Val", {}).get("sharpe", 0.0))
        comparison = {
            "baseline_factor_names": sorted(BASELINE_FACTOR_NAMES),
            "best_baseline_val_sharpe": best_val_sharpe,
            "val_sharpe_minus_best_baseline": float(val_sharpe - best_val_sharpe),
            "note": "Baseline comparison is diagnostic. Holdout is not used for candidate selection.",
        }
        if bool(row.get("holdout_accessed", True)):
            holdout_sharpe = float((row.get("long_short") or {}).get("Holdout", {}).get("sharpe", 0.0))
            comparison.update(
                {
                    "best_baseline_holdout_sharpe": best_holdout_sharpe,
                    "holdout_sharpe_minus_best_baseline": float(holdout_sharpe - best_holdout_sharpe),
                }
            )
        row["baseline_comparison"] = comparison


def _factor_pass_status(
    splits: dict[str, dict],
    ic: dict[str, dict],
    coverage: dict[str, int],
    rolling: dict[str, Any],
    trial_adjustment: dict[str, Any],
    robustness: dict[str, Any] | None = None,
    required_min_assets: int | None = None,
) -> tuple[str, dict[str, bool]]:
    window_count = int(rolling.get("window_count") or 0)
    positive_ic_windows = int(rolling.get("positive_ic_windows") or 0)
    positive_sharpe_windows = int(rolling.get("positive_sharpe_windows") or 0)
    coverage_floor = int(required_min_assets or getattr(config, "PANEL_MIN_ASSETS", 5))
    checks = {
        "coverage_ok": all(value >= coverage_floor for value in coverage.values()),
        "val_ic_positive": ic["Val"]["mean_rank_ic"] > 0.0,
        "val_long_short_positive": splits["Val"]["sharpe"] > 0.0 and splits["Val"]["total_return"] > 0.0,
        "holdout_noncollapse": splits["Holdout"]["sharpe"] > -0.25 and splits["Holdout"]["max_drawdown"] < 0.35,
        "holdout_sharpe_positive": splits["Holdout"]["sharpe"] > 0.0,
        "holdout_ic_positive": ic["Holdout"]["mean_rank_ic"] > 0.0,
        "turnover_reasonable": splits["Val"]["turnover"] < 0.08,
        "is_not_opposite": splits["IS"]["sharpe"] > -0.50,
        "rolling_ic_stable": window_count > 0 and positive_ic_windows / window_count >= 0.60 and rolling["min_rank_ic"] > -0.10,
        "rolling_sharpe_not_fragile": window_count > 0 and positive_sharpe_windows / window_count >= 0.45 and rolling["min_sharpe"] > -3.0,
        "multiple_testing_pass": bool(trial_adjustment.get("pass")),
    }
    robustness_checks = _robustness_quality_checks(robustness or {})
    checks.update(robustness_checks)
    if all(checks.values()):
        return "panel_factor_pass", checks
    if (
        checks["val_ic_positive"]
        and checks["val_long_short_positive"]
        and checks["holdout_noncollapse"]
        and checks["rolling_ic_stable"]
        and checks["robust_large_liquid_val_ic_positive"]
        and checks["robust_large_liquid_holdout_nonnegative"]
        and checks["robust_bucket_val_not_single_bucket"]
        and checks["robust_bucket_holdout_not_single_bucket"]
        and checks["robust_family_neutral_val_ic_positive"]
        and checks["robust_family_neutral_holdout_nonnegative"]
        and checks["robust_crash_window_count"]
        and checks["robust_crash_loss_contained"]
        and checks["robust_crash_not_mostly_negative"]
    ):
        return "panel_factor_watchlist", checks
    return "panel_factor_reject", checks


def _apply_evidence_promotion_ceiling(
    status: str,
    checks: dict[str, bool],
    evidence_policy: dict[str, Any],
) -> tuple[str, dict[str, bool]]:
    checks = dict(checks)
    formal_allowed = bool(evidence_policy.get("formal_promotion_allowed"))
    checks["evidence_universe_formal_promotion_allowed"] = formal_allowed
    if status == "panel_factor_pass" and not formal_allowed:
        status = "panel_factor_watchlist"
    return status, checks


def _load_panel(
    inst_ids: list[str],
    days: int,
    force_refresh: bool = False,
    *,
    load_spot: bool = True,
    load_open_interest: bool = True,
    load_market_cap: bool = True,
) -> tuple[dict, list[dict]]:
    panel = {}
    failures = []
    registry_assets = panel_universe.registry_asset_map()
    instruments = None
    instrument_snapshot_error = None
    try:
        instruments = data_module.load_instruments('SWAP', force_refresh=force_refresh)
    except Exception as exc:
        instrument_snapshot_error = str(exc)
        print(f"INSTRUMENT_METADATA_LOAD_FAILED {exc}")
    for inst_id in inst_ids:
        try:
            ohlcv = data_module.load_data(inst_id, config.BAR, days, force_refresh=force_refresh)
            funding = data_module.load_funding_rates(inst_id, days, force_refresh=force_refresh)
            spot_ohlcv = None
            spot_error = None
            open_interest = None
            open_interest_error = None
            market_cap = None
            market_cap_error = None
            if load_spot:
                try:
                    spot_ohlcv = data_module.load_spot_data(inst_id, config.BAR, days, force_refresh=force_refresh)
                except Exception as exc:
                    spot_error = str(exc)
                    print(f"SPOT_LOAD_FAILED {inst_id} {exc}")
            else:
                spot_error = "not_requested"
            if load_open_interest:
                try:
                    open_interest = data_module.load_open_interest_history(
                        inst_id,
                        days=days,
                        period='1D',
                        force_refresh=force_refresh,
                    )
                except Exception as exc:
                    open_interest_error = str(exc)
                    print(f"OPEN_INTEREST_LOAD_FAILED {inst_id} {exc}")
            else:
                open_interest_error = "not_requested"
            if load_market_cap:
                try:
                    market_cap = data_module.load_market_cap_history(
                        inst_id,
                        days=days,
                        force_refresh=force_refresh,
                    )
                except Exception as exc:
                    market_cap_error = str(exc)
                    print(f"MARKET_CAP_LOAD_FAILED {inst_id} {exc}")
            else:
                market_cap_error = "not_requested"

            instrument = None
            instrument_error = instrument_snapshot_error
            if instruments is not None and inst_id in instruments.index:
                row = instruments.loc[inst_id]
                instrument = {
                    "inst_id": inst_id,
                    "state": row.get("state"),
                    "list_time_ms": int(row["list_time_ms"]) if pd.notna(row.get("list_time_ms")) else None,
                    "list_time": str(row.get("list_time")) if pd.notna(row.get("list_time")) else None,
                    "settle_ccy": row.get("settle_ccy"),
                    "contract_value": row.get("contract_value"),
                    "contract_value_ccy": row.get("contract_value_ccy"),
                    "fetched_at_utc": str(row.get("fetched_at_utc")),
                }
                instrument_error = None
            elif instruments is not None:
                instrument_error = "instrument_not_present_in_okx_snapshot"

            panel[inst_id] = {
                "ohlcv": ohlcv,
                "funding": funding,
                "spot_ohlcv": spot_ohlcv,
                "spot_error": spot_error,
                "open_interest": open_interest,
                "open_interest_error": open_interest_error,
                "market_cap": market_cap,
                "market_cap_error": market_cap_error,
                "instrument": instrument,
                "instrument_error": instrument_error,
                "asset_label": (registry_assets.get(inst_id) or {}).get("asset_family"),
            }
            spot_bars = len(spot_ohlcv) if spot_ohlcv is not None else 0
            oi_rows = len(open_interest) if open_interest is not None else 0
            market_cap_rows = len(market_cap) if market_cap is not None else 0
            print(
                f"LOADED {inst_id} bars={len(ohlcv)} spot={spot_bars} "
                f"funding={int(funding.notna().sum())} oi_daily={oi_rows} market_cap_daily={market_cap_rows}"
            )
        except Exception as exc:
            failures.append({"inst_id": inst_id, "error": str(exc)})
            print(f"LOAD_FAILED {inst_id} {exc}")
    return panel, failures


def _build_matrices(
    panel: dict[str, dict],
    candidate_definitions: list[dict[str, Any]] | None = None,
    universe_registry: dict[str, Any] | None = None,
    build_factors: bool = True,
    requested_factor_names: set[str] | None = None,
) -> dict[str, pd.DataFrame]:
    close = pd.concat({k: v["ohlcv"]["close"] for k, v in panel.items()}, axis=1).sort_index()
    spot_frames = {k: v["spot_ohlcv"]["close"] for k, v in panel.items() if v.get("spot_ohlcv") is not None}
    spot_close = pd.concat(spot_frames, axis=1).reindex(close.index) if spot_frames else pd.DataFrame(index=close.index, columns=close.columns)
    volume = pd.concat({k: v["ohlcv"]["volume"] for k, v in panel.items()}, axis=1).reindex(close.index)
    vol_quote = pd.concat({k: v["ohlcv"]["vol_quote"] for k, v in panel.items()}, axis=1).reindex(close.index)
    funding_events = pd.concat({k: v["funding"] for k, v in panel.items()}, axis=1).reindex(close.index)
    funding_signal = funding_events.ffill(limit=24)
    open_interest_frames = {
        k: v["open_interest"]["open_interest_usd"]
        for k, v in panel.items()
        if v.get("open_interest") is not None and "open_interest_usd" in v["open_interest"]
    }
    open_interest_events = (
        pd.concat(open_interest_frames, axis=1).reindex(index=close.index, columns=close.columns)
        if open_interest_frames
        else pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    )
    open_interest_signal = open_interest_events.ffill(limit=24)
    market_cap_frames = {
        k: v["market_cap"]["market_cap_usd"]
        for k, v in panel.items()
        if v.get("market_cap") is not None and "market_cap_usd" in v["market_cap"]
    }
    market_cap_daily_events = (
        pd.concat(market_cap_frames, axis=1).sort_index().reindex(columns=close.columns)
        if market_cap_frames
        else pd.DataFrame(columns=close.columns, dtype=float)
    )
    market_cap_signal = _lag_daily_events_to_intraday(market_cap_daily_events, close.index, lag_days=1)
    universe = panel_universe.build_point_in_time_eligibility(
        panel,
        close,
        vol_quote,
        registry=universe_registry,
    )
    eligibility = universe["eligibility"]
    returns = _pct_change(close)
    fwd_returns = _pct_change(close, 24).shift(-24)
    dollar_volume = vol_quote.where(vol_quote > 0, close * volume)
    realized_vol = returns.rolling(24 * 7, min_periods=24 * 3).std()
    liquidity_size = np.log(dollar_volume.rolling(24 * 7, min_periods=24 * 3).mean().replace(0, np.nan))
    liquidity_change = liquidity_size - liquidity_size.shift(24 * 7)
    amihud = returns.abs().rolling(24 * 7, min_periods=24 * 3).sum() / dollar_volume.rolling(24 * 7, min_periods=24 * 3).sum().replace(0, np.nan)
    momentum_7d = _pct_change(close, 24 * 7)
    funding_mean = funding_signal.rolling(24 * 90, min_periods=24 * 30).mean()
    funding_std = funding_signal.rolling(24 * 90, min_periods=24 * 30).std()
    funding_z = ((funding_signal - funding_mean) / funding_std.replace(0, np.nan)).clip(-5, 5)
    basis = _basis_from_prices(close, spot_close)
    basis_mean = basis.rolling(24 * 90, min_periods=24 * 30).mean()
    basis_std = basis.rolling(24 * 90, min_periods=24 * 30).std()
    basis_z = ((basis - basis_mean) / basis_std.replace(0, np.nan)).clip(-5, 5)
    vol_floor = realized_vol.replace(0, np.nan)
    eligible_liquidity_size = liquidity_size.where(eligibility)
    eligible_momentum_7d = momentum_7d.where(eligibility)
    eligible_funding_signal = funding_signal.where(eligibility)

    if not build_factors:
        return {
            "close": close,
            "spot_close": spot_close,
            "basis": basis,
            "returns": returns,
            "fwd_returns": fwd_returns,
            "funding_signal": funding_signal,
            "funding_cost": funding_events,
            "open_interest": open_interest_signal,
            "open_interest_events": open_interest_events,
            "market_cap": market_cap_signal,
            "market_cap_daily_events": market_cap_daily_events,
            "listing_age": universe["listing_age_days"],
            "asset_labels": universe["asset_labels"],
            "eligibility": eligibility,
            "universe": universe,
            "vol_quote": vol_quote,
            "factors": {},
            "factor_definitions": {},
            "formula_library": {"liquidity_size": eligible_liquidity_size},
        }

    oi_change_7d = _pct_change(open_interest_signal, 24 * 7).clip(-1.0, 3.0).shift(24)
    positive_oi_growth = oi_change_7d.clip(lower=0.0)

    candidate_formula_names = {
        str(candidate.get("panel_formula"))
        for candidate in candidate_definitions or []
        if candidate.get("panel_formula")
    }
    required_names = None if requested_factor_names is None else set(requested_factor_names) | candidate_formula_names

    def factor_is_required(name: str) -> bool:
        return required_names is None or name in required_names

    raw_factors = {
        "momentum_24h": _pct_change(close, 24),
        "momentum_7d": momentum_7d,
        "short_reversal_24h": _pct_change(close, 24),
        "low_vol_7d": realized_vol,
        "liquidity_size": liquidity_size,
        "liquidity_change_7d": liquidity_change,
        "amihud_illiquidity_7d": amihud,
        "volume_shock_24h": volume.rolling(24, min_periods=12).sum() / volume.rolling(24 * 14, min_periods=24 * 7).mean(),
        "funding_carry": funding_signal.shift(1),
        "funding_extreme_reversal": funding_z.shift(1),
        "trend_carry_aligned": _pct_change(close, 24 * 7) - funding_z.shift(1).clip(lower=0),
        "basis_carry": basis.shift(1),
        "funding_persistence": funding_signal.rolling(24 * 14, min_periods=24 * 5).mean().shift(1),
        "basis_funding_dislocation": (basis_z - funding_z).shift(1),
        "vol_managed_funding_carry": (funding_signal / vol_floor).replace([np.inf, -np.inf], np.nan).shift(1),
        "vol_managed_momentum": (momentum_7d / vol_floor).replace([np.inf, -np.inf], np.nan),
        "oi_change_7d": oi_change_7d,
        "oi_price_crowding_reversal": momentum_7d * positive_oi_growth,
        "oi_funding_crowding_reversal": funding_z.shift(1) * positive_oi_growth,
        "oi_price_crowding_reversal_v2": momentum_7d * positive_oi_growth,
        "oi_funding_crowding_reversal_v2": funding_z.shift(1) * positive_oi_growth,
    }
    if factor_is_required("liquidity_neutral_momentum_7d"):
        raw_factors["liquidity_neutral_momentum_7d"] = _cross_sectional_residual(
            eligible_momentum_7d,
            eligible_liquidity_size,
            getattr(config, "PANEL_MIN_ASSETS", 5),
        )
    if factor_is_required("liquidity_neutral_funding_carry"):
        raw_factors["liquidity_neutral_funding_carry"] = _cross_sectional_residual(
            eligible_funding_signal.shift(1),
            eligible_liquidity_size,
            getattr(config, "PANEL_MIN_ASSETS", 5),
        )
    if factor_is_required("liquidity_bucket_momentum"):
        raw_factors["liquidity_bucket_momentum"] = _liquidity_bucket_neutral_signal(
            eligible_momentum_7d,
            eligible_liquidity_size,
            getattr(config, "PANEL_MIN_ASSETS", 5),
        )
    if factor_is_required("liquidity_bucket_reversal"):
        raw_factors["liquidity_bucket_reversal"] = _liquidity_bucket_neutral_signal(
            _pct_change(close, 24).where(eligibility),
            eligible_liquidity_size,
            getattr(config, "PANEL_MIN_ASSETS", 5),
        )
    raw_factors = {name: value.where(eligibility) for name, value in raw_factors.items()}
    factors = {}
    for name, meta in FACTOR_DEFINITIONS.items():
        if requested_factor_names is not None and name not in requested_factor_names:
            continue
        factors[name] = raw_factors[name] * meta["direction"]

    factor_definitions = {
        name: meta
        for name, meta in FACTOR_DEFINITIONS.items()
        if requested_factor_names is None or name in requested_factor_names
    }
    for candidate in candidate_definitions or []:
        candidate_id = candidate["candidate_id"]
        formula = candidate["panel_formula"]
        if formula not in raw_factors:
            continue
        controlled = _apply_candidate_controls(
            raw_factors[formula],
            candidate,
            eligibility=eligibility,
            liquidity_size=liquidity_size,
            min_assets=getattr(config, "PANEL_MIN_ASSETS", 5),
        )
        factors[candidate_id] = controlled * _candidate_direction_multiplier(candidate["direction"])
        factor_definitions[candidate_id] = {
            "family": candidate["family"],
            "direction": _candidate_direction_multiplier(candidate["direction"]),
            "logic": candidate["hypothesis"],
            "source_ids": candidate["source_ids"],
            "candidate_id": candidate_id,
            "panel_formula": formula,
            "required_fields": candidate["required_fields"],
            "neutralization": candidate["neutralization"],
            "bucket_policy": candidate["bucket_policy"],
            "weighting_modes": candidate["weighting_modes"],
            "generated_by": candidate["generated_by"],
            "is_candidate": True,
        }

    return {
        "close": close,
        "spot_close": spot_close,
        "basis": basis,
        "returns": returns,
        "fwd_returns": fwd_returns,
        "funding_signal": funding_signal,
        "funding_cost": funding_events,
        "open_interest": open_interest_signal,
        "open_interest_events": open_interest_events,
        "market_cap": market_cap_signal,
        "market_cap_daily_events": market_cap_daily_events,
        "listing_age": universe["listing_age_days"],
        "asset_labels": universe["asset_labels"],
        "eligibility": eligibility,
        "universe": universe,
        "vol_quote": vol_quote,
        "factors": factors,
        "factor_definitions": factor_definitions,
        "formula_library": raw_factors,
    }


def _staged_trial_context(
    candidate_definitions: list[dict[str, Any]],
    trial_registry_path: Path | str,
) -> dict[str, Any]:
    registry_rows, registry_breakdown = candidate_registry.validate_trial_registry_for_candidates(
        candidate_definitions,
        trial_registry_path,
    )
    registry_trials = int(registry_breakdown["portfolio_variant_trial_count"])
    current_candidate_ids = {
        str(candidate["candidate_id"])
        for candidate in candidate_definitions
        if candidate.get("candidate_id")
    }
    registered_candidate_ids = {
        str(row.get("candidate_id"))
        for row in registry_rows
        if row.get("candidate_id")
    }
    scoped_definition_count = len(BASELINE_FACTOR_NAMES) + len(candidate_definitions)
    trial_count = max(
        scoped_definition_count * len(WEIGHTING_MODES),
        len(FACTOR_DEFINITIONS) * len(WEIGHTING_MODES) + registry_trials,
    )
    signal_trial_count = len(FACTOR_DEFINITIONS) + len(registered_candidate_ids | current_candidate_ids)
    return {
        "registry_breakdown": registry_breakdown,
        "trial_count": int(trial_count),
        "signal_trial_count": int(signal_trial_count),
        "current_candidate_ids": sorted(current_candidate_ids),
        "registered_candidate_ids": sorted(registered_candidate_ids),
    }


def _evidence_cache_code_fingerprint() -> dict[str, Any]:
    paths = [
        Path(__file__),
        Path(panel_universe.__file__),
        Path(panel_overfit_audit.__file__),
        Path(config.__file__),
        Path(__file__).with_name("backtest.py"),
    ]
    files = []
    for path in paths:
        raw = path.read_bytes()
        files.append(
            {
                "name": path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
        )
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "files": files,
    }


def _factor_path_evidence_request(
    *,
    panel_fingerprint: str,
    common_index: pd.DatetimeIndex,
    signal_key: tuple[Any, ...],
    weighting_mode: str,
    effective_min_assets: int,
    rebalance_hours: int,
    code_fingerprint: dict[str, Any],
    universe_identity: dict[str, Any],
) -> dict[str, Any]:
    index_digest = hashlib.sha256(common_index.asi8.tobytes()).hexdigest()
    return {
        "schema_version": "panel_factor_path_evidence_request_v2",
        "artifact_kind": "pre_multiplicity_factor_path_evidence",
        "panel_fingerprint": str(panel_fingerprint),
        "analysis_index": {
            "start": str(common_index.min()) if len(common_index) else None,
            "end": str(common_index.max()) if len(common_index) else None,
            "bars": int(len(common_index)),
            "sha256": index_digest,
        },
        "split_ratios": list(config.SPLIT_RATIOS),
        "signal_key": [str(value) if not isinstance(value, int) else value for value in signal_key],
        "weighting_mode": weighting_mode,
        "effective_min_assets": int(effective_min_assets),
        "rebalance_hours": int(rebalance_hours),
        "universe_identity": universe_identity,
        "cost_bps": float(config.COST_BPS),
        "slippage_bps": float(config.SLIPPAGE_BPS),
        "bar": str(config.BAR),
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "computation_code": code_fingerprint,
    }


def _universe_evidence_identity(
    universe: dict[str, Any],
    eligibility: pd.DataFrame,
    common_index: pd.DatetimeIndex,
) -> dict[str, Any]:
    selected = eligibility.reindex(common_index).fillna(False).astype(bool)
    digest = hashlib.sha256()
    digest.update(json.dumps([str(column) for column in selected.columns], separators=(",", ":")).encode("utf-8"))
    digest.update(selected.index.asi8.tobytes())
    digest.update(np.ascontiguousarray(selected.to_numpy(dtype=np.uint8)).tobytes())
    return {
        "rules": universe.get("rules") or {},
        "survivorship": universe.get("survivorship") or {},
        "eligibility_sha256": digest.hexdigest(),
        "eligible_cell_count": int(selected.to_numpy(dtype=np.uint8).sum()),
    }


def _selection_dependence_report(
    ic_series: pd.Series,
    factor: pd.DataFrame,
    split_indexes: dict[str, pd.DatetimeIndex],
    *,
    signal_trial_count: int,
) -> dict[str, dict[str, Any]]:
    if set(split_indexes) != set(panel_stage_policy.SELECTION_SPLITS):
        raise ValueError("stage_2_dependence_report_requires_selection_splits_only")
    report = {}
    for split_name in panel_stage_policy.SELECTION_SPLITS:
        idx = split_indexes[split_name]
        split_series = ic_series.reindex(idx).dropna()
        diagnostics = panel_gate_calibration.ic_inference_diagnostics(split_series)
        daily_path = diagnostics.pop("daily_rank_ic")
        diagnostics["daily_rank_ic_start"] = str(daily_path.index.min()) if len(daily_path) else None
        diagnostics["daily_rank_ic_end"] = str(daily_path.index.max()) if len(daily_path) else None
        diagnostics["daily_rank_ic_sha256"] = hashlib.sha256(
            daily_path.to_csv(header=False).encode("utf-8")
        ).hexdigest()
        if split_name == "Val":
            median_assets = int(factor.reindex(idx).notna().sum(axis=1).median()) if len(idx) else 0
            diagnostics["empirical_block_audit"] = panel_gate_calibration.empirical_block_rank_ic_audit(
                split_series,
                trial_count=signal_trial_count,
                asset_count=max(median_assets, 4),
            )
        report[split_name] = diagnostics
    return report


def _selection_only_candidate_screen(
    selection_panel: dict[str, dict[str, Any]],
    selection_split_indexes: dict[str, pd.DatetimeIndex],
    *,
    candidate_definitions: list[dict[str, Any]],
    rebalance_hours: int,
    min_assets: int,
    trial_count: int,
    signal_trial_count: int,
) -> dict[str, Any]:
    """Evaluate candidate paths with objects that contain no Holdout rows."""
    if set(selection_split_indexes) != set(panel_stage_policy.SELECTION_SPLITS):
        raise ValueError("stage_2_requires_is_and_val_only")
    selection_index = selection_split_indexes["IS"].append(selection_split_indexes["Val"])
    if len(selection_index) == 0:
        raise ValueError("stage_2_selection_index_empty")
    for item in selection_panel.values():
        ohlcv = item.get("ohlcv")
        if ohlcv is not None and len(ohlcv) and ohlcv.index.max() > selection_index.max():
            raise ValueError("stage_2_panel_contains_post_validation_rows")

    matrices = _build_matrices(
        selection_panel,
        candidate_definitions=candidate_definitions,
        requested_factor_names=set(),
    )
    returns = matrices["returns"].reindex(selection_index)
    fwd_returns = _purge_forward_returns_at_split_boundaries(
        matrices["fwd_returns"],
        selection_split_indexes,
    ).reindex(selection_index)
    funding_cost = matrices["funding_cost"].reindex(selection_index)
    factor_definitions = matrices["factor_definitions"]
    screen_rows: list[dict[str, Any]] = []
    selection_returns: dict[tuple[Any, ...], dict[str, pd.Series]] = {}
    survivor_modes: dict[str, list[str]] = {}
    candidate_p_values: dict[str, dict[str, Any]] = {}
    ic_cache: dict[tuple[Any, ...], pd.Series] = {}
    inference_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    weights_cache: dict[tuple[tuple[Any, ...], str], pd.DataFrame] = {}

    for candidate in candidate_definitions:
        candidate_id = str(candidate["candidate_id"])
        if candidate_id not in matrices["factors"]:
            raise ValueError(f"stage_2_candidate_factor_missing:{candidate_id}")
        factor = matrices["factors"][candidate_id].reindex(selection_index)
        definition = factor_definitions[candidate_id]
        bucket_policy = str(definition.get("bucket_policy") or "none")
        large_top_n = min(8, int(matrices["universe"]["rules"]["target_size"]))
        effective_min_assets = min(min_assets, large_top_n) if bucket_policy == "large_liquid_only" else min_assets
        signal_key = (
            str(definition.get("panel_formula") or candidate_id),
            str(definition.get("neutralization") or "none"),
            bucket_policy,
            int(definition.get("direction") or 1),
        )
        if signal_key not in ic_cache:
            ic_cache[signal_key] = _spearman_by_time(factor, fwd_returns, effective_min_assets)
        ic_series = ic_cache[signal_key]
        if signal_key not in inference_cache:
            inference_cache[signal_key] = _selection_dependence_report(
                ic_series,
                factor,
                selection_split_indexes,
                signal_trial_count=signal_trial_count,
            )
        dependence_report = inference_cache[signal_key]
        empirical_p = ((dependence_report.get("Val") or {}).get("empirical_block_audit") or {}).get(
            "empirical_one_sided_p"
        )
        candidate_p_values[candidate_id] = {
            "family": str(definition.get("family") or "unclassified"),
            "p_value": float(empirical_p) if empirical_p is not None else None,
            "source": "stage_2_purged_selection_only_rank_ic",
        }

        for weighting_mode in definition.get("weighting_modes", list(WEIGHTING_MODES)):
            mode_key = (signal_key, weighting_mode)
            if mode_key not in weights_cache:
                weights_cache[mode_key] = _held_weights(
                    factor,
                    effective_min_assets,
                    rebalance_hours,
                    weighting_mode,
                )
            weights = weights_cache[mode_key]
            ic_report = {}
            split_metrics = {}
            coverage = {}
            for split_name in panel_stage_policy.SELECTION_SPLITS:
                idx = selection_split_indexes[split_name]
                split_ic = ic_series.reindex(idx).dropna()
                coverage[split_name] = int(factor.reindex(idx).notna().sum(axis=1).median()) if len(idx) else 0
                ic_report[split_name] = {
                    "observations": int(len(split_ic)),
                    "mean_rank_ic": float(split_ic.mean()) if len(split_ic) else 0.0,
                    "ic_tstat": (
                        float(split_ic.mean() / (split_ic.std(ddof=1) / math.sqrt(len(split_ic))))
                        if len(split_ic) > 2 and split_ic.std(ddof=1) > 0
                        else 0.0
                    ),
                    "positive_ic_frac": float((split_ic > 0).mean()) if len(split_ic) else 0.0,
                }
                metrics = _portfolio_metrics_from_weights(
                    weights,
                    returns,
                    funding_cost,
                    idx,
                    include_net_returns=True,
                )
                net_returns = metrics.pop("_net_return_series")
                selection_returns.setdefault(mode_key, {})[split_name] = net_returns
                split_metrics[split_name] = metrics

            stage_2 = panel_stage_policy.evaluate_stage_2(
                split_metrics,
                ic_report,
                coverage,
                required_min_assets=effective_min_assets,
            )
            if stage_2["survives_to_stage_3"]:
                survivor_modes.setdefault(candidate_id, []).append(weighting_mode)
            screen_rows.append(
                {
                    "name": f"{candidate_id}__{weighting_mode}",
                    "factor_name": candidate_id,
                    "candidate_id": candidate_id,
                    "source_ids": definition.get("source_ids", []),
                    "panel_formula": definition.get("panel_formula"),
                    "neutralization": definition.get("neutralization"),
                    "bucket_policy": definition.get("bucket_policy"),
                    "generated_by": definition.get("generated_by"),
                    "weighting_mode": weighting_mode,
                    "weighting_logic": WEIGHTING_MODES[weighting_mode]["logic"],
                    "family": definition["family"],
                    "logic": definition["logic"],
                    "status": "panel_factor_reject",
                    "checks": dict(stage_2["checks"]),
                    "failed_checks": list(stage_2["failed_checks"]),
                    "coverage_median_assets": coverage,
                    "required_min_assets": effective_min_assets,
                    "rank_ic": ic_report,
                    "dependence_aware_rank_ic": dependence_report,
                    "trial_adjustment": _trial_adjustment(ic_report["Val"]["ic_tstat"], trial_count),
                    "long_short": split_metrics,
                    "evaluation_stage": "stage_2_survivor" if stage_2["survives_to_stage_3"] else "stage_2_reject",
                    "stage_2": stage_2,
                    "stage_3": {
                        "executed": False,
                        "reason": "pending_stage_3" if stage_2["survives_to_stage_3"] else "stage_2_objective_failure",
                    },
                    "holdout_accessed": False,
                    "_selection_path_key": mode_key,
                }
            )

    return {
        "rows": screen_rows,
        "survivor_modes": survivor_modes,
        "selection_returns": selection_returns,
        "candidate_p_values": candidate_p_values,
        "selection_index_start": str(selection_index.min()),
        "selection_index_end": str(selection_index.max()),
        "selection_bar_count": int(len(selection_index)),
        "purge_policy": "forward_return_targets_after_validation_end_are_absent_from_truncated_panel",
    }


def _evaluate_legacy_full(
    panel: dict[str, dict],
    days: int,
    rebalance_hours: int,
    min_assets: int,
    candidate_definitions: list[dict[str, Any]] | None = None,
    candidate_batch_id: str | None = None,
    factor_scope: str = "all",
    evaluation_start_utc: Any | None = None,
    evaluation_end_utc: Any | None = None,
    trial_registry_path: Path | str | None = None,
    trial_event_registry_path: Path | str | None = None,
    trial_candidate_definitions: list[dict[str, Any]] | None = None,
    trial_count_override: int | None = None,
    signal_trial_count_override: int | None = None,
    additional_selection_returns: dict[tuple[Any, ...], dict[str, pd.Series]] | None = None,
    additional_candidate_p_values: dict[str, dict[str, Any]] | None = None,
    record_trial_events: bool = True,
    panel_fingerprint: str | None = None,
    artifact_cache_dir: Path | str | None = None,
    use_artifact_cache: bool = False,
) -> dict:
    if factor_scope not in {"all", "candidates_and_baselines"}:
        raise ValueError(f"unknown factor_scope: {factor_scope}")
    requested_factor_names = set(BASELINE_FACTOR_NAMES) if factor_scope == "candidates_and_baselines" else None
    matrices = _build_matrices(
        panel,
        candidate_definitions=candidate_definitions,
        requested_factor_names=requested_factor_names,
    )
    close = matrices["close"]
    returns = matrices["returns"]
    fwd_returns = matrices["fwd_returns"]
    funding_cost = matrices["funding_cost"]
    factor_definitions = matrices["factor_definitions"]
    eligibility = matrices["eligibility"]
    common_index = eligibility.index[eligibility.sum(axis=1) >= min_assets]
    if evaluation_start_utc is not None:
        common_index = common_index[common_index >= pd.Timestamp(evaluation_start_utc)]
    if evaluation_end_utc is not None:
        common_index = common_index[common_index <= pd.Timestamp(evaluation_end_utc)]
    split_indexes = _split_index(common_index)
    fwd_returns = _purge_forward_returns_at_split_boundaries(fwd_returns, split_indexes)
    liquidity_size = matrices["formula_library"]["liquidity_size"].reindex(common_index)
    large_top_n = min(8, int(matrices["universe"]["rules"]["target_size"]))
    robustness_large_mask = _large_liquid_mask(
        liquidity_size,
        eligibility,
        common_index,
        top_n=large_top_n,
    )
    robustness_bucket_masks = _liquidity_bucket_masks(liquidity_size, common_index, min_assets=min_assets)
    robustness_crash_windows = _crash_window_indexes(returns.where(eligibility), common_index, n_windows=5)
    asset_families = {
        str(asset): str(row.get("asset_label"))
        for asset, row in panel.items()
        if row.get("asset_label")
    }
    universe_summary = panel_universe.summarize_eligibility(matrices["universe"], split_indexes)
    power_proxy = panel_universe.design_power_proxy(matrices["universe"], split_indexes)
    evidence_policy = panel_universe.evidence_policy(common_index)
    artifact_store = (
        panel_artifact_cache.PanelArtifactStore(artifact_cache_dir or PANEL_ARTIFACT_CACHE_DIR)
        if use_artifact_cache
        else None
    )
    if artifact_store is not None and panel_fingerprint is None:
        panel_fingerprint = _panel_input_fingerprint(panel)["panel_sha256"]
    artifact_code_fingerprint = _evidence_cache_code_fingerprint() if artifact_store is not None else None
    artifact_universe_identity = (
        _universe_evidence_identity(matrices["universe"], eligibility, common_index)
        if artifact_store is not None
        else None
    )
    artifact_cache_hits = 0
    artifact_cache_misses = 0
    artifact_cache_records: list[dict[str, Any]] = []

    selected_factor_names = list(matrices["factors"])
    if factor_scope == "candidates_and_baselines":
        selected_factor_names = [
            name
            for name in selected_factor_names
            if name in BASELINE_FACTOR_NAMES or factor_definitions[name].get("is_candidate")
        ]

    factor_reports = []
    ic_series_cache: dict[tuple[Any, ...], pd.Series] = {}
    ic_inference_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    weights_cache: dict[tuple[tuple[Any, ...], str], pd.DataFrame] = {}
    rolling_cache: dict[tuple[tuple[Any, ...], str], dict[str, Any]] = {}
    cross_robustness_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    split_metrics_cache: dict[tuple[tuple[tuple[Any, ...], str], str], dict[str, Any]] = {}
    selection_returns: dict[tuple[Any, ...], dict[str, pd.Series]] = {
        path_key: dict(by_split)
        for path_key, by_split in (additional_selection_returns or {}).items()
    }
    trial_registry_path = Path(trial_registry_path) if trial_registry_path is not None else LOG_DIR / "panel_trial_registry.jsonl"
    trial_event_registry_path = (
        Path(trial_event_registry_path)
        if trial_event_registry_path is not None
        else LOG_DIR / "panel_trial_registry.jsonl"
    )
    trial_candidates = trial_candidate_definitions if trial_candidate_definitions is not None else candidate_definitions
    registry_rows, registry_breakdown = candidate_registry.validate_trial_registry_for_candidates(
        list(trial_candidates or []),
        trial_registry_path,
    )
    registry_trials = int(registry_breakdown["portfolio_variant_trial_count"])
    trial_count = max(len(matrices["factors"]) * len(WEIGHTING_MODES), len(FACTOR_DEFINITIONS) * len(WEIGHTING_MODES) + registry_trials)
    if trial_count_override is not None:
        trial_count = int(trial_count_override)
    current_candidate_ids = {
        str(candidate.get("candidate_id"))
        for candidate in trial_candidates or []
        if candidate.get("candidate_id")
    }
    registered_candidate_ids = {
        str(row.get("candidate_id"))
        for row in registry_rows
        if row.get("candidate_id")
    }
    signal_trial_count = len(FACTOR_DEFINITIONS) + len(registered_candidate_ids | current_candidate_ids)
    if signal_trial_count_override is not None:
        signal_trial_count = int(signal_trial_count_override)
    for factor_name in selected_factor_names:
        factor = matrices["factors"][factor_name]
        factor = factor.reindex(common_index)
        definition = factor_definitions[factor_name]
        bucket_policy = str(definition.get("bucket_policy") or "none")
        effective_min_assets = min(min_assets, large_top_n) if bucket_policy == "large_liquid_only" else min_assets
        signal_key = (
            str(definition.get("panel_formula") or factor_name),
            str(definition.get("neutralization") or "none"),
            bucket_policy,
            int(definition.get("direction") or 1),
        )
        if signal_key not in ic_series_cache:
            ic_series_cache[signal_key] = _spearman_by_time(
                factor,
                fwd_returns.reindex(common_index),
                effective_min_assets,
            )
        ic_series = ic_series_cache[signal_key]
        if signal_key not in ic_inference_cache:
            split_inference = {}
            for split_name, idx in split_indexes.items():
                split_series = ic_series.reindex(idx).dropna()
                diagnostics = panel_gate_calibration.ic_inference_diagnostics(split_series)
                daily_path = diagnostics.pop("daily_rank_ic")
                diagnostics["daily_rank_ic_start"] = str(daily_path.index.min()) if len(daily_path) else None
                diagnostics["daily_rank_ic_end"] = str(daily_path.index.max()) if len(daily_path) else None
                diagnostics["daily_rank_ic_sha256"] = hashlib.sha256(
                    daily_path.to_csv(header=False).encode("utf-8")
                ).hexdigest()
                if split_name == "Val":
                    median_assets = int(factor.reindex(idx).notna().sum(axis=1).median()) if len(idx) else 0
                    diagnostics["empirical_block_audit"] = panel_gate_calibration.empirical_block_rank_ic_audit(
                        split_series,
                        trial_count=signal_trial_count,
                        asset_count=max(median_assets, 4),
                    )
                split_inference[split_name] = diagnostics
            ic_inference_cache[signal_key] = split_inference
        dependence_aware_ic_report = ic_inference_cache[signal_key]
        modes = definition.get("weighting_modes", list(WEIGHTING_MODES))
        for weighting_mode in modes:
            mode_key = (signal_key, weighting_mode)
            artifact_request = None
            cached_artifact = None
            if artifact_store is not None:
                artifact_request = _factor_path_evidence_request(
                    panel_fingerprint=str(panel_fingerprint),
                    common_index=common_index,
                    signal_key=signal_key,
                    weighting_mode=weighting_mode,
                    effective_min_assets=effective_min_assets,
                    rebalance_hours=rebalance_hours,
                    code_fingerprint=artifact_code_fingerprint or {},
                    universe_identity=artifact_universe_identity or {},
                )
                cached_artifact, _ = artifact_store.lookup(artifact_request)

            if cached_artifact is not None:
                artifact_cache_hits += 1
                cached_payload = cached_artifact["payload"]
                if cached_payload.get("schema_version") != "panel_factor_path_raw_evidence_v1":
                    raise ValueError("panel_factor_path_artifact_payload_schema_invalid")
                ic_report = cached_payload["rank_ic"]
                split_metrics = cached_payload["long_short"]
                coverage = cached_payload["coverage_median_assets"]
                rolling = cached_payload["rolling_90d"]
                robustness = cached_payload["robustness"]
                selection_returns.setdefault(mode_key, {}).update(cached_payload["selection_returns"])
                artifact_metadata = cached_artifact
                if signal_key not in cross_robustness_cache:
                    cross_robustness_cache[signal_key] = {
                        name: robustness[name]
                        for name in ("large_liquid", "liquidity_buckets", "asset_family_neutral")
                    }
            else:
                if artifact_store is not None:
                    artifact_cache_misses += 1
                if mode_key not in weights_cache:
                    weights_cache[mode_key] = _held_weights(
                        factor,
                        effective_min_assets,
                        rebalance_hours,
                        weighting_mode,
                    )
                weights = weights_cache[mode_key]
                ic_report = {}
                split_metrics = {}
                coverage = {}
                for split_name, idx in split_indexes.items():
                    split_ic = ic_series.reindex(idx).dropna()
                    coverage[split_name] = int(factor.reindex(idx).notna().sum(axis=1).median()) if len(idx) else 0
                    ic_report[split_name] = {
                        "observations": int(len(split_ic)),
                        "mean_rank_ic": float(split_ic.mean()) if len(split_ic) else 0.0,
                        "ic_tstat": float(split_ic.mean() / (split_ic.std(ddof=1) / math.sqrt(len(split_ic)))) if len(split_ic) > 2 and split_ic.std(ddof=1) > 0 else 0.0,
                        "positive_ic_frac": float((split_ic > 0).mean()) if len(split_ic) else 0.0,
                    }
                    metric_key = (mode_key, split_name)
                    if metric_key not in split_metrics_cache:
                        metrics = _portfolio_metrics_from_weights(
                            weights,
                            returns,
                            funding_cost,
                            idx,
                            include_net_returns=split_name in {"IS", "Val"},
                        )
                        net_returns = metrics.pop("_net_return_series", None)
                        if net_returns is not None:
                            selection_returns.setdefault(mode_key, {})[split_name] = net_returns
                        split_metrics_cache[metric_key] = metrics
                    split_metrics[split_name] = split_metrics_cache[metric_key]
                if mode_key not in rolling_cache:
                    rolling_cache[mode_key] = _rolling_factor_audit(
                        weights,
                        returns,
                        funding_cost,
                        ic_series,
                        common_index,
                    )
                rolling = rolling_cache[mode_key]
                robustness = _factor_robustness_diagnostics(
                    factor,
                    weights,
                    ic_series,
                    matrices,
                    split_indexes,
                    common_index,
                    min_assets=effective_min_assets,
                    rebalance_hours=rebalance_hours,
                    weighting_mode=weighting_mode,
                    large_mask=robustness_large_mask,
                    large_top_n=large_top_n,
                    bucket_masks=robustness_bucket_masks,
                    crash_windows=robustness_crash_windows,
                    asset_families=asset_families,
                    cross_sectional=cross_robustness_cache.get(signal_key),
                )
                if signal_key not in cross_robustness_cache:
                    cross_robustness_cache[signal_key] = {
                        name: robustness[name]
                        for name in ("large_liquid", "liquidity_buckets", "asset_family_neutral")
                    }
                artifact_metadata = None
                if artifact_store is not None and artifact_request is not None:
                    artifact_metadata = artifact_store.write(
                        artifact_request,
                        {
                            "schema_version": "panel_factor_path_raw_evidence_v1",
                            "rank_ic": ic_report,
                            "coverage_median_assets": coverage,
                            "long_short": split_metrics,
                            "rolling_90d": rolling,
                            "robustness": robustness,
                            "selection_returns": dict(selection_returns.get(mode_key, {})),
                        },
                    )

            if artifact_store is not None and artifact_metadata is not None:
                artifact_cache_records.append(
                    {
                        "name": f"{factor_name}__{weighting_mode}",
                        "factor_name": factor_name,
                        "weighting_mode": weighting_mode,
                        "cache_hit": cached_artifact is not None,
                        "artifact_id": artifact_metadata["artifact_id"],
                        "request_key": artifact_metadata["request_key"],
                        "manifest_path": artifact_metadata["manifest_path"],
                        "manifest_file_sha256": artifact_metadata["manifest_file_sha256"],
                    }
                )
            trial_adjustment = _trial_adjustment(ic_report["Val"]["ic_tstat"], trial_count)
            status, checks = _factor_pass_status(
                split_metrics,
                ic_report,
                coverage,
                rolling,
                trial_adjustment,
                robustness,
                required_min_assets=effective_min_assets,
            )
            status, checks = _apply_evidence_promotion_ceiling(status, checks, evidence_policy)
            factor_reports.append(
                {
                    "name": f"{factor_name}__{weighting_mode}",
                    "factor_name": factor_name,
                    "candidate_id": factor_definitions[factor_name].get("candidate_id"),
                    "source_ids": factor_definitions[factor_name].get("source_ids", []),
                    "panel_formula": factor_definitions[factor_name].get("panel_formula"),
                    "neutralization": factor_definitions[factor_name].get("neutralization"),
                    "bucket_policy": factor_definitions[factor_name].get("bucket_policy"),
                    "generated_by": factor_definitions[factor_name].get("generated_by"),
                    "weighting_mode": weighting_mode,
                    "weighting_logic": WEIGHTING_MODES[weighting_mode]["logic"],
                    "family": factor_definitions[factor_name]["family"],
                    "logic": factor_definitions[factor_name]["logic"],
                    "status": status,
                    "checks": checks,
                    "failed_checks": [name for name, passed in checks.items() if not passed],
                    "coverage_median_assets": coverage,
                    "required_min_assets": effective_min_assets,
                    "rank_ic": ic_report,
                    "dependence_aware_rank_ic": dependence_aware_ic_report,
                    "trial_adjustment": trial_adjustment,
                    "long_short": split_metrics,
                    "rolling_90d": rolling,
                    "robustness": robustness,
                    "_selection_path_key": mode_key,
                }
            )

    overfit_audit = _attach_panel_overfit_audits(
        factor_reports,
        selection_returns,
        trial_count=trial_count,
        split_indexes=split_indexes,
    )
    selection_return_archive = overfit_audit.pop("_selection_return_archive")
    if record_trial_events:
        for factor_name, definition in factor_definitions.items():
            if not definition.get("is_candidate"):
                continue
            candidate_factor_rows = [row for row in factor_reports if row.get("candidate_id") == definition.get("candidate_id")]
            best_status = "panel_factor_reject"
            if any(row["status"] == "panel_factor_pass" for row in candidate_factor_rows):
                best_status = "panel_factor_pass"
            elif any(row["status"] == "panel_factor_watchlist" for row in candidate_factor_rows):
                best_status = "panel_factor_watchlist"
            candidate_registry.append_trial_event(
                definition,
                event="evaluated",
                status=best_status,
                reason="panel_audit_complete_with_dsr_cscv_pbo",
                batch_id=candidate_batch_id,
                variant_count=len(candidate_factor_rows),
                log_dir=LOG_DIR,
                registry_path=trial_event_registry_path,
            )

    _attach_baseline_comparisons(factor_reports)
    pbo_path_count = int((overfit_audit.get("cscv_pbo") or {}).get("n_strategies") or 0)
    dsr_dispersion_path_count = int(overfit_audit.get("observed_unique_val_path_count") or 0)
    for row in factor_reports:
        draft_checks = dict(row["checks"])
        val_block_audit = (
            ((row.get("dependence_aware_rank_ic") or {}).get("Val") or {}).get("empirical_block_audit") or {}
        )
        draft_checks["dependence_aware_val_ic_clue"] = bool(val_block_audit.get("watchlist_clue"))
        draft_checks["multiple_testing_pass"] = bool(val_block_audit.get("multiple_testing_pass"))
        draft_checks["return_evidence_complete_while_held"] = all(
            bool((row.get("long_short") or {}).get(split_name, {}).get("return_evidence_complete_while_held"))
            for split_name in SPLIT_NAMES
        )
        if row.get("candidate_id"):
            draft_checks["baseline_incremental_evidence"] = bool(
                (row.get("baseline_comparison") or {}).get("val_sharpe_minus_best_baseline", float("-inf")) > 0.0
            )
        panel_gate_policy.assert_catalog_covers(set(draft_checks))
        states = panel_gate_policy.annotate_gate_states(
            draft_checks,
            candidate_definition=row,
            evidence_coverage={
                "deflated_sharpe_pass": {
                    "observed": dsr_dispersion_path_count,
                    "required": trial_count,
                },
                "cscv_pbo_pass": {
                    "observed": pbo_path_count,
                    "required": trial_count,
                },
                "dependence_aware_val_ic_clue": {
                    "observed": int(val_block_audit.get("block_count") or 0),
                    "required": 3,
                },
                "multiple_testing_pass": {
                    "observed": int(val_block_audit.get("block_count") or 0),
                    "required": 3,
                },
            },
        )
        row["gate_v2_draft"] = {
            "policy_version": panel_gate_policy.GATE_POLICY_VERSION,
            "binding": False,
            "states": states,
            "effective_failures": panel_gate_policy.effective_failures(states),
            "insufficient_evidence": panel_gate_policy.insufficient_evidence(states),
            "classification": panel_gate_policy.classify_gate_v2_draft(states),
            "note": "Diagnostic only until null/planted-alpha calibration and prospective preregistration are complete.",
        }
    gate_v3_draft = panel_gate_policy_v3.attach_gate_v3_drafts(
        factor_reports,
        registry_breakdown=registry_breakdown,
        additional_candidate_p_values=additional_candidate_p_values,
    )
    factor_reports.sort(
        key=lambda row: (
            row["status"] == "panel_factor_pass",
            row["status"] == "panel_factor_watchlist",
            row["rank_ic"]["Val"]["mean_rank_ic"],
            row["long_short"]["Val"]["sharpe"],
            str(row.get("candidate_id") or row.get("factor_name") or row.get("name") or ""),
        ),
        reverse=True,
    )
    return {
        "created_at_utc": _stamp(),
        "schema_version": 1,
        "research_mode": "multi_asset_panel_factor_first",
        "evidence_policy": evidence_policy,
        "config": {
            "inst_ids": list(panel),
            "bar": config.BAR,
            "history_days": days,
            "split_ratios": config.SPLIT_RATIOS,
            "min_assets": min_assets,
            "rebalance_hours": rebalance_hours,
            "cost_bps": config.COST_BPS,
            "slippage_bps": config.SLIPPAGE_BPS,
            "factor_layer_leverage": 1.0,
            "strategy_layer_leverage_config": config.LEVERAGE,
            "exposure_accounting": "factor_1x_notional_v2",
        },
        "time_ranges": {
            name: {
                "start": str(idx[0]) if len(idx) else None,
                "end": str(idx[-1]) if len(idx) else None,
                "bars": int(len(idx)),
            }
            for name, idx in split_indexes.items()
        },
        "factor_definition_count": len(matrices["factors"]),
        "evaluated_factor_definition_count": len(selected_factor_names),
        "factor_scope": factor_scope,
        "builtin_factor_definition_count": len(FACTOR_DEFINITIONS),
        "candidate_factor_definition_count": len(candidate_definitions or []),
        "candidate_batch_id": candidate_batch_id,
        "weighting_modes": WEIGHTING_MODES,
        "baseline_factor_names": sorted(BASELINE_FACTOR_NAMES),
        "multiple_testing_trial_count": trial_count,
        "trial_count_breakdown": {
            "built_in_signal_attempt_count": len(FACTOR_DEFINITIONS),
            "candidate_signal_attempt_count": len(registered_candidate_ids | current_candidate_ids),
            "rank_ic_signal_trial_count": signal_trial_count,
            "portfolio_path_trial_count": trial_count,
            "candidate_registry": registry_breakdown,
            "v1_sidak_count_used": trial_count,
            "gate_v2_rank_ic_count_candidate": signal_trial_count,
            "gate_v3_outcome_seen_registry_variant_count": registry_breakdown.get(
                "outcome_seen_portfolio_variant_count", 0
            ),
            "note": "Audit logging, signal-level IC inference, and portfolio-path overfit inference use different trial units.",
        },
        "overfit_audit": overfit_audit,
        "evidence_artifact_cache": {
            "schema_version": panel_artifact_cache.ARTIFACT_SCHEMA_VERSION,
            "enabled": artifact_store is not None,
            "cache_dir": str(artifact_store.root) if artifact_store is not None else None,
            "hit_count": int(artifact_cache_hits),
            "miss_count": int(artifact_cache_misses),
            "artifact_count": len(artifact_cache_records),
            "classification_recomputed_each_run": True,
            "trial_count_cached": False,
            "records": artifact_cache_records,
        },
        "gate_policy_draft": panel_gate_policy.policy_summary(),
        "gate_policy_v3_draft": gate_v3_draft,
        "_selection_return_archive": selection_return_archive,
        "universe_registry_id": panel_universe.load_registry()["registry_id"],
        "point_in_time_universe": universe_summary,
        "design_power_proxy": power_proxy,
        "factor_count": len(factor_reports),
        "pass_count": sum(row["status"] == "panel_factor_pass" for row in factor_reports),
        "watchlist_count": sum(row["status"] == "panel_factor_watchlist" for row in factor_reports),
        "factors": factor_reports,
        "note": "Panel factors are diagnostics only. Holdout is audit evidence, not a tuning target.",
    }


def _evaluate_staged_v1(
    panel: dict[str, dict],
    days: int,
    rebalance_hours: int,
    min_assets: int,
    candidate_definitions: list[dict[str, Any]] | None = None,
    candidate_batch_id: str | None = None,
    factor_scope: str = "candidates_and_baselines",
    evaluation_start_utc: Any | None = None,
    evaluation_end_utc: Any | None = None,
    trial_registry_path: Path | str | None = None,
    trial_event_registry_path: Path | str | None = None,
    panel_fingerprint: str | None = None,
    artifact_cache_dir: Path | str | None = None,
    use_artifact_cache: bool = False,
) -> dict[str, Any]:
    if factor_scope != "candidates_and_baselines":
        raise ValueError("staged_v1_requires_candidates_and_baselines_scope")
    candidate_definitions = list(candidate_definitions or [])
    trial_registry_path = Path(trial_registry_path) if trial_registry_path is not None else LOG_DIR / "panel_trial_registry.jsonl"
    trial_context = _staged_trial_context(candidate_definitions, trial_registry_path)

    stage_2_started = time.perf_counter()
    routing_matrices = _build_matrices(panel, build_factors=False)
    routing_index = routing_matrices["eligibility"].index[
        routing_matrices["eligibility"].sum(axis=1) >= min_assets
    ]
    if evaluation_start_utc is not None:
        routing_index = routing_index[routing_index >= pd.Timestamp(evaluation_start_utc)]
    if evaluation_end_utc is not None:
        routing_index = routing_index[routing_index <= pd.Timestamp(evaluation_end_utc)]
    split_indexes = _split_index(routing_index)
    selection_split_indexes = {
        split_name: split_indexes[split_name]
        for split_name in panel_stage_policy.SELECTION_SPLITS
    }
    selection_index = selection_split_indexes["IS"].append(selection_split_indexes["Val"])
    if len(selection_index) == 0:
        raise ValueError("staged_evaluator_selection_index_empty")
    selection_end = selection_index.max()
    selection_panel = _truncate_panel_as_of(panel, selection_end)
    stage_2_result = _selection_only_candidate_screen(
        selection_panel,
        selection_split_indexes,
        candidate_definitions=candidate_definitions,
        rebalance_hours=rebalance_hours,
        min_assets=min_assets,
        trial_count=trial_context["trial_count"],
        signal_trial_count=trial_context["signal_trial_count"],
    )
    stage_2_seconds = time.perf_counter() - stage_2_started

    survivor_modes = stage_2_result["survivor_modes"]
    survivor_definitions = []
    for candidate in candidate_definitions:
        modes = survivor_modes.get(str(candidate["candidate_id"]), [])
        if not modes:
            continue
        survivor = dict(candidate)
        survivor["weighting_modes"] = [
            mode for mode in candidate.get("weighting_modes", []) if mode in modes
        ]
        survivor_definitions.append(survivor)

    stage_3_started = time.perf_counter()
    report = _evaluate_legacy_full(
        panel,
        days,
        rebalance_hours,
        min_assets,
        candidate_definitions=survivor_definitions,
        candidate_batch_id=candidate_batch_id,
        factor_scope=factor_scope,
        evaluation_start_utc=evaluation_start_utc,
        evaluation_end_utc=evaluation_end_utc,
        trial_registry_path=trial_registry_path,
        trial_event_registry_path=trial_event_registry_path,
        trial_candidate_definitions=candidate_definitions,
        trial_count_override=trial_context["trial_count"],
        signal_trial_count_override=trial_context["signal_trial_count"],
        additional_selection_returns=stage_2_result["selection_returns"],
        additional_candidate_p_values=stage_2_result["candidate_p_values"],
        record_trial_events=False,
        panel_fingerprint=panel_fingerprint,
        artifact_cache_dir=artifact_cache_dir,
        use_artifact_cache=use_artifact_cache,
    )
    stage_3_seconds = time.perf_counter() - stage_3_started

    stage_2_rows_by_name = {row["name"]: row for row in stage_2_result["rows"]}
    full_rows = report["factors"]
    for row in full_rows:
        row["holdout_accessed"] = True
        row["stage_3"] = {
            "executed": True,
            "audit_scope": ["Holdout", "rolling_90d", "robustness", "overfit", "gate_v2", "gate_v3"],
        }
        if row.get("candidate_id"):
            stage_2_row = stage_2_rows_by_name.get(row["name"])
            if stage_2_row is None or not stage_2_row["stage_2"]["survives_to_stage_3"]:
                raise ValueError(f"stage_3_candidate_missing_stage_2_survival:{row['name']}")
            row["evaluation_stage"] = "stage_3_complete"
            row["stage_2"] = stage_2_row["stage_2"]
        else:
            row["evaluation_stage"] = "stage_3_benchmark"
            row["stage_2"] = {
                "executed": False,
                "decision": "benchmark_bypass_to_stage_3",
                "reason": "registered_baselines_are_mandatory_controls",
                "formal_promotion": False,
            }

    rejected_rows = []
    for row in stage_2_result["rows"]:
        if row["stage_2"]["survives_to_stage_3"]:
            continue
        rejected = dict(row)
        rejected.pop("_selection_path_key", None)
        rejected["rolling_90d"] = {
            "executed": False,
            "reason": "stage_2_objective_failure",
        }
        rejected["robustness"] = {
            "executed": False,
            "reason": "stage_2_objective_failure",
        }
        rejected["overfit_audit"] = {
            "executed": False,
            "reason": "stage_2_objective_failure",
            "selection_return_still_counted_in_run_level_multiplicity": True,
            "holdout_used_for_selection": False,
        }
        rejected["gate_v2_draft"] = {
            "policy_version": panel_gate_policy.GATE_POLICY_VERSION,
            "binding": False,
            "classification": {
                "status": "stage_2_reject",
                "reason": "selection_only_necessary_condition_failed",
                "formal_pass_possible": False,
            },
            "not_executed_reason": "stage_2_objective_failure",
        }
        rejected["gate_v3_draft"] = {
            "policy_version": panel_gate_policy_v3.GATE_POLICY_VERSION,
            "binding": False,
            "classification": {
                "status": "historical_reject",
                "reason": "stage_2_selection_only_failure",
                "blockers": list(rejected["failed_checks"]),
                "formal_pass_possible": False,
            },
            "holdout_role": "not_accessed_for_stage_2_reject",
            "legacy_status_unchanged": True,
        }
        rejected_rows.append(rejected)

    factor_reports = full_rows + rejected_rows
    _attach_baseline_comparisons(factor_reports)
    factor_reports.sort(
        key=lambda row: (
            row["status"] == "panel_factor_pass",
            row["status"] == "panel_factor_watchlist",
            row.get("evaluation_stage") == "stage_3_complete",
            float(((row.get("rank_ic") or {}).get("Val") or {}).get("mean_rank_ic") or 0.0),
            float(((row.get("long_short") or {}).get("Val") or {}).get("sharpe") or 0.0),
            str(row.get("candidate_id") or row.get("factor_name") or row.get("name") or ""),
        ),
        reverse=True,
    )

    for candidate in candidate_definitions:
        candidate_id = str(candidate["candidate_id"])
        candidate_rows = [row for row in factor_reports if row.get("candidate_id") == candidate_id]
        best_status = "panel_factor_reject"
        if any(row["status"] == "panel_factor_pass" for row in candidate_rows):
            best_status = "panel_factor_pass"
        elif any(row["status"] == "panel_factor_watchlist" for row in candidate_rows):
            best_status = "panel_factor_watchlist"
        stage_3_path_count = sum(bool(row.get("holdout_accessed")) for row in candidate_rows)
        candidate_registry.append_trial_event(
            candidate,
            event="evaluated",
            status=best_status,
            reason=(
                "staged_panel_audit_complete_with_dsr_cscv_pbo"
                if stage_3_path_count
                else "stage_2_objective_failure"
            ),
            batch_id=candidate_batch_id,
            variant_count=len(candidate.get("weighting_modes", [])),
            log_dir=LOG_DIR,
            registry_path=trial_event_registry_path,
            extra={
                "evaluation_funnel": "staged_v1",
                "stage_2_path_count": len(candidate_rows),
                "stage_3_path_count": stage_3_path_count,
                "holdout_accessed_path_count": stage_3_path_count,
            },
        )

    stage_2_reject_count = len(rejected_rows)
    stage_2_survivor_count = sum(
        bool(row["stage_2"]["survives_to_stage_3"])
        for row in stage_2_result["rows"]
    )
    benchmark_stage_3_count = sum(not row.get("candidate_id") for row in full_rows)
    report["factors"] = factor_reports
    report["factor_definition_count"] = len(BASELINE_FACTOR_NAMES) + len(candidate_definitions)
    report["evaluated_factor_definition_count"] = len(BASELINE_FACTOR_NAMES) + len(candidate_definitions)
    report["stage_3_factor_definition_count"] = len(BASELINE_FACTOR_NAMES) + len(survivor_definitions)
    report["candidate_factor_definition_count"] = len(candidate_definitions)
    report["factor_count"] = len(factor_reports)
    report["pass_count"] = sum(row["status"] == "panel_factor_pass" for row in factor_reports)
    report["watchlist_count"] = sum(row["status"] == "panel_factor_watchlist" for row in factor_reports)
    report["combo_allowed"] = bool(report["pass_count"] > 0)
    report["evaluation_funnel"] = "staged_v1"
    report["config"]["evaluation_funnel"] = "staged_v1"
    report["stage_policy"] = panel_stage_policy.policy_summary()
    report["evaluation_funnel_summary"] = {
        "policy_version": panel_stage_policy.STAGE_POLICY_VERSION,
        "candidate_path_count": len(stage_2_result["rows"]),
        "stage_2_reject_path_count": stage_2_reject_count,
        "stage_2_survivor_path_count": stage_2_survivor_count,
        "stage_3_candidate_path_count": stage_2_survivor_count,
        "stage_3_benchmark_path_count": benchmark_stage_3_count,
        "holdout_accessed_candidate_path_count": stage_2_survivor_count,
        "holdout_isolated_candidate_path_count": stage_2_reject_count,
        "stage_2_seconds": float(stage_2_seconds),
        "stage_3_seconds": float(stage_3_seconds),
        "selection_index_start": stage_2_result["selection_index_start"],
        "selection_index_end": stage_2_result["selection_index_end"],
        "selection_bar_count": stage_2_result["selection_bar_count"],
        "holdout_start": str(split_indexes["Holdout"].min()) if len(split_indexes["Holdout"]) else None,
        "purge_policy": stage_2_result["purge_policy"],
        "full_trial_count_unchanged_by_early_stop": True,
        "multiple_testing_trial_count": trial_context["trial_count"],
        "selection_return_paths_retained_for_run_level_overfit_audit": True,
    }
    gate_v3_counts = (report.get("gate_policy_v3_draft") or {}).setdefault(
        "candidate_path_status_counts", {}
    )
    gate_v3_counts["historical_reject_stage_2"] = stage_2_reject_count
    report["note"] = (
        "Candidate Stage 2 uses physically truncated IS/Val data. Only survivors access Holdout; "
        "all outcome-seen paths remain in multiplicity and selection-return evidence."
    )
    return report


def _evaluate(
    panel: dict[str, dict],
    days: int,
    rebalance_hours: int,
    min_assets: int,
    candidate_definitions: list[dict[str, Any]] | None = None,
    candidate_batch_id: str | None = None,
    factor_scope: str = "all",
    evaluation_start_utc: Any | None = None,
    evaluation_end_utc: Any | None = None,
    trial_registry_path: Path | str | None = None,
    trial_event_registry_path: Path | str | None = None,
    evaluation_funnel: str = "legacy_full",
    panel_fingerprint: str | None = None,
    artifact_cache_dir: Path | str | None = None,
    use_artifact_cache: bool = False,
) -> dict[str, Any]:
    if evaluation_funnel == "staged_v1":
        return _evaluate_staged_v1(
            panel,
            days,
            rebalance_hours,
            min_assets,
            candidate_definitions=candidate_definitions,
            candidate_batch_id=candidate_batch_id,
            factor_scope=factor_scope,
            evaluation_start_utc=evaluation_start_utc,
            evaluation_end_utc=evaluation_end_utc,
            trial_registry_path=trial_registry_path,
            trial_event_registry_path=trial_event_registry_path,
            panel_fingerprint=panel_fingerprint,
            artifact_cache_dir=artifact_cache_dir,
            use_artifact_cache=use_artifact_cache,
        )
    if evaluation_funnel != "legacy_full":
        raise ValueError(f"unknown_evaluation_funnel:{evaluation_funnel}")
    report = _evaluate_legacy_full(
        panel,
        days,
        rebalance_hours,
        min_assets,
        candidate_definitions=candidate_definitions,
        candidate_batch_id=candidate_batch_id,
        factor_scope=factor_scope,
        evaluation_start_utc=evaluation_start_utc,
        evaluation_end_utc=evaluation_end_utc,
        trial_registry_path=trial_registry_path,
        trial_event_registry_path=trial_event_registry_path,
        panel_fingerprint=panel_fingerprint,
        artifact_cache_dir=artifact_cache_dir,
        use_artifact_cache=use_artifact_cache,
    )
    report["evaluation_funnel"] = "legacy_full"
    report["config"]["evaluation_funnel"] = "legacy_full"
    report["combo_allowed"] = bool(report["pass_count"] > 0)
    for row in report["factors"]:
        row.setdefault("evaluation_stage", "legacy_full")
        row.setdefault("holdout_accessed", True)
    return report


def _persist_selection_return_archive(
    report: dict[str, Any],
    *,
    candidate_batch_id: str | None,
    log_dir: Path,
    run_id: str | None = None,
) -> Path:
    archive = report.pop("_selection_return_archive")
    archive.update(
        {
            "created_at_utc": report["created_at_utc"],
            "candidate_batch_id": candidate_batch_id,
        }
    )
    run_suffix = f"_{run_id}" if run_id else ""
    archive_path = log_dir / f"panel_selection_return_paths_{report['created_at_utc']}{run_suffix}.json"
    archive_text = json.dumps(archive, ensure_ascii=False, indent=2, allow_nan=False)
    archive_bytes = archive_text.encode("utf-8")
    archive_path.write_bytes(archive_bytes)
    report["selection_return_archive"] = {
        "path": str(archive_path),
        "sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "path_count": len(archive["paths"]),
        "empty_path_count": archive["empty_path_count"],
        "holdout_included": False,
        "selection_end": archive["selection_end"],
    }
    return archive_path


def _write_factor_report(report: dict[str, Any], run_id: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(report, ensure_ascii=False, indent=2)
    out_path = LOG_DIR / f"panel_factor_report_{report['created_at_utc']}_{run_id}.json"
    with out_path.open("x", encoding="utf-8") as handle:
        handle.write(raw)
    (LOG_DIR / "panel_factor_report_latest.json").write_text(raw, encoding="utf-8")
    return out_path


def _execute_factor_run(
    args: argparse.Namespace,
    *,
    factor_scope: str,
    registry: panel_run_registry.RunRegistry,
    contract: dict[str, Any],
    contract_path: Path,
) -> int:
    run_id = contract["run_id"]
    if args.candidate_batch:
        critic_report = json.loads(Path(args.critic_report).read_text(encoding="utf-8"))
        critic_ok, critic_failures = panel_critic_contract.validate_critic_approval(
            critic_report,
            args.candidate_batch,
        )
        if not critic_ok:
            raise ValueError("critic_approval_invalid_before_evaluation:" + ",".join(critic_failures))
    reaudit_contract = _load_reaudit_contract(args.reference_report) if args.reference_report else None
    as_of = args.as_of or (reaudit_contract or {}).get("evaluation_end_utc")

    candidate_definitions, candidate_rejections, candidate_batch_id = _load_candidate_definitions(
        args.candidate_batch,
        args.hypothesis_registry,
    )
    if candidate_batch_id != contract.get("batch_id"):
        raise ValueError("candidate_batch_id_changed_after_run_registration")
    if args.candidate_batch:
        print(f"CANDIDATE_BATCH {candidate_batch_id} ACCEPTED {len(candidate_definitions)} REJECTED {len(candidate_rejections)}")
    trial_registry_snapshot = registry.snapshot_file(
        run_id,
        "effective_trial_registry_snapshot",
        args.trial_registry,
    )

    inst_ids = [item.strip() for item in args.symbols.split(",") if item.strip()]
    panel, failures, input_fingerprint, substrate_resolution = _resolve_panel_substrate(
        args,
        inst_ids,
        as_of,
    )
    substrate_artifact = registry.record_artifact(
        run_id,
        "panel_substrate_manifest",
        substrate_resolution["manifest_path"],
    )
    registry.record_data_fingerprint(
        run_id,
        input_fingerprint["panel_sha256"],
        details={
            "method": input_fingerprint["method"],
            "asset_count": input_fingerprint["asset_count"],
            "load_failure_count": len(failures),
            "resolved_as_of_utc": str(pd.Timestamp(as_of)) if as_of else None,
            "panel_substrate_id": substrate_resolution["substrate_id"],
            "panel_substrate_cache_hit": substrate_resolution["cache_hit"],
            "panel_loader_invoked": substrate_resolution["panel_loader_invoked"],
        },
    )
    if len(panel) < args.min_assets:
        report = {
            "created_at_utc": _stamp(),
            "schema_version": 1,
            "research_mode": "multi_asset_panel_factor_first",
            "strict_objective_satisfied": False,
            "failed_reasons": ["panel_min_assets_not_met"],
            "loaded_assets": list(panel),
            "load_failures": failures,
            "candidate_batch_id": candidate_batch_id,
            "candidate_rejections": candidate_rejections,
            "required_min_assets": args.min_assets,
            "input_data_fingerprint": input_fingerprint,
            "panel_substrate": {
                **substrate_resolution,
                "manifest_file_sha256": substrate_artifact["sha256"],
            },
            "effective_trial_registry_snapshot": {
                "path": trial_registry_snapshot["path"],
                "sha256": trial_registry_snapshot["sha256"],
                "size_bytes": trial_registry_snapshot["size_bytes"],
                "source_path": trial_registry_snapshot["snapshot_source_path"],
                "source_existed_before_evaluation": trial_registry_snapshot["snapshot_source_exists"],
            },
        }
        _attach_factory_run_metadata(
            report,
            contract=contract,
            contract_path=contract_path,
            registry=registry,
        )
        out_path = _write_factor_report(report, run_id)
        registry.record_artifact(run_id, "primary_report", out_path)
        registry.fail_run(
            run_id,
            "panel_min_assets_not_met",
            details={"loaded_asset_count": len(panel), "required_min_assets": int(args.min_assets)},
        )
        print(f"WROTE {out_path}")
        print("PANEL_MIN_ASSETS_NOT_MET", len(panel), args.min_assets)
        return 2

    report = _evaluate(
        panel,
        args.days,
        args.rebalance_hours,
        args.min_assets,
        candidate_definitions=candidate_definitions,
        candidate_batch_id=candidate_batch_id,
        factor_scope=factor_scope,
        evaluation_start_utc=(reaudit_contract or {}).get("evaluation_start_utc"),
        evaluation_end_utc=(reaudit_contract or {}).get("evaluation_end_utc"),
        trial_registry_path=trial_registry_snapshot["path"],
        trial_event_registry_path=args.trial_event_registry,
        evaluation_funnel=args.evaluation_funnel,
        panel_fingerprint=input_fingerprint["panel_sha256"],
        artifact_cache_dir=args.evidence_cache_dir,
        use_artifact_cache=not args.disable_evidence_cache,
    )
    report["load_failures"] = failures
    report["candidate_rejections"] = candidate_rejections
    report["strict_objective_satisfied"] = False
    report["data_as_of_utc"] = str(pd.Timestamp(as_of)) if as_of else None
    report["input_data_fingerprint"] = input_fingerprint
    report["panel_substrate"] = {
        **substrate_resolution,
        "manifest_file_sha256": substrate_artifact["sha256"],
    }
    report["effective_trial_registry_snapshot"] = {
        "path": trial_registry_snapshot["path"],
        "sha256": trial_registry_snapshot["sha256"],
        "size_bytes": trial_registry_snapshot["size_bytes"],
        "source_path": trial_registry_snapshot["snapshot_source_path"],
        "source_existed_before_evaluation": trial_registry_snapshot["snapshot_source_exists"],
    }
    report["trial_event_registry"] = {
        "path": str(Path(args.trial_event_registry).resolve(strict=False)),
        "role": "mutable_evaluation_event_output",
    }
    for artifact in (report.get("evidence_artifact_cache") or {}).get("records", []):
        registry.record_artifact(
            run_id,
            f"factor_evidence:{artifact['name']}",
            artifact["manifest_path"],
        )
    if reaudit_contract:
        _attach_reaudit_comparability(report, reaudit_contract)
    report["failed_reasons"] = [] if report["pass_count"] else ["no_panel_factor_pass"]
    _attach_factory_run_metadata(
        report,
        contract=contract,
        contract_path=contract_path,
        registry=registry,
    )
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = _persist_selection_return_archive(
        report,
        candidate_batch_id=candidate_batch_id,
        log_dir=LOG_DIR,
        run_id=run_id,
    )
    registry.record_artifact(run_id, "selection_return_archive", archive_path)
    out_path = _write_factor_report(report, run_id)
    report_artifact = registry.record_artifact(run_id, "primary_report", out_path)

    print(f"WROTE {out_path}")
    print(f"ASSETS {len(panel)} FACTORS {report['factor_count']} PASS {report['pass_count']} WATCHLIST {report['watchlist_count']}")
    for row in report["factors"]:
        val = row["long_short"]["Val"]
        ic_val = row["rank_ic"]["Val"]
        if not row.get("holdout_accessed", True):
            print(
                f"{row['status']:22s} {row['name']:28s} "
                f"ValIC {ic_val['mean_rank_ic']:7.4f} ValSR {val['sharpe']:6.2f} "
                f"Stage2 REJECT Holdout NOT_ACCESSED Turn {val['turnover']:.4f}"
            )
        else:
            hold = row["long_short"]["Holdout"]
            print(
                f"{row['status']:22s} {row['name']:28s} "
                f"ValIC {ic_val['mean_rank_ic']:7.4f} ValSR {val['sharpe']:6.2f} "
                f"HoldSR {hold['sharpe']:6.2f} HDD {hold['max_drawdown']:5.2%} "
                f"RollIC+ {row['rolling_90d']['positive_ic_windows']}/{row['rolling_90d']['window_count']} "
                f"AdjP {row['trial_adjustment']['sidak_adjusted_p']:.4f} "
                f"Turn {val['turnover']:.4f}"
            )
    registry.complete_run(
        run_id,
        details={
            "loaded_asset_count": len(panel),
            "evaluated_factor_count": int(report["factor_count"]),
            "pass_count": int(report["pass_count"]),
            "watchlist_count": int(report["watchlist_count"]),
            "primary_report_sha256": report_artifact["sha256"],
            "panel_substrate_id": substrate_resolution["substrate_id"],
            "panel_substrate_cache_hit": substrate_resolution["cache_hit"],
            "evaluation_funnel": report.get("evaluation_funnel"),
            "stage_2_reject_path_count": int(
                (report.get("evaluation_funnel_summary") or {}).get("stage_2_reject_path_count") or 0
            ),
            "stage_3_candidate_path_count": int(
                (report.get("evaluation_funnel_summary") or {}).get("stage_3_candidate_path_count") or 0
            ),
        },
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    global LOG_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=getattr(config, "PANEL_HISTORY_DAYS", config.HISTORY_DAYS))
    parser.add_argument("--symbols", default=",".join(getattr(config, "PANEL_INST_IDS", [config.INST_ID])))
    parser.add_argument("--min-assets", type=int, default=getattr(config, "PANEL_MIN_ASSETS", 5))
    parser.add_argument("--rebalance-hours", type=int, default=getattr(config, "PANEL_REBALANCE_HOURS", 24))
    parser.add_argument("--candidate-batch", help="Frozen panel candidate batch JSON to audit")
    parser.add_argument(
        "--critic-report",
        help="Independent approved critic report bound to the frozen candidate batch",
    )
    parser.add_argument(
        "--trial-registry",
        default=str(LOG_DIR / "panel_trial_registry.jsonl"),
        help="Frozen trial-registry input used for multiplicity accounting",
    )
    parser.add_argument(
        "--trial-event-registry",
        default=str(LOG_DIR / "panel_trial_registry.jsonl"),
        help="Mutable output for evaluated trial events; orchestration should use a job-local file",
    )
    parser.add_argument(
        "--run-log-dir",
        help="Output root for run registry, reports, and selection archives",
    )
    parser.add_argument(
        "--hypothesis-registry",
        default=str(Path(__file__).with_name("LITERATURE_HYPOTHESIS_REGISTRY.md")),
        help="Literature hypothesis registry used to authorize candidate source ids",
    )
    parser.add_argument(
        "--factor-scope",
        choices=["auto", "all", "candidates_and_baselines"],
        default="auto",
        help="auto evaluates candidates plus registered baselines when a batch is supplied",
    )
    parser.add_argument(
        "--evaluation-funnel",
        choices=["auto", "legacy_full", "staged_v1"],
        default="auto",
        help="auto uses staged_v1 for candidate batches and legacy_full otherwise",
    )
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--as-of", help="UTC data cutoff for a reproducible audit")
    parser.add_argument("--reference-report", help="Prior report whose sample/trials/path identities must remain unchanged")
    parser.add_argument(
        "--substrate-manifest",
        help="Immutable panel substrate manifest; bypasses all panel source loaders",
    )
    parser.add_argument(
        "--require-cached-substrate",
        action="store_true",
        help="Fail closed when no validated automatic substrate alias is available",
    )
    parser.add_argument(
        "--substrate-cache-dir",
        default=str(PANEL_SUBSTRATE_DIR),
        help="Content-addressed panel substrate store",
    )
    parser.add_argument(
        "--evidence-cache-dir",
        default=str(PANEL_ARTIFACT_CACHE_DIR),
        help="Content-addressed pre-multiplicity factor-path evidence store",
    )
    parser.add_argument(
        "--disable-evidence-cache",
        dest="disable_evidence_cache",
        action="store_true",
        help="Recompute raw path evidence instead of reading or writing immutable artifacts",
    )
    parser.add_argument(
        "--enable-evidence-cache",
        dest="disable_evidence_cache",
        action="store_false",
        help="Opt in to the universe-bound immutable evidence cache",
    )
    parser.set_defaults(disable_evidence_cache=True)
    args = parser.parse_args(argv)
    if args.run_log_dir:
        LOG_DIR = Path(args.run_log_dir).expanduser().resolve(strict=False)
    if bool(args.candidate_batch) != bool(args.critic_report):
        parser.error("--candidate-batch and --critic-report must be supplied together")
    if args.candidate_batch:
        try:
            critic_report = json.loads(Path(args.critic_report).read_text(encoding="utf-8"))
            critic_ok, critic_failures = panel_critic_contract.validate_critic_approval(
                critic_report,
                args.candidate_batch,
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            parser.error(f"critic approval could not be validated: {exc}")
        if not critic_ok:
            parser.error("critic approval rejected: " + ",".join(critic_failures))
    if args.force_refresh and (args.substrate_manifest or args.require_cached_substrate):
        parser.error("--force-refresh cannot be combined with frozen or required cached substrate modes")
    factor_scope = args.factor_scope
    if factor_scope == "auto":
        factor_scope = "candidates_and_baselines" if args.candidate_batch else "all"
    if args.evaluation_funnel == "auto":
        args.evaluation_funnel = "staged_v1" if args.candidate_batch else "legacy_full"
    if args.evaluation_funnel == "staged_v1" and factor_scope != "candidates_and_baselines":
        parser.error("--evaluation-funnel staged_v1 requires candidates_and_baselines factor scope")
    registry = panel_run_registry.RunRegistry(
        LOG_DIR / "factory_runs",
        LOG_DIR / "factory_run_index.sqlite3",
    )
    contract = _build_factor_run_contract(args, factor_scope)
    contract_path = registry.create_run(contract)
    run_id = contract["run_id"]
    try:
        registry.start_run(
            run_id,
            details={"factor_scope": factor_scope, "evaluation_funnel": args.evaluation_funnel},
        )
        return _execute_factor_run(
            args,
            factor_scope=factor_scope,
            registry=registry,
            contract=contract,
            contract_path=contract_path,
        )
    except KeyboardInterrupt:
        try:
            registry.interrupt_run(run_id, details={"reason": "keyboard_interrupt"})
        except Exception as registry_error:
            print(f"RUN_REGISTRY_INTERRUPT_ERROR {registry_error}", file=sys.stderr)
        raise
    except Exception as exc:
        try:
            current = registry.get_run(run_id) or {}
            if current.get("status") not in panel_run_registry.TERMINAL_STATUSES:
                registry.fail_run(
                    run_id,
                    type(exc).__name__,
                    details={"message": str(exc)[:1000]},
                )
        except Exception as registry_error:
            print(f"RUN_REGISTRY_FAILURE_ERROR {registry_error}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
