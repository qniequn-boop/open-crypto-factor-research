"""Literature-constrained AI candidate generator for panel factor research.

This script is intentionally a thin gatekeeper:
- AI may propose candidates only against the literature registry.
- Every accepted and rejected candidate is appended to the trial registry.
- A frozen candidate batch is written before any optional audit is run.
- Holdout details are never passed into the AI prompt.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import config
import llm_client
import panel_candidate_registry as registry
import panel_factor_research as panel
import panel_literature_registry


DEFAULT_MAX_CANDIDATES = 10
DEFAULT_MAX_FAMILY_VARIANTS = 20
DEFAULT_SMOKE_SYMBOLS = [
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
    "XRP-USDT-SWAP",
    "DOGE-USDT-SWAP",
    "ADA-USDT-SWAP",
    "LINK-USDT-SWAP",
    "LTC-USDT-SWAP",
]
LATEST_REPORT_PATH = Path(config.LOG_DIR) / "panel_factor_report_latest.json"


def load_json_if_exists(path: Path | str | None) -> dict[str, Any] | None:
    if not path:
        return None
    json_path = Path(path)
    if not json_path.exists():
        return None
    return json.loads(json_path.read_text(encoding="utf-8"))


def build_candidate_generation_prompts(
    *,
    max_candidates: int,
    literature_path: Path | str = registry.REGISTRY_PATH,
    recent_report_path: Path | str | None = LATEST_REPORT_PATH,
    allowed_source_ids: set[str] | None = None,
    allowed_panel_formulas: set[str] | None = None,
) -> tuple[str, str]:
    max_candidates = min(int(max_candidates), DEFAULT_MAX_CANDIDATES)
    literature_text = Path(literature_path).read_text(encoding="utf-8")
    if allowed_source_ids is not None:
        literature_text = _filter_literature_registry(literature_text, allowed_source_ids)
    recent_report = load_json_if_exists(recent_report_path)
    base_prompt = registry.build_ai_generation_prompt(literature_text, recent_report)
    replication_context = panel_literature_registry.replication_prompt_context(
        source_ids=allowed_source_ids
    )
    formula_catalog = {
        name: {
            "family": spec.get("family"),
            "logic": spec.get("logic"),
            "expected_direction": panel._formula_candidate_direction(spec),
        }
        for name, spec in sorted(panel.FACTOR_DEFINITIONS.items())
        if not spec.get("deprecated_for_candidates")
        and (allowed_panel_formulas is None or name in allowed_panel_formulas)
    }
    trial_rows = registry.load_trial_rows()
    used_candidate_ids = sorted({str(row.get("candidate_id")) for row in trial_rows if row.get("candidate_id")})
    accepted_formulas = sorted(
        {
            str(row.get("panel_formula"))
            for row in trial_rows
            if row.get("panel_formula") and str(row.get("status")) != "rejected"
            and (
                allowed_panel_formulas is None
                or str(row.get("panel_formula")) in allowed_panel_formulas
            )
        }
    )
    system_prompt = (
        "You are an audit-disciplined quantitative research assistant. "
        "Return only valid JSON and do not invent literature source_ids or formulas."
    )
    user_prompt = "\n".join(
        [
            base_prompt,
            "",
            "=== Exact replication constraints and evidence tiers ===",
            replication_context,
            "Engineering-only sources cannot authorize a factor direction.",
            "=== Admitted source_ids for this cycle ===",
            json.dumps(sorted(allowed_source_ids), ensure_ascii=False)
            if allowed_source_ids is not None
            else "All registry source_ids are available to the supervised generator.",
            "Candidates citing any other source_id must be rejected.",
            "A blocked or adaptation-only specification must be labelled honestly and cannot be called a replication.",
            "Prefer one canonical replication over parameter variants. AI extensions are not allowed until the canonical data blockers are cleared and the canonical batch is frozen.",
            "",
            "=== Allowed panel_formula catalog ===",
            json.dumps(formula_catalog, ensure_ascii=False, indent=2),
            "",
            "=== Forbidden previously used candidate_ids ===",
            json.dumps(used_candidate_ids, ensure_ascii=False),
            "=== Previously accepted formulas; do not propose near-duplicates ===",
            json.dumps(accepted_formulas, ensure_ascii=False),
            "",
            f"Generate at most {max_candidates} candidates.",
            "Every candidate_id must be unique and stable, preferably ai_<family>_<three_digit_number>.",
            "Do not include weighting mode names inside candidate_id.",
            "Use only these weighting modes: rank_linear, top_bottom_30.",
            "When a formula catalog entry has expected_direction, candidate direction must match it exactly.",
            "Use only these neutralization values: none, liquidity_size, liquidity_bucket.",
            "Use only these bucket_policy values: none, liquidity_tercile, large_liquid_only.",
            "Return exactly this JSON shape:",
            '{"candidates": ['
            '{"candidate_id": "...", "source_ids": ["..."], "hypothesis": "...", '
            '"family": "...", "required_fields": ["..."], "panel_formula": "...", '
            '"direction": "long|short|neutral", "neutralization": "none|liquidity_size|liquidity_bucket", '
            '"bucket_policy": "none|liquidity_tercile|large_liquid_only", '
            '"weighting_modes": ["rank_linear"], "generated_by": "ai_panel_generator"}'
            "]}",
        ]
    )
    return system_prompt, user_prompt


def _filter_literature_registry(text: str, allowed_source_ids: set[str]) -> str:
    """Return only complete source-entry blocks admitted for this AI cycle."""
    lines = text.splitlines()
    selected: list[str] = ["# Admitted Literature Hypotheses", ""]
    found: set[str] = set()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped.startswith("- id:"):
            index += 1
            continue
        source_id = stripped.split(":", 1)[1].strip()
        end = index + 1
        while end < len(lines) and not lines[end].strip().startswith("- id:"):
            end += 1
        if source_id in allowed_source_ids:
            selected.extend(lines[index:end])
            selected.append("")
            found.add(source_id)
        index = end
    missing = sorted(allowed_source_ids - found)
    if missing:
        raise ValueError("admitted_source_missing_from_literature_registry:" + ",".join(missing))
    if not allowed_source_ids:
        selected.append("No source is currently admitted for candidate generation.")
    return "\n".join(selected).rstrip() + "\n"


def parse_llm_candidates(raw_text: str) -> list[dict[str, Any]]:
    payload = json.loads(raw_text)
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("LLM response must contain a candidates array")
    return [item for item in candidates if isinstance(item, dict)]


def generate_raw_candidates(
    *,
    max_candidates: int,
    client: llm_client.LLMClient | None = None,
    literature_path: Path | str = registry.REGISTRY_PATH,
    recent_report_path: Path | str | None = LATEST_REPORT_PATH,
    allowed_source_ids: set[str] | None = None,
    allowed_panel_formulas: set[str] | None = None,
) -> list[dict[str, Any]]:
    system_prompt, user_prompt = build_candidate_generation_prompts(
        max_candidates=max_candidates,
        literature_path=literature_path,
        recent_report_path=recent_report_path,
        allowed_source_ids=allowed_source_ids,
        allowed_panel_formulas=allowed_panel_formulas,
    )
    active_client = client or llm_client.get_client()
    raw_text = active_client._call(system_prompt, user_prompt)
    return parse_llm_candidates(raw_text)[: min(int(max_candidates), DEFAULT_MAX_CANDIDATES)]


def _variant_count(candidate: dict[str, Any]) -> int:
    modes = candidate.get("weighting_modes")
    return max(len(modes), 1) if isinstance(modes, list) else 1


def _guardrail_errors(
    candidate: dict[str, Any],
    *,
    registry_path: Path | str,
    accepted_so_far: list[dict[str, Any]],
    seen_candidate_ids: set[str],
    seen_signatures: set[str],
    family_counts: dict[str, int],
    max_family_variants: int,
) -> list[str]:
    errors = []
    candidate_id = str(candidate.get("candidate_id", ""))
    family = str(candidate.get("family", ""))
    signature = registry.candidate_signature(candidate)
    approximate_signature = registry.candidate_signature(candidate, approximate=True)
    formula_spec = panel.FACTOR_DEFINITIONS.get(str(candidate.get("panel_formula")), {})

    if candidate_id in seen_candidate_ids:
        errors.append("duplicate_candidate_id_in_batch")
    if candidate_id in registry.rejected_candidate_ids(registry_path):
        errors.append("candidate_id_previously_rejected")
    if signature in seen_signatures or approximate_signature in seen_signatures:
        errors.append("duplicate_candidate_signature")
    expected_direction = panel._formula_candidate_direction(formula_spec)
    if expected_direction and str(candidate.get("direction", "")).lower() != expected_direction:
        errors.append(f"formula_direction_mismatch:{expected_direction}")
    if formula_spec.get("deprecated_for_candidates"):
        errors.append("formula_deprecated_for_candidates")

    current_family_variants = sum(
        _variant_count(row) for row in accepted_so_far if str(row.get("family")) == family
    )
    projected = family_counts.get(family, 0) + current_family_variants + _variant_count(candidate)
    if projected > max_family_variants:
        errors.append(f"family_budget_exceeded:{family}:{projected}>{max_family_variants}")
    return errors


def freeze_generated_candidates(
    raw_candidates: list[dict[str, Any]],
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_family_variants: int = DEFAULT_MAX_FAMILY_VARIANTS,
    log_dir: Path | str = registry.LOG_DIR,
    literature_path: Path | str = registry.REGISTRY_PATH,
    trial_registry_path: Path | str | None = None,
    batch_id: str | None = None,
    allowed_source_ids: set[str] | None = None,
    allowed_panel_formulas: set[str] | None = None,
    source_variant_budgets: dict[str, int] | None = None,
    max_accepted_candidates: int | None = None,
) -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]]]:
    capped = raw_candidates[: min(int(max_candidates), DEFAULT_MAX_CANDIDATES)]
    source_ids = registry.load_literature_source_ids(literature_path)
    known_formulas = set(panel.FACTOR_DEFINITIONS)
    registry_path = Path(trial_registry_path) if trial_registry_path else Path(log_dir) / "panel_trial_registry.jsonl"
    historical_signatures = registry.historical_candidate_signatures(registry_path)
    family_counts = registry.historical_family_variant_counts(registry_path)
    source_counts = registry.historical_source_variant_counts(registry_path)
    current_source_counts: dict[str, int] = {}
    seen_candidate_ids: set[str] = set()
    seen_signatures: set[str] = set(historical_signatures)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    batch_id = batch_id or registry.utc_stamp()

    for candidate in capped:
        candidate = dict(candidate)
        candidate.setdefault("generated_by", "ai_panel_generator")
        ok, errors = registry.validate_candidate(
            candidate,
            literature_source_ids=source_ids,
            known_formulas=known_formulas,
            allowed_weighting_modes=set(panel.WEIGHTING_MODES),
        )
        guardrail_errors = []
        if ok:
            candidate_sources = {str(item) for item in candidate.get("source_ids", [])}
            if allowed_source_ids is not None:
                for source_id in sorted(candidate_sources - allowed_source_ids):
                    guardrail_errors.append(f"source_not_admitted_for_generation:{source_id}")
            formula = str(candidate.get("panel_formula") or "")
            if allowed_panel_formulas is not None and formula not in allowed_panel_formulas:
                guardrail_errors.append(f"formula_not_admitted_for_generation:{formula}")
            if max_accepted_candidates is not None and len(accepted) >= max_accepted_candidates:
                guardrail_errors.append(
                    f"accepted_batch_budget_exceeded:{len(accepted) + 1}>{max_accepted_candidates}"
                )
            if source_variant_budgets is not None:
                for source_id in sorted(candidate_sources):
                    if source_id not in source_variant_budgets:
                        guardrail_errors.append(f"source_budget_missing:{source_id}")
                        continue
                    projected = (
                        source_counts.get(source_id, 0)
                        + current_source_counts.get(source_id, 0)
                        + _variant_count(candidate)
                    )
                    budget = int(source_variant_budgets[source_id])
                    if projected > budget:
                        guardrail_errors.append(
                            f"source_budget_exceeded:{source_id}:{projected}>{budget}"
                        )
            guardrail_errors.extend(
                _guardrail_errors(
                    candidate,
                    registry_path=registry_path,
                    accepted_so_far=accepted,
                    seen_candidate_ids=seen_candidate_ids,
                    seen_signatures=seen_signatures,
                    family_counts=family_counts,
                    max_family_variants=max_family_variants,
                )
            )
            errors.extend(guardrail_errors)
            ok = not errors

        for source_id in {
            str(item) for item in candidate.get("source_ids", []) if str(item) in source_ids
        }:
            current_source_counts[source_id] = (
                current_source_counts.get(source_id, 0) + _variant_count(candidate)
            )

        if ok:
            normalized = registry.normalize_candidate(candidate)
            accepted.append(normalized)
            seen_candidate_ids.add(normalized["candidate_id"])
            seen_signatures.add(registry.candidate_signature(normalized))
            seen_signatures.add(registry.candidate_signature(normalized, approximate=True))
            registry.append_trial_event(
                normalized,
                event="generated",
                status="accepted",
                batch_id=batch_id,
                log_dir=log_dir,
                registry_path=registry_path,
                extra={
                    "generator": "panel_ai_candidate_generator",
                    "candidate_signature": registry.candidate_signature(normalized),
                },
            )
        else:
            rejected.append({"candidate": candidate, "errors": errors})
            registry.append_trial_event(
                candidate,
                event="guardrail_rejected" if guardrail_errors else "schema_rejected",
                status="rejected",
                reason=";".join(errors),
                batch_id=batch_id,
                log_dir=log_dir,
                registry_path=registry_path,
                extra={
                    "generator": "panel_ai_candidate_generator",
                    "candidate_signature": registry.candidate_signature(candidate),
                },
            )

    batch_path = registry.write_candidate_batch(accepted, log_dir=log_dir, batch_id=batch_id)
    return batch_path, accepted, rejected


def run_smoke_audit(
    batch_path: Path,
    *,
    substrate_manifest: Path | str,
    days: int,
    symbols: list[str],
    min_assets: int,
) -> int:
    import panel_factory_orchestrator

    job_id = panel_factory_orchestrator.create_job(
        batch_path,
        substrate_manifest,
        days=days,
        symbols=symbols,
        min_assets=min_assets,
    )
    print(f"FACTORY_JOB {job_id}")
    status = panel_factory_orchestrator.run_job(job_id)
    if status["state"] == "completed":
        return 0
    if status["state"] in {"formula_rejected", "critic_rejected"}:
        return 2
    return 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--max-family-variants", type=int, default=DEFAULT_MAX_FAMILY_VARIANTS)
    parser.add_argument("--from-json", help="Use a local LLM-style JSON response instead of calling the LLM")
    parser.add_argument("--recent-report", default=str(LATEST_REPORT_PATH))
    parser.add_argument("--print-prompt", action="store_true")
    parser.add_argument("--audit-smoke", action="store_true")
    parser.add_argument(
        "--substrate-manifest",
        help="Frozen panel substrate required when --audit-smoke is used",
    )
    parser.add_argument("--smoke-days", type=int, default=60)
    parser.add_argument("--smoke-symbols", default=",".join(DEFAULT_SMOKE_SYMBOLS))
    parser.add_argument("--smoke-min-assets", type=int, default=8)
    args = parser.parse_args()

    if args.print_prompt:
        _, user_prompt = build_candidate_generation_prompts(
            max_candidates=args.max_candidates,
            recent_report_path=args.recent_report,
        )
        print(user_prompt)
        return 0

    if args.from_json:
        raw_candidates = parse_llm_candidates(Path(args.from_json).read_text(encoding="utf-8"))
    else:
        raw_candidates = generate_raw_candidates(
            max_candidates=args.max_candidates,
            recent_report_path=args.recent_report,
        )

    batch_path, accepted, rejected = freeze_generated_candidates(
        raw_candidates,
        max_candidates=args.max_candidates,
        max_family_variants=args.max_family_variants,
    )
    print(f"WROTE {batch_path}")
    print(f"ACCEPTED {len(accepted)} REJECTED {len(rejected)}")
    if rejected:
        for row in rejected:
            candidate = row.get("candidate") or {}
            print(f"REJECTED {candidate.get('candidate_id')} {';'.join(row.get('errors', []))}")

    if args.audit_smoke:
        if not args.substrate_manifest:
            parser.error("--audit-smoke requires --substrate-manifest; direct evaluator bypass is forbidden")
        symbols = [item.strip() for item in args.smoke_symbols.split(",") if item.strip()]
        return run_smoke_audit(
            batch_path,
            substrate_manifest=args.substrate_manifest,
            days=args.smoke_days,
            symbols=symbols,
            min_assets=args.smoke_min_assets,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
