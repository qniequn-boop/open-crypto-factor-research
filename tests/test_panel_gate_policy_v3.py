import panel_gate_policy_v3 as policy


def _discovery_checks():
    return {
        "coverage_ok": True,
        "return_evidence_complete_while_held": True,
        "val_ic_positive": True,
        "dependence_aware_val_ic_clue": True,
        "val_long_short_positive": True,
        "turnover_reasonable": True,
        "rolling_ic_stable": True,
        "holdout_noncollapse": True,
        "deflated_sharpe_pass": False,
        "cscv_pbo_pass": False,
    }


def test_bh_adjustment_is_monotone_and_less_conservative_than_by():
    p_values = {"a": 0.01, "b": 0.03, "c": 0.20}
    bh = policy.false_discovery_adjustment(p_values, q=0.10)
    by = policy.false_discovery_adjustment(p_values, q=0.10, method="benjamini_yekutieli")

    assert bh["a"]["adjusted_p"] <= bh["b"]["adjusted_p"] <= bh["c"]["adjusted_p"]
    assert all(by[key]["adjusted_p"] >= bh[key]["adjusted_p"] for key in p_values)
    assert bh["a"]["passed"]


def test_historical_screen_can_only_authorize_prospective_observation():
    result = policy.classify_historical_discovery(_discovery_checks(), fdr_state="pass")

    assert result["status"] == "prospective_eligible"
    assert result["formal_pass_possible"] is False


def test_dsr_and_pbo_do_not_block_low_stakes_prospective_entry():
    checks = _discovery_checks()
    checks["deflated_sharpe_pass"] = False
    checks["cscv_pbo_pass"] = False

    assert policy.classify_historical_discovery(checks, fdr_state="pass")["status"] == "prospective_eligible"


def test_holdout_collapse_remains_a_hard_reject():
    checks = _discovery_checks()
    checks["holdout_noncollapse"] = False

    result = policy.classify_historical_discovery(checks, fdr_state="pass")

    assert result["status"] == "historical_reject"
    assert result["blockers"] == ["holdout_noncollapse"]


def test_incomplete_family_ledger_never_becomes_prospective_eligible():
    rows = [
        {
            "candidate_id": "new_one",
            "family": "carry",
            "checks": _discovery_checks(),
            "dependence_aware_rank_ic": {
                "Val": {"empirical_block_audit": {"empirical_one_sided_p": 0.001}}
            },
        }
    ]
    summary = policy.attach_gate_v3_drafts(
        rows,
        registry_breakdown={
            "outcome_seen_candidate_ids_by_family": {"carry": ["old_missing", "new_one"]}
        },
    )

    assert not summary["family_audits"]["carry"]["ledger_complete"]
    assert rows[0]["gate_v3_draft"]["family_fdr_state"] == "insufficient"
    assert rows[0]["gate_v3_draft"]["classification"]["status"] == "historical_clue"
