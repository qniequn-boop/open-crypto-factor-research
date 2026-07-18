"""Append authoritative frozen-batch metadata to legacy trial-registry rows."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import panel_candidate_registry as registry


ENRICHMENT_VERSION = 1


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def collect_frozen_candidate_metadata(log_dir: Path | str) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    log_dir = Path(log_dir)
    candidates: dict[str, dict[str, Any]] = {}
    sources: dict[str, list[str]] = {}
    for path in sorted(log_dir.glob("panel_candidate_batch_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for candidate in payload.get("candidates", []):
            candidate_id = str(candidate.get("candidate_id") or "")
            if not candidate_id:
                continue
            normalized = registry.normalize_candidate(candidate)
            existing = candidates.get(candidate_id)
            if existing and registry.candidate_signature(existing) != registry.candidate_signature(normalized):
                raise ValueError(f"conflicting_frozen_candidate_metadata:{candidate_id}:{path}")
            candidates[candidate_id] = normalized
            sources.setdefault(candidate_id, []).append(str(path))
    return candidates, sources


def enrich_trial_registry(*, log_dir: Path | str, apply: bool) -> dict[str, Any]:
    log_dir = Path(log_dir)
    registry_path = log_dir / "panel_trial_registry.jsonl"
    before = registry.trial_count_breakdown(registry_path)
    rows = registry.load_trial_rows(registry_path)
    known_ids = {str(row.get("candidate_id")) for row in rows if row.get("candidate_id")}
    variant_counts: dict[str, int] = {}
    already_complete = set()
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            continue
        variant_counts[candidate_id] = max(variant_counts.get(candidate_id, 0), int(row.get("variant_count") or 1))
        signal_signature = str(row.get("signal_signature") or "")
        if signal_signature and not signal_signature.startswith("|||"):
            already_complete.add(candidate_id)

    frozen, sources = collect_frozen_candidate_metadata(log_dir)
    enrichable = sorted((known_ids & set(frozen)) - already_complete)
    appended = []
    if apply:
        for candidate_id in enrichable:
            row = registry.append_trial_event(
                frozen[candidate_id],
                event="metadata_enriched",
                status="metadata_only",
                reason="authoritative_frozen_batch_metadata_backfill",
                batch_id=None,
                variant_count=variant_counts[candidate_id],
                log_dir=log_dir,
                extra={
                    "metadata_enrichment_version": ENRICHMENT_VERSION,
                    "metadata_source_paths": sorted(set(sources[candidate_id])),
                    "trial_count_effect": "none_existing_candidate_id_max_variant_preserved",
                },
            )
            appended.append(row["candidate_id"])

    after = registry.trial_count_breakdown(registry_path)
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_type": "panel_trial_registry_metadata_enrichment",
        "enrichment_version": ENRICHMENT_VERSION,
        "applied": bool(apply),
        "registry_path": str(registry_path),
        "known_candidate_id_count": len(known_ids),
        "frozen_metadata_candidate_count": len(frozen),
        "enrichable_candidate_ids": enrichable,
        "appended_candidate_ids": appended,
        "unrecoverable_candidate_ids": sorted(known_ids - set(frozen) - already_complete),
        "trial_count_unchanged": before["portfolio_variant_trial_count"] == after["portfolio_variant_trial_count"],
        "before": before,
        "after": after,
        "note": "Legacy rows remain untouched. Unrecoverable metadata is preserved as unknown, never inferred.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = enrich_trial_registry(log_dir=args.log_dir, apply=args.apply)
    out_path = Path(args.log_dir) / f"panel_trial_registry_enrichment_{_stamp()}.json"
    out_path.write_bytes(json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
    print(f"WROTE {out_path}")
    print(
        f"APPLIED {report['applied']} APPENDED {len(report['appended_candidate_ids'])} "
        f"UNRECOVERABLE {len(report['unrecoverable_candidate_ids'])} "
        f"TRIAL_COUNT_UNCHANGED {report['trial_count_unchanged']}"
    )
    return 0 if report["trial_count_unchanged"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
