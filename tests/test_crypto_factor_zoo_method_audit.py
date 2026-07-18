import pandas as pd

import crypto_factor_zoo_method_audit as audit


def _hourly(scale: float) -> pd.DataFrame:
    index = pd.date_range("2025-12-01", periods=24 * 45, freq="h", tz="UTC")
    base = pd.Series(range(len(index)), index=index, dtype=float) / 10000.0 + scale
    return pd.DataFrame(
        {
            "open": base,
            "high": base * 1.01,
            "low": base * 0.99,
            "close": base * 1.002,
            "vol_quote": 1000.0,
        },
        index=index,
    )


def _l2() -> dict:
    return {
        "assets": {
            "A": {
                "quoted_spread_bps": {"median": 1.0},
                "effective_spread_bps": {
                    "median": 1.2,
                    "quote_notional_weighted_mean": 1.4,
                },
            },
            "B": {
                "quoted_spread_bps": {"median": 2.0},
                "effective_spread_bps": {
                    "median": 2.2,
                    "quote_notional_weighted_mean": 2.4,
                },
            },
        }
    }


def test_method_audit_never_authorizes_factor_from_bounded_proxy_check():
    report = audit.build_audit(
        {"A": _hourly(100.0), "B": _hourly(10.0)},
        _l2(),
        target_date="2026-01-10",
    )
    assert report["decision"]["exact_formula_executable"] is True
    assert report["decision"]["spread_proxy_magnitude_calibrated"] is False
    assert report["decision"]["spread_proxy_cross_regime_validated"] is False
    assert report["decision"]["new_factor_batch_authorized"] is False
    assert report["factor_generated"] is False
    assert report["trial_registry_changed"] is False
