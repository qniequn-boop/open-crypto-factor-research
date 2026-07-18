"""Export an audited combo into an executable strategy specification.

The exported JSON is deliberately explicit: it records the signal definitions,
position aggregation, risk/execution rules, validation evidence, and whether the
candidate satisfies the full research objective.
"""

from __future__ import annotations

import glob
import json
from datetime import datetime, timezone
from pathlib import Path

import config


SIGNAL_LIBRARY = {
    "ema100_slope_long_flat": {
        "logic": "Long when EMA(close,100) is above its value 24 bars ago; otherwise flat.",
        "position_values": {"long": 1.0, "flat": 0.0},
        "market_explanation": "Slow trend slope captures persistent directional drift while avoiding short exposure.",
    },
    "atr_expansion_short_filter": {
        "logic": "Long when close > EMA(close,200); short when close < EMA(close,200) and ATR(14)/close is above its 120-bar rolling median; otherwise flat.",
        "position_values": {"long": 1.0, "short": -1.0, "flat": 0.0},
        "market_explanation": "Combines trend state with volatility expansion, allowing shorts mainly during high-volatility downside regimes.",
    },
    "breakout72_low_vol_long_flat": {
        "logic": "Long when close breaks above the prior 72-bar high and ATR(14)/close is below its 120-bar rolling median; otherwise flat.",
        "position_values": {"long": 1.0, "flat": 0.0},
        "market_explanation": "Donchian-style breakout gated by lower volatility; aims to enter cleaner trend continuations.",
    },
    "bollinger_reversion_long_short": {
        "logic": "Long when close < SMA(close,20)-2*STD(close,20); short when close > SMA(close,20)+2*STD(close,20); otherwise flat.",
        "position_values": {"long": 1.0, "short": -1.0, "flat": 0.0},
        "market_explanation": "Mean-reversion leg that diversifies trend and breakout exposure.",
    },
    "naive_momentum_20_long_short": {
        "logic": "Long when 20-bar return is positive; short when 20-bar return is negative.",
        "position_values": {"long": 1.0, "short": -1.0},
        "market_explanation": "Simple time-series momentum baseline; included only when the audited combo explicitly uses it.",
    },
}


def _latest_audit_report() -> Path:
    paths = sorted(glob.glob(str(Path(config.LOG_DIR) / "strategy_audit_report_*.json")))
    if not paths:
        raise FileNotFoundError("no strategy_audit_report_*.json found; run strategy_audit.py first")
    return Path(paths[-1])


def _latest_blend_report() -> Path | None:
    paths = sorted(glob.glob(str(Path(config.LOG_DIR) / "strategy_blend_report_*.json")))
    return Path(paths[-1]) if paths else None


def _member_rule(member_name: str) -> tuple[str, str]:
    return member_name.rsplit(":", 1)


def _choose_candidate(audit: dict) -> dict:
    candidates = [
        row
        for row in audit["audited_combos"]
        if row["status"] in ("hard_audit_and_baseline_pass", "hard_audit_pass")
    ]
    if not candidates:
        raise ValueError("no hard-audit-passing combo available to export")

    baseline_passes = [row for row in candidates if row["status"] == "hard_audit_and_baseline_pass"]
    if baseline_passes:
        pool = baseline_passes
    else:
        pool = candidates

    return max(
        pool,
        key=lambda row: (
            row["baseline_dominance"]["beats_all_baselines"],
            row["splits"]["Holdout"]["sharpe"],
            row["rolling_90d"]["positive_windows"],
            row["splits"]["Val"]["sharpe"],
        ),
    )


def _choose_blend_candidate(blend_report: dict) -> dict | None:
    selected = list(blend_report.get("selected", []))
    if not selected:
        return None
    return max(
        selected,
        key=lambda row: (
            row["selection_results"]["Val"]["sharpe"],
            row["selection_results"]["min_val_subperiod_sharpe"],
            row["splits"]["IS"]["sharpe"],
            -row["selection_results"]["Val"]["max_drawdown"],
            -row["selection_results"]["Val"]["turnover"],
        ),
    )


