"""Focused tests for the sanitized public execution-economics package demo.

These tests are data-free and deterministic: they validate the shipped JSON
package, the recomputed conclusions, the false authority fields and
false-flag claims, fail-closed behaviour on unknown keys and tampered
copies, the immutable published rates, the CLI output modes, and the public
repository relocation layout.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_PATH = REPOSITORY_ROOT / "evidence" / "execution_economics_power_v1.json"
DEMO_PATH = REPOSITORY_ROOT / "examples" / "run_execution_economics_power_demo.py"

spec = importlib.util.spec_from_file_location("run_execution_economics_power_demo", DEMO_PATH)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def _load_package() -> dict:
    return json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))


def _power_cells(package: dict) -> dict:
    return {cell["cell_id"]: cell for cell in package["detection_power"]["cells"]}


def _write_tampered(tmp_path: Path, mutate) -> Path:
    package = _load_package()
    mutate(package)
    target = tmp_path / "tampered_package.json"
    target.write_text(json.dumps(package), encoding="utf-8")
    return target


# --- Package identity -------------------------------------------------------


def test_package_identity():
    package = _load_package()
    assert package["schema_version"] == "1.0"
    assert package["package_id"] == "execution_economics_power_v1"
    assert package["kind"] == "sanitized_public_research_package"
    assert package["scope"]["real_factor_tested"] is False
    assert package["scope"]["mechanics_anchor_is_economic_evidence"] is False

    surface = package["visible_book_cost_surface"]
    assert surface["asset_count"] == 5
    assert surface["frozen_date_count"] == 5
    assert surface["fee_included_bps"] == 5.0
    assert len(surface["cells"]) == 15
    assert len({(c["inst_id"], c["notional_usdt"]) for c in surface["cells"]}) == 15
    assert len({c["inst_id"] for c in surface["cells"]}) == 5
    assert {c["notional_usdt"] for c in surface["cells"]} == {100.0, 1000.0, 10000.0}
    assert all(c["regime_day_count"] == 5 for c in surface["cells"])


def test_full_evaluation_passes_on_shipped_package():
    report = demo.evaluate_package(demo.load_package(PACKAGE_PATH))
    assert report["status"] == "ok"


# --- Cost and proxy conclusions ----------------------------------------------

def test_cost_heterogeneity_recomputed():
    report = demo.evaluate_package(demo.load_package(PACKAGE_PATH))
    cost = report["cost_heterogeneity"]
    assert cost["min_median_one_way_bps"] == pytest.approx(5.1841349346407455)
    assert cost["max_median_one_way_bps"] == pytest.approx(12.9109512975701)
    assert cost["max_over_min_median_ratio"] == pytest.approx(2.4905, abs=1e-4)
    assert cost["max_over_min_p95_ratio"] == pytest.approx(5.7581, abs=1e-4)
    assert cost["median_cost_increases_with_notional_for_every_asset"] is True
    assert cost["all_min_fill_fractions_complete"] is True


def test_proxy_rejected_by_frozen_gate():
    report = demo.evaluate_package(demo.load_package(PACKAGE_PATH))
    proxy = report["proxy_admission"]
    assert proxy["dates_with_positive_rank"] == 5
    assert proxy["valid_date_count"] == 5
    assert proxy["median_cross_sectional_spearman"] == pytest.approx(0.4)
    assert proxy["frozen_gate_minimum_median_spearman"] == pytest.approx(0.5)
    assert proxy["admitted_for_cost_calibration"] is False
    assert proxy["role"] == "ranking_diagnostic_only"


def test_proxy_identity_is_corrected_composite():
    package = _load_package()
    proxy = package["ohlc_proxy_admission"]
    assert proxy["proxy_name"] == "ohlc_bidask_composite_spread_proxy"
    assert proxy["proxy_type"] == "corwin_schultz_abdi_ranaldo_bidask_composite"
    construction = proxy["interpretation"]
    assert "Corwin-Schultz" in construction
    assert "Abdi-Ranaldo" in construction
    assert "two-day-corrected" in construction
    assert "29 overlapping pairs" in construction


def test_cost_sensitivity_group_conclusion_public_safe():
    package = _load_package()
    groups = package["cost_sensitivity_groups"]
    assert groups["conclusion"] == (
        "low_turnover_groups_comparatively_stable_higher_turnover_groups_deteriorated"
    )
    assert groups["profit_recipe_published"] is False
    assert groups["named_path_outcomes_published"] is False
    stable = [g for g in groups["groups"] if g["interpretation"] == "comparatively_stable"]
    deteriorated = [g for g in groups["groups"] if g["interpretation"] == "deteriorated"]
    assert len(stable) == 2 and len(deteriorated) == 4
    assert all(g["range"][1] >= -0.0121 for g in stable)
    assert all(g["range"][0] <= -0.24 for g in deteriorated)


# --- Power classification -----------------------------------------------------

def test_power_classification_identity():
    report = demo.evaluate_package(demo.load_package(PACKAGE_PATH))
    power = report["detection_power"]
    assert power["classification"] == "mechanically_open_realistic_power_insufficient"
    assert power["matched_rule_order"] == 6
    assert power["outcome_count"] == 3600
    assert power["realistic_outcome_count"] == 1800
    assert power["realistic_formal_pass_count"] == 0
    assert power["mechanics_anchor_diagnostic_only"] is True
    assert power["real_factor_tested"] is False


def test_power_frozen_window_rates():
    package = _load_package()
    cells = _power_cells(package)
    expected_watchlist = {
        "full_panel_net_sharpe_0.30": {"124": 0.29, "365": 0.32, "730": 0.395},
        "full_panel_net_sharpe_0.60": {"124": 0.43, "365": 0.51, "730": 0.615},
        "large_liquid_only_net_sharpe_0.50": {"124": 0.15, "365": 0.28, "730": 0.385},
    }
    expected_minima = {
        "full_panel_net_sharpe_0.30": 0.65,
        "full_panel_net_sharpe_0.60": 0.95,
        "large_liquid_only_net_sharpe_0.50": 0.8,
    }
    for cell_id, per_window in expected_watchlist.items():
        for window, rate in per_window.items():
            assert cells[cell_id]["windows"][window]["screened_watchlist_or_pass_rate"] == rate
            assert cells[cell_id]["windows"][window]["screened_pass_rate"] == 0.0
            assert rate < expected_minima[cell_id]
    for null_id in ("null_full_panel", "null_large_liquid_only"):
        for window in ("124", "365", "730"):
            entry = cells[null_id]["windows"][window]
            assert entry["screened_pass_successes"] == 0
            assert entry["screened_watchlist_or_pass_rate"] <= 0.1
    anchor = cells["mechanics_anchor_extreme_synthetic"]
    assert anchor["diagnostic_only"] is True
    for window in ("124", "365", "730"):
        assert anchor["windows"][window]["screened_pass_rate"] == 1.0


def test_anchor_identity_is_loading_free():
    raw_package = PACKAGE_PATH.read_text(encoding="utf-8")
    raw_demo = DEMO_PATH.read_text(encoding="utf-8")
    assert "mechanics_anchor_loading" not in raw_package
    assert "mechanics_anchor_loading" not in raw_demo
    assert "mechanics_anchor_extreme_synthetic" in raw_package
    assert demo.MECHANICS_ANCHOR_CELL_ID == "mechanics_anchor_extreme_synthetic"
    anchor = _power_cells(_load_package())["mechanics_anchor_extreme_synthetic"]
    assert not any("loading" in key for key in anchor)


# --- False authorities --------------------------------------------------------


def test_all_authorities_false():
    package = _load_package()
    assert set(package["authorities"]) == set(demo.AUTHORITY_FIELDS)
    assert all(value is False for value in package["authorities"].values())


# --- Fail-closed tampering ----------------------------------------------------


def test_fail_closed_on_malformed_schema(tmp_path):
    def mutate(package):
        del package["detection_power"]

    with pytest.raises(demo.PackageError):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


def test_fail_closed_on_wrong_package_id(tmp_path):
    def mutate(package):
        package["package_id"] = "execution_economics_power_v2"

    with pytest.raises(demo.PackageError):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


def test_fail_closed_on_incomplete_cost_cells(tmp_path):
    def mutate(package):
        package["visible_book_cost_surface"]["cells"] = package["visible_book_cost_surface"]["cells"][:14]

    with pytest.raises(demo.PackageError, match="incomplete_cells"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


def test_fail_closed_on_duplicate_cost_cell(tmp_path):
    def mutate(package):
        cells = package["visible_book_cost_surface"]["cells"]
        cells[-1] = copy.deepcopy(cells[0])

    with pytest.raises(demo.PackageError, match="duplicate_cell"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


def test_fail_closed_on_changed_power_identity(tmp_path):
    def mutate(package):
        package["detection_power"]["expected_classification"] = (
            "adequate_realistic_power_within_feasible_horizon"
        )
        package["detection_power"]["expected_matched_rule_order"] = 2

    with pytest.raises(demo.PackageError, match="classification_identity_changed"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


def test_fail_closed_on_tampered_power_rate_changes_classification(tmp_path):
    def mutate(package):
        for cell in package["detection_power"]["cells"]:
            if cell["cell_id"] == "null_full_panel":
                cell["windows"]["124"]["screened_watchlist_or_pass_rate"] = 0.5

    # Published rates are immutable evidence: the tamper is refused before
    # the classification is even recomputed.
    with pytest.raises(demo.PackageError, match="rate_tampered"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


@pytest.mark.parametrize("field", demo.AUTHORITY_FIELDS)
def test_fail_closed_on_any_true_authority(tmp_path, field):
    def mutate(package):
        package["authorities"][field] = True

    with pytest.raises(demo.PackageError, match="true_authority_refused"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


def test_fail_closed_on_tampered_heterogeneity_conclusion(tmp_path):
    def mutate(package):
        package["visible_book_cost_surface"]["heterogeneity_conclusion"]["max_over_min_median_ratio"] = 1.0

    with pytest.raises(demo.PackageError, match="heterogeneity_mismatch"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


def test_fail_closed_on_tampered_proxy_admission(tmp_path):
    def mutate(package):
        package["ohlc_proxy_admission"]["admitted_for_cost_calibration"] = True

    with pytest.raises(demo.PackageError, match="proxy:admission_mismatch"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


# --- Fail-closed on unknown keys at every documented object level -------------

UNKNOWN_KEY_CASES = [
    ("top_level", lambda p: p.__setitem__("unexpected_top_level", 1)),
    ("scope", lambda p: p["scope"].__setitem__("unexpected_scope", 1)),
    ("authorities", lambda p: p["authorities"].__setitem__("unexpected_authority", False)),
    ("visible_book_section", lambda p: p["visible_book_cost_surface"].__setitem__("unexpected_surface", 1)),
    ("cost_cell", lambda p: p["visible_book_cost_surface"]["cells"][0].__setitem__("unexpected_cell", 1)),
    (
        "heterogeneity_conclusion",
        lambda p: p["visible_book_cost_surface"]["heterogeneity_conclusion"].__setitem__(
            "unexpected_heterogeneity", 1
        ),
    ),
    ("proxy_section", lambda p: p["ohlc_proxy_admission"].__setitem__("unexpected_proxy", 1)),
    ("sensitivity_section", lambda p: p["cost_sensitivity_groups"].__setitem__("unexpected_sensitivity", 1)),
    ("sensitivity_group", lambda p: p["cost_sensitivity_groups"]["groups"][0].__setitem__("unexpected_group", 1)),
    ("detection_power_section", lambda p: p["detection_power"].__setitem__("unexpected_power", 1)),
    ("null_bands", lambda p: p["detection_power"]["null_bands"].__setitem__("unexpected_null_band", 1)),
    ("power_cell", lambda p: _power_cells(p)["null_full_panel"].__setitem__("unexpected_power_cell", 1)),
    (
        "band_minima",
        lambda p: _power_cells(p)["full_panel_net_sharpe_0.30"]["band_minima"].__setitem__(
            "unexpected_band_minimum", 1
        ),
    ),
    (
        "window_entry",
        lambda p: _power_cells(p)["null_full_panel"]["windows"]["124"].__setitem__(
            "unexpected_window_field", 1
        ),
    ),
    (
        "windows_map",
        lambda p: _power_cells(p)["null_full_panel"]["windows"].__setitem__(
            "999",
            {"screened_pass_successes": 0, "screened_pass_rate": 0.0, "screened_watchlist_or_pass_rate": 0.0},
        ),
    ),
]


@pytest.mark.parametrize(
    "mutate",
    [case for _, case in UNKNOWN_KEY_CASES],
    ids=[name for name, _ in UNKNOWN_KEY_CASES],
)
def test_fail_closed_on_unknown_keys(tmp_path, mutate):
    with pytest.raises(demo.PackageError, match="unknown_keys"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


# --- Fail-closed on any true false-flag claim ---------------------------------

FALSE_FLAG_CASES = [
    ("scope_production_cost_calibration_supported", lambda p: p["scope"].__setitem__(
        "production_cost_calibration_supported", True)),
    ("scope_production_capacity_inference_supported", lambda p: p["scope"].__setitem__(
        "production_capacity_inference_supported", True)),
    ("scope_real_factor_tested", lambda p: p["scope"].__setitem__("real_factor_tested", True)),
    ("scope_mechanics_anchor_is_economic_evidence", lambda p: p["scope"].__setitem__(
        "mechanics_anchor_is_economic_evidence", True)),
    ("sensitivity_profit_recipe_published", lambda p: p["cost_sensitivity_groups"].__setitem__(
        "profit_recipe_published", True)),
    ("sensitivity_named_path_outcomes_published", lambda p: p["cost_sensitivity_groups"].__setitem__(
        "named_path_outcomes_published", True)),
    ("detection_power_real_factor_tested", lambda p: p["detection_power"].__setitem__(
        "real_factor_tested", True)),
]


@pytest.mark.parametrize(
    "mutate",
    [case for _, case in FALSE_FLAG_CASES],
    ids=[name for name, _ in FALSE_FLAG_CASES],
)
def test_fail_closed_on_false_flag_claims(tmp_path, mutate):
    with pytest.raises(demo.PackageError):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


# --- Immutable published rates and band values ---------------------------------


def test_fail_closed_on_realistic_rate_tampered_without_classification_change(tmp_path):
    def mutate(package):
        cell = _power_cells(package)["full_panel_net_sharpe_0.30"]
        cell["windows"]["124"]["screened_watchlist_or_pass_rate"] = 0.28

    # 0.28 is still below the frozen 0.65 watchlist minimum, so the frozen
    # classification would remain unchanged; the rate itself is immutable.
    with pytest.raises(demo.PackageError, match="rate_tampered"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


def test_fail_closed_on_null_rate_tampered_without_classification_change(tmp_path):
    def mutate(package):
        cell = _power_cells(package)["null_full_panel"]
        cell["windows"]["365"]["screened_watchlist_or_pass_rate"] = 0.004

    # 0.004 stays inside every frozen null band, so the classification would
    # remain unchanged; the rate itself is immutable.
    with pytest.raises(demo.PackageError, match="rate_tampered"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


def test_fail_closed_on_anchor_rate_tampered(tmp_path):
    def mutate(package):
        cell = _power_cells(package)["mechanics_anchor_extreme_synthetic"]
        cell["windows"]["730"]["screened_pass_successes"] = 198
        cell["windows"]["730"]["screened_pass_rate"] = 0.99

    # 0.99 is still above the 0.8 anchor minimum, so the classification
    # would remain unchanged; the anchor rate itself is immutable.
    with pytest.raises(demo.PackageError, match="rate_tampered"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


def test_fail_closed_on_band_minima_tampered(tmp_path):
    def mutate(package):
        cell = _power_cells(package)["full_panel_net_sharpe_0.60"]
        cell["band_minima"]["screened_watchlist_or_pass_rate_min"] = 0.5

    with pytest.raises(demo.PackageError, match="band_minima_changed"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


def test_fail_closed_on_null_band_tampered(tmp_path):
    def mutate(package):
        package["detection_power"]["null_bands"]["screened_watchlist_or_pass_rate_max"] = 0.2

    with pytest.raises(demo.PackageError, match="null_band_value_changed"):
        demo.evaluate_package(demo.load_package(_write_tampered(tmp_path, mutate)))


# --- CLI output ----------------------------------------------------------------


def test_cli_json_output(capsys):
    exit_code = demo.main(["--package", str(PACKAGE_PATH), "--json"])
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert report["package_id"] == "execution_economics_power_v1"
    assert report["detection_power"]["classification"] == (
        "mechanically_open_realistic_power_insufficient"
    )
    assert all(value is False for value in report["authorities"].values())
    assert report["proxy_admission"]["admitted_for_cost_calibration"] is False


def test_cli_human_output(capsys):
    exit_code = demo.main(["--package", str(PACKAGE_PATH)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Sanitized public package validation: OK" in out
    assert "mechanically_open_realistic_power_insufficient" in out
    assert "admitted for cost calibration: False" in out


def test_cli_explicit_package_path_public_layout(capsys):
    """Positive CLI check with the explicit package path.

    The demo's default package path resolves as a sibling of the demo
    file, which only holds in staging. The public repository layout keeps
    the demo in examples/ and the package in evidence/, so the CLI is
    exercised exactly as documented for the public repository root: with
    --package pointing at PACKAGE_PATH.
    """
    exit_code = demo.main(["--package", str(PACKAGE_PATH), "--json"])
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert report["package_id"] == "execution_economics_power_v1"


def test_cli_fails_closed_on_tampered_package(tmp_path, capsys):
    target = _write_tampered(tmp_path, lambda package: package["authorities"].update(capital_authorized=True))
    exit_code = demo.main(["--package", str(target), "--json"])
    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "error"
    assert "true_authority_refused" in report["error"]


# --- Public repository relocation layout ----------------------------------------


def test_public_repository_layout_relocation(tmp_path, capsys):
    """Package and demo validate after relocation to examples/ and evidence/."""
    examples_dir = tmp_path / "examples"
    evidence_dir = tmp_path / "evidence"
    examples_dir.mkdir()
    evidence_dir.mkdir()
    demo_target = examples_dir / DEMO_PATH.name
    package_target = evidence_dir / PACKAGE_PATH.name
    demo_target.write_text(DEMO_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    package_target.write_text(PACKAGE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("relocated_demo", demo_target)
    relocated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(relocated)
    report = relocated.evaluate_package(relocated.load_package(package_target))
    assert report["status"] == "ok"
    exit_code = relocated.main(["--package", str(package_target), "--json"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
