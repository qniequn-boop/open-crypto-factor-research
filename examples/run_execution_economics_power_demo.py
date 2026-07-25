#!/usr/bin/env python3
"""Deterministic, data-free validator for the sanitized public package
``execution_economics_power_v1.json``.

The tool uses only the Python 3.11 standard library. It performs no network
access, reads no market data, and imports no private modules. It:

1. validates the package schema fail-closed, rejecting unknown keys at
   every documented object level;
2. recomputes the visible-book cost heterogeneity aggregates from the 15
   surface cells and compares them with the declared conclusion;
3. recomputes the OHLC bid-ask composite proxy admission decision from the
   declared aggregate rank statistics and the frozen 0.5 gate;
4. recomputes the frozen seven-rule detection-power classification from the
   per-window aggregate rates and compares it with the declared identity;
5. requires every authority field and every declared false-flag claim to
   remain false;
6. treats every published rate and band value used in the frozen
   classification as immutable evidence, so tampering fails validation even
   when the classification itself would remain unchanged.

Any malformed schema, unknown key, incomplete or duplicated cost cell,
changed power identity, tampered published rate, true authority field, or
true false-flag claim aborts with a non-zero exit code.

Usage:
    python run_execution_economics_power_demo.py [--package PATH] [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
PACKAGE_ID = "execution_economics_power_v1"

EXPECTED_COST_BASIS = "one_way_all_in_visible_book_includes_taker_fee"
EXPECTED_FEE_BPS = 5.0
EXPECTED_GRID_NOTIONALS = [100.0, 1000.0, 10000.0]
EXPECTED_ASSETS = [
    "LDO-USDT-SWAP",
    "LTC-USDT-SWAP",
    "SOL-USDT-SWAP",
    "TRX-USDT-SWAP",
    "XRP-USDT-SWAP",
]
EXPECTED_EXCLUSIONS = [
    "latency",
    "queue_position",
    "hidden_liquidity",
    "rejects",
    "outages",
    "production_capacity_inference",
]
EXPECTED_CELL_COUNT = 15
EXPECTED_REGIME_DAY_COUNT = 5

AUTHORITY_FIELDS = [
    "factor_admission_authorized",
    "combo_authorized",
    "paper_trading_authorized",
    "deployment_authorized",
    "capital_authorized",
]

TOP_LEVEL_KEYS = [
    "schema_version",
    "package_id",
    "kind",
    "created_at_utc",
    "scope",
    "authorities",
    "visible_book_cost_surface",
    "ohlc_proxy_admission",
    "cost_sensitivity_groups",
    "detection_power",
]
SCOPE_KEYS = [
    "description",
    "real_factor_tested",
    "mechanics_anchor_is_economic_evidence",
    "production_cost_calibration_supported",
    "production_capacity_inference_supported",
]
SURFACE_KEYS = [
    "surface_id",
    "cost_basis",
    "fee_included_bps",
    "asset_count",
    "frozen_date_count",
    "grid_notionals_usdt",
    "expected_cell_count",
    "exclusions",
    "assets",
    "cells",
    "heterogeneity_conclusion",
]
COST_CELL_KEYS = [
    "inst_id",
    "notional_usdt",
    "median_one_way_bps",
    "p95_one_way_bps",
    "min_buy_fill_fraction",
    "min_sell_fill_fraction",
    "regime_day_count",
]
HETEROGENEITY_KEYS = [
    "min_median_one_way_bps",
    "max_median_one_way_bps",
    "max_over_min_median_ratio",
    "min_p95_one_way_bps",
    "max_p95_one_way_bps",
    "max_over_min_p95_ratio",
    "median_cost_increases_with_notional_for_every_asset",
    "all_min_fill_fractions_complete",
]
PROXY_KEYS = [
    "proxy_name",
    "proxy_type",
    "valid_date_count",
    "dates_with_positive_rank",
    "median_cross_sectional_spearman",
    "frozen_gate_minimum_median_spearman",
    "admitted_for_cost_calibration",
    "role",
    "interpretation",
]
SENSITIVITY_KEYS = [
    "design",
    "metric",
    "groups",
    "conclusion",
    "profit_recipe_published",
    "named_path_outcomes_published",
]
SENSITIVITY_GROUP_KEYS = ["group", "range", "interpretation"]
POWER_KEYS = [
    "study_kind",
    "synthetic_only",
    "real_factor_tested",
    "windows_days",
    "feasible_horizon_windows_days",
    "reference_window_days",
    "replications_per_cell",
    "distinct_cell_count",
    "cell_count",
    "outcome_count",
    "realistic_outcome_count",
    "realistic_formal_pass_count",
    "null_bands",
    "cells",
    "classification_order",
    "expected_classification",
    "expected_matched_rule_order",
    "interpretation",
]
NULL_BAND_KEYS = [
    "screened_pass_successes_max",
    "screened_pass_wilson95_upper_max",
    "screened_watchlist_or_pass_rate_max",
]
POWER_CELL_BASE_KEYS = ["cell_id", "cell_type", "windows"]
WINDOW_ENTRY_KEYS = [
    "screened_pass_successes",
    "screened_pass_rate",
    "screened_watchlist_or_pass_rate",
]

EXPECTED_PROXY_NAME = "ohlc_bidask_composite_spread_proxy"
EXPECTED_PROXY_TYPE = "corwin_schultz_abdi_ranaldo_bidask_composite"

EXPECTED_SENSITIVITY_CONCLUSION = (
    "low_turnover_groups_comparatively_stable_higher_turnover_groups_deteriorated"
)
EXPECTED_SENSITIVITY_GROUPS = {
    "low_turnover_liquidity_amihud_rank_linear": ([-0.0074, -0.0066], "comparatively_stable"),
    "low_turnover_liquidity_amihud_top_bottom": ([-0.012, -0.012], "comparatively_stable"),
    "momentum": ([-0.37, -0.24], "deteriorated"),
    "funding_carry": ([-0.65, -0.51], "deteriorated"),
    "basis_carry": ([-0.65, -0.55], "deteriorated"),
    "short_reversal": ([-0.79, -0.67], "deteriorated"),
}

WINDOWS_DAYS = (124, 365, 730)
FEASIBLE_HORIZON_WINDOWS = (124, 365)
REFERENCE_WINDOW_DAYS = 730
REPLICATIONS_PER_CELL = 200

CLASSIFICATION_ORDER = [
    "false_pass_uncontrolled",
    "adequate_realistic_power_within_feasible_horizon",
    "adequate_realistic_power_only_beyond_feasible_horizon",
    "watchlist_power_only_within_feasible_horizon",
    "watchlist_power_only_beyond_feasible_horizon",
    "mechanically_open_realistic_power_insufficient",
    "mechanics_not_demonstrated",
]

NULL_CELL_IDS = ("null_full_panel", "null_large_liquid_only")
REALISTIC_CELL_IDS = (
    "full_panel_net_sharpe_0.30",
    "full_panel_net_sharpe_0.60",
    "large_liquid_only_net_sharpe_0.50",
)
MECHANICS_ANCHOR_CELL_ID = "mechanics_anchor_extreme_synthetic"

EXPECTED_NULL_BANDS = {
    "screened_pass_successes_max": 1,
    "screened_pass_wilson95_upper_max": 0.028,
    "screened_watchlist_or_pass_rate_max": 0.1,
}
EXPECTED_BAND_MINIMA = {
    "full_panel_net_sharpe_0.30": {
        "screened_pass_rate_min": 0.25,
        "screened_watchlist_or_pass_rate_min": 0.65,
    },
    "full_panel_net_sharpe_0.60": {
        "screened_pass_rate_min": 0.8,
        "screened_watchlist_or_pass_rate_min": 0.95,
    },
    "large_liquid_only_net_sharpe_0.50": {
        "screened_pass_rate_min": 0.15,
        "screened_watchlist_or_pass_rate_min": 0.8,
    },
    MECHANICS_ANCHOR_CELL_ID: {"screened_pass_rate_min": 0.8},
}
EXPECTED_WINDOW_RATES = {
    "null_full_panel": {
        "124": (0, 0.0, 0.005),
        "365": (0, 0.0, 0.0),
        "730": (0, 0.0, 0.0),
    },
    "null_large_liquid_only": {
        "124": (0, 0.0, 0.01),
        "365": (0, 0.0, 0.005),
        "730": (0, 0.0, 0.01),
    },
    "full_panel_net_sharpe_0.30": {
        "124": (0, 0.0, 0.29),
        "365": (0, 0.0, 0.32),
        "730": (0, 0.0, 0.395),
    },
    "full_panel_net_sharpe_0.60": {
        "124": (0, 0.0, 0.43),
        "365": (0, 0.0, 0.51),
        "730": (0, 0.0, 0.615),
    },
    "large_liquid_only_net_sharpe_0.50": {
        "124": (0, 0.0, 0.15),
        "365": (0, 0.0, 0.28),
        "730": (0, 0.0, 0.385),
    },
    MECHANICS_ANCHOR_CELL_ID: {
        "124": (200, 1.0, 1.0),
        "365": (200, 1.0, 1.0),
        "730": (200, 1.0, 1.0),
    },
}

# Standard-normal 0.975 quantile used by the Wilson score interval.
Z_975 = 1.959963984540054


class PackageError(Exception):
    """Raised when the package fails any fail-closed validation."""


def _fail(message: str) -> None:
    raise PackageError(message)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"schema:{name}:not_an_object")
    return value


def _require_key_set(mapping: dict[str, Any], expected_keys: list[str], name: str) -> None:
    """Fail closed on any unknown or missing key at a documented level."""
    actual = set(mapping.keys())
    expected = set(expected_keys)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    _require(not unknown, f"schema:{name}:unknown_keys:{','.join(unknown)}")
    _require(not missing, f"schema:{name}:missing_keys:{','.join(missing)}")


def _wilson95_upper(successes: int, trials: int) -> float:
    """Upper bound of the 95% Wilson score interval for a binomial rate."""
    if trials <= 0:
        _fail("power:wilson:non_positive_trials")
    p = successes / trials
    z2 = Z_975 * Z_975
    denominator = 1.0 + z2 / trials
    centre = p + z2 / (2.0 * trials)
    margin = Z_975 * math.sqrt(p * (1.0 - p) / trials + z2 / (4.0 * trials * trials))
    return (centre + margin) / denominator


def load_package(path: str | Path) -> dict[str, Any]:
    package_path = Path(path)
    try:
        raw = package_path.read_text(encoding="utf-8")
    except OSError as exc:
        _fail(f"io:cannot_read_package:{exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"schema:invalid_json:{exc}")
    return _require_mapping(data, "package")


def validate_identity(package: dict[str, Any]) -> None:
    _require_key_set(package, TOP_LEVEL_KEYS, "package")
    _require(package.get("schema_version") == SCHEMA_VERSION, "schema:schema_version_mismatch")
    _require(package.get("package_id") == PACKAGE_ID, "schema:package_id_mismatch")
    _require(package.get("kind") == "sanitized_public_research_package", "schema:kind_mismatch")
    scope = _require_mapping(package.get("scope"), "scope")
    _require_key_set(scope, SCOPE_KEYS, "scope")
    _require(scope.get("real_factor_tested") is False, "scope:real_factor_tested_not_false")
    _require(
        scope.get("mechanics_anchor_is_economic_evidence") is False,
        "scope:mechanics_anchor_marked_as_economic_evidence",
    )
    _require(
        scope.get("production_cost_calibration_supported") is False,
        "scope:production_cost_calibration_supported_not_false",
    )
    _require(
        scope.get("production_capacity_inference_supported") is False,
        "scope:production_capacity_inference_supported_not_false",
    )


def validate_authorities(package: dict[str, Any]) -> dict[str, bool]:
    authorities = _require_mapping(package.get("authorities"), "authorities")
    _require_key_set(authorities, AUTHORITY_FIELDS, "authorities")
    for field in AUTHORITY_FIELDS:
        value = authorities[field]
        _require(isinstance(value, bool), f"authorities:{field}:not_boolean")
        _require(value is False, f"authorities:{field}:true_authority_refused")
    return {field: authorities[field] for field in AUTHORITY_FIELDS}


def recompute_cost_heterogeneity(package: dict[str, Any]) -> dict[str, Any]:
    surface = _require_mapping(package.get("visible_book_cost_surface"), "visible_book_cost_surface")
    _require_key_set(surface, SURFACE_KEYS, "visible_book_cost_surface")
    _require(surface.get("cost_basis") == EXPECTED_COST_BASIS, "cost:basis_mismatch")
    _require(surface.get("fee_included_bps") == EXPECTED_FEE_BPS, "cost:fee_included_bps_mismatch")
    _require(surface.get("exclusions") == EXPECTED_EXCLUSIONS, "cost:exclusions_mismatch")
    _require(surface.get("grid_notionals_usdt") == EXPECTED_GRID_NOTIONALS, "cost:grid_mismatch")
    _require(surface.get("assets") == EXPECTED_ASSETS, "cost:asset_set_mismatch")
    _require(surface.get("expected_cell_count") == EXPECTED_CELL_COUNT, "cost:expected_cell_count_mismatch")
    _require(surface.get("asset_count") == len(EXPECTED_ASSETS), "cost:asset_count_mismatch")
    _require(surface.get("frozen_date_count") == EXPECTED_REGIME_DAY_COUNT, "cost:frozen_date_count_mismatch")

    cells = surface.get("cells")
    _require(isinstance(cells, list), "cost:cells_not_a_list")
    _require(len(cells) == EXPECTED_CELL_COUNT, f"cost:incomplete_cells:{len(cells)}")

    seen: set[tuple[str, float]] = set()
    medians: list[float] = []
    p95s: list[float] = []
    per_asset_medians: dict[str, list[tuple[float, float]]] = {}
    for cell in cells:
        cell = _require_mapping(cell, "cost_cell")
        _require_key_set(cell, COST_CELL_KEYS, "cost_cell")
        inst = cell.get("inst_id")
        notional = cell.get("notional_usdt")
        _require(isinstance(inst, str) and inst in EXPECTED_ASSETS, "cost:unknown_asset")
        _require(_is_finite_number(notional) and float(notional) in EXPECTED_GRID_NOTIONALS, "cost:unknown_notional")
        key = (inst, float(notional))
        _require(key not in seen, f"cost:duplicate_cell:{inst}:{notional}")
        seen.add(key)
        median = cell.get("median_one_way_bps")
        p95 = cell.get("p95_one_way_bps")
        _require(_is_finite_number(median) and median > 0, "cost:bad_median")
        _require(_is_finite_number(p95) and p95 >= median, "cost:bad_p95")
        for field in ("min_buy_fill_fraction", "min_sell_fill_fraction"):
            value = cell.get(field)
            _require(_is_finite_number(value) and 0.0 <= value <= 1.0, f"cost:bad_{field}")
        _require(cell.get("regime_day_count") == EXPECTED_REGIME_DAY_COUNT, "cost:regime_day_count_mismatch")
        medians.append(float(median))
        p95s.append(float(p95))
        per_asset_medians.setdefault(inst, []).append((float(notional), float(median)))

    for inst in EXPECTED_ASSETS:
        _require(len(per_asset_medians.get(inst, [])) == len(EXPECTED_GRID_NOTIONALS), f"cost:incomplete_asset:{inst}")

    monotonic = all(
        [m for _, m in sorted(entries)] == sorted(m for _, m in entries)
        for entries in per_asset_medians.values()
    )
    fills_complete = all(
        cell["min_buy_fill_fraction"] == 1.0 and cell["min_sell_fill_fraction"] == 1.0
        for cell in cells
    )

    recomputed = {
        "min_median_one_way_bps": min(medians),
        "max_median_one_way_bps": max(medians),
        "max_over_min_median_ratio": round(max(medians) / min(medians), 4),
        "min_p95_one_way_bps": min(p95s),
        "max_p95_one_way_bps": max(p95s),
        "max_over_min_p95_ratio": round(max(p95s) / min(p95s), 4),
        "median_cost_increases_with_notional_for_every_asset": monotonic,
        "all_min_fill_fractions_complete": fills_complete,
    }

    declared = _require_mapping(surface.get("heterogeneity_conclusion"), "heterogeneity_conclusion")
    _require_key_set(declared, HETEROGENEITY_KEYS, "heterogeneity_conclusion")
    for field, value in recomputed.items():
        _require(declared.get(field) == value, f"cost:heterogeneity_mismatch:{field}")
    return recomputed


def recompute_proxy_admission(package: dict[str, Any]) -> dict[str, Any]:
    proxy = _require_mapping(package.get("ohlc_proxy_admission"), "ohlc_proxy_admission")
    _require_key_set(proxy, PROXY_KEYS, "ohlc_proxy_admission")
    _require(proxy.get("proxy_name") == EXPECTED_PROXY_NAME, "proxy:identity_changed")
    _require(proxy.get("proxy_type") == EXPECTED_PROXY_TYPE, "proxy:identity_changed")
    valid_dates = proxy.get("valid_date_count")
    positive_dates = proxy.get("dates_with_positive_rank")
    median = proxy.get("median_cross_sectional_spearman")
    gate = proxy.get("frozen_gate_minimum_median_spearman")
    _require(isinstance(valid_dates, int) and valid_dates > 0, "proxy:bad_valid_date_count")
    _require(
        isinstance(positive_dates, int) and 0 <= positive_dates <= valid_dates,
        "proxy:bad_positive_date_count",
    )
    _require(_is_finite_number(median) and -1.0 <= median <= 1.0, "proxy:bad_median_spearman")
    _require(_is_finite_number(gate) and 0.0 < gate <= 1.0, "proxy:bad_gate")
    admitted = bool(float(median) >= float(gate))
    _require(
        proxy.get("admitted_for_cost_calibration") is admitted,
        "proxy:admission_mismatch",
    )
    if admitted:
        _require(proxy.get("role") != "ranking_diagnostic_only", "proxy:role_inconsistent")
    else:
        _require(proxy.get("role") == "ranking_diagnostic_only", "proxy:role_inconsistent")
    return {
        "valid_date_count": valid_dates,
        "dates_with_positive_rank": positive_dates,
        "median_cross_sectional_spearman": float(median),
        "frozen_gate_minimum_median_spearman": float(gate),
        "admitted_for_cost_calibration": admitted,
        "role": proxy.get("role"),
    }


def validate_cost_sensitivity(package: dict[str, Any]) -> None:
    sensitivity = _require_mapping(package.get("cost_sensitivity_groups"), "cost_sensitivity_groups")
    _require_key_set(sensitivity, SENSITIVITY_KEYS, "cost_sensitivity_groups")
    _require(
        sensitivity.get("profit_recipe_published") is False,
        "sensitivity:profit_recipe_published_not_false",
    )
    _require(
        sensitivity.get("named_path_outcomes_published") is False,
        "sensitivity:named_path_outcomes_published_not_false",
    )
    _require(
        sensitivity.get("conclusion") == EXPECTED_SENSITIVITY_CONCLUSION,
        "sensitivity:conclusion_changed",
    )
    groups = sensitivity.get("groups")
    _require(isinstance(groups, list), "sensitivity:groups_not_a_list")
    by_group: dict[str, dict[str, Any]] = {}
    for group in groups:
        group = _require_mapping(group, "sensitivity_group")
        _require_key_set(group, SENSITIVITY_GROUP_KEYS, "sensitivity_group")
        group_id = group.get("group")
        _require(isinstance(group_id, str), "sensitivity:group_id_missing")
        _require(group_id not in by_group, f"sensitivity:duplicate_group:{group_id}")
        by_group[group_id] = group
    _require(set(by_group.keys()) == set(EXPECTED_SENSITIVITY_GROUPS), "sensitivity:group_set_mismatch")
    for group_id, (expected_range, expected_interpretation) in EXPECTED_SENSITIVITY_GROUPS.items():
        group = by_group[group_id]
        _require(group.get("range") == expected_range, f"sensitivity:{group_id}:range_changed")
        _require(
            group.get("interpretation") == expected_interpretation,
            f"sensitivity:{group_id}:interpretation_changed",
        )


def _window_entry(cell: dict[str, Any], window: int, cell_id: str) -> dict[str, Any]:
    windows = _require_mapping(cell.get("windows"), f"power:{cell_id}:windows")
    entry = _require_mapping(windows.get(str(window)), f"power:{cell_id}:window_{window}")
    _require_key_set(entry, WINDOW_ENTRY_KEYS, f"power:{cell_id}:window_{window}")
    successes = entry.get("screened_pass_successes")
    pass_rate = entry.get("screened_pass_rate")
    watchlist_rate = entry.get("screened_watchlist_or_pass_rate")
    _require(
        isinstance(successes, int) and 0 <= successes <= REPLICATIONS_PER_CELL,
        f"power:{cell_id}:bad_pass_successes",
    )
    _require(_is_finite_number(pass_rate) and 0.0 <= pass_rate <= 1.0, f"power:{cell_id}:bad_pass_rate")
    _require(
        _is_finite_number(watchlist_rate) and 0.0 <= watchlist_rate <= 1.0,
        f"power:{cell_id}:bad_watchlist_rate",
    )
    _require(
        abs(float(pass_rate) - successes / REPLICATIONS_PER_CELL) < 1e-9,
        f"power:{cell_id}:pass_rate_inconsistent_with_successes",
    )
    expected_rates = EXPECTED_WINDOW_RATES.get(cell_id, {}).get(str(window))
    _require(expected_rates is not None, f"power:{cell_id}:unexpected_window:{window}")
    _require(
        (successes, float(pass_rate), float(watchlist_rate)) == tuple(expected_rates),
        f"power:{cell_id}:window_{window}:rate_tampered",
    )
    return {
        "screened_pass_successes": successes,
        "screened_pass_rate": float(pass_rate),
        "screened_watchlist_or_pass_rate": float(watchlist_rate),
    }


def recompute_power_classification(package: dict[str, Any]) -> dict[str, Any]:
    power = _require_mapping(package.get("detection_power"), "detection_power")
    _require_key_set(power, POWER_KEYS, "detection_power")
    _require(power.get("synthetic_only") is True, "power:synthetic_only_not_true")
    _require(power.get("real_factor_tested") is False, "power:real_factor_tested_not_false")
    _require(power.get("windows_days") == list(WINDOWS_DAYS), "power:windows_mismatch")
    _require(
        power.get("feasible_horizon_windows_days") == list(FEASIBLE_HORIZON_WINDOWS),
        "power:feasible_windows_mismatch",
    )
    _require(power.get("reference_window_days") == REFERENCE_WINDOW_DAYS, "power:reference_window_mismatch")
    _require(power.get("replications_per_cell") == REPLICATIONS_PER_CELL, "power:replications_mismatch")
    _require(
        power.get("classification_order") == CLASSIFICATION_ORDER,
        "power:classification_order_mismatch",
    )

    null_bands = _require_mapping(power.get("null_bands"), "null_bands")
    _require_key_set(null_bands, NULL_BAND_KEYS, "null_bands")
    for field, expected_value in EXPECTED_NULL_BANDS.items():
        _require(
            null_bands.get(field) == expected_value,
            f"power:null_band_value_changed:{field}",
        )
    null_pass_max = null_bands["screened_pass_successes_max"]
    null_wilson_max = null_bands["screened_pass_wilson95_upper_max"]
    null_watchlist_max = null_bands["screened_watchlist_or_pass_rate_max"]

    cells = power.get("cells")
    _require(isinstance(cells, list), "power:cells_not_a_list")
    by_id: dict[str, dict[str, Any]] = {}
    for cell in cells:
        cell = _require_mapping(cell, "power_cell")
        cell_id = cell.get("cell_id")
        _require(isinstance(cell_id, str), "power:cell_id_missing")
        _require(cell_id not in by_id, f"power:duplicate_cell:{cell_id}")
        by_id[cell_id] = cell
    expected_ids = set(NULL_CELL_IDS) | set(REALISTIC_CELL_IDS) | {MECHANICS_ANCHOR_CELL_ID}
    _require(set(by_id.keys()) == expected_ids, "power:cell_id_set_mismatch")
    for cell_id in NULL_CELL_IDS:
        _require(by_id[cell_id].get("cell_type") == "null", f"power:{cell_id}:cell_type_mismatch")
    for cell_id in REALISTIC_CELL_IDS:
        _require(
            by_id[cell_id].get("cell_type") == "realistic_reference_effect",
            f"power:{cell_id}:cell_type_mismatch",
        )
    anchor = by_id[MECHANICS_ANCHOR_CELL_ID]
    _require(anchor.get("cell_type") == "mechanics_only_anchor", "power:anchor:cell_type_mismatch")
    _require(anchor.get("diagnostic_only") is True, "power:anchor:not_marked_diagnostic_only")
    _require(
        anchor.get("excluded_from_realistic_power_claims") is True,
        "power:anchor:not_excluded_from_realistic_claims",
    )

    for cell_id, cell in by_id.items():
        expected_cell_keys = list(POWER_CELL_BASE_KEYS)
        if cell_id in REALISTIC_CELL_IDS:
            expected_cell_keys = expected_cell_keys + ["band_minima"]
        elif cell_id == MECHANICS_ANCHOR_CELL_ID:
            expected_cell_keys = expected_cell_keys + [
                "diagnostic_only",
                "excluded_from_realistic_power_claims",
                "band_minima",
            ]
        _require_key_set(cell, expected_cell_keys, f"power:{cell_id}:cell")
        cell_windows = _require_mapping(cell.get("windows"), f"power:{cell_id}:windows")
        _require_key_set(cell_windows, [str(w) for w in WINDOWS_DAYS], f"power:{cell_id}:windows")

    window_evaluations: dict[int, dict[str, bool]] = {}
    for window in WINDOWS_DAYS:
        null_breach = False
        for cell_id in NULL_CELL_IDS:
            entry = _window_entry(by_id[cell_id], window, cell_id)
            wilson_upper = _wilson95_upper(entry["screened_pass_successes"], REPLICATIONS_PER_CELL)
            passed = (
                entry["screened_pass_successes"] <= null_pass_max
                and wilson_upper <= float(null_wilson_max)
                and entry["screened_watchlist_or_pass_rate"] <= float(null_watchlist_max)
            )
            if not passed:
                null_breach = True

        realistic_both = True
        realistic_watchlist = True
        for cell_id in REALISTIC_CELL_IDS:
            band = _require_mapping(by_id[cell_id].get("band_minima"), f"power:{cell_id}:band_minima")
            expected_band = EXPECTED_BAND_MINIMA[cell_id]
            _require_key_set(band, list(expected_band.keys()), f"power:{cell_id}:band_minima")
            for field, expected_value in expected_band.items():
                _require(
                    band.get(field) == expected_value,
                    f"power:{cell_id}:band_minima_changed:{field}",
                )
            pass_min = band["screened_pass_rate_min"]
            watchlist_min = band["screened_watchlist_or_pass_rate_min"]
            entry = _window_entry(by_id[cell_id], window, cell_id)
            if not (
                entry["screened_pass_rate"] >= float(pass_min)
                and entry["screened_watchlist_or_pass_rate"] >= float(watchlist_min)
            ):
                realistic_both = False
            if entry["screened_watchlist_or_pass_rate"] < float(watchlist_min):
                realistic_watchlist = False

        anchor_band = _require_mapping(anchor.get("band_minima"), "power:anchor:band_minima")
        expected_anchor_band = EXPECTED_BAND_MINIMA[MECHANICS_ANCHOR_CELL_ID]
        _require_key_set(anchor_band, list(expected_anchor_band.keys()), "power:anchor:band_minima")
        anchor_min = anchor_band["screened_pass_rate_min"]
        _require(
            anchor_min == expected_anchor_band["screened_pass_rate_min"],
            "power:anchor:band_minima_changed:screened_pass_rate_min",
        )
        anchor_entry = _window_entry(anchor, window, MECHANICS_ANCHOR_CELL_ID)

        window_evaluations[window] = {
            "null_breach": null_breach,
            "realistic_both_bands_met": realistic_both,
            "realistic_watchlist_minimum_met": realistic_watchlist,
            "mechanics_anchor_pass_minimum_met": anchor_entry["screened_pass_rate"] >= float(anchor_min),
        }

    evals = window_evaluations
    rule_checks = [
        any(evals[w]["null_breach"] for w in WINDOWS_DAYS),
        any(evals[w]["realistic_both_bands_met"] for w in FEASIBLE_HORIZON_WINDOWS),
        evals[REFERENCE_WINDOW_DAYS]["realistic_both_bands_met"],
        any(evals[w]["realistic_watchlist_minimum_met"] for w in FEASIBLE_HORIZON_WINDOWS),
        evals[REFERENCE_WINDOW_DAYS]["realistic_watchlist_minimum_met"],
        any(evals[w]["mechanics_anchor_pass_minimum_met"] for w in WINDOWS_DAYS),
        True,
    ]
    matched_order = len(CLASSIFICATION_ORDER)
    for index, matched in enumerate(rule_checks):
        if matched:
            matched_order = index + 1
            break
    classification = CLASSIFICATION_ORDER[matched_order - 1]

    realistic_formal_passes = sum(
        _window_entry(by_id[cell_id], window, cell_id)["screened_pass_successes"]
        for cell_id in REALISTIC_CELL_IDS
        for window in WINDOWS_DAYS
    )
    outcome_count = len(by_id) * len(WINDOWS_DAYS) * REPLICATIONS_PER_CELL
    realistic_outcome_count = len(REALISTIC_CELL_IDS) * len(WINDOWS_DAYS) * REPLICATIONS_PER_CELL
    _require(power.get("distinct_cell_count") == len(by_id), "power:distinct_cell_count_mismatch")
    _require(power.get("cell_count") == outcome_count // REPLICATIONS_PER_CELL, "power:cell_count_mismatch")
    _require(power.get("outcome_count") == outcome_count, "power:outcome_count_mismatch")
    _require(
        power.get("realistic_outcome_count") == realistic_outcome_count,
        "power:realistic_outcome_count_mismatch",
    )
    _require(
        power.get("realistic_formal_pass_count") == realistic_formal_passes,
        "power:realistic_formal_pass_count_mismatch",
    )

    _require(
        power.get("expected_classification") == classification,
        f"power:classification_identity_changed:{power.get('expected_classification')}!={classification}",
    )
    _require(
        power.get("expected_matched_rule_order") == matched_order,
        "power:matched_rule_order_changed",
    )

    return {
        "classification": classification,
        "matched_rule_order": matched_order,
        "window_evaluations": {str(w): evals[w] for w in WINDOWS_DAYS},
        "outcome_count": outcome_count,
        "realistic_outcome_count": realistic_outcome_count,
        "realistic_formal_pass_count": realistic_formal_passes,
        "mechanics_anchor_diagnostic_only": True,
        "real_factor_tested": False,
    }


def evaluate_package(package: dict[str, Any]) -> dict[str, Any]:
    validate_identity(package)
    authorities = validate_authorities(package)
    cost = recompute_cost_heterogeneity(package)
    proxy = recompute_proxy_admission(package)
    validate_cost_sensitivity(package)
    power = recompute_power_classification(package)
    return {
        "package_id": package["package_id"],
        "schema_version": package["schema_version"],
        "status": "ok",
        "authorities": authorities,
        "cost_heterogeneity": cost,
        "proxy_admission": proxy,
        "detection_power": power,
    }


def _format_human(report: dict[str, Any]) -> str:
    cost = report["cost_heterogeneity"]
    proxy = report["proxy_admission"]
    power = report["detection_power"]
    lines = [
        "Sanitized public package validation: OK",
        f"package_id: {report['package_id']} (schema {report['schema_version']})",
        "",
        "Authorities (all must be false):",
    ]
    lines += [f"  {name}: {value}" for name, value in sorted(report["authorities"].items())]
    lines += [
        "",
        "Visible-book cost heterogeneity (15 cells, 5 assets x 3 notionals, 5 bps taker fee included):",
        f"  median one-way cost range: {cost['min_median_one_way_bps']:.4f} to {cost['max_median_one_way_bps']:.4f} bps"
        f" (max/min {cost['max_over_min_median_ratio']})",
        f"  p95 one-way cost range:    {cost['min_p95_one_way_bps']:.4f} to {cost['max_p95_one_way_bps']:.4f} bps"
        f" (max/min {cost['max_over_min_p95_ratio']})",
        f"  median cost rises with notional for every asset: {cost['median_cost_increases_with_notional_for_every_asset']}",
        f"  all minimum fill fractions complete: {cost['all_min_fill_fractions_complete']}",
        "",
        "OHLC bid-ask composite proxy admission:",
        f"  positive rank on {proxy['dates_with_positive_rank']} of {proxy['valid_date_count']} dates;"
        f" median cross-sectional Spearman {proxy['median_cross_sectional_spearman']}"
        f" vs frozen gate {proxy['frozen_gate_minimum_median_spearman']}",
        f"  admitted for cost calibration: {proxy['admitted_for_cost_calibration']} (role: {proxy['role']})",
        "",
        "Detection power (synthetic study; no real factor was tested):",
        f"  classification: {power['classification']} (rule {power['matched_rule_order']} of 7)",
        f"  outcomes: {power['outcome_count']} total,"
        f" {power['realistic_outcome_count']} realistic,"
        f" realistic formal passes: {power['realistic_formal_pass_count']}",
        f"  mechanics anchor diagnostic only: {power['mechanics_anchor_diagnostic_only']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the sanitized execution-economics and detection-power package."
    )
    parser.add_argument(
        "--package",
        default=str(Path(__file__).resolve().with_name("execution_economics_power_v1.json")),
        help="Path to execution_economics_power_v1.json (default: sibling of this script).",
    )
    parser.add_argument("--json", action="store_true", help="Emit the validation report as JSON.")
    args = parser.parse_args(argv)

    try:
        package = load_package(args.package)
        report = evaluate_package(package)
    except PackageError as exc:
        message = {"status": "error", "error": str(exc)}
        if args.json:
            print(json.dumps(message, indent=2, sort_keys=True))
        else:
            print(f"Package validation FAILED: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_format_human(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
