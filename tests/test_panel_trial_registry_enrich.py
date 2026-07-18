import json

import panel_candidate_registry as registry
import panel_trial_registry_enrich as enrichment


def _candidate(candidate_id="candidate_a"):
    return {
        "candidate_id": candidate_id,
        "source_ids": ["SOURCE"],
        "hypothesis": "Frozen hypothesis.",
        "family": "carry",
        "required_fields": ["close"],
        "panel_formula": "basis_carry",
        "direction": "short",
        "neutralization": "none",
        "bucket_policy": "none",
        "weighting_modes": ["rank_linear", "top_bottom_30"],
        "generated_by": "unit_test",
    }


def test_enrichment_is_append_only_idempotent_and_trial_count_neutral(tmp_path):
    legacy_row = {
        "candidate_id": "candidate_a",
        "event": "generated",
        "status": "accepted",
        "panel_formula": "basis_carry",
        "weighting_modes": ["rank_linear", "top_bottom_30"],
        "variant_count": 2,
    }
    (tmp_path / "panel_trial_registry.jsonl").write_text(json.dumps(legacy_row) + "\n", encoding="utf-8")
    (tmp_path / "panel_candidate_batch_test.json").write_text(
        json.dumps({"batch_id": "test", "candidates": [_candidate()]}),
        encoding="utf-8",
    )

    dry_run = enrichment.enrich_trial_registry(log_dir=tmp_path, apply=False)
    applied = enrichment.enrich_trial_registry(log_dir=tmp_path, apply=True)
    repeated = enrichment.enrich_trial_registry(log_dir=tmp_path, apply=True)

    rows = registry.load_trial_rows(tmp_path / "panel_trial_registry.jsonl")
    assert dry_run["enrichable_candidate_ids"] == ["candidate_a"]
    assert applied["appended_candidate_ids"] == ["candidate_a"]
    assert applied["trial_count_unchanged"] is True
    assert repeated["appended_candidate_ids"] == []
    assert len(rows) == 2
    assert rows[-1]["signal_signature"] == "basis_carry|short|none|none"
    assert registry.trial_variant_count(tmp_path / "panel_trial_registry.jsonl") == 2


def test_conflicting_frozen_metadata_stops_enrichment(tmp_path):
    first = _candidate()
    second = {**_candidate(), "neutralization": "liquidity_size"}
    (tmp_path / "panel_candidate_batch_a.json").write_text(
        json.dumps({"candidates": [first]}), encoding="utf-8"
    )
    (tmp_path / "panel_candidate_batch_b.json").write_text(
        json.dumps({"candidates": [second]}), encoding="utf-8"
    )

    try:
        enrichment.collect_frozen_candidate_metadata(tmp_path)
    except ValueError as exc:
        assert "conflicting_frozen_candidate_metadata:candidate_a" in str(exc)
    else:
        raise AssertionError("conflicting metadata should fail closed")