def _objective_status(candidate: dict) -> dict:
    dominance = candidate["baseline_dominance"]
    checks = {
        "hard_audit_pass": candidate["status"] in ("hard_audit_and_baseline_pass", "hard_audit_pass"),
        "beats_all_baselines": dominance["beats_all_baselines"],
        "val_positive": candidate["splits"]["Val"]["sharpe"] > 0,
        "holdout_noncollapse": candidate["splits"]["Holdout"]["sharpe"] >= 0 and candidate["splits"]["Holdout"]["max_drawdown"] <= 0.45,
        "low_member_correlation": all(abs(item["val_position_corr"]) <= 0.75 for item in candidate["val_position_correlations"]),
    }
    return {
        "full_objective_satisfied": all(checks.values()),
        "checks": checks,
        "failed_baselines": dominance["failed_baselines"],
        "note": "Do not treat this as final unless full_objective_satisfied is true.",
    }


def _blend_objective_status(candidate: dict) -> dict:
    dominance = candidate["baseline_dominance"]
    checks = {
        "blend_full_pass": candidate["status"] == "blend_full_pass",
        "beats_all_baselines": dominance["beats_all_baselines"],
        "val_positive": candidate["splits"]["Val"]["sharpe"] > 0,
        "holdout_noncollapse": candidate["splits"]["Holdout"]["sharpe"] >= 0 and candidate["splits"]["Holdout"]["max_drawdown"] <= 0.45,
        "low_component_correlation": all(abs(item["val_position_corr"]) <= 0.80 for item in candidate["val_component_correlations"]),
        "funding_recorded": "funding_paid" in candidate["splits"]["Val"],
    }
    return {
        "full_objective_satisfied": all(checks.values()),
        "checks": checks,
        "failed_baselines": dominance["failed_baselines"],
        "note": "This is an audit status, not proof of live readiness. Funding is recorded in metrics; current research uses zero funding unless a funding-rate series is supplied.",
    }


def _strategy_spec(candidate: dict, audit: dict, audit_path: Path) -> dict:
    members = []
    for member in candidate["members"]:
        rule, update = _member_rule(member["name"])
        members.append(
            {
                "name": member["name"],
                "rule": rule,
                "update_frequency": update,
                "definition": SIGNAL_LIBRARY.get(rule, {"logic": "See strategy_research.py", "market_explanation": "Not documented."}),
                "evidence": {
                    "IS": member["splits"]["IS"],
                    "Val": member["splits"]["Val"],
                    "Holdout": member["splits"]["Holdout"],
                    "min_val_subperiod_sharpe": member["min_val_subperiod_sharpe"],
                },
            }
        )

    return {
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "source_audit_report": str(audit_path),
        "source_combo_report": audit["source_combo_report"],
        "strategy_id": "btc_hard_audit_combo_candidate_v1",
        "instrument": getattr(config, "INST_ID", None),
        "bar": getattr(config, "BAR", None),
        "history_days": getattr(config, "HISTORY_DAYS", None),
        "research_status": _objective_status(candidate),
        "combo": {
            "name": candidate["name"],
            "mode": candidate["mode"],
            "aggregation_rule": "Average member desired positions. If mode is threshold_050, target +1 when average >= 0.50, -1 when average <= -0.50, else 0. If mode is threshold_025, use +/-0.25 thresholds.",
            "members": members,
            "val_position_correlations": candidate["val_position_correlations"],
        },
        "signal_to_position": {
            "timing": "All signals are calculated after bar t close. Position is applied from bar t+1.",
            "position_unit": "Target notional direction in [-1, 1] before account-level sizing.",
            "rebalance": "Member signals update on their declared UTC daily/weekly/hourly schedule; combo target is held between updates.",
        },
        "risk_rules": {
            "max_abs_position": 1.0,
            "account_leverage_from_config": getattr(config, "LEVERAGE", None),
            "research_holdout_drawdown_gate": audit["audit_filters"]["holdout_drawdown_max"],
            "kill_switch_recommendation": "Disable new entries and flatten if live realized drawdown exceeds the audited Holdout max drawdown by 1.5x or if data/feed errors occur.",
            "not_yet_implemented": ["exchange order sizing", "real funding-rate ingestion", "live slippage monitor"],
        },
        "cost_model": {
            "cost_bps": getattr(config, "COST_BPS", None),
            "slippage_bps": getattr(config, "SLIPPAGE_BPS", None),
            "funding_rate": "Recorded as zero in current research backtest unless a funding-rate series is supplied. This remains a gap before production trading.",
        },
        "execution_rules": {
            "order_type": "Use reduce-only market order for risk exits; otherwise use conservative limit/marketable-limit order at scheduled rebalance.",
            "rebalance_clock": "1H bars; UTC day/week boundaries for daily/weekly members.",
            "data_requirements": ["open", "high", "low", "close", "volume", "timestamp"],
        },
        "evidence": {
            "splits": candidate["splits"],
            "val_subperiods": candidate["val_subperiods"],
            "rolling_90d": candidate["rolling_90d"],
            "baseline_dominance": candidate["baseline_dominance"],
            "baselines": audit["baselines"],
        },
    }


