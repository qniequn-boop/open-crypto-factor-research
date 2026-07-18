"""Immutable daily shadow returns for preregistered panel factor paths."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import config
import data as data_module
import panel_candidate_registry as candidate_registry
import panel_factor_research as factor_research
import panel_literature_replication as literature_replication
import panel_universe


TRACKING_REGISTRY_PATH = Path("PROSPECTIVE_FACTOR_TRACKING_REGISTRY.json")
PROMOTION_POLICY_PATH = Path("PROSPECTIVE_FACTOR_PROMOTION_POLICY_V1.json")
SNAPSHOT_DIR = Path("prospective_factor_snapshots")
LOW_VOL_EVALUATOR_TYPE = "monthly_spot_low_vol_v1"
LOW_VOL_EVALUATOR_TYPE_V2 = "monthly_spot_low_vol_v2"
LOW_VOL_EVALUATOR_TYPES = {LOW_VOL_EVALUATOR_TYPE, LOW_VOL_EVALUATOR_TYPE_V2}


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def snapshot_evidence_sha256(payload: dict[str, Any]) -> str:
    evidence = dict(payload)
    evidence.pop("captured_at_utc", None)
    return payload_sha256(evidence)


def file_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_bundle_fingerprint(paths: list[Path | str]) -> dict[str, Any]:
    components = {}
    for value in paths:
        path = Path(value)
        key = path.name
        if key in components:
            raise ValueError(f"duplicate_bundle_filename:{key}")
        components[key] = file_sha256(path)
    digest = hashlib.sha256()
    for name, value in sorted(components.items()):
        digest.update(name.encode("utf-8"))
        digest.update(value.encode("ascii"))
    return {
        "method": "sha256_of_sorted_filename_and_file_sha256_v1",
        "bundle_sha256": digest.hexdigest(),
        "components": components,
    }


def callable_bundle_fingerprint(components: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint named behavior without coupling to unrelated module edits."""
    source_hashes = {}
    for name, value in components.items():
        source = inspect.getsource(value).encode("utf-8")
        source_hashes[str(name)] = hashlib.sha256(source).hexdigest()
    digest = hashlib.sha256()
    for name, value in sorted(source_hashes.items()):
        digest.update(name.encode("utf-8"))
        digest.update(value.encode("ascii"))
    return {
        "method": "sha256_of_sorted_callable_name_and_source_sha256_v2",
        "bundle_sha256": digest.hexdigest(),
        "components": source_hashes,
    }


