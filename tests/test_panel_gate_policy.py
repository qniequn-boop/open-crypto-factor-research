import pytest

import panel_gate_policy as policy


def test_large_liquid_scope_marks_cross_bucket_breadth_not_applicable():
    checks = {
        "coverage_ok": True,
        "robust_bucket_val_not_single_bucket": False,
        "robust_bucket_holdout_not_single_bucket": False,
    }

    states = policy.annotate_gate_states(
        checks,
        candidate_definition={"bucket_policy": "large_liquid_only"},
    )

    assert states["coverage_ok"]["state"] == "pass"
    assert states["robust_bucket_val_not_single_bucket"]["state"] == "not_applicable"
    assert states["robust_bucket_holdout_not_single_bucket"]["state"] == "not_applicable"
    assert policy.effective_failures(states) == []


def test_full_panel_candidate_still_requires_bucket_breadth():
    states = policy.annotate_gate_states(
        {"robust_bucket_val_not_single_bucket": False},
        candidate_definition={"bucket_policy": "none"},
    )

    assert states["robust_bucket_val_not_single_bucket"]["state"] == "fail"
    assert policy.effective_failures(states) == ["robust_bucket_val_not_single_bucket"]


def test_incomplete_pbo_and_dsr_path_coverage_is_insufficient_not_failure():
    checks = {"deflated_sharpe_pass": False, "cscv_pbo_pass": False}
    coverage = {
        "deflated_sharpe_pass": {"observed": 16, "required": 94},
        "cscv_pbo_pass": {"observed": 16, "required": 94},
    }

    states = policy.annotate_gate_states(checks, evidence_coverage=coverage)

    assert states["deflated_sharpe_pass"]["state"] == "insufficient"
    assert states["cscv_pbo_pass"]["state"] == "insufficient"
    assert policy.effective_failures(states) == []
    assert set(policy.insufficient_evidence(states)) == {"deflated_sharpe_pass", "cscv_pbo_pass"}


def test_catalog_rejects_hidden_or_unregistered_gates():
    with pytest.raises(ValueError, match="uncataloged_gates:hidden_gate"):
        policy.assert_catalog_covers({"coverage_ok", "hidden_gate"})


def test_catalog_explicitly_records_hidden_holdout_and_baseline_conditions():
    policy.assert_catalog_covers(
        {
            "holdout_sharpe_positive",
            "holdout_ic_positive",
            "baseline_incremental_evidence",
            "evidence_universe_formal_promotion_allowed",
        }
    )
    assert policy.policy_summary()["status"] == "synthetically_calibrated_nonbinding_pending_prospective_evidence"
    assert policy.policy_summary()["calibration_evidence"]["combined_summary"].endswith(
        "panel_gate_complete_calibration_summary_20260714.json"
    )


def _all_pass_states():
    return {
        name: {"state": "pass", "reason": None, "catalog": row}
        for name, row in policy.GATE_CATALOG.items()
    }


def test_gate_v2_draft_preserves_val_clue_as_watchlist_when_pass_evidence_is_insufficient():
    states = _all_pass_states()
    states["cscv_pbo_pass"]["state"] = "insufficient"
    states["robust_family_neutral_val_ic_positive"]["state"] = "fail"

    result = policy.classify_gate_v2_draft(states)

    assert result["status"] == "panel_factor_watchlist"
    assert result["pass_blockers"]["cscv_pbo_pass"] == "insufficient"
    assert result["pass_blockers"]["robust_family_neutral_val_ic_positive"] == "fail"


@pytest.mark.parametrize("dsr_state", ["fail", "insufficient"])
def test_gate_v2_draft_never_passes_when_dsr_is_not_complete_and_passing(dsr_state):
    states = _all_pass_states()
    states["deflated_sharpe_pass"]["state"] = dsr_state

    result = policy.classify_gate_v2_draft(states)

    assert result["status"] == "panel_factor_watchlist"
    assert result["pass_blockers"]["deflated_sharpe_pass"] == dsr_state


def test_gate_v2_draft_rejects_no_val_evidence_or_holdout_collapse():
    no_val = _all_pass_states()
    no_val["val_ic_positive"]["state"] = "fail"
    collapse = _all_pass_states()
    collapse["holdout_noncollapse"]["state"] = "fail"

    assert policy.classify_gate_v2_draft(no_val)["status"] == "panel_factor_reject"
    assert policy.classify_gate_v2_draft(collapse)["status"] == "panel_factor_reject"


def test_gate_v2_draft_rejects_positive_but_statistically_weak_val_ic():
    states = _all_pass_states()
    states["dependence_aware_val_ic_clue"]["state"] = "fail"

    result = policy.classify_gate_v2_draft(states)

    assert result["status"] == "panel_factor_reject"
    assert result["watchlist_blockers"]["dependence_aware_val_ic_clue"] == "fail"


def test_gate_v2_draft_can_pass_large_liquid_scope_when_bucket_gates_are_not_applicable():
    states = _all_pass_states()
    states["robust_bucket_val_not_single_bucket"]["state"] = "not_applicable"
    states["robust_bucket_holdout_not_single_bucket"]["state"] = "not_applicable"

    result = policy.classify_gate_v2_draft(states)

    assert result["status"] == "panel_factor_pass"
    assert result["pass_blockers"] == {}
