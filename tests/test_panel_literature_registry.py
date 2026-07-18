import copy

import pytest

import panel_literature_registry as registry


def test_replication_registry_is_valid_and_separates_evidence_uses():
    payload = registry.load_registry()
    entries = payload["entries"]

    assert len(entries) >= 7
    assert registry.canonical_replications_ready(payload) == []
    assert all(
        entry["allowed_use"] in {"factor_direction", "mechanism_constraint"}
        for entry in registry.candidate_authorizing_entries(payload)
    )
    assert all(
        entry["allowed_use"] == "engineering_pattern"
        for entry in entries
        if entry["replication_status"] == "engineering_only"
    )


def test_engineering_source_cannot_be_promoted_to_factor_evidence():
    payload = registry.load_registry()
    changed = copy.deepcopy(payload)
    engineering = next(entry for entry in changed["entries"] if entry["allowed_use"] == "engineering_pattern")
    engineering["replication_status"] = "ready_canonical"

    with pytest.raises(ValueError, match="engineering_source_cannot_authorize_factor"):
        registry.validate_registry(changed)


def test_replication_prompt_exposes_blockers_and_not_reported_returns():
    context = registry.replication_prompt_context()

    assert "adaptation_only" in context
    assert "survivor-conditioned perpetual universe" in context
    assert "44.55" not in context
