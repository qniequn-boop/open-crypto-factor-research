"""Audit whether prospective panel evidence is mature enough for re-evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import config
import panel_universe


SNAPSHOT_DIR = Path("prospective_snapshots")
FACTOR_SNAPSHOT_DIR = Path("prospective_factor_snapshots")
TRACKING_REGISTRY_PATH = Path("PROSPECTIVE_FACTOR_TRACKING_REGISTRY.json")
PROMOTION_POLICY_PATH = Path("PROSPECTIVE_FACTOR_PROMOTION_POLICY_V1.json")
LOG_DIR = Path(config.LOG_DIR)
STAGES = {
    "operational_observation": {"min_days": 30, "min_coverage": 0.95},
    "non_promotional_reaudit": {"min_days": 90, "min_coverage": 0.98},
    "formal_promotion_audit": {"min_days": 365, "min_coverage": 0.99},
}


def load_promotion_policy(path: Path | str = PROMOTION_POLICY_PATH) -> dict[str, Any]:
    policy_path = Path(path)
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not payload.get("policy_id"):
        raise ValueError("invalid_prospective_promotion_policy")
    stages = payload.get("readiness_stages")
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        raise ValueError("invalid_prospective_readiness_stages")
    for name, stage in stages.items():
        if int(stage.get("min_days", 0)) <= 0:
            raise ValueError(f"invalid_prospective_min_days:{name}")
        coverage = float(stage.get("min_coverage", 0.0))
        if not 0.0 < coverage <= 1.0:
            raise ValueError(f"invalid_prospective_min_coverage:{name}")
    return payload


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _payload_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _freshness_hours(created_at: Any, now_utc: datetime) -> float | None:
    try:
        parsed = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max((now_utc - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0, 0.0)


def _factor_shadow_summary(
    *,
    snapshot_dir: Path,
    tracking_registry: dict[str, Any],
    now_utc: datetime,
    eligible_universe_dates: set[date],
) -> dict[str, Any]:
    manifest_rows = _read_jsonl(snapshot_dir / "manifest.jsonl")
    integrity_errors: list[str] = []
    seen_dates: set[str] = set()
    operational_dates: dict[str, set[date]] = {}
    formal_dates: dict[str, set[date]] = {}
    loaded_rows = 0
    expected_registry_id = str(tracking_registry.get("tracking_registry_id") or "")
    registered_plans = {
        str(plan.get("track_id")): plan
        for plan in tracking_registry.get("plans") or []
    }
    active_plans = {
        track_id: plan
        for track_id, plan in registered_plans.items()
        if plan.get("status") == "active"
    }
    ignored_inactive_plan_rows = 0
    for manifest in manifest_rows:
        date_text = str(manifest.get("snapshot_date_utc") or "")
        if date_text in seen_dates:
            integrity_errors.append(f"duplicate_factor_manifest_date:{date_text}")
        seen_dates.add(date_text)
        declared_path = Path(str(manifest.get("path") or ""))
        snapshot_path = declared_path if declared_path.is_absolute() else snapshot_dir.parent / declared_path
        if not snapshot_path.exists():
            fallback = snapshot_dir / f"{date_text}.json"
            snapshot_path = fallback if fallback.exists() else snapshot_path
        if not snapshot_path.exists():
            integrity_errors.append(f"missing_factor_snapshot:{date_text}")
            continue
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            integrity_errors.append(f"invalid_factor_snapshot_json:{date_text}")
            continue
        if _payload_sha256(payload) != str(manifest.get("sha256") or ""):
            integrity_errors.append(f"factor_sha256_mismatch:{date_text}")
        if str(payload.get("tracking_registry_id") or "") != expected_registry_id:
            integrity_errors.append(f"factor_tracking_registry_mismatch:{date_text}")
        parsed_date = _parse_date(date_text)
        if parsed_date is None:
            integrity_errors.append(f"invalid_factor_snapshot_date:{date_text}")
            continue
        loaded_rows += 1
        day_complete = bool(payload.get("day_complete"))
        for plan in payload.get("plans") or []:
            track_id = str(plan.get("track_id") or "")
            registered_plan = registered_plans.get(track_id)
            plan_valid = True
            if registered_plan is None:
                integrity_errors.append(f"unknown_registered_factor_track:{date_text}:{track_id}")
                continue
            if track_id not in active_plans:
                ignored_inactive_plan_rows += 1
                continue
            expected_contract_sha256 = str(registered_plan.get("track_contract_sha256") or "")
            contract = plan.get("track_contract")
            actual_contract_sha256 = _payload_sha256(contract) if isinstance(contract, dict) else ""
            declared_contract_sha256 = str(plan.get("track_contract_sha256") or "")
            if not expected_contract_sha256:
                integrity_errors.append(f"missing_registered_track_contract:{date_text}:{track_id}")
                plan_valid = False
            if actual_contract_sha256 != expected_contract_sha256:
                integrity_errors.append(f"factor_track_contract_mismatch:{date_text}:{track_id}")
                plan_valid = False
            if declared_contract_sha256 != expected_contract_sha256:
                integrity_errors.append(f"factor_declared_contract_mismatch:{date_text}:{track_id}")
                plan_valid = False
            if not bool(plan.get("contract_matches_registry")):
                integrity_errors.append(f"factor_contract_match_flag_false:{date_text}:{track_id}")
                plan_valid = False
            paths = plan.get("paths") or []
            actual_path_ids = [str(path.get("path_id") or "") for path in paths]
            expected_path_ids = list(contract.get("expected_path_ids") or []) if isinstance(contract, dict) else []
            if sorted(actual_path_ids) != expected_path_ids or len(actual_path_ids) != len(set(actual_path_ids)):
                integrity_errors.append(f"factor_path_set_mismatch:{date_text}:{track_id}")
                plan_valid = False
            if int(plan.get("path_count") or 0) != len(expected_path_ids):
                integrity_errors.append(f"factor_path_count_mismatch:{date_text}:{track_id}")
                plan_valid = False
            if not bool(plan.get("path_set_matches_contract")):
                integrity_errors.append(f"factor_path_match_flag_false:{date_text}:{track_id}")
                plan_valid = False
            paired_universe_day = parsed_date in eligible_universe_dates
            if not paired_universe_day:
                integrity_errors.append(f"unpaired_factor_universe_date:{date_text}:{track_id}")
                plan_valid = False
            path_complete = bool(paths) and all(bool(path.get("observation_eligible")) for path in paths)
            operational = (
                plan_valid
                and day_complete
                and path_complete
                and bool(plan.get("operational_evidence_eligible"))
            )
            formal = operational and bool(plan.get("formal_promotion_evidence_eligible"))
            if operational:
                operational_dates.setdefault(track_id, set()).add(parsed_date)
            if formal:
                formal_dates.setdefault(track_id, set()).add(parsed_date)

    def track_stats(track_id: str, dates: set[date]) -> dict[str, Any]:
        ordered = sorted(dates)
        span = (ordered[-1] - ordered[0]).days + 1 if ordered else 0
        latest_age = (now_utc.date() - ordered[-1]).days if ordered else None
        return {
            "day_count": len(ordered),
            "first_date": ordered[0].isoformat() if ordered else None,
            "latest_date": ordered[-1].isoformat() if ordered else None,
            "calendar_span_days": span,
            "calendar_coverage": float(len(ordered) / span) if span else 0.0,
            "latest_age_days": latest_age,
        }

    tracks = {}
    for track_id, plan in active_plans.items():
        tracks[track_id] = {
            "promotion_eligible": bool(plan.get("promotion_eligible")),
            "track_contract_sha256": str(plan.get("track_contract_sha256") or ""),
            "operational": track_stats(track_id, operational_dates.get(track_id, set())),
            "formal": track_stats(track_id, formal_dates.get(track_id, set())),
        }
    return {
        "tracking_registry_id": expected_registry_id,
        "manifest_rows": len(manifest_rows),
        "snapshot_rows_loaded": loaded_rows,
        "integrity_ok": not integrity_errors,
        "integrity_errors": integrity_errors,
        "active_track_count": len(active_plans),
        "promotion_eligible_active_track_count": sum(bool(plan.get("promotion_eligible")) for plan in active_plans.values()),
        "ignored_inactive_plan_rows": ignored_inactive_plan_rows,
        "tracks": tracks,
    }


def build_readiness_report(
    *,
    snapshot_dir: Path | str = SNAPSHOT_DIR,
    data_update_path: Path | str | None = None,
    now_utc: datetime | None = None,
    registry: dict[str, Any] | None = None,
    factor_snapshot_dir: Path | str | None = None,
    tracking_registry: dict[str, Any] | None = None,
    promotion_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot_dir = Path(snapshot_dir)
    now_utc = now_utc or datetime.now(timezone.utc)
    registry = registry or panel_universe.load_registry()
    registry_id = str(registry["registry_id"])
    min_assets = int(getattr(config, "PANEL_MIN_ASSETS", 20))
    manifest_rows = _read_jsonl(snapshot_dir / "manifest.jsonl")

    integrity_errors: list[str] = []
    snapshot_rows = []
    seen_dates: set[str] = set()
    for manifest in manifest_rows:
        date_text = str(manifest.get("snapshot_date_utc") or "")
        if date_text in seen_dates:
            integrity_errors.append(f"duplicate_manifest_date:{date_text}")
        seen_dates.add(date_text)
        declared_path = Path(str(manifest.get("path") or ""))
        snapshot_path = declared_path if declared_path.is_absolute() else snapshot_dir.parent / declared_path
        if not snapshot_path.exists():
            fallback = snapshot_dir / f"{date_text}.json"
            snapshot_path = fallback if fallback.exists() else snapshot_path
        if not snapshot_path.exists():
            integrity_errors.append(f"missing_snapshot:{date_text}")
            continue
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            integrity_errors.append(f"invalid_snapshot_json:{date_text}")
            continue
        actual_hash = _payload_sha256(payload)
        if actual_hash != str(manifest.get("sha256") or ""):
            integrity_errors.append(f"sha256_mismatch:{date_text}")
        snapshot_registry = str(payload.get("registry_id") or manifest.get("registry_id") or "")
        if snapshot_registry != registry_id:
            integrity_errors.append(f"registry_mismatch:{date_text}:{snapshot_registry}")
        eligible_count = int(payload.get("eligible_count") or 0)
        formal = bool(payload.get("formal_evidence_eligible")) and bool(payload.get("day_complete"))
        if formal and eligible_count < min_assets:
            integrity_errors.append(f"formal_snapshot_breadth_below_minimum:{date_text}:{eligible_count}")
        snapshot_rows.append(
            {
                "snapshot_date_utc": date_text,
                "as_of_bar_utc": payload.get("as_of_bar_utc"),
                "eligible_count": eligible_count,
                "day_complete": bool(payload.get("day_complete")),
                "formal_evidence_eligible": formal,
                "sha256": actual_hash,
            }
        )

    formal_dates = sorted(
        parsed
        for row in snapshot_rows
        if row["formal_evidence_eligible"]
        for parsed in [_parse_date(row["snapshot_date_utc"])]
        if parsed is not None
    )
    formal_count = len(formal_dates)
    span_days = (formal_dates[-1] - formal_dates[0]).days + 1 if formal_dates else 0
    coverage = formal_count / span_days if span_days else 0.0
    latest_age_days = (now_utc.date() - formal_dates[-1]).days if formal_dates else None
    latest_fresh = latest_age_days is not None and latest_age_days <= 2

    update = None
    if data_update_path and Path(data_update_path).exists():
        update = json.loads(Path(data_update_path).read_text(encoding="utf-8"))
    update_age_hours = _freshness_hours((update or {}).get("created_at_utc"), now_utc) if update else None
    update_ok = bool(
        update
        and update.get("overall_status") == "pass"
        and str(update.get("registry_id")) == registry_id
        and int(update.get("failed_asset_count") or 0) == 0
        and update_age_hours is not None
        and update_age_hours <= 48.0
    )
    integrity_ok = not integrity_errors
    factor_summary = None
    if factor_snapshot_dir is not None:
        if tracking_registry is None:
            raise ValueError("tracking_registry_required_with_factor_snapshot_dir")
        factor_summary = _factor_shadow_summary(
            snapshot_dir=Path(factor_snapshot_dir),
            tracking_registry=tracking_registry,
            now_utc=now_utc,
            eligible_universe_dates=set(formal_dates),
        )

    stage_policy = (promotion_policy or {}).get("readiness_stages") or STAGES
    stage_results = {}
    for name, policy in stage_policy.items():
        blockers = []
        if formal_count < policy["min_days"]:
            blockers.append(f"formal_days:{formal_count}<{policy['min_days']}")
        if coverage < policy["min_coverage"]:
            blockers.append(f"calendar_coverage:{coverage:.4f}<{policy['min_coverage']:.4f}")
        if not latest_fresh:
            blockers.append("latest_formal_snapshot_stale_or_missing")
        if not update_ok:
            blockers.append("prospective_data_update_stale_or_failed")
        if not integrity_ok:
            blockers.append("snapshot_integrity_failed")
        if factor_summary is not None:
            if not factor_summary["integrity_ok"]:
                blockers.append("factor_snapshot_integrity_failed")
            tracks = factor_summary["tracks"]
            if not tracks:
                blockers.append("no_active_factor_tracking_plan")
            target_tracks = tracks
            evidence_key = "operational"
            if name == "formal_promotion_audit":
                target_tracks = {
                    track_id: row for track_id, row in tracks.items() if row["promotion_eligible"]
                }
                evidence_key = "formal"
                if not target_tracks:
                    blockers.append("no_promotion_eligible_factor_tracking_plan")
            for track_id, track in target_tracks.items():
                evidence = track[evidence_key]
                if evidence["day_count"] < policy["min_days"]:
                    blockers.append(f"factor_days:{track_id}:{evidence['day_count']}<{policy['min_days']}")
                if evidence["calendar_coverage"] < policy["min_coverage"]:
                    blockers.append(
                        f"factor_calendar_coverage:{track_id}:{evidence['calendar_coverage']:.4f}<{policy['min_coverage']:.4f}"
                    )
                if evidence["latest_age_days"] is None or evidence["latest_age_days"] > 2:
                    blockers.append(f"factor_latest_snapshot_stale_or_missing:{track_id}")
        stage_results[name] = {
            **policy,
            "ready": not blockers,
            "blockers": blockers,
        }

    if stage_results["formal_promotion_audit"]["ready"]:
        action = "formal_promotion_audit_allowed"
    elif stage_results["non_promotional_reaudit"]["ready"]:
        action = "non_promotional_reaudit_allowed"
    else:
        action = "collect_only"

    return {
        "created_at_utc": now_utc.isoformat(),
        "schema_version": 1,
        "audit_type": "prospective_evidence_readiness",
        "promotion_policy_id": (promotion_policy or {}).get("policy_id"),
        "registry_id": registry_id,
        "formal_evidence_start_utc": registry["construction"]["prospective_start_utc"],
        "snapshot_manifest_rows": len(manifest_rows),
        "snapshot_rows_loaded": len(snapshot_rows),
        "bootstrap_or_incomplete_snapshot_count": sum(not row["formal_evidence_eligible"] for row in snapshot_rows),
        "formal_complete_day_count": formal_count,
        "formal_first_date": formal_dates[0].isoformat() if formal_dates else None,
        "formal_latest_date": formal_dates[-1].isoformat() if formal_dates else None,
        "formal_calendar_span_days": span_days,
        "formal_calendar_coverage": float(coverage),
        "latest_formal_age_days": latest_age_days,
        "snapshot_integrity_ok": integrity_ok,
        "snapshot_integrity_errors": integrity_errors,
        "prospective_data_update_ok": update_ok,
        "prospective_data_update_age_hours": update_age_hours,
        "stages": stage_results,
        "automation_action": action,
        "automated_reaudit_allowed": stage_results["non_promotional_reaudit"]["ready"],
        "formal_promotion_audit_allowed": stage_results["formal_promotion_audit"]["ready"],
        "candidate_generation_allowed": False,
        "factor_shadow": factor_summary,
        "snapshots": snapshot_rows,
        "note": "Missing or incomplete days are preserved as missing and are never backfilled into formal evidence.",
    }


def write_readiness_report(
    *,
    snapshot_dir: Path | str = SNAPSHOT_DIR,
    data_update_path: Path | str | None = None,
    log_dir: Path | str = LOG_DIR,
    factor_snapshot_dir: Path | str | None = FACTOR_SNAPSHOT_DIR,
    tracking_registry_path: Path | str = TRACKING_REGISTRY_PATH,
    promotion_policy_path: Path | str = PROMOTION_POLICY_PATH,
) -> Path:
    tracking_registry = None
    if factor_snapshot_dir is not None:
        tracking_registry = json.loads(Path(tracking_registry_path).read_text(encoding="utf-8"))
    promotion_policy = load_promotion_policy(promotion_policy_path)
    policy_sha256 = hashlib.sha256(Path(promotion_policy_path).read_bytes()).hexdigest()
    for plan in (tracking_registry or {}).get("plans") or []:
        if plan.get("status") == "active" and bool(plan.get("promotion_eligible")):
            if str(plan.get("promotion_policy_id")) != str(promotion_policy["policy_id"]):
                raise ValueError(f"active_track_promotion_policy_id_mismatch:{plan.get('track_id')}")
            if str(plan.get("promotion_policy_sha256")) != policy_sha256:
                raise ValueError(f"active_track_promotion_policy_sha256_mismatch:{plan.get('track_id')}")
    report = build_readiness_report(
        snapshot_dir=snapshot_dir,
        data_update_path=data_update_path,
        factor_snapshot_dir=factor_snapshot_dir,
        tracking_registry=tracking_registry,
        promotion_policy=promotion_policy,
    )
    out_dir = Path(log_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    path = out_dir / f"prospective_evidence_readiness_{stamp}.json"
    text = json.dumps(report, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    (out_dir / "prospective_evidence_readiness_latest.json").write_text(text, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", default=str(SNAPSHOT_DIR))
    parser.add_argument("--data-update", default=str(LOG_DIR / "prospective_data_update_latest.json"))
    parser.add_argument("--factor-snapshot-dir", default=str(FACTOR_SNAPSHOT_DIR))
    parser.add_argument("--tracking-registry", default=str(TRACKING_REGISTRY_PATH))
    parser.add_argument("--promotion-policy", default=str(PROMOTION_POLICY_PATH))
    args = parser.parse_args()
    path = write_readiness_report(
        snapshot_dir=args.snapshot_dir,
        data_update_path=args.data_update,
        factor_snapshot_dir=args.factor_snapshot_dir,
        tracking_registry_path=args.tracking_registry,
        promotion_policy_path=args.promotion_policy,
    )
    report = json.loads(path.read_text(encoding="utf-8"))
    print(f"WROTE {path}")
    print(
        f"FORMAL_DAYS {report['formal_complete_day_count']} "
        f"COVERAGE {report['formal_calendar_coverage']:.4f} "
        f"ACTION {report['automation_action']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
