"""Run a small, deterministic demonstration of the research evidence gates.

The example uses synthetic data only. It is intentionally not a return
backtest and makes no empirical market claim.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import panel_formula_audit
import panel_gate_policy_v3


def _synthetic_panel(periods: int = 240, assets: int = 4) -> dict[str, dict[str, Any]]:
    index = pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC")
    panel: dict[str, dict[str, Any]] = {}
    for asset_number in range(assets):
        close = pd.Series(
            [100.0 + asset_number + 0.01 * (asset_number + 1) * step for step in range(periods)],
            index=index,
        )
        panel[f"SYNTH-{asset_number}"] = {
            "ohlcv": pd.DataFrame(
                {
                    "open": close.shift(1).bfill(),
                    "high": close * 1.001,
                    "low": close * 0.999,
                    "close": close,
                    "volume": 1000.0 + asset_number,
                    "vol_quote": close * (1000.0 + asset_number),
                },
                index=index,
            ),
            "spot_ohlcv": None,
            "funding": pd.Series(0.0, index=index[::8]),
            "open_interest": None,
            "market_cap": None,
            "asset_label": "synthetic",
        }
    return panel


def _future_leaking_builder(panel: dict[str, dict[str, Any]], **_: Any) -> dict[str, Any]:
    close = pd.concat({name: item["ohlcv"]["close"] for name, item in panel.items()}, axis=1)
    future_close = close.shift(-1)
    return {
        "close": close,
        "returns": close.pct_change(fill_method=None),
        "eligibility": close.notna(),
        "formula_library": {"future_close_formula": future_close},
        "factors": {"future_leak_candidate": future_close},
    }


def _discovery_checks() -> dict[str, bool]:
    return {
        "coverage_ok": True,
        "return_evidence_complete_while_held": True,
        "val_ic_positive": True,
        "dependence_aware_val_ic_clue": True,
        "val_long_short_positive": True,
        "turnover_reasonable": True,
        "rolling_ic_stable": True,
        "holdout_noncollapse": True,
    }


def run_demo() -> dict[str, Any]:
    leakage_audit = panel_formula_audit.run_differential_audit(
        _synthetic_panel(),
        cutoff_fractions=(0.5, 0.8),
        required_factor_names={"future_leak_candidate"},
        matrix_builder=_future_leaking_builder,
    )

    family_p_values = {
        "prospective_candidate": 0.001,
        "multiplicity_candidate": 0.040,
        "control_01": 0.20,
        "control_02": 0.30,
        "control_03": 0.40,
        "control_04": 0.50,
        "control_05": 0.60,
        "control_06": 0.70,
        "control_07": 0.80,
        "control_08": 0.90,
    }
    bh = panel_gate_policy_v3.false_discovery_adjustment(family_p_values)
    by = panel_gate_policy_v3.false_discovery_adjustment(
        family_p_values,
        method="benjamini_yekutieli",
    )
    multiplicity_fdr = bh["multiplicity_candidate"]
    prospective_fdr = bh["prospective_candidate"]
    multiplicity_classification = panel_gate_policy_v3.classify_historical_discovery(
        _discovery_checks(),
        fdr_state="pass" if multiplicity_fdr["passed"] else "fail",
    )
    prospective_classification = panel_gate_policy_v3.classify_historical_discovery(
        _discovery_checks(),
        fdr_state="pass" if prospective_fdr["passed"] else "fail",
    )

    cases = [
        {
            "candidate_id": "future_leak_candidate",
            "status": "historical_reject",
            "reason": "point_in_time_leakage",
            "audit_passed": leakage_audit["passed"],
            "leakage_frames": leakage_audit["leakage_frames"],
            "formal_pass_possible": False,
        },
        {
            "candidate_id": "multiplicity_candidate",
            "status": multiplicity_classification["status"],
            "reason": multiplicity_classification["reason"],
            "raw_p": multiplicity_fdr["raw_p"],
            "bh_adjusted_p": multiplicity_fdr["adjusted_p"],
            "by_adjusted_p": by["multiplicity_candidate"]["adjusted_p"],
            "family_hypothesis_count": multiplicity_fdr["family_hypothesis_count"],
            "prospective_entry_allowed": multiplicity_classification["status"] == "prospective_eligible",
            "formal_pass_possible": multiplicity_classification["formal_pass_possible"],
        },
        {
            "candidate_id": "prospective_candidate",
            "status": prospective_classification["status"],
            "reason": prospective_classification["reason"],
            "raw_p": prospective_fdr["raw_p"],
            "bh_adjusted_p": prospective_fdr["adjusted_p"],
            "by_adjusted_p": by["prospective_candidate"]["adjusted_p"],
            "family_hypothesis_count": prospective_fdr["family_hypothesis_count"],
            "prospective_entry_allowed": prospective_classification["status"] == "prospective_eligible",
            "formal_pass_possible": prospective_classification["formal_pass_possible"],
        },
    ]
    formal_pass_count = sum(bool(case["formal_pass_possible"]) for case in cases)
    decision = {
        "formal_factor_pass_count": formal_pass_count,
        "combo_allowed": formal_pass_count > 0,
        "paper_trading_allowed": False,
        "capital_allowed": False,
        "reason": "historical_evidence_can_reject_or_authorize_observation_but_cannot_authorize_capital",
    }
    report = {
        "demo": "synthetic_evidence_pipeline",
        "external_market_data_used": False,
        "empirical_market_claim": False,
        "cases": cases,
        "decision": decision,
    }

    if leakage_audit["passed"] or "factor:future_leak_candidate" not in leakage_audit["leakage_frames"]:
        raise RuntimeError("synthetic_leakage_case_was_not_rejected")
    if multiplicity_fdr["passed"] or multiplicity_classification["status"] == "prospective_eligible":
        raise RuntimeError("synthetic_multiplicity_case_was_not_blocked")
    if prospective_classification["status"] != "prospective_eligible":
        raise RuntimeError("synthetic_clue_did_not_reach_prospective_eligibility")
    if decision["combo_allowed"] or decision["paper_trading_allowed"] or decision["capital_allowed"]:
        raise RuntimeError("synthetic_demo_crossed_a_forbidden_evidence_boundary")
    return report


def _print_human(report: dict[str, Any]) -> None:
    print("Open Crypto Factor Research - Synthetic Evidence Demo")
    print("External market data used: no")
    print()
    for case in report["cases"]:
        print(f"{case['candidate_id']}: {case['status']}")
        if "leakage_frames" in case:
            print(f"  leakage detected: {', '.join(case['leakage_frames'])}")
        else:
            print(
                "  raw p={raw_p:.3f}, BH adjusted p={bh_adjusted_p:.3f}, "
                "BY adjusted p={by_adjusted_p:.3f}".format(**case)
            )
        print(f"  reason: {case['reason']}")
    print()
    decision = report["decision"]
    print(f"Formal factor passes: {decision['formal_factor_pass_count']}")
    print(f"Combination allowed: {'yes' if decision['combo_allowed'] else 'no'}")
    print(f"Paper trading allowed: {'yes' if decision['paper_trading_allowed'] else 'no'}")
    print(f"Capital allowed: {'yes' if decision['capital_allowed'] else 'no'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the machine-readable report")
    args = parser.parse_args(argv)
    report = run_demo()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