def _blend_strategy_spec(candidate: dict, blend_report: dict, blend_path: Path) -> dict:
    return {
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "source_blend_report": str(blend_path),
        "strategy_id": "btc_weighted_blend_candidate_v1",
        "instrument": getattr(config, "INST_ID", None),
        "bar": getattr(config, "BAR", None),
        "history_days": getattr(config, "HISTORY_DAYS", None),
        "research_status": _blend_objective_status(candidate),
        "blend": {
            "name": candidate["name"],
            "candidate_audit_status": candidate["status"],
            "weights": candidate["weights"],
            "aggregation_rule": "Continuous weighted blend: target_position = clip(sum(component_position * weight), -1, 1).",
            "components": candidate["component_specs"],
            "val_component_correlations": candidate["val_component_correlations"],
            "selection_filters": blend_report["selection_filters"],
            "selection_policy": blend_report.get("selection_policy", {}),
            "selection_note": "Weights come from a pre-declared 0.1 grid. Export ranking uses only IS and Validation; Holdout is audit evidence.",
            "selection_integrity": {
                "export_candidate_pool": "all selected Val-only blend candidates",
                "export_ranking_fields": [
                    "Val.sharpe",
                    "min_val_subperiod_sharpe",
                    "IS.sharpe",
                    "negative Val.max_drawdown",
                    "negative Val.turnover",
                ],
                "holdout_used_to_choose_export": False,
                "holdout_used_after_selection_for_audit": True,
            },
        },
        "signal_to_position": {
            "timing": "All component signals are calculated after bar t close. Target position is applied from bar t+1.",
            "position_unit": "Continuous target notional direction in [-1, 1] before account-level sizing.",
            "rebalance": "Components update on declared UTC hourly/daily/weekly schedules and are held between updates.",
        },
        "risk_rules": {
            "max_abs_position": 1.0,
            "account_leverage_from_config": getattr(config, "LEVERAGE", None),
            "research_holdout_drawdown": candidate["splits"]["Holdout"]["max_drawdown"],
            "kill_switch_recommendation": "Disable new entries and flatten if live realized drawdown exceeds 1.5x audited Holdout max drawdown or if market/data execution errors occur.",
            "remaining_gap": "Real funding-rate series is not yet supplied; metrics record funding_paid=0.0 under the current research data.",
        },
        "cost_model": {
            "cost_bps": getattr(config, "COST_BPS", None),
            "slippage_bps": getattr(config, "SLIPPAGE_BPS", None),
            "funding_rate_source": blend_report.get("funding_source", {}),
            "funding_paid_recorded": {
                split: candidate["splits"][split].get("funding_paid")
                for split in ["IS", "Val", "Holdout"]
            },
            "funding_abs_paid_recorded": {
                split: candidate["splits"][split].get("funding_abs_paid")
                for split in ["IS", "Val", "Holdout"]
            },
            "funding_observations": {
                split: candidate["splits"][split].get("funding_observations")
                for split in ["IS", "Val", "Holdout"]
            },
        },
        "execution_rules": {
            "order_type": "Use reduce-only market order for emergency exits; otherwise use conservative limit/marketable-limit order at scheduled rebalance.",
            "rebalance_clock": "1H bars; UTC day/week boundaries for daily/weekly components.",
            "data_requirements": ["open", "high", "low", "close", "volume", "timestamp"],
        },
        "evidence": {
            "splits": candidate["splits"],
            "val_subperiods": candidate["val_subperiods"],
            "rolling_90d": candidate["rolling_90d"],
            "baseline_dominance": candidate["baseline_dominance"],
            "baselines": blend_report["baselines"],
            "selection_results": candidate["selection_results"],
            "audit_results": candidate["audit_results"],
        },
    }


