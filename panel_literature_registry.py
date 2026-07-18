"""Validation and selection rules for literature replication specifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REGISTRY_PATH = Path(__file__).with_name("LITERATURE_REPLICATION_REGISTRY.json")
REQUIRED_ENTRY_FIELDS = {
    "replication_id",
    "source_id",
    "citation",
    "url",
    "evidence_tier",
    "allowed_use",
    "market_in_source",
    "source_sample",
    "signal",
    "formation_frequency",
    "forward_horizon",
    "portfolio_rule",
    "weighting",
    "expected_direction",
    "primary_endpoint",
    "required_fields",
    "target_scope",
    "replication_status",
    "blockers",
    "permitted_next_action",
}
ALLOWED_USES = {"factor_direction", "mechanism_constraint", "audit_method", "engineering_pattern"}
ALLOWED_EVIDENCE_TIERS = {
    "peer_reviewed",
    "peer_reviewed_conference",
    "working_paper",
    "preprint",
    "documentation",
}
ALLOWED_REPLICATION_STATUSES = {
    "blocked_missing_data",
    "adaptation_only",
    "ready_mechanism_only",
    "ready_audit_method",
    "engineering_only",
    "ready_canonical",
}


def load_registry(path: Path | str = REGISTRY_PATH) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_registry(payload)
    return payload


def validate_registry(payload: dict[str, Any]) -> None:
    if int(payload.get("schema_version") or 0) != 1:
        raise ValueError("unsupported_literature_replication_schema")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("literature_replication_entries_required")
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"replication_entry_not_object:{index}")
        missing = sorted(REQUIRED_ENTRY_FIELDS - set(entry))
        if missing:
            raise ValueError(f"replication_entry_missing_fields:{index}:{','.join(missing)}")
        replication_id = str(entry["replication_id"])
        if replication_id in seen_ids:
            raise ValueError(f"duplicate_replication_id:{replication_id}")
        seen_ids.add(replication_id)
        if entry["allowed_use"] not in ALLOWED_USES:
            raise ValueError(f"invalid_allowed_use:{replication_id}")
        if entry["evidence_tier"] not in ALLOWED_EVIDENCE_TIERS:
            raise ValueError(f"invalid_evidence_tier:{replication_id}")
        if entry["replication_status"] not in ALLOWED_REPLICATION_STATUSES:
            raise ValueError(f"invalid_replication_status:{replication_id}")
        if not isinstance(entry["required_fields"], list) or not isinstance(entry["blockers"], list):
            raise ValueError(f"replication_lists_required:{replication_id}")
        if entry["allowed_use"] == "engineering_pattern" and entry["replication_status"] != "engineering_only":
            raise ValueError(f"engineering_source_cannot_authorize_factor:{replication_id}")


def candidate_authorizing_entries(payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    registry = payload or load_registry()
    return [
        entry
        for entry in registry["entries"]
        if entry["allowed_use"] in {"factor_direction", "mechanism_constraint"}
        and entry["evidence_tier"] in {"peer_reviewed", "working_paper"}
    ]


def canonical_replications_ready(payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    registry = payload or load_registry()
    return [entry for entry in registry["entries"] if entry["replication_status"] == "ready_canonical"]


def replication_prompt_context(
    payload: dict[str, Any] | None = None,
    *,
    source_ids: set[str] | None = None,
) -> str:
    registry = payload or load_registry()
    selected_entries = registry["entries"]
    if source_ids is not None:
        selected_entries = [
            entry for entry in selected_entries if str(entry["source_id"]) in source_ids
        ]
    compact = [
        {
            "replication_id": entry["replication_id"],
            "source_id": entry["source_id"],
            "evidence_tier": entry["evidence_tier"],
            "allowed_use": entry["allowed_use"],
            "replication_status": entry["replication_status"],
            "signal": entry["signal"],
            "formation_frequency": entry["formation_frequency"],
            "forward_horizon": entry["forward_horizon"],
            "portfolio_rule": entry["portfolio_rule"],
            "weighting": entry["weighting"],
            "target_scope": entry["target_scope"],
            "blockers": entry["blockers"],
            "permitted_next_action": entry["permitted_next_action"],
        }
        for entry in selected_entries
    ]
    return json.dumps(compact, ensure_ascii=False, indent=2)
