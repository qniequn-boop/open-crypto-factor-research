"""Compare a gate-version re-audit without treating a newer sample as a policy change."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PORTFOLIO_KEYS = (
    "bars",
    "sharpe",
    "gross_sharpe",
    "total_return",
    "gross_return",
    "max_drawdown",
    "turnover",
    "cost_paid",
    "funding_paid",
    "funding_abs_paid",
    "avg_gross_exposure",
    "active_bars",
)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stable_portfolio(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: metrics.get(key) for key in PORTFOLIO_KEYS}


def _stable_rolling(rolling: dict[str, Any]) -> dict[str, Any]:
    return {
        key: rolling.get(key)
        for key in (
            "window_days",
            "window_count",
            "positive_ic_windows",
            "positive_sharpe_windows",
            "min_rank_ic",
            "min_sharpe",
            "rows",
        )
    }


def legacy_economic_view(report: dict[str, Any]) -> dict[str, Any]:
    paths = {}
    for row in report.get("factors") or []:
        name = str(row.get("name") or "")
        paths[name] = {
            "identity": {
                "candidate_id": row.get("candidate_id"),
                "factor_name": row.get("factor_name"),
                "panel_formula": row.get("panel_formula"),
                "weighting_mode": row.get("weighting_mode"),
            },
            "rank_ic": row.get("rank_ic"),
            "long_short": {
                split: _stable_portfolio((row.get("long_short") or {}).get(split) or {})
                for split in ("IS", "Val", "Holdout")
            },
            "rolling_90d": _stable_rolling(row.get("rolling_90d") or {}),
            "trial_adjustment": row.get("trial_adjustment"),
        }
    return {
        "candidate_batch_id": report.get("candidate_batch_id"),
        "multiple_testing_trial_count": report.get("multiple_testing_trial_count"),
        "time_ranges": report.get("time_ranges"),
        "paths": paths,
    }


def _canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return _sha256_bytes(raw)


def compare_reports(reference_path: Path | str, reaudit_path: Path | str) -> dict[str, Any]:
    reference_path = Path(reference_path)
    reaudit_path = Path(reaudit_path)
    reference_raw = reference_path.read_bytes()
    reaudit_raw = reaudit_path.read_bytes()
    reference = json.loads(reference_raw)
    reaudit = json.loads(reaudit_raw)
    old_view = legacy_economic_view(reference)
    new_view = legacy_economic_view(reaudit)
    old_paths = old_view["paths"]
    new_paths = new_view["paths"]
    changed_paths = sorted(
        name for name in set(old_paths) | set(new_paths) if old_paths.get(name) != new_paths.get(name)
    )
    structural_failures = []
    for key in ("candidate_batch_id", "multiple_testing_trial_count", "time_ranges"):
        if old_view.get(key) != new_view.get(key):
            structural_failures.append(f"{key}_changed")
    if set(old_paths) != set(new_paths):
        structural_failures.append("path_identity_set_changed")

    v2_counts: dict[str, int] = {}
    candidate_rows = []
    for row in reaudit.get("factors") or []:
        v2_status = (((row.get("gate_v2_draft") or {}).get("classification") or {}).get("status") or "missing")
        v2_counts[v2_status] = v2_counts.get(v2_status, 0) + 1
        if row.get("candidate_id"):
            candidate_rows.append(
                {
                    "name": row.get("name"),
                    "candidate_id": row.get("candidate_id"),
                    "v1_status": row.get("status"),
                    "v2_draft_status": v2_status,
                    "v2_watchlist_blockers": (
                        ((row.get("gate_v2_draft") or {}).get("classification") or {}).get("watchlist_blockers") or {}
                    ),
                    "v2_pass_blockers": (
                        ((row.get("gate_v2_draft") or {}).get("classification") or {}).get("pass_blockers") or {}
                    ),
                }
            )
    exact_match = not changed_paths
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_type": "panel_gate_version_reaudit_comparison",
        "reference_report": {"path": str(reference_path), "sha256": _sha256_bytes(reference_raw)},
        "reaudit_report": {"path": str(reaudit_path), "sha256": _sha256_bytes(reaudit_raw)},
        "structural_contract_match": not structural_failures,
        "structural_failures": structural_failures,
        "reference_legacy_output_sha256": _canonical_hash(old_view),
        "reaudit_legacy_output_sha256": _canonical_hash(new_view),
        "exact_legacy_economic_output_match": exact_match,
        "changed_legacy_path_count": len(changed_paths),
        "changed_legacy_paths": changed_paths,
        "gate_only_reaudit_interpretation_allowed": not structural_failures and exact_match,
        "gate_v2_draft_status_counts": v2_counts,
        "candidate_rows": candidate_rows,
        "raw_input_value_hash_available_in_legacy_reference": False,
        "note": "Exact legacy-output equality is a strong functional equivalence check, but not a raw market-data bitwise proof.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference_report")
    parser.add_argument("reaudit_report")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = compare_reports(args.reference_report, args.reaudit_report)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {path}")
    print(
        f"STRUCTURAL {result['structural_contract_match']} "
        f"LEGACY_OUTPUTS {result['exact_legacy_economic_output_match']} "
        f"GATE_ONLY_ALLOWED {result['gate_only_reaudit_interpretation_allowed']}"
    )
    return 0 if result["gate_only_reaudit_interpretation_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