def _no_candidate_spec(reason: str, source_path: Path | None = None) -> dict:
    return {
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "source_report": str(source_path) if source_path is not None else None,
        "strategy_id": "no_exportable_strategy_candidate",
        "instrument": getattr(config, "INST_ID", None),
        "bar": getattr(config, "BAR", None),
        "history_days": getattr(config, "HISTORY_DAYS", None),
        "research_status": {
            "full_objective_satisfied": False,
            "checks": {
                "exportable_candidate_exists": False,
            },
            "failed_baselines": [],
            "note": reason,
        },
        "evidence": {
            "no_candidate_reason": reason,
        },
    }


def main() -> int:
    blend_path = _latest_blend_report()
    spec = None
    if blend_path is not None:
        blend = json.loads(blend_path.read_text(encoding="utf-8"))
        blend_candidate = _choose_blend_candidate(blend)
        if blend_candidate is not None:
            spec = _blend_strategy_spec(blend_candidate, blend, blend_path)

    if spec is None:
        try:
            audit_path = _latest_audit_report()
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            candidate = _choose_candidate(audit)
            spec = _strategy_spec(candidate, audit, audit_path)
        except (FileNotFoundError, ValueError) as exc:
            spec = _no_candidate_spec(f"No exportable candidate: {exc}", blend_path)

    timestamp = spec["created_at_utc"]
    out_dir = Path(config.LOG_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamped_path = out_dir / f"strategy_spec_{timestamp}.json"
    latest_path = out_dir / "strategy_spec_latest.json"
    payload = json.dumps(spec, ensure_ascii=False, indent=2)
    stamped_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")

    status = spec["research_status"]
    print(f"WROTE {stamped_path}")
    print(f"WROTE {latest_path}")
    print(f"STRATEGY {spec['strategy_id']}")
    print(f"FULL_OBJECTIVE_SATISFIED {status['full_objective_satisfied']}")
    print(f"FAILED_BASELINES {status['failed_baselines']}")
    evidence = spec["evidence"]
    if "splits" in evidence:
        print(
            "METRICS "
            f"IS {evidence['splits']['IS']['sharpe']:.2f} "
            f"Val {evidence['splits']['Val']['sharpe']:.2f} "
            f"Holdout {evidence['splits']['Holdout']['sharpe']:.2f} "
            f"HDD {evidence['splits']['Holdout']['max_drawdown']:.2%} "
            f"Roll+ {evidence['rolling_90d']['positive_windows']}/{evidence['rolling_90d']['window_count']}"
        )
    else:
        print(f"NO_CANDIDATE {evidence.get('no_candidate_reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
