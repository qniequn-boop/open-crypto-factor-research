"""Candidate and trial registry helpers for panel factor research.

The panel factory deliberately separates three jobs:
1. literature sources constrain what AI can propose,
2. candidate batches freeze formulas before evaluation,
3. the trial registry counts every generated/rejected/evaluated attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config


REGISTRY_PATH = Path("LITERATURE_HYPOTHESIS_REGISTRY.md")
LOG_DIR = Path(config.LOG_DIR)
TRIAL_REGISTRY_PATH = LOG_DIR / "panel_trial_registry.jsonl"

AI_FEEDBACK_CHECK_ALLOWLIST = {
    "val_ic_positive",
    "val_long_short_positive",
    "turnover_reasonable",
    "is_not_opposite",
    "multiple_testing_pass",
    "deflated_sharpe_pass",
    "cscv_pbo_pass",
    "robust_large_liquid_val_ic_positive",
    "robust_bucket_val_not_single_bucket",
    "robust_family_neutral_val_ic_positive",
}

REQUIRED_CANDIDATE_FIELDS = {
    "candidate_id",
    "source_ids",
    "hypothesis",
    "family",
    "required_fields",
    "panel_formula",
    "direction",
    "neutralization",
    "bucket_policy",
    "weighting_modes",
    "generated_by",
}

ALLOWED_REQUIRED_FIELDS = {
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vol_quote",
    "funding_signal",
    "funding_cost",
    "spot_close",
    "basis",
    "liquidity_size",
    "realized_vol",
    "open_interest",
    "market_cap",
    "listing_age",
    "asset_label",
}

ALLOWED_DIRECTIONS = {"long", "short", "neutral"}
ALLOWED_NEUTRALIZATION = {"none", "liquidity_size", "liquidity_bucket"}
ALLOWED_BUCKET_POLICY = {"none", "liquidity_tercile", "large_liquid_only"}
ALLOWED_WEIGHTING_MODES = {"rank_linear", "top_bottom_30"}
_CANDIDATE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{3,96}$")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_literature_source_ids(path: Path | str = REGISTRY_PATH) -> set[str]:
    registry_path = Path(path)
    if not registry_path.exists():
        return set()
    ids = set()
    for line in registry_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- id:"):
            source_id = stripped.split(":", 1)[1].strip()
            if source_id:
                ids.add(source_id)
    return ids


def validate_candidate(
    candidate: dict[str, Any],
    *,
    literature_source_ids: set[str] | None = None,
    known_formulas: set[str] | None = None,
    allowed_weighting_modes: set[str] | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    missing = sorted(REQUIRED_CANDIDATE_FIELDS - set(candidate))
    if missing:
        errors.append("missing_fields:" + ",".join(missing))

    candidate_id = str(candidate.get("candidate_id", ""))
    if not _CANDIDATE_ID_RE.match(candidate_id):
        errors.append("invalid_candidate_id")

    source_ids = candidate.get("source_ids")
    if not isinstance(source_ids, list) or not source_ids:
        errors.append("source_ids_required")
    else:
        known_sources = literature_source_ids if literature_source_ids is not None else load_literature_source_ids()
        unknown = sorted(str(item) for item in source_ids if str(item) not in known_sources)
        if unknown:
            errors.append("unknown_source_ids:" + ",".join(unknown))

    required_fields = candidate.get("required_fields")
    if not isinstance(required_fields, list):
        errors.append("required_fields_must_be_list")
    else:
        unknown_fields = sorted(str(item) for item in required_fields if str(item) not in ALLOWED_REQUIRED_FIELDS)
        if unknown_fields:
            errors.append("unknown_required_fields:" + ",".join(unknown_fields))

    formula = candidate.get("panel_formula")
    if not isinstance(formula, str) or not formula:
        errors.append("panel_formula_required")
    elif known_formulas is not None and formula not in known_formulas:
        errors.append("unknown_panel_formula:" + formula)

    direction = str(candidate.get("direction", "")).lower()
    if direction not in ALLOWED_DIRECTIONS:
        errors.append("invalid_direction")

    neutralization = str(candidate.get("neutralization", "")).lower()
    if neutralization not in ALLOWED_NEUTRALIZATION:
        errors.append("invalid_neutralization")

    bucket_policy = str(candidate.get("bucket_policy", "")).lower()
    if bucket_policy not in ALLOWED_BUCKET_POLICY:
        errors.append("invalid_bucket_policy")

    weighting_modes = candidate.get("weighting_modes")
    allowed_modes = allowed_weighting_modes or ALLOWED_WEIGHTING_MODES
    if not isinstance(weighting_modes, list) or not weighting_modes:
        errors.append("weighting_modes_required")
    else:
        unknown_modes = sorted(str(item) for item in weighting_modes if str(item) not in allowed_modes)
        if unknown_modes:
            errors.append("unknown_weighting_modes:" + ",".join(unknown_modes))

    for text_field in ("hypothesis", "family", "generated_by"):
        if not str(candidate.get(text_field, "")).strip():
            errors.append(f"{text_field}_required")

    return not errors, errors


def normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(candidate)
    normalized["candidate_id"] = str(normalized["candidate_id"])
    normalized["source_ids"] = [str(item) for item in normalized["source_ids"]]
    normalized["required_fields"] = [str(item) for item in normalized["required_fields"]]
    normalized["panel_formula"] = str(normalized["panel_formula"])
    normalized["direction"] = str(normalized["direction"]).lower()
    normalized["neutralization"] = str(normalized["neutralization"]).lower()
    normalized["bucket_policy"] = str(normalized["bucket_policy"]).lower()
    normalized["weighting_modes"] = [str(item) for item in normalized["weighting_modes"]]
    normalized["generated_by"] = str(normalized["generated_by"])
    return normalized


def load_candidate_batch(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_candidate_batch(candidates: list[dict[str, Any]], *, log_dir: Path | str = LOG_DIR, batch_id: str | None = None) -> Path:
    out_dir = Path(log_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_id = batch_id or utc_stamp()
    payload = {
        "schema_version": 1,
        "batch_id": batch_id,
        "created_at_utc": utc_stamp(),
        "holdout_policy": "audit_only_not_visible_to_ai_generation",
        "candidates": candidates,
    }
    out_path = out_dir / f"panel_candidate_batch_{batch_id}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def append_trial_event(
    candidate: dict[str, Any],
    *,
    event: str,
    status: str,
    reason: str = "",
    batch_id: str | None = None,
    variant_count: int | None = None,
    log_dir: Path | str = LOG_DIR,
    registry_path: Path | str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out_dir = Path(log_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    modes = candidate.get("weighting_modes") if isinstance(candidate.get("weighting_modes"), list) else []
    candidate_payload = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    row = {
        "created_at_utc": utc_stamp(),
        "event": event,
        "status": status,
        "reason": reason,
        "batch_id": batch_id,
        "candidate_id": candidate.get("candidate_id"),
        "source_ids": candidate.get("source_ids", []),
        "family": candidate.get("family"),
        "panel_formula": candidate.get("panel_formula"),
        "direction": candidate.get("direction"),
        "neutralization": candidate.get("neutralization"),
        "bucket_policy": candidate.get("bucket_policy"),
        "required_fields": candidate.get("required_fields", []),
        "hypothesis": candidate.get("hypothesis"),
        "weighting_modes": modes,
        "variant_count": int(variant_count if variant_count is not None else max(len(modes), 1)),
        "generated_by": candidate.get("generated_by"),
        "candidate_signature": candidate_signature(candidate),
        "signal_signature": candidate_signal_signature(candidate),
        "candidate_payload_sha256": hashlib.sha256(candidate_payload.encode("utf-8")).hexdigest(),
    }
    if extra:
        row.update(extra)
    destination = Path(registry_path) if registry_path else out_dir / "panel_trial_registry.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _canonical_direction(value: Any) -> str:
    text = str(value).strip().lower()
    return {
        "1": "long",
        "+1": "long",
        "1.0": "long",
        "-1": "short",
        "-1.0": "short",
        "0": "neutral",
        "0.0": "neutral",
    }.get(text, text)


def candidate_signature(candidate: dict[str, Any], *, approximate: bool = False) -> str:
    source_ids = ",".join(sorted(str(item) for item in candidate.get("source_ids", [])))
    weighting_modes = ",".join(sorted(str(item) for item in candidate.get("weighting_modes", [])))
    parts = [source_ids, str(candidate.get("panel_formula", ""))]
    if approximate:
        return str(candidate.get("panel_formula", ""))
    parts.extend(
        [
            _canonical_direction(candidate.get("direction", "")),
            str(candidate.get("neutralization", "")).lower(),
            str(candidate.get("bucket_policy", "")).lower(),
            weighting_modes,
        ]
    )
    return "|".join(parts)


def candidate_signal_signature(candidate: dict[str, Any]) -> str:
    return "|".join(
        [
            str(candidate.get("panel_formula", "")),
            _canonical_direction(candidate.get("direction", "")),
            str(candidate.get("neutralization", "")).lower(),
            str(candidate.get("bucket_policy", "")).lower(),
        ]
    )


def complete_candidate_signal_signature(candidate: dict[str, Any]) -> str | None:
    required = (
        str(candidate.get("panel_formula") or "").strip(),
        _canonical_direction(candidate.get("direction", "")),
        str(candidate.get("neutralization") or "").strip().lower(),
        str(candidate.get("bucket_policy") or "").strip().lower(),
    )
    if not all(required):
        return None
    return "|".join(required)


def load_trial_rows(
    path: Path | str = TRIAL_REGISTRY_PATH,
    *,
    require_exists: bool = False,
) -> list[dict[str, Any]]:
    registry_path = Path(path)
    if not registry_path.exists():
        if require_exists:
            raise FileNotFoundError(f"trial_registry_missing:{registry_path}")
        return []
    rows = []
    for line_number, line in enumerate(registry_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"trial_registry_invalid_json_line:{line_number}:{registry_path}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"trial_registry_row_not_object:{line_number}:{registry_path}")
        rows.append(row)
    return rows


def rejected_candidate_ids(path: Path | str = TRIAL_REGISTRY_PATH) -> set[str]:
    rejected_statuses = {"rejected", "panel_factor_reject"}
    ids = set()
    for row in load_trial_rows(path):
        candidate_id = row.get("candidate_id")
        if candidate_id and str(row.get("status")) in rejected_statuses:
            ids.add(str(candidate_id))
    return ids


def historical_candidate_signatures(path: Path | str = TRIAL_REGISTRY_PATH) -> set[str]:
    signatures = set()
    for row in load_trial_rows(path):
        if str(row.get("status")) == "rejected":
            continue
        if row.get("candidate_signature"):
            signatures.add(str(row["candidate_signature"]))
        if row.get("source_ids") and row.get("panel_formula"):
            signatures.add(candidate_signature(row, approximate=True))
    return signatures


def historical_family_variant_counts(path: Path | str = TRIAL_REGISTRY_PATH) -> dict[str, int]:
    counts: dict[str, int] = {}
    by_candidate: dict[str, tuple[str, int]] = {}
    for row in load_trial_rows(path):
        candidate_id = row.get("candidate_id")
        family = row.get("family")
        if not candidate_id or not family:
            continue
        variants = int(row.get("variant_count") or 1)
        old_family, old_variants = by_candidate.get(str(candidate_id), (str(family), 0))
        by_candidate[str(candidate_id)] = (old_family, max(old_variants, variants))
    for family, variants in by_candidate.values():
        counts[family] = counts.get(family, 0) + variants
    return counts


def historical_source_variant_counts(path: Path | str = TRIAL_REGISTRY_PATH) -> dict[str, int]:
    """Count every unique proposed candidate against each cited source.

    Rejected and unevaluated candidates deliberately count. Repeated lifecycle
    events for one candidate count only its maximum registered variant count.
    """
    by_source_candidate: dict[tuple[str, str], int] = {}
    for row in load_trial_rows(path):
        candidate_id = str(row.get("candidate_id") or "")
        source_ids = row.get("source_ids")
        if not candidate_id or not isinstance(source_ids, list):
            continue
        variants = int(row.get("variant_count") or 1)
        for source_id in {str(item) for item in source_ids if str(item)}:
            key = (source_id, candidate_id)
            by_source_candidate[key] = max(by_source_candidate.get(key, 0), variants)
    counts: dict[str, int] = {}
    for (source_id, _), variants in by_source_candidate.items():
        counts[source_id] = counts.get(source_id, 0) + variants
    return counts


def trial_variant_count(path: Path | str = TRIAL_REGISTRY_PATH) -> int:
    registry_path = Path(path)
    if not registry_path.exists():
        return 0
    by_candidate: dict[str, int] = {}
    for row in load_trial_rows(registry_path):
        candidate_id = row.get("candidate_id")
        if not candidate_id:
            continue
        by_candidate[str(candidate_id)] = max(
            by_candidate.get(str(candidate_id), 0),
            int(row.get("variant_count") or 1),
        )
    return int(sum(by_candidate.values()))


def trial_count_breakdown(
    path: Path | str = TRIAL_REGISTRY_PATH,
    *,
    require_exists: bool = False,
) -> dict[str, Any]:
    by_candidate: dict[str, dict[str, Any]] = {}
    outcome_seen: dict[str, dict[str, Any]] = {}
    generated_accepted: set[str] = set()
    rows = load_trial_rows(path, require_exists=require_exists)
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            continue
        current = by_candidate.setdefault(
            candidate_id,
            {"variant_count": 0, "signal_signature": None, "event_count": 0},
        )
        current["variant_count"] = max(current["variant_count"], int(row.get("variant_count") or 1))
        current["event_count"] += 1
        signal_signature = complete_candidate_signal_signature(row)
        if signal_signature:
            previous_signature = current.get("signal_signature")
            if previous_signature and previous_signature != signal_signature:
                raise ValueError(f"trial_registry_candidate_identity_conflict:{candidate_id}")
            current["signal_signature"] = signal_signature
        if row.get("event") == "generated" and row.get("status") == "accepted":
            generated_accepted.add(candidate_id)
        if row.get("event") == "evaluated":
            seen = outcome_seen.setdefault(
                candidate_id,
                {"variant_count": 0, "family": str(row.get("family") or "unclassified")},
            )
            seen["variant_count"] = max(seen["variant_count"], int(row.get("variant_count") or 1))
            if row.get("family"):
                seen["family"] = str(row["family"])
    complete_signatures = {
        row["signal_signature"]
        for row in by_candidate.values()
        if row.get("signal_signature")
    }
    missing = sorted(
        candidate_id
        for candidate_id, row in by_candidate.items()
        if not row.get("signal_signature") or str(row["signal_signature"]).startswith("|||")
    )
    outcome_seen_by_family: dict[str, list[str]] = {}
    for candidate_id, row in outcome_seen.items():
        outcome_seen_by_family.setdefault(row["family"], []).append(candidate_id)
    outcome_seen_by_family = {
        family: sorted(candidate_ids)
        for family, candidate_ids in sorted(outcome_seen_by_family.items())
    }
    return {
        "candidate_id_trial_count": len(by_candidate),
        "portfolio_variant_trial_count": int(sum(row["variant_count"] for row in by_candidate.values())),
        "audit_registry_candidate_count": len(by_candidate),
        "audit_registry_portfolio_variant_count": int(sum(row["variant_count"] for row in by_candidate.values())),
        "outcome_seen_candidate_count": len(outcome_seen),
        "outcome_seen_portfolio_variant_count": int(sum(row["variant_count"] for row in outcome_seen.values())),
        "outcome_seen_candidate_ids": sorted(outcome_seen),
        "outcome_seen_candidate_ids_by_family": outcome_seen_by_family,
        "generated_accepted_not_evaluated_candidate_ids": sorted(generated_accepted - set(outcome_seen)),
        "unique_complete_signal_signature_count": len(complete_signatures),
        "candidate_ids_missing_complete_signature": missing,
        "metadata_complete": not missing,
        "counting_policy": {
            "audit_registry": "all logged candidate ids, including guardrail and syntax rejects",
            "statistical_multiplicity": "all registered candidate variants, including rejected and unevaluated attempts",
            "pbo_matrix": "actual contemporaneous return-path columns; reported by the evaluator",
        },
    }


def validate_trial_registry_for_candidates(
    candidates: list[dict[str, Any]],
    path: Path | str = TRIAL_REGISTRY_PATH,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = load_trial_rows(path, require_exists=bool(candidates))
    breakdown = trial_count_breakdown(path, require_exists=bool(candidates))
    if not candidates:
        return rows, breakdown

    rows_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        if candidate_id:
            rows_by_candidate.setdefault(candidate_id, []).append(row)

    failures = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        candidate_rows = rows_by_candidate.get(candidate_id, [])
        if not candidate_rows:
            failures.append(f"unregistered_candidate:{candidate_id}")
            continue
        admitted = any(
            row.get("event") in {"generated", "frozen"} and row.get("status") == "accepted"
            for row in candidate_rows
        )
        if not admitted:
            failures.append(f"candidate_missing_accepted_admission:{candidate_id}")
        expected_signature = candidate_signal_signature(candidate)
        observed_signatures = {
            signature
            for row in candidate_rows
            if (signature := complete_candidate_signal_signature(row)) is not None
        }
        if expected_signature not in observed_signatures:
            failures.append(f"candidate_identity_not_registered:{candidate_id}")
        registered_variants = max((int(row.get("variant_count") or 1) for row in candidate_rows), default=0)
        required_variants = max(len(candidate.get("weighting_modes") or []), 1)
        if registered_variants < required_variants:
            failures.append(f"candidate_variant_count_underregistered:{candidate_id}")
    if failures:
        raise ValueError("trial_registry_candidate_validation_failed:" + ",".join(sorted(failures)))
    return rows, breakdown


def _feedback_metric(row: dict[str, Any], section: str, field: str) -> float:
    value = ((row.get(section) or {}).get("Val") or {}).get(field)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("-inf")
    return number if math.isfinite(number) else float("-inf")


def _ai_feedback_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -_feedback_metric(row, "rank_ic", "mean_rank_ic"),
        -_feedback_metric(row, "long_short", "sharpe"),
        -_feedback_metric(row, "long_short", "total_return"),
        str(row.get("candidate_id") or row.get("factor_name") or row.get("name") or ""),
        str(row.get("name") or ""),
    )


def build_ai_generation_prompt(literature_registry_text: str, recent_panel_report: dict[str, Any] | None = None) -> str:
    lines = [
        "You generate preregistered multi-asset crypto panel factor candidates.",
        "Every candidate must cite source_ids from the literature registry.",
        "Do not generate full trading strategies; generate panel factor formulas only.",
        "Default research budget is at most 20 candidates per batch and 20 per mechanism family before freeze/review.",
        "The objective is a disciplined audit loop, not forcing a pass.",
        "Holdout is audit-only and is intentionally withheld from this prompt.",
        "",
        "=== Literature Registry ===",
        literature_registry_text,
    ]
    if recent_panel_report:
        lines.extend(["", "=== Prior IS/Val Feedback Only ==="])
        report_rows = list(recent_panel_report.get("factors", []))
        candidate_rows = sorted(
            (row for row in report_rows if row.get("candidate_id")),
            key=_ai_feedback_sort_key,
        )
        baseline_rows = sorted(
            (row for row in report_rows if not row.get("candidate_id")),
            key=_ai_feedback_sort_key,
        )
        feedback_rows = (candidate_rows + baseline_rows)[:12]
        for row in feedback_rows:
            val = (row.get("long_short") or {}).get("Val") or {}
            rank_ic = (row.get("rank_ic") or {}).get("Val") or {}
            failed_checks = sorted(
                str(item)
                for item in row.get("failed_checks", [])
                if str(item) in AI_FEEDBACK_CHECK_ALLOWLIST
            )
            val_ic = rank_ic.get("mean_rank_ic")
            val_sharpe = val.get("sharpe")
            val_total_return = val.get("total_return")
            val_clue = bool(
                val_ic is not None
                and val_sharpe is not None
                and float(val_ic) > 0.0
                and float(val_sharpe) > 0.0
                and (val_total_return is None or float(val_total_return) > 0.0)
            )
            lines.append(
                f"- {row.get('name')} selection_label={'val_clue' if val_clue else 'no_val_clue'} "
                f"ValIC={val_ic} ValSR={val_sharpe} ValReturn={val_total_return} "
                f"failed={failed_checks}"
            )
    lines.extend(
        [
            "",
            "Return JSON with a candidates array. Required fields:",
            ", ".join(sorted(REQUIRED_CANDIDATE_FIELDS)),
        ]
    )
    prompt = "\n".join(lines)
    return re.sub("holdout", "AuditSplit", prompt, flags=re.IGNORECASE)


def freeze_candidates_from_json(input_path: Path | str, *, log_dir: Path | str = LOG_DIR) -> Path:
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    candidates = payload.get("candidates", payload if isinstance(payload, list) else [])
    if not isinstance(candidates, list):
        raise ValueError("input JSON must be a candidate list or contain candidates")
    source_ids = load_literature_source_ids()
    accepted = []
    batch_id = utc_stamp()
    for candidate in candidates:
        ok, errors = validate_candidate(candidate, literature_source_ids=source_ids)
        if ok:
            normalized = normalize_candidate(candidate)
            accepted.append(normalized)
            append_trial_event(normalized, event="generated", status="accepted", batch_id=batch_id, log_dir=log_dir)
        else:
            append_trial_event(candidate, event="schema_rejected", status="rejected", reason=";".join(errors), batch_id=batch_id, log_dir=log_dir)
    return write_candidate_batch(accepted, log_dir=log_dir, batch_id=batch_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-json", help="Freeze candidate JSON into a preregistered batch")
    parser.add_argument("--print-prompt", action="store_true")
    args = parser.parse_args()
    if args.print_prompt:
        text = REGISTRY_PATH.read_text(encoding="utf-8")
        print(build_ai_generation_prompt(text))
        return 0
    if args.freeze_json:
        out_path = freeze_candidates_from_json(args.freeze_json)
        print(f"WROTE {out_path}")
        return 0
    parser.error("choose --freeze-json or --print-prompt")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
