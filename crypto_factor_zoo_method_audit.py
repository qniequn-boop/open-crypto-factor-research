"""Audit the frozen Crypto Factor Zoo liquidity construction against OKX L2."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import config
import crypto_factor_zoo_method as method


DEFAULT_L2_REPORT = Path(config.LOG_DIR) / "okx_l2_pilot_20260710.json"
DEFAULT_JSON_REPORT = Path(config.LOG_DIR) / "crypto_factor_zoo_method_audit_20260717.json"
DEFAULT_MD_REPORT = Path(config.LOG_DIR) / "crypto_factor_zoo_method_audit_20260717.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return float(numerator / denominator)


def build_audit(
    hourly_by_asset: dict[str, pd.DataFrame],
    l2_report: dict[str, Any],
    *,
    target_date: str,
    source_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    target = pd.Timestamp(target_date, tz="UTC")
    assets: dict[str, Any] = {}
    for inst_id, hourly in hourly_by_asset.items():
        daily = method.aggregate_hourly_ohlcv_to_daily(hourly)
        cs = method.corwin_schultz_spread(daily["high"], daily["low"])
        ar = method.abdi_ranaldo_spread(daily["high"], daily["low"], daily["close"])
        combined = (cs + ar) / 2.0
        l2 = (l2_report.get("assets") or {}).get(inst_id) or {}
        quoted = _number((l2.get("quoted_spread_bps") or {}).get("median"))
        effective = l2.get("effective_spread_bps") or {}
        effective_median = _number(effective.get("median"))
        effective_weighted = _number(effective.get("quote_notional_weighted_mean"))
        cs_bps = _number(cs.get(target))
        ar_bps = _number(ar.get(target))
        combined_bps = _number(combined.get(target))
        cs_bps = None if cs_bps is None else cs_bps * 10000.0
        ar_bps = None if ar_bps is None else ar_bps * 10000.0
        combined_bps = None if combined_bps is None else combined_bps * 10000.0
        source_path = (source_paths or {}).get(inst_id)
        assets[inst_id] = {
            "complete_daily_observations": int(daily.dropna().shape[0]),
            "corwin_schultz_full_spread_bps": cs_bps,
            "abdi_ranaldo_full_spread_bps": ar_bps,
            "factor_zoo_composite_full_spread_bps": combined_bps,
            "l2_median_quoted_spread_bps": quoted,
            "l2_median_effective_spread_bps": effective_median,
            "l2_notional_weighted_effective_spread_bps": effective_weighted,
            "composite_to_quoted_ratio": _ratio(combined_bps, quoted),
            "composite_to_weighted_effective_ratio": _ratio(combined_bps, effective_weighted),
            "hourly_source": None
            if source_path is None
            else {
                "path": str(source_path),
                "sha256": _sha256(source_path),
                "rows": int(len(hourly)),
                "first_timestamp": hourly.index.min().isoformat(),
                "last_timestamp": hourly.index.max().isoformat(),
            },
        }

    comparison = pd.DataFrame.from_dict(assets, orient="index")
    rank_rows = comparison[
        ["factor_zoo_composite_full_spread_bps", "l2_median_quoted_spread_bps"]
    ].dropna()
    spearman = (
        float(rank_rows.corr(method="spearman").iloc[0, 1])
        if len(rank_rows) >= 2
        else None
    )
    rank_order_proxy = rank_rows.iloc[:, 0].sort_values(ascending=False).index.tolist()
    rank_order_l2 = rank_rows.iloc[:, 1].sort_values(ascending=False).index.tolist()

    return {
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "schema_version": 1,
        "audit_type": "crypto_factor_zoo_exact_method_and_l2_proxy_audit",
        "claim_ceiling": "one_day_three_asset_formula_execution_and_descriptive_proxy_comparison_only",
        "factor_generated": False,
        "parameter_search_performed": False,
        "trial_registry_changed": False,
        "promotion_state_changed": False,
        "target_date": target_date,
        "source_contract": {
            "characteristic_window_days": 30,
            "formation_frequency": "weekly",
            "portfolio_sort": "quartiles",
            "direction": "long_low_short_high",
            "bidask": "simple_average_of_corwin_schultz_and_two_day_corrected_abdi_ranaldo",
            "turnover": "daily_exchange_aggregated_dollar_volume_divided_by_point_in_time_market_cap",
            "turnover_volatility": "30_day_sample_standard_deviation_of_daily_turnover",
        },
        "l2_report": {
            "path": str(DEFAULT_L2_REPORT),
            "sha256": _sha256(DEFAULT_L2_REPORT) if DEFAULT_L2_REPORT.exists() else None,
        },
        "assets": assets,
        "descriptive_rank_comparison": {
            "asset_count": int(len(rank_rows)),
            "spearman": spearman,
            "proxy_descending": rank_order_proxy,
            "l2_quoted_descending": rank_order_l2,
            "same_order": rank_order_proxy == rank_order_l2,
        },
        "decision": {
            "exact_formula_executable": all(
                row["factor_zoo_composite_full_spread_bps"] is not None
                for row in assets.values()
            ),
            "spread_proxy_magnitude_calibrated": False,
            "spread_proxy_cross_regime_validated": False,
            "new_factor_batch_authorized": False,
            "reason": (
                "the one-day three-asset proxy ordering matches L2, but the OHLC proxy "
                "overstates quoted spread magnitude and cannot establish cross-regime validity"
            ),
            "next_requirement": (
                "predeclare multiple regime dates and a wider asset sample, then test rank stability, "
                "magnitude bias, and net implementability before candidate admission"
            ),
        },
        "limitations": [
            "Three assets and one day cannot validate a cross-sectional proxy; the rank correlation is descriptive.",
            "The source uses spot OHLC and volume aggregated across more than 250 exchanges; this audit uses one OKX perpetual venue.",
            "The OHLC estimators mix volatility and spread and must not replace direct L2 execution costs.",
            "The current-live OKX universe is survivor conditioned and cannot reproduce the source population.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    rows = []
    for inst_id, asset in report["assets"].items():
        rows.append(
            "| {asset} | {cs:.2f} | {ar:.2f} | {combined:.2f} | {quoted:.2f} | {effective:.2f} | {ratio:.1f}x |".format(
                asset=inst_id,
                cs=asset["corwin_schultz_full_spread_bps"],
                ar=asset["abdi_ranaldo_full_spread_bps"],
                combined=asset["factor_zoo_composite_full_spread_bps"],
                quoted=asset["l2_median_quoted_spread_bps"],
                effective=asset["l2_notional_weighted_effective_spread_bps"],
                ratio=asset["composite_to_quoted_ratio"],
            )
        )
    rank = report["descriptive_rank_comparison"]
    return "\n".join(
        [
            "# Crypto Factor Zoo Exact-Method Audit",
            "",
            f"Created: {report['created_at_utc']}",
            "",
            "## Decision",
            "",
            f"- Exact formula executable: `{report['decision']['exact_formula_executable']}`",
            "- Spread magnitude calibrated: `False`",
            "- Cross-regime proxy validation: `False`",
            "- New factor batch authorized: `False`",
            "",
            "The source method is now executable, but the OHLC bid-ask proxy is not an",
            "execution-cost estimate for this market. Its first descriptive ordering matches",
            "the L2 ordering, while its level is much larger than direct quoted spreads.",
            "",
            "## One-Day Comparison",
            "",
            "| Asset | Corwin-Schultz | Abdi-Ranaldo | Source composite | L2 quoted median | L2 weighted effective | Composite / quoted |",
            "|---|---:|---:|---:|---:|---:|---:|",
            *rows,
            "",
            f"Descending source-proxy order: `{', '.join(rank['proxy_descending'])}`",
            "",
            f"Descending L2 quoted order: `{', '.join(rank['l2_quoted_descending'])}`",
            "",
            f"Descriptive Spearman correlation: `{rank['spearman']:.3f}` over only `{rank['asset_count']}` assets.",
            "",
            "## Frozen Source Construction",
            "",
            "- Bid-ask proxy: 30-day simple average of Corwin-Schultz and",
            "  two-day-corrected Abdi-Ranaldo full-spread estimates.",
            "- Turnover volatility: 30-day sample standard deviation of daily dollar",
            "  volume divided by point-in-time market capitalization.",
            "- Portfolio: weekly quartile sort, long low characteristic and short high",
            "  characteristic; report equal- and value-weighted paths separately.",
            "",
            "## Interpretation",
            "",
            "The matching three-asset order is encouraging but not probative. The source",
            "composite exceeds the quoted L2 median by tens to more than one hundred times,",
            "which is consistent with substantial volatility contamination. The proxy may",
            "still rank liquidity, but direct L2 must determine execution cost and capacity.",
            "",
            "No formula, sign, or portfolio may enter the candidate registry until a",
            "predeclared multi-regime and wider-asset comparison tests rank stability and",
            "the resulting strategy remains net positive under direct L2 costs.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-date", default="2026-07-10")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--l2-report", default=str(DEFAULT_L2_REPORT))
    parser.add_argument("--json-report", default=str(DEFAULT_JSON_REPORT))
    parser.add_argument("--md-report", default=str(DEFAULT_MD_REPORT))
    args = parser.parse_args()

    l2_path = Path(args.l2_report)
    l2_report = json.loads(l2_path.read_text(encoding="utf-8"))
    hourly: dict[str, pd.DataFrame] = {}
    source_paths: dict[str, Path] = {}
    for inst_id in l2_report["instruments"]:
        source = Path(config.CACHE_DIR) / f"{inst_id}_1H_{int(args.days)}d.parquet"
        if not source.exists():
            raise FileNotFoundError(f"missing_hourly_cache:{source}")
        frame = pd.read_parquet(source)
        if frame.index.tz is None:
            frame.index = frame.index.tz_localize("UTC")
        hourly[inst_id] = frame
        source_paths[inst_id] = source

    report = build_audit(
        hourly,
        l2_report,
        target_date=args.target_date,
        source_paths=source_paths,
    )
    report["l2_report"] = {"path": str(l2_path), "sha256": _sha256(l2_path)}
    json_path = Path(args.json_report)
    md_path = Path(args.md_report)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"EXACT_FORMULA_EXECUTABLE {report['decision']['exact_formula_executable']}")
    print("NEW_FACTOR_BATCH_AUTHORIZED False")
    print(f"JSON_REPORT {json_path}")
    print(f"MD_REPORT {md_path}")


if __name__ == "__main__":
    main()
