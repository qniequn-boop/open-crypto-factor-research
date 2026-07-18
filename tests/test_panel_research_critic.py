import copy
import hashlib
import json

import panel_candidate_registry
import panel_critic_contract
import panel_formula_audit
import panel_literature_registry
import panel_research_critic


def _candidate():
    return {
        "candidate_id": "critic_momentum_001",
        "source_ids": ["CRYPTO_MARKET_SIZE_MOMENTUM"],
        "hypothesis": "Medium-horizon momentum persists across the liquid panel.",
        "family": "momentum",
        "required_fields": ["close"],
        "panel_formula": "momentum_7d",
        "direction": "long",
        "neutralization": "none",
        "bucket_policy": "none",
        "weighting_modes": ["rank_linear"],
        "generated_by": "unit_test",
    }


def _batch(candidate=None):
    return {
        "schema_version": 1,
        "batch_id": "batch_critic_test",
        "created_at_utc": "20260715T000000Z",
        "holdout_policy": "audit_only_not_visible_to_ai_generation",
        "candidates": [candidate or _candidate()],
    }


def _audit(status="causal_pass"):
    return {
        "schema_version": panel_formula_audit.AUDIT_SCHEMA_VERSION,
        "candidate_batch_id": "batch_critic_test",
        "leakage_free": True,
        "required_factor_results": {"critic_momentum_001": status},
    }


def _review(batch=None, audit=None, trial_rows=None):
    return panel_research_critic.review_batch(
        batch or _batch(),
        audit or _audit(),
        literature_registry=panel_literature_registry.load_registry(),
        trial_rows=trial_rows or [],
    )


def test_critic_approves_authorized_unique_causally_verified_candidate():
    report = _review()

    assert report["approved"] is True
    assert report["decision"] == "critic_approved"
    assert report["candidate_reviews"][0]["approved"] is True
    assert report["holdout_read_by_critic"] is False
    assert report["performance_outcomes_read_by_critic"] is False
    assert report["formal_promotion_possible"] is False


def test_critic_rejects_unobservable_required_formula():
    report = _review(audit=_audit("inconclusive_no_observations"))

    assert report["approved"] is False
    assert "candidate_formula_causally_verified" in report["candidate_reviews"][0]["blockers"]


def test_critic_rejects_source_without_formal_replication_authorization():
    candidate = _candidate()
    candidate["candidate_id"] = "critic_oi_001"
    candidate["source_ids"] = ["PERP_OPEN_INTEREST_CROWDING"]
    candidate["panel_formula"] = "oi_price_crowding_reversal_v2"
    candidate["family"] = "open_interest_crowding"
    audit = _audit()
    audit["required_factor_results"] = {"critic_oi_001": "causal_pass"}

    report = _review(batch=_batch(candidate), audit=audit)

    review = report["candidate_reviews"][0]
    assert report["approved"] is False
    assert review["unauthorized_sources"] == ["PERP_OPEN_INTEREST_CROWDING"]
    assert "all_sources_formally_authorized" in review["blockers"]


def test_critic_rejects_historical_signature_duplicate():
    candidate = _candidate()
    historical = {
        **candidate,
        "candidate_id": "old_momentum_candidate",
        "batch_id": "older_batch",
        "status": "accepted",
        "candidate_signature": panel_candidate_registry.candidate_signature(candidate),
        "variant_count": 1,
    }

    report = _review(trial_rows=[historical])

    review = report["candidate_reviews"][0]
    assert report["approved"] is False
    assert review["historical_signature_duplicate"] is True
    assert "candidate_signature_unique" in review["blockers"]


def test_critic_rejects_formula_audit_containing_holdout_payload():
    audit = copy.deepcopy(_audit())
    audit["diagnostics"] = {"Holdout": {"sharpe": 999.0}}

    report = _review(audit=audit)

    assert report["approved"] is False
    assert report["batch_checks"]["formula_audit_contains_no_holdout"] is False
    assert "formula_audit_contains_no_holdout" in report["candidate_reviews"][0]["blockers"]


def _write_approved_contract(tmp_path):
    batch_path = tmp_path / "candidate_batch.json"
    formula_path = tmp_path / "formula_audit.json"
    batch_path.write_text(json.dumps(_batch()), encoding="utf-8")
    formula_path.write_text(json.dumps(_audit()), encoding="utf-8")
    report = _review()
    report["inputs"] = {
        "candidate_batch": {
            "path": str(batch_path),
            "sha256": hashlib.sha256(batch_path.read_bytes()).hexdigest(),
        },
        "formula_audit_report": {
            "path": str(formula_path),
            "sha256": hashlib.sha256(formula_path.read_bytes()).hexdigest(),
        },
    }
    return batch_path, formula_path, report


def test_critic_approval_contract_binds_batch_and_formula_audit(tmp_path):
    batch_path, _, report = _write_approved_contract(tmp_path)

    approved, failures = panel_critic_contract.validate_critic_approval(report, batch_path)

    assert approved is True
    assert failures == []


def test_critic_approval_contract_rejects_batch_mutation(tmp_path):
    batch_path, _, report = _write_approved_contract(tmp_path)
    mutated = _batch()
    mutated["candidates"][0]["hypothesis"] = "Changed after approval."
    batch_path.write_text(json.dumps(mutated), encoding="utf-8")

    approved, failures = panel_critic_contract.validate_critic_approval(report, batch_path)

    assert approved is False
    assert "critic_candidate_batch_sha256_mismatch" in failures


def test_critic_approval_contract_rejects_formula_audit_mutation(tmp_path):
    batch_path, formula_path, report = _write_approved_contract(tmp_path)
    formula = _audit("inconclusive_no_observations")
    formula_path.write_text(json.dumps(formula), encoding="utf-8")

    approved, failures = panel_critic_contract.validate_critic_approval(report, batch_path)

    assert approved is False
    assert "critic_formula_audit_sha256_mismatch" in failures


def test_critic_approval_contract_rechecks_causal_results(tmp_path):
    batch_path, formula_path, report = _write_approved_contract(tmp_path)
    formula = _audit("inconclusive_no_observations")
    formula_path.write_text(json.dumps(formula), encoding="utf-8")
    report["inputs"]["formula_audit_report"]["sha256"] = hashlib.sha256(
        formula_path.read_bytes()
    ).hexdigest()

    approved, failures = panel_critic_contract.validate_critic_approval(report, batch_path)

    assert approved is False
    assert "critic_formula_results_not_all_causal_pass" in failures
