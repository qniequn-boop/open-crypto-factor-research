import pandas as pd

import panel_factor_research
import panel_formula_audit


def _panel(periods: int = 240, assets: int = 3):
    index = pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC")
    result = {}
    for asset_number in range(assets):
        close = pd.Series(
            [100.0 + asset_number + 0.01 * (asset_number + 1) * step for step in range(periods)],
            index=index,
        )
        ohlcv = pd.DataFrame(
            {
                "open": close.shift(1).bfill(),
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": 1000.0 + asset_number,
                "vol_quote": close * (1000.0 + asset_number),
            },
            index=index,
        )
        result[f"A{asset_number}-USDT-SWAP"] = {
            "ohlcv": ohlcv,
            "spot_ohlcv": None,
            "funding": pd.Series(0.00001, index=index[::8]),
            "open_interest": None,
            "market_cap": None,
            "asset_label": "synthetic",
        }
    return result


def _simple_builder(*, leak: bool = False, empty: bool = False):
    def build(panel, **kwargs):
        close = pd.concat({name: item["ohlcv"]["close"] for name, item in panel.items()}, axis=1)
        if empty:
            signal = close * float("nan")
        elif leak:
            signal = close.shift(-1)
        else:
            signal = close.pct_change(fill_method=None)
        return {
            "close": close,
            "returns": close.pct_change(fill_method=None),
            "eligibility": close.notna(),
            "formula_library": {"test_formula": signal},
            "factors": {"test_factor": signal},
        }

    return build


def test_differential_audit_accepts_causal_formula():
    report = panel_formula_audit.run_differential_audit(
        _panel(),
        cutoff_fractions=(0.5, 0.8),
        required_factor_names={"test_factor"},
        matrix_builder=_simple_builder(),
    )

    assert report["passed"] is True
    assert report["leakage_frames"] == []
    assert report["required_factor_results"] == {"test_factor": "causal_pass"}
    assert report["forward_return_label_audited"] is False


def test_differential_audit_detects_planted_future_leak():
    report = panel_formula_audit.run_differential_audit(
        _panel(),
        cutoff_fractions=(0.5, 0.8),
        required_factor_names={"test_factor"},
        matrix_builder=_simple_builder(leak=True),
    )

    assert report["passed"] is False
    assert "factor:test_factor" in report["leakage_frames"]
    assert "formula:test_formula" in report["leakage_frames"]
    factor_rows = [row for row in report["comparisons"] if row["frame"] == "factor:test_factor"]
    assert any(row["mismatch_count"] > 0 for row in factor_rows)
    assert any(row["first_mismatch"] is not None for row in factor_rows)


def test_differential_audit_fails_closed_for_unobservable_required_factor():
    report = panel_formula_audit.run_differential_audit(
        _panel(),
        cutoff_fractions=(0.5,),
        required_factor_names={"test_factor"},
        matrix_builder=_simple_builder(empty=True),
    )

    assert report["leakage_free"] is True
    assert report["required_factors_fully_verified"] is False
    assert report["required_factor_results"] == {"test_factor": "inconclusive_no_observations"}
    assert report["passed"] is False


def test_real_matrix_builder_observable_momentum_is_point_in_time(monkeypatch):
    original = panel_factor_research.panel_universe.build_point_in_time_eligibility

    def force_eligible(*args, **kwargs):
        result = original(*args, **kwargs)
        close = args[1]
        result["eligibility"] = close.notna()
        result["base_eligibility"] = close.notna()
        return result

    monkeypatch.setattr(
        panel_factor_research.panel_universe,
        "build_point_in_time_eligibility",
        force_eligible,
    )
    report = panel_formula_audit.run_differential_audit(
        _panel(periods=24 * 20, assets=6),
        cutoff_fractions=(0.7,),
        required_factor_names={"momentum_7d"},
    )

    assert report["passed"] is True
    assert report["frame_summary"]["factor:momentum_7d"]["status"] == "causal_pass"
    assert "formula:momentum_7d" in report["frame_summary"]
    assert not any(
        name.startswith("factor:") and name != "factor:momentum_7d"
        for name in report["frame_summary"]
    )
    assert not any(
        name.startswith("formula:") and name != "formula:momentum_7d"
        for name in report["frame_summary"]
    )
    assert not any(name.startswith("factor:momentum_7d") for name in report["leakage_frames"])