def _as_utc(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def load_tracking_registry(path: Path | str = TRACKING_REGISTRY_PATH) -> dict[str, Any]:
    registry_path = Path(path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported_tracking_registry_schema")
    if not payload.get("tracking_registry_id"):
        raise ValueError("missing_tracking_registry_id")
    plans = payload.get("plans")
    if not isinstance(plans, list):
        raise ValueError("tracking_registry_plans_must_be_list")
    seen = set()
    for plan in plans:
        track_id = str(plan.get("track_id") or "")
        if not track_id or track_id in seen:
            raise ValueError(f"invalid_or_duplicate_track_id:{track_id}")
        seen.add(track_id)
        if bool(plan.get("selection_feedback_allowed")):
            raise ValueError(f"selection_feedback_must_be_disabled:{track_id}")
        if plan.get("status") == "active" and not plan.get("activation_date_utc"):
            raise ValueError(f"active_plan_missing_activation_date:{track_id}")
        if plan.get("status") == "active" and not plan.get("track_contract_sha256"):
            raise ValueError(f"active_plan_missing_track_contract_sha256:{track_id}")
        if plan.get("status") == "active" and plan.get("evaluator_type") in LOW_VOL_EVALUATOR_TYPES:
            required = {
                "candidate_path_id",
                "historical_report_path",
                "historical_report_sha256",
                "candidate_batch_path",
                "candidate_batch_sha256",
            }
            if bool(plan.get("promotion_eligible")):
                required.update({"promotion_policy_id", "promotion_policy_path", "promotion_policy_sha256"})
            missing = sorted(required - set(plan))
            if missing:
                raise ValueError(f"active_low_vol_plan_missing_fields:{track_id}:{','.join(missing)}")
    return payload


def active_plans(tracking_registry: dict[str, Any], evidence_date: Any) -> list[dict[str, Any]]:
    day = _as_utc(evidence_date).date()
    active = []
    for plan in tracking_registry.get("plans", []):
        if plan.get("status") != "active":
            continue
        activation = pd.Timestamp(str(plan["activation_date_utc"])).date()
        end_value = plan.get("end_date_utc")
        end = pd.Timestamp(str(end_value)).date() if end_value else None
        if day >= activation and (end is None or day <= end):
            active.append(plan)
    return active


def _load_low_vol_plan_candidates(
    plan: dict[str, Any],
    *,
    project_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if bool(plan.get("promotion_eligible")):
        policy_path = project_dir / str(plan["promotion_policy_path"])
        if file_sha256(policy_path) != str(plan["promotion_policy_sha256"]).lower():
            raise ValueError(f"promotion_policy_sha256_mismatch:{plan['track_id']}")
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        if policy.get("schema_version") != 1:
            raise ValueError(f"unsupported_promotion_policy_schema:{plan['track_id']}")
        if str(policy.get("policy_id")) != str(plan["promotion_policy_id"]):
            raise ValueError(f"promotion_policy_id_mismatch:{plan['track_id']}")
    batch_path = project_dir / str(plan["candidate_batch_path"])
    expected_hash = str(plan["candidate_batch_sha256"]).lower()
    actual_hash = file_sha256(batch_path)
    if actual_hash != expected_hash:
        raise ValueError(f"candidate_batch_sha256_mismatch:{plan['track_id']}")
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    if str(batch.get("batch_id")) != str(plan.get("candidate_batch_id")):
        raise ValueError(f"candidate_batch_id_mismatch:{plan['track_id']}")
    if batch.get("replication_id") != literature_replication.LOW_VOL_REPLICATION_ID:
        raise ValueError(f"tracking_batch_not_monthly_low_vol:{plan['track_id']}")
    report_path = project_dir / str(plan["historical_report_path"])
    if file_sha256(report_path) != str(plan["historical_report_sha256"]).lower():
        raise ValueError(f"historical_report_sha256_mismatch:{plan['track_id']}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if str(report.get("batch_sha256")) != actual_hash:
        raise ValueError(f"historical_report_batch_sha256_mismatch:{plan['track_id']}")
    path_id = str(plan["candidate_path_id"])
    rows = [row for row in report.get("paths", []) if str(row.get("path_id")) == path_id]
    if len(rows) != 1:
        raise ValueError(f"historical_candidate_path_missing:{plan['track_id']}:{path_id}")
    row = rows[0]
    if row.get("classification", {}).get("status") != "prospective_shadow_strong":
        raise ValueError(f"historical_candidate_not_strong:{plan['track_id']}:{path_id}")
    if not bool(row.get("holdout_accessed")):
        raise ValueError(f"historical_candidate_holdout_not_audited:{plan['track_id']}:{path_id}")
    return [dict(row["candidate"])], batch


def load_plan_candidates(plan: dict[str, Any], *, project_dir: Path | str = Path(".")) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    project_dir = Path(project_dir)
    if plan.get("evaluator_type") in LOW_VOL_EVALUATOR_TYPES:
        return _load_low_vol_plan_candidates(plan, project_dir=project_dir)
    if bool(plan.get("promotion_eligible")):
        policy_path = project_dir / str(plan["promotion_policy_path"])
        if file_sha256(policy_path) != str(plan["promotion_policy_sha256"]).lower():
            raise ValueError(f"promotion_policy_sha256_mismatch:{plan['track_id']}")
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        if policy.get("schema_version") != 1:
            raise ValueError(f"unsupported_promotion_policy_schema:{plan['track_id']}")
        if str(policy.get("policy_id")) != str(plan["promotion_policy_id"]):
            raise ValueError(f"promotion_policy_id_mismatch:{plan['track_id']}")
    batch_path = project_dir / str(plan["candidate_batch_path"])
    expected_hash = str(plan["candidate_batch_sha256"]).lower()
    actual_hash = file_sha256(batch_path)
    if actual_hash != expected_hash:
        raise ValueError(f"candidate_batch_sha256_mismatch:{plan['track_id']}")
    batch = candidate_registry.load_candidate_batch(batch_path)
    if str(batch.get("batch_id")) != str(plan.get("candidate_batch_id")):
        raise ValueError(f"candidate_batch_id_mismatch:{plan['track_id']}")

    source_ids = candidate_registry.load_literature_source_ids()
    candidates = []
    errors = []
    for candidate in batch.get("candidates", []):
        ok, candidate_errors = candidate_registry.validate_candidate(
            candidate,
            literature_source_ids=source_ids,
            known_formulas=set(factor_research.FACTOR_DEFINITIONS),
            allowed_weighting_modes=set(factor_research.WEIGHTING_MODES),
        )
        formula_spec = factor_research.FACTOR_DEFINITIONS.get(str(candidate.get("panel_formula")), {})
        expected_direction = factor_research._formula_candidate_direction(formula_spec)
        if expected_direction and str(candidate.get("direction", "")).lower() != expected_direction:
            candidate_errors.append(f"formula_direction_mismatch:{expected_direction}")
            ok = False
        if ok:
            candidates.append(candidate_registry.normalize_candidate(candidate))
        else:
            errors.append({"candidate_id": candidate.get("candidate_id"), "errors": candidate_errors})
    if errors:
        raise ValueError(f"invalid_tracking_candidates:{json.dumps(errors, sort_keys=True)}")
    return candidates, batch


def expected_plan_path_ids(plan: dict[str, Any], candidates: list[dict[str, Any]]) -> list[str]:
    if plan.get("evaluator_type") in LOW_VOL_EVALUATOR_TYPES:
        if len(candidates) != 1:
            raise ValueError(f"low_vol_tracking_requires_one_candidate:{plan['track_id']}")
        return [str(plan["candidate_path_id"])]
    path_ids = []
    baseline_names = sorted(set(plan.get("baseline_factor_names") or factor_research.BASELINE_FACTOR_NAMES))
    for factor_name in baseline_names:
        definition = factor_research.FACTOR_DEFINITIONS.get(factor_name)
        if definition is None or factor_name not in factor_research.BASELINE_FACTOR_NAMES:
            raise ValueError(f"unknown_tracking_baseline:{factor_name}")
        for weighting_mode in definition.get("weighting_modes", factor_research.WEIGHTING_MODES):
            path_ids.append(f"{factor_name}__{weighting_mode}")
    for candidate in sorted(candidates, key=lambda row: str(row["candidate_id"])):
        for weighting_mode in candidate["weighting_modes"]:
            path_ids.append(f"{candidate['candidate_id']}__{weighting_mode}")
    if len(path_ids) != len(set(path_ids)):
        raise ValueError(f"duplicate_expected_path_id:{plan['track_id']}")
    return sorted(path_ids)


def _build_low_vol_track_contract(
    plan: dict[str, Any],
    candidate_batch: dict[str, Any],
    *,
    universe_registry: dict[str, Any],
    universe_registry_sha256: str,
    evaluator_bundle_fingerprint: dict[str, Any] | None,
    low_vol_evaluator_fingerprint: dict[str, Any] | None,
) -> dict[str, Any]:
    evaluator_type = plan.get("evaluator_type")
    path_id = str(plan["candidate_path_id"])
    source_path = next(
        (row for row in candidate_batch.get("paths", []) if str(row.get("path_id")) == path_id),
        None,
    )
    if source_path is None:
        raise ValueError(f"low_vol_path_not_in_frozen_batch:{plan['track_id']}:{path_id}")
    artifacts = candidate_batch["frozen_implementation"]
    contract = {
        "schema_version": 2 if evaluator_type == LOW_VOL_EVALUATOR_TYPE_V2 else 1,
        "track_id": str(plan["track_id"]),
        "evaluator_type": str(evaluator_type),
        "candidate_batch_id": str(candidate_batch["batch_id"]),
        "candidate_batch_sha256": str(plan["candidate_batch_sha256"]),
        "historical_report_sha256": str(plan["historical_report_sha256"]),
        "promotion_policy_id": str(plan["promotion_policy_id"]),
        "promotion_policy_sha256": str(plan["promotion_policy_sha256"]),
        "candidate_ids": [path_id],
        "baseline_factor_names": [],
        "expected_path_ids": [path_id],
        "panel_formula": f"monthly_low_vol_{int(source_path['lookback_days'])}d",
        "lookback_days": int(source_path["lookback_days"]),
        "bar": str(artifacts["bar"]),
        "history_days": int(artifacts["history_days"]),
        "minimum_lookback_coverage_fraction": float(artifacts["minimum_lookback_coverage_fraction"]),
        "side_fraction": float(artifacts["side_fraction"]),
        "execution_lag_days": int(artifacts["execution_lag_days"]),
        "panel_min_assets": int(artifacts["minimum_assets"]),
        "cost_bps": float(artifacts["cost_bps_one_way"]),
        "slippage_bps": float(artifacts["slippage_bps_one_way"]),
        "factor_layer_leverage": 1.0,
        "exposure_accounting": "daily_spot_factor_1x_notional_v1",
        "execution_claim": "spot_return_factor_shadow_only",
        "universe_registry_id": str(universe_registry["registry_id"]),
        "universe_registry_sha256": str(universe_registry_sha256),
        "activation_date_utc": str(plan["activation_date_utc"]),
        "promotion_eligible": bool(plan.get("promotion_eligible", False)),
    }
    if evaluator_type == LOW_VOL_EVALUATOR_TYPE_V2:
        contract.update(
            {
                "evaluator_contract_method": str((low_vol_evaluator_fingerprint or {}).get("method") or ""),
                "evaluator_semantic_sha256": str(
                    (low_vol_evaluator_fingerprint or {}).get("bundle_sha256") or ""
                ),
                "cache_refresh_inside_factor_snapshot": low_vol_cache_refresh_enabled(),
            }
        )
    else:
        contract["evaluator_bundle_sha256"] = str(
            (evaluator_bundle_fingerprint or {}).get("bundle_sha256") or ""
        )
    return contract


def build_track_contract(
    plan: dict[str, Any],
    candidates: list[dict[str, Any]],
    candidate_batch: dict[str, Any],
    *,
    universe_registry: dict[str, Any],
    universe_registry_sha256: str,
    evaluator_bundle_fingerprint: dict[str, Any] | None,
    low_vol_evaluator_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if plan.get("evaluator_type") in LOW_VOL_EVALUATOR_TYPES:
        return _build_low_vol_track_contract(
            plan,
            candidate_batch,
            universe_registry=universe_registry,
            universe_registry_sha256=universe_registry_sha256,
            evaluator_bundle_fingerprint=evaluator_bundle_fingerprint,
            low_vol_evaluator_fingerprint=low_vol_evaluator_fingerprint,
        )
    return {
        "schema_version": 1,
        "track_id": str(plan["track_id"]),
        "candidate_batch_id": str(candidate_batch["batch_id"]),
        "candidate_batch_sha256": str(plan["candidate_batch_sha256"]),
        "candidate_ids": sorted(str(candidate["candidate_id"]) for candidate in candidates),
        "baseline_factor_names": sorted(set(plan.get("baseline_factor_names") or factor_research.BASELINE_FACTOR_NAMES)),
        "expected_path_ids": expected_plan_path_ids(plan, candidates),
        "rebalance_hours": int(plan.get("rebalance_hours", getattr(config, "PANEL_REBALANCE_HOURS", 24))),
        "panel_min_assets": int(getattr(config, "PANEL_MIN_ASSETS", 20)),
        "cost_bps": float(config.COST_BPS),
        "slippage_bps": float(config.SLIPPAGE_BPS),
        "factor_layer_leverage": 1.0,
        "strategy_layer_leverage_config": float(getattr(config, "LEVERAGE", 1)),
        "exposure_accounting": "factor_1x_notional_v2",
        "universe_registry_id": str(universe_registry["registry_id"]),
        "universe_registry_sha256": str(universe_registry_sha256),
        "evaluator_bundle_sha256": str((evaluator_bundle_fingerprint or {}).get("bundle_sha256") or ""),
        "activation_date_utc": str(plan["activation_date_utc"]),
        "promotion_eligible": bool(plan.get("promotion_eligible", False)),
    }


def _truncate_panel(panel: dict[str, dict[str, Any]], as_of: pd.Timestamp) -> dict[str, dict[str, Any]]:
    truncated: dict[str, dict[str, Any]] = {}
    for inst_id, item in panel.items():
        clean = dict(item)
        for key in ("ohlcv", "spot_ohlcv", "open_interest"):
            value = clean.get(key)
            if value is not None:
                clean[key] = value.loc[value.index <= as_of].copy()
        funding = clean.get("funding")
        if funding is not None:
            clean["funding"] = funding.loc[funding.index <= as_of].copy()
        truncated[inst_id] = clean
    return truncated


def collect_daily_spot_tracking_panel(
    registry: dict[str, Any],
    *,
    bar: str,
    days: int,
    refresh: bool,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    instruments = data_module.load_instruments("SWAP", force_refresh=False)
    panel: dict[str, Any] = {}
    failures = []
    for inst_id in panel_universe.registry_inst_ids(registry):
        try:
            if refresh:
                daily_spot = data_module.refresh_ohlcv_cache_incremental(
                    inst_id,
                    bar=bar,
                    days=days,
                    spot=True,
                )
            else:
                daily_spot = data_module.load_spot_data(inst_id, bar=bar, days=days)
            instrument = instruments.loc[inst_id].to_dict() if inst_id in instruments.index else None
            if not instrument:
                raise ValueError("instrument_missing_from_swap_snapshot")
            panel[inst_id] = {
                "daily_spot_ohlcv": daily_spot,
                "instrument": instrument,
            }
        except Exception as exc:
            failures.append({"inst_id": inst_id, "error": str(exc)})
    return panel, failures


def low_vol_cache_refresh_enabled() -> bool:
    """Refresh once after UTC close, retaining only exchange-confirmed bars."""
    return True


def _build_monthly_low_vol_plan_evidence(
    panel: dict[str, dict[str, Any]],
    *,
    plan: dict[str, Any],
    candidates: list[dict[str, Any]],
    candidate_batch: dict[str, Any],
    as_of: pd.Timestamp,
    universe_registry: dict[str, Any],
    track_contract: dict[str, Any],
) -> dict[str, Any]:
    if len(candidates) != 1:
        raise ValueError(f"low_vol_tracking_requires_one_candidate:{plan['track_id']}")
    expected_bar = as_of.normalize()
    close_frames = {}
    volume_frames = {}
    for inst_id, item in panel.items():
        daily = item.get("daily_spot_ohlcv")
        if daily is None:
            continue
        daily = daily.loc[daily.index <= expected_bar]
        close_frames[inst_id] = daily["close"]
        volume_frames[inst_id] = daily["vol_quote"]
    close = pd.DataFrame(close_frames).sort_index()
    vol_quote = pd.DataFrame(volume_frames).reindex(close.index)
    if close.empty or expected_bar not in close.index:
        raise ValueError(f"confirmed_daily_spot_bar_missing:{expected_bar.isoformat()}")
    universe = panel_universe.build_point_in_time_eligibility(
        panel,
        close,
        vol_quote,
        registry=universe_registry,
    )
    eligibility = universe["eligibility"]
    minimum_assets = int(track_contract["panel_min_assets"])
    common_index = eligibility.index[eligibility.sum(axis=1) >= minimum_assets]
    if expected_bar not in common_index:
        raise ValueError(f"daily_spot_breadth_below_minimum:{expected_bar.isoformat()}")
    formation_times = literature_replication._month_end_formation_times(common_index)
    signal = literature_replication._trailing_low_vol_signal(
        close,
        formation_times,
        eligibility,
        lookback_days=int(track_contract["lookback_days"]),
        minimum_coverage_fraction=float(track_contract["minimum_lookback_coverage_fraction"]),
    )
    dummy_caps = pd.DataFrame(1.0, index=formation_times, columns=close.columns)
    scope = eligibility.reindex(formation_times).fillna(False)
    formation_weights, coverage = literature_replication._quintile_long_short_weights(
        signal,
        dummy_caps,
        scope,
        min_assets=minimum_assets,
        side_fraction=float(track_contract["side_fraction"]),
        weighting_mode="equal_weighted",
    )
    held = literature_replication._execute_monthly_targets(
        formation_weights,
        common_index,
        execution_lag_days=int(track_contract["execution_lag_days"]),
    )
    returns = close.pct_change(fill_method=None).reindex(common_index)
    current_weights = held.loc[expected_bar]
    previous_bar = common_index[common_index.get_loc(expected_bar) - 1] if common_index.get_loc(expected_bar) > 0 else None
    previous_weights = held.loc[previous_bar] if previous_bar is not None else current_weights * 0.0
    activation_date = pd.Timestamp(str(plan["activation_date_utc"])).date()
    initial_entry = expected_bar.date() == activation_date
    turnover = float(
        current_weights.abs().sum()
        if initial_entry
        else current_weights.sub(previous_weights).abs().sum()
    )
    current_returns = returns.loc[expected_bar]
    positioned = current_weights.abs().gt(1e-12)
    missing_returns = current_returns.isna() & positioned
    gross_return = float((current_weights * current_returns.fillna(0.0)).sum())
    transaction_cost = turnover * (
        float(track_contract["cost_bps"]) + float(track_contract["slippage_bps"])
    ) / 10000.0
    net_return = gross_return - transaction_cost
    latest_formation = formation_times[formation_times < expected_bar].max()
    formation_signal = signal.loc[latest_formation]
    signal_breadth = int(formation_signal.notna().sum())
    gross_exposure = float(current_weights.abs().sum())
    return_complete = bool(not missing_returns.any())
    observation_eligible = bool(
        signal_breadth >= minimum_assets
        and abs(gross_exposure - 1.0) <= 1e-9
        and return_complete
        and coverage["valid_formation_count"] > 0
    )
    weights_payload = {
        str(inst_id): float(value)
        for inst_id, value in current_weights.items()
        if np.isfinite(value) and abs(float(value)) > 1e-12
    }
    path_id = str(plan["candidate_path_id"])
    path = {
        "path_id": path_id,
        "factor_name": path_id,
        "candidate_id": path_id,
        "panel_formula": str(track_contract["panel_formula"]),
        "source_ids": list(candidates[0].get("source_ids") or []),
        "weighting_mode": "monthly_equal_weighted_quintiles",
        "daily_spot_bar_utc": expected_bar.isoformat(),
        "signal_formation_utc": latest_formation.isoformat(),
        "signal_breadth": signal_breadth,
        "required_min_assets": minimum_assets,
        "gross_exposure": gross_exposure,
        "long_exposure": float(current_weights.clip(lower=0).sum()),
        "short_exposure": float(-current_weights.clip(upper=0).sum()),
        "weights": weights_payload,
        "gross_return": gross_return,
        "transaction_cost": float(transaction_cost),
        "funding_paid": 0.0,
        "net_return": float(net_return),
        "turnover": turnover,
        "initial_entry_cost_charged": initial_entry,
        "missing_return_assets_while_held": [
            str(inst_id) for inst_id in missing_returns.index[missing_returns]
        ],
        "return_evidence_complete_while_held": return_complete,
        "funding_evidence_complete_while_held": True,
        "execution_claim": "spot_return_factor_shadow_only",
        "observation_eligible": observation_eligible,
    }
    contract_sha256 = payload_sha256(track_contract)
    declared_contract_sha256 = str(plan.get("track_contract_sha256") or "")
    contract_matches_registry = bool(declared_contract_sha256) and contract_sha256 == declared_contract_sha256
    expected_paths = list(track_contract["expected_path_ids"])
    path_set_matches_contract = [path_id] == expected_paths
    operational_eligible = observation_eligible and contract_matches_registry and path_set_matches_contract
    return {
        "track_id": plan["track_id"],
        "purpose": plan["purpose"],
        "evaluator_type": str(plan["evaluator_type"]),
        "candidate_batch_id": candidate_batch["batch_id"],
        "candidate_batch_path": plan["candidate_batch_path"],
        "candidate_batch_sha256": plan["candidate_batch_sha256"],
        "historical_report_path": plan["historical_report_path"],
        "historical_report_sha256": plan["historical_report_sha256"],
        "activation_date_utc": plan["activation_date_utc"],
        "promotion_eligible": bool(plan.get("promotion_eligible", False)),
        "selection_feedback_allowed": False,
        "track_contract": track_contract,
        "track_contract_sha256": contract_sha256,
        "declared_track_contract_sha256": declared_contract_sha256,
        "contract_matches_registry": contract_matches_registry,
        "path_set_matches_contract": path_set_matches_contract,
        "operational_evidence_eligible": operational_eligible,
        "formal_promotion_evidence_eligible": operational_eligible and bool(plan.get("promotion_eligible", False)),
        "path_count": 1,
        "median_eligible_assets": float(eligibility.loc[expected_bar].sum()),
        "paths": [path],
        "note": "Formal evidence concerns the frozen factor relation only; perpetual execution remains unaudited.",
    }


def _position_changes(weights: pd.DataFrame, day_index: pd.DatetimeIndex) -> list[dict[str, Any]]:
    prior = weights.shift(1)
    changed = weights.sub(prior).abs().sum(axis=1).fillna(weights.abs().sum(axis=1)) > 1e-12
    rows = []
    for timestamp in day_index[changed.reindex(day_index).fillna(False)]:
        values = weights.loc[timestamp]
        rows.append(
            {
                "timestamp_utc": timestamp.isoformat(),
                "weights": {
                    str(asset): float(value)
                    for asset, value in values.items()
                    if np.isfinite(value) and abs(float(value)) > 1e-12
                },
            }
        )
    return rows


def _path_observation(
    factor: pd.DataFrame,
    returns: pd.DataFrame,
    funding: pd.DataFrame,
    *,
    day_index: pd.DatetimeIndex,
    min_assets: int,
    weighting_mode: str,
    rebalance_hours: int,
) -> dict[str, Any]:
    weights = factor_research._held_weights(factor, min_assets, rebalance_hours, weighting_mode)
    weights = weights.reindex(returns.index).fillna(0.0)
    turnover = weights.diff().abs().sum(axis=1).fillna(weights.abs().sum(axis=1))
    raw_returns = returns.reindex(weights.index)
    positioned_missing = raw_returns.isna() & weights.abs().gt(1e-12)
    missing_exposure = weights.abs().where(positioned_missing, 0.0).sum(axis=1)
    gross = (weights * raw_returns.fillna(0.0)).sum(axis=1)
    raw_funding = funding.reindex(weights.index)
    funding_interval = int(getattr(config, "FUNDING_INTERVAL", 8))
    expected_funding_event = pd.Series(
        weights.index.hour % funding_interval == 0,
        index=weights.index,
    )
    expected_funding_mask = pd.DataFrame(
        np.broadcast_to(expected_funding_event.to_numpy()[:, None], raw_funding.shape),
        index=raw_funding.index,
        columns=raw_funding.columns,
    )
    positioned_missing_funding = (
        raw_funding.isna()
        & weights.abs().gt(1e-12)
        & expected_funding_mask
    )
    funding_paid = (weights * raw_funding.fillna(0.0)).sum(axis=1)
    transaction_cost = turnover * (config.COST_BPS + config.SLIPPAGE_BPS) / 10000.0
    net = (gross - transaction_cost - funding_paid).fillna(0.0)
    exposure = weights.abs().sum(axis=1)

    observed_index = day_index.intersection(weights.index)
    hourly = []
    for timestamp in observed_index:
        hourly.append(
            {
                "timestamp_utc": timestamp.isoformat(),
                "gross_return": float(gross.loc[timestamp]),
                "transaction_cost": float(transaction_cost.loc[timestamp]),
                "funding_paid": float(funding_paid.loc[timestamp]),
                "net_return": float(net.loc[timestamp]),
                "turnover": float(turnover.loc[timestamp]),
                "gross_exposure": float(exposure.loc[timestamp]),
                "weighted_missing_return_exposure": float(missing_exposure.loc[timestamp]),
            }
        )
    active_bars = int((exposure.reindex(observed_index) > 0).sum())
    day_missing_exposure = missing_exposure.reindex(observed_index).fillna(0.0)
    day_missing_funding = positioned_missing_funding.reindex(observed_index).fillna(False)
    missing_funding_exposure = weights.abs().where(day_missing_funding, 0.0).sum(axis=1).reindex(observed_index).fillna(0.0)
    required_active_bars = 24
    observation_eligible = (
        len(observed_index) == 24
        and active_bars == required_active_bars
        and float(day_missing_exposure.max()) == 0.0
        and not bool(day_missing_funding.any().any())
    )
    return {
        "weighting_mode": weighting_mode,
        "required_min_assets": int(min_assets),
        "hour_count": len(observed_index),
        "active_bars": active_bars,
        "required_active_bars": required_active_bars,
        "observation_eligible": observation_eligible,
        "daily_net_return": float(net.reindex(observed_index).sum()),
        "daily_gross_return": float(gross.reindex(observed_index).sum()),
        "daily_transaction_cost": float(transaction_cost.reindex(observed_index).sum()),
        "daily_funding_paid": float(funding_paid.reindex(observed_index).sum()),
        "daily_turnover": float(turnover.reindex(observed_index).sum()),
        "missing_return_hours_while_held": int((day_missing_exposure > 0).sum()),
        "weighted_missing_return_exposure_sum": float(day_missing_exposure.sum()),
        "weighted_missing_return_exposure_max": float(day_missing_exposure.max()) if len(day_missing_exposure) else 0.0,
        "return_evidence_complete_while_held": bool(float(day_missing_exposure.max()) == 0.0) if len(day_missing_exposure) else False,
        "missing_expected_funding_asset_bars_while_held": int(day_missing_funding.sum().sum()),
        "missing_expected_funding_hours_while_held": int(day_missing_funding.any(axis=1).sum()),
        "weighted_missing_expected_funding_exposure_sum": float(missing_funding_exposure.sum()),
        "funding_evidence_complete_while_held": bool(not day_missing_funding.any().any()),
        "hourly": hourly,
        "position_changes": _position_changes(weights, observed_index),
    }


def build_plan_evidence(
    panel: dict[str, dict[str, Any]],
    *,
    plan: dict[str, Any],
    candidates: list[dict[str, Any]],
    candidate_batch: dict[str, Any],
    as_of: pd.Timestamp,
    universe_registry: dict[str, Any],
    track_contract: dict[str, Any],
) -> dict[str, Any]:
    if plan.get("evaluator_type") in LOW_VOL_EVALUATOR_TYPES:
        return _build_monthly_low_vol_plan_evidence(
            panel,
            plan=plan,
            candidates=candidates,
            candidate_batch=candidate_batch,
            as_of=as_of,
            universe_registry=universe_registry,
            track_contract=track_contract,
        )
    baseline_names = set(plan.get("baseline_factor_names") or factor_research.BASELINE_FACTOR_NAMES)
    unknown_baselines = baseline_names - set(factor_research.BASELINE_FACTOR_NAMES)
    if unknown_baselines:
        raise ValueError(f"unknown_tracking_baselines:{sorted(unknown_baselines)}")
    matrices = factor_research._build_matrices(
        _truncate_panel(panel, as_of),
        candidate_definitions=candidates,
        universe_registry=universe_registry,
        requested_factor_names=baseline_names,
    )
    day_start = as_of.normalize()
    day_index = pd.date_range(day_start, as_of, freq="h", tz="UTC")
    paths = []
    large_top_n = min(8, int(matrices["universe"]["rules"]["target_size"]))
    for factor_name, factor in matrices["factors"].items():
        definition = matrices["factor_definitions"][factor_name]
        min_assets = int(getattr(config, "PANEL_MIN_ASSETS", 20))
        if str(definition.get("bucket_policy") or "none") == "large_liquid_only":
            min_assets = min(min_assets, large_top_n)
        for weighting_mode in definition.get("weighting_modes", factor_research.WEIGHTING_MODES):
            observation = _path_observation(
                factor,
                matrices["returns"],
                matrices["funding_cost"],
                day_index=day_index,
                min_assets=min_assets,
                weighting_mode=weighting_mode,
                rebalance_hours=int(plan.get("rebalance_hours", getattr(config, "PANEL_REBALANCE_HOURS", 24))),
            )
            paths.append(
                {
                    "path_id": f"{factor_name}__{weighting_mode}",
                    "factor_name": factor_name,
                    "candidate_id": definition.get("candidate_id"),
                    "panel_formula": definition.get("panel_formula") or factor_name,
                    "source_ids": definition.get("source_ids", []),
                    **observation,
                }
            )

    eligible_count = matrices["eligibility"].reindex(day_index).sum(axis=1)
    actual_path_ids = sorted(str(path["path_id"]) for path in paths)
    contract_sha256 = payload_sha256(track_contract)
    declared_contract_sha256 = str(plan.get("track_contract_sha256") or "")
    contract_matches_registry = bool(declared_contract_sha256) and contract_sha256 == declared_contract_sha256
    path_set_matches_contract = actual_path_ids == list(track_contract["expected_path_ids"])
    operational_eligible = (
        bool(paths)
        and contract_matches_registry
        and path_set_matches_contract
        and all(path["observation_eligible"] for path in paths)
    )
    return {
        "track_id": plan["track_id"],
        "purpose": plan["purpose"],
        "candidate_batch_id": candidate_batch["batch_id"],
        "candidate_batch_path": plan["candidate_batch_path"],
        "candidate_batch_sha256": plan["candidate_batch_sha256"],
        "activation_date_utc": plan["activation_date_utc"],
        "promotion_eligible": bool(plan.get("promotion_eligible", False)),
        "selection_feedback_allowed": False,
        "track_contract": track_contract,
        "track_contract_sha256": contract_sha256,
        "declared_track_contract_sha256": declared_contract_sha256,
        "contract_matches_registry": contract_matches_registry,
        "path_set_matches_contract": path_set_matches_contract,
        "operational_evidence_eligible": operational_eligible,
        "formal_promotion_evidence_eligible": operational_eligible and bool(plan.get("promotion_eligible", False)),
        "path_count": len(paths),
        "median_eligible_assets": float(eligible_count.median()) if len(eligible_count) else 0.0,
        "paths": paths,
    }


def build_snapshot(
    panel: dict[str, dict[str, Any]],
    *,
    tracking_registry: dict[str, Any],
    plan_inputs: list[tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]],
    as_of: Any,
    captured_at: Any,
    universe_registry: dict[str, Any],
    tracking_registry_sha256: str,
    evaluator_code_sha256: str,
    evaluator_bundle_fingerprint: dict[str, Any] | None = None,
    low_vol_evaluator_fingerprint: dict[str, Any] | None = None,
    universe_registry_sha256: str = "",
) -> dict[str, Any]:
    as_of = _as_utc(as_of)
    captured_at = _as_utc(captured_at)
    expected_day_end = as_of.normalize() + pd.Timedelta(hours=23)
    day_complete = as_of == expected_day_end
    plans = []
    for plan, candidates, batch in plan_inputs:
        track_contract = build_track_contract(
            plan,
            candidates,
            batch,
            universe_registry=universe_registry,
            universe_registry_sha256=universe_registry_sha256,
            evaluator_bundle_fingerprint=evaluator_bundle_fingerprint,
            low_vol_evaluator_fingerprint=low_vol_evaluator_fingerprint,
        )
        plans.append(
            build_plan_evidence(
                panel,
                plan=plan,
                candidates=candidates,
                candidate_batch=batch,
                as_of=as_of,
                universe_registry=universe_registry,
                track_contract=track_contract,
            )
        )
    return {
        "schema_version": 1,
        "snapshot_type": "prospective_panel_factor_shadow_returns",
        "snapshot_date_utc": as_of.date().isoformat(),
        "captured_at_utc": captured_at.isoformat(),
        "as_of_bar_utc": as_of.isoformat(),
        "expected_day_end_bar_utc": expected_day_end.isoformat(),
        "day_complete": day_complete,
        "operational_evidence_eligible": bool(plans) and day_complete and all(
            plan["operational_evidence_eligible"] for plan in plans
        ),
        "formal_evidence_eligible": bool(plans) and day_complete and all(
            plan["formal_promotion_evidence_eligible"] for plan in plans
        ),
        "selection_feedback_allowed": False,
        "holdout_feedback_allowed": False,
        "universe_registry_id": universe_registry["registry_id"],
        "tracking_registry_id": tracking_registry["tracking_registry_id"],
        "tracking_registry_sha256": tracking_registry_sha256,
        "evaluator_code_sha256": evaluator_code_sha256,
        "evaluator_bundle_fingerprint": evaluator_bundle_fingerprint,
        "low_vol_evaluator_fingerprint": low_vol_evaluator_fingerprint,
        "active_plan_count": len(plans),
        "plans": plans,
        "note": "Frozen shadow paths only. These observations are never fed back into candidate generation.",
    }


def low_vol_evaluator_fingerprint() -> dict[str, Any]:
    """Hash only behavior that can change the frozen low-volatility evidence."""
    return callable_bundle_fingerprint(
        {
            "snapshot._load_low_vol_plan_candidates": _load_low_vol_plan_candidates,
            "snapshot.collect_daily_spot_tracking_panel": collect_daily_spot_tracking_panel,
            "snapshot.low_vol_cache_refresh_enabled": low_vol_cache_refresh_enabled,
            "snapshot._build_low_vol_track_contract": _build_low_vol_track_contract,
            "snapshot._build_monthly_low_vol_plan_evidence": _build_monthly_low_vol_plan_evidence,
            "data._instrument_cache_path": data_module._instrument_cache_path,
            "data._spot_cache_path": data_module._spot_cache_path,
            "data.swap_to_spot_inst_id": data_module.swap_to_spot_inst_id,
            "data.load_instruments": data_module.load_instruments,
            "data.load_spot_data": data_module.load_spot_data,
            "data._request_with_retries": data_module._request_with_retries,
            "data.fetch_okx_candles": data_module.fetch_okx_candles,
            "data._candles_to_df": data_module._candles_to_df,
            "data.refresh_ohlcv_cache_incremental": data_module.refresh_ohlcv_cache_incremental,
            "universe.registry_inst_ids": panel_universe.registry_inst_ids,
            "universe.registry_asset_map": panel_universe.registry_asset_map,
            "universe._bar_hours": panel_universe._bar_hours,
            "universe._listing_timestamp": panel_universe._listing_timestamp,
            "universe.top_n_mask": panel_universe.top_n_mask,
            "universe.build_point_in_time_eligibility": panel_universe.build_point_in_time_eligibility,
            "literature._month_end_formation_times": literature_replication._month_end_formation_times,
            "literature._trailing_low_vol_signal": literature_replication._trailing_low_vol_signal,
            "literature._quintile_long_short_weights": literature_replication._quintile_long_short_weights,
            "literature._execute_monthly_targets": literature_replication._execute_monthly_targets,
        }
    )


def write_snapshot_immutable(payload: dict[str, Any], *, snapshot_dir: Path | str = SNAPSHOT_DIR) -> tuple[Path, bool]:
    out_dir = Path(snapshot_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{payload['snapshot_date_utc']}.json"
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        manifest_path = out_dir / "manifest.jsonl"
        rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()] if manifest_path.exists() else []
        matches = [row for row in rows if row.get("snapshot_date_utc") == payload["snapshot_date_utc"]]
        if not matches or matches[-1].get("sha256") != payload_sha256(existing):
            raise ValueError(f"factor_snapshot_manifest_integrity_failed:{path}")
        if snapshot_evidence_sha256(existing) != snapshot_evidence_sha256(payload):
            conflict = {
                "detected_at_utc": _utc_now().isoformat(),
                "snapshot_date_utc": payload["snapshot_date_utc"],
                "existing_payload_sha256": payload_sha256(existing),
                "new_payload_sha256": payload_sha256(payload),
                "existing_evidence_sha256": snapshot_evidence_sha256(existing),
                "new_evidence_sha256": snapshot_evidence_sha256(payload),
                "status": "recompute_conflict",
            }
            with (out_dir / "conflicts.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(conflict, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            raise ValueError(f"factor_snapshot_recompute_conflict:{path}")
        return path, False
    with os.fdopen(fd, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    manifest = {
        "snapshot_date_utc": payload["snapshot_date_utc"],
        "as_of_bar_utc": payload["as_of_bar_utc"],
        "tracking_registry_id": payload["tracking_registry_id"],
        "active_plan_count": payload["active_plan_count"],
        "formal_evidence_eligible": payload["formal_evidence_eligible"],
        "path": str(path),
        "sha256": payload_sha256(payload),
    }
    with (out_dir / "manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path, True


def append_run_event(snapshot_dir: Path | str, event: dict[str, Any]) -> None:
    out_dir = Path(snapshot_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", help="UTC timestamp; defaults to the last fully closed hourly bar")
    parser.add_argument("--days", type=int, default=getattr(config, "PANEL_HISTORY_DAYS", 730))
    parser.add_argument("--tracking-registry", default=str(TRACKING_REGISTRY_PATH))
    parser.add_argument("--snapshot-dir", default=str(SNAPSHOT_DIR))
    args = parser.parse_args()

    captured_at = _utc_now()
    as_of = _as_utc(args.as_of) if args.as_of else captured_at.floor("h") - pd.Timedelta(hours=1)
    tracking_path = Path(args.tracking_registry)
    tracking_registry = load_tracking_registry(tracking_path)
    universe_registry = panel_universe.load_registry()
    plans = active_plans(tracking_registry, as_of)
    plan_inputs = []
    try:
        for plan in plans:
            candidates, batch = load_plan_candidates(plan)
            plan_inputs.append((plan, candidates, batch))
        panel = {}
        failures = []
        standard_inputs = [item for item in plan_inputs if item[0].get("evaluator_type") not in LOW_VOL_EVALUATOR_TYPES]
        low_vol_inputs = [item for item in plan_inputs if item[0].get("evaluator_type") in LOW_VOL_EVALUATOR_TYPES]
        if standard_inputs:
            standard_panel, standard_failures = factor_research._load_panel(
                panel_universe.registry_inst_ids(universe_registry),
                args.days,
                force_refresh=False,
            )
            panel.update(standard_panel)
            failures.extend(standard_failures)
        if low_vol_inputs:
            daily_specs = {
                (
                    str(item[2]["frozen_implementation"]["bar"]),
                    int(item[2]["frozen_implementation"]["history_days"]),
                )
                for item in low_vol_inputs
            }
            if len(daily_specs) != 1:
                raise ValueError(f"incompatible_low_vol_daily_specs:{sorted(daily_specs)}")
            daily_bar, daily_days = next(iter(daily_specs))
            daily_panel, daily_failures = collect_daily_spot_tracking_panel(
                universe_registry,
                bar=daily_bar,
                days=daily_days,
                refresh=low_vol_cache_refresh_enabled(),
            )
            for inst_id, item in daily_panel.items():
                panel.setdefault(inst_id, {}).update(item)
            failures.extend(daily_failures)
        if failures:
            raise ValueError(f"panel_load_failures:{json.dumps(failures, sort_keys=True)}")
        payload = build_snapshot(
            panel,
            tracking_registry=tracking_registry,
            plan_inputs=plan_inputs,
            as_of=as_of,
            captured_at=captured_at,
            universe_registry=universe_registry,
            tracking_registry_sha256=file_sha256(tracking_path),
            evaluator_code_sha256=file_sha256(Path(factor_research.__file__)),
            evaluator_bundle_fingerprint=file_bundle_fingerprint(
                [
                    Path(__file__),
                    Path(factor_research.__file__),
                    Path(literature_replication.__file__),
                    Path(data_module.__file__),
                    Path(panel_universe.__file__),
                    Path(candidate_registry.__file__),
                    Path(config.__file__),
                    Path(config.PANEL_UNIVERSE_REGISTRY),
                    PROMOTION_POLICY_PATH,
                    Path("prospective_evidence_readiness.py"),
                ]
            ),
            low_vol_evaluator_fingerprint=low_vol_evaluator_fingerprint(),
            universe_registry_sha256=file_sha256(config.PANEL_UNIVERSE_REGISTRY),
        )
        path, created = write_snapshot_immutable(payload, snapshot_dir=args.snapshot_dir)
        append_run_event(
            args.snapshot_dir,
            {
                "captured_at_utc": captured_at.isoformat(),
                "as_of_bar_utc": as_of.isoformat(),
                "status": "created" if created else "already_exists",
                "snapshot_path": str(path),
                "active_plan_count": len(plans),
            },
        )
        print("FACTOR_SNAPSHOT", "CREATED" if created else "EXISTS", path, "ACTIVE_PLANS", len(plans))
        return 0
    except Exception as exc:
        append_run_event(
            args.snapshot_dir,
            {
                "captured_at_utc": captured_at.isoformat(),
                "as_of_bar_utc": as_of.isoformat(),
                "status": "failed",
                "error": str(exc),
            },
        )
        print("FACTOR_SNAPSHOT FAILED", str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
