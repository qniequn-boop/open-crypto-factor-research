"""Apply nonbinding Gate v3 to a frozen report without recomputing outcomes."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import config
import panel_candidate_registry
import panel_gate_policy_v3


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def shadow_reaudit(report_path: Path, trial_registry_path: Path) -> dict:
    raw = report_path.read_bytes()
    report = json.loads(raw.decode("utf-8"))
    rows = copy.deepcopy(report.get("factors") or [])
    legacy = {row.get("name"): row.get("status") for row in rows}
    breakdown = panel_candidate_registry.trial_count_breakdown(trial_registry_path)
    summary = panel_gate_policy_v3.attach_gate_v3_drafts(rows, registry_breakdown=breakdown)
    if legacy != {row.get("name"): row.get("status") for row in rows}:
        raise AssertionError("gate_v3_shadow_reaudit_changed_legacy_status")
    candidate_rows = [
        {
            "name": row.get("name"),
            "candidate_id": row.get("candidate_id"),
            "family": row.get("family"),
            "legacy_status": row.get("status"),
            "gate_v2_status": ((row.get("gate_v2_draft") or {}).get("classification") or {}).get("status"),
            "gate_v3": row.get("gate_v3_draft"),
        }
        for row in rows
        if row.get("candidate_id")
    ]
    return {
        "created_at_utc": _stamp(),
        "audit_type": "panel_gate_v3_nonbinding_shadow_reaudit",
        "source_report": str(report_path),
        "source_report_sha256": hashlib.sha256(raw).hexdigest(),
        "legacy_statuses_unchanged": True,
        "trial_count_breakdown": breakdown,
        "summary": summary,
        "candidate_rows": candidate_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="logs/panel_factor_report_20260713T170357Z.json")
    parser.add_argument("--trial-registry", default="logs/panel_trial_registry.jsonl")
    parser.add_argument("--out")
    args = parser.parse_args()
    result = shadow_reaudit(Path(args.report), Path(args.trial_registry))
    out = Path(args.out) if args.out else Path(config.LOG_DIR) / f"panel_gate_v3_shadow_reaudit_{result['created_at_utc']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {out}")
    print(json.dumps(result["summary"]["candidate_path_status_counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
