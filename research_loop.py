"""Cross-platform research loop runner.

Runs one or more research cycles, writes per-cycle logs, and records a compact
machine-readable summary. The loop deliberately stops only when the strict
skeptical audit passes; otherwise it leaves explicit failure reasons.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


LOG_DIR = Path("logs")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_step(command: list[str], log_file, env: dict[str, str]) -> None:
    log_file.write("\n$ " + " ".join(command) + "\n")
    log_file.flush()
    completed = subprocess.run(
        command,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, command)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_summary(cycle: int, max_cycles: int, log_path: Path, failed_step: str | None = None) -> dict:
    audit = _load_json(LOG_DIR / "strategy_skeptic_audit_latest.json")
    spec = _load_json(LOG_DIR / "strategy_spec_latest.json")
    summary = {
        "created_at_utc": _stamp(),
        "cycle": cycle,
        "max_cycles": max_cycles,
        "log": str(log_path),
        "failed_step": failed_step,
        "strict_objective_satisfied": bool(audit.get("strict_objective_satisfied")) if audit else False,
        "current_conditions_no_strict_pass": bool(audit.get("current_conditions_no_strict_pass")) if audit else False,
        "structural_blockers": audit.get("structural_blockers", []),
        "failed_reasons": audit.get("failed_reasons", ["audit_missing"]) if audit else ["audit_missing"],
        "strategy_id": spec.get("strategy_id"),
        "weights": (spec.get("blend") or {}).get("weights"),
        "top_level_checks": audit.get("top_level_checks", {}),
        "funding_checks": (audit.get("funding_audit") or {}).get("checks", {}),
        "funding_source": (audit.get("funding_audit") or {}).get("source", {}),
        "multiple_testing": (audit.get("trial_audit") or {}).get("multiple_testing", {}),
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "research_loop_summary_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (LOG_DIR / "research_loop_summary.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return summary


def _cycle_steps(python_bin: str, run_seed: bool, run_llm: bool) -> list[tuple[str, list[str]]]:
    steps: list[tuple[str, list[str]]] = [
        ("pytest", [python_bin, "-m", "pytest", "tests", "-q"]),
    ]
    if run_seed:
        steps.append(("seed_research", [python_bin, "-u", "seed_research.py"]))
    if run_llm:
        steps.append(("llm_factor_search", [python_bin, "-u", "main.py"]))
    steps.extend(
        [
            ("strategy_combo_research", [python_bin, "-u", "strategy_combo_research.py"]),
            ("strategy_audit", [python_bin, "-u", "strategy_audit.py"]),
            ("strategy_blend_research", [python_bin, "-u", "strategy_blend_research.py"]),
            ("strategy_export", [python_bin, "-u", "strategy_export.py"]),
            ("strategy_skeptic_audit", [python_bin, "-u", "strategy_skeptic_audit.py"]),
        ]
    )
    return steps


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--skip-seed", action="store_true")
    parser.add_argument("--run-llm", action="store_true")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    final_summary = {}

    for cycle in range(1, args.cycles + 1):
        log_path = LOG_DIR / f"research_loop_cycle_{cycle}_{_stamp()}.log"
        failed_step = None
        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write(f"START research loop cycle {cycle}/{args.cycles} {_stamp()}\n")
            for name, command in _cycle_steps(args.python_bin, not args.skip_seed, args.run_llm):
                try:
                    _run_step(command, log_file, env)
                except subprocess.CalledProcessError as exc:
                    failed_step = name
                    log_file.write(f"\nSTEP_FAILED {name} exit={exc.returncode}\n")
                    break
            log_file.write(f"DONE research loop cycle {cycle}/{args.cycles} {_stamp()}\n")

        final_summary = _write_summary(cycle, args.cycles, log_path, failed_step)
        print("SUMMARY", LOG_DIR / "research_loop_summary_latest.json")
        print("STRICT_OBJECTIVE_SATISFIED", final_summary["strict_objective_satisfied"])
        print("FAILED_REASONS", final_summary["failed_reasons"])
        if failed_step:
            print("FAILED_STEP", failed_step)
            return 1
        if final_summary["strict_objective_satisfied"]:
            print(f"STRICT OBJECTIVE PASSED at cycle {cycle}")
            return 0
        if final_summary["current_conditions_no_strict_pass"]:
            print("CURRENT CONDITIONS CANNOT STRICT PASS")
            print("STRUCTURAL_BLOCKERS", final_summary["structural_blockers"])
            return 3

    print(f"STRICT OBJECTIVE NOT SATISFIED after {args.cycles} cycles")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
