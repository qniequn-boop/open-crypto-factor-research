import json

import pytest

import panel_candidate_registry as registry


def _candidate(candidate_id="cand_basis_001"):
    return {
        "candidate_id": candidate_id,
        "source_ids": ["PERP_FUNDING_BASIS"],
        "hypothesis": "Rich basis should predict weaker forward returns after funding costs.",
        "family": "carry",
        "required_fields": ["close", "spot_close", "basis", "funding_cost"],
        "panel_formula": "basis_carry",
        "direction": "short",
        "neutralization": "none",
        "bucket_policy": "none",
        "weighting_modes": ["rank_linear", "top_bottom_30"],
        "generated_by": "unit_test",
    }


def test_candidate_schema_requires_known_literature_source():
    ok, errors = registry.validate_candidate(
        _candidate(),
        literature_source_ids={"PERP_FUNDING_BASIS"},
        known_formulas={"basis_carry"},
    )

    assert ok
    assert errors == []

    bad = _candidate()
    bad["source_ids"] = ["MADE_UP_SOURCE"]
    ok, errors = registry.validate_candidate(
        bad,
        literature_source_ids={"PERP_FUNDING_BASIS"},
        known_formulas={"basis_carry"},
    )

    assert not ok
    assert any("unknown_source_ids" in error for error in errors)


def test_trial_registry_counts_rejected_and_evaluated_unique_variants(tmp_path):
    registry.append_trial_event(
        _candidate("cand_a"),
        event="generated",
        status="accepted",
        log_dir=tmp_path,
    )
    registry.append_trial_event(
        _candidate("cand_a"),
        event="evaluated",
        status="panel_factor_reject",
        variant_count=2,
        log_dir=tmp_path,
    )
    registry.append_trial_event(
        {"candidate_id": "cand_bad", "weighting_modes": ["rank_linear"]},
        event="schema_rejected",
        status="rejected",
        log_dir=tmp_path,
    )

    registry_path = tmp_path / "panel_trial_registry.jsonl"
    assert registry.trial_variant_count(registry_path) == 3
    rows = registry.load_trial_rows(registry_path)
    accepted = next(row for row in rows if row["candidate_id"] == "cand_a")
    assert accepted["direction"] == "short"
    assert accepted["neutralization"] == "none"
    assert accepted["bucket_policy"] == "none"
    assert accepted["signal_signature"] == "basis_carry|short|none|none"
    assert len(accepted["candidate_payload_sha256"]) == 64


def test_trial_count_breakdown_separates_signal_ids_and_portfolio_variants(tmp_path):
    first = _candidate("signal_a")
    second = {**_candidate("signal_b"), "weighting_modes": ["rank_linear"]}
    registry.append_trial_event(first, event="generated", status="accepted", log_dir=tmp_path)
    registry.append_trial_event(first, event="evaluated", status="rejected", log_dir=tmp_path)
    registry.append_trial_event(second, event="generated", status="accepted", log_dir=tmp_path)

    result = registry.trial_count_breakdown(tmp_path / "panel_trial_registry.jsonl")

    assert result["candidate_id_trial_count"] == 2
    assert result["portfolio_variant_trial_count"] == 3
    assert result["unique_complete_signal_signature_count"] == 1
    assert result["metadata_complete"] is True


def test_trial_count_breakdown_separates_audit_log_from_outcome_seen_trials(tmp_path):
    path = tmp_path / "panel_trial_registry.jsonl"
    rows = [
        {
            "event": "guardrail_rejected",
            "status": "rejected",
            "candidate_id": "syntax_reject",
            "family": "momentum",
            "variant_count": 2,
        },
        {
            "event": "generated",
            "status": "accepted",
            "candidate_id": "evaluated_one",
            "family": "carry",
            "variant_count": 2,
        },
        {
            "event": "evaluated",
            "status": "panel_factor_reject",
            "candidate_id": "evaluated_one",
            "family": "carry",
            "variant_count": 2,
        },
    ]
    path.write_text("\n".join(__import__("json").dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = registry.trial_count_breakdown(path)

    assert result["audit_registry_candidate_count"] == 2
    assert result["audit_registry_portfolio_variant_count"] == 4
    assert result["outcome_seen_candidate_count"] == 1
    assert result["outcome_seen_portfolio_variant_count"] == 2
    assert result["outcome_seen_candidate_ids_by_family"] == {"carry": ["evaluated_one"]}


def test_trial_registry_fails_closed_on_malformed_jsonl(tmp_path):
    path = tmp_path / "panel_trial_registry.jsonl"
    path.write_text(json.dumps({"candidate_id": "valid", "variant_count": 2}) + "\n{broken\n", encoding="utf-8")

    with pytest.raises(ValueError, match="trial_registry_invalid_json_line:2"):
        registry.trial_count_breakdown(path)


def test_current_candidate_must_have_matching_accepted_registry_admission(tmp_path):
    path = tmp_path / "panel_trial_registry.jsonl"
    candidate = _candidate("registered_candidate")

    with pytest.raises(FileNotFoundError, match="trial_registry_missing"):
        registry.validate_trial_registry_for_candidates([candidate], path)

    registry.append_trial_event(candidate, event="generated", status="accepted", log_dir=tmp_path)
    rows, breakdown = registry.validate_trial_registry_for_candidates([candidate], path)

    assert len(rows) == 1
    assert breakdown["portfolio_variant_trial_count"] == 2


def test_ai_generation_prompt_does_not_include_holdout_metrics():
    report = {
        "factors": [
            {
                "name": "basis_carry__rank_linear",
                "status": "panel_factor_reject",
                "rank_ic": {
                    "Val": {"mean_rank_ic": 0.02},
                    "Holdout": {"mean_rank_ic": -0.05},
                },
                "long_short": {
                    "Val": {"sharpe": 1.2},
                    "Holdout": {"sharpe": -2.0},
                },
                "failed_checks": ["holdout_noncollapse"],
            }
        ]
    }

    prompt = registry.build_ai_generation_prompt("source text", report)

    assert "Holdout" not in prompt
    assert "holdout" not in prompt.lower()
    assert "-2.0" not in prompt
    assert "ValSR=1.2" in prompt


def test_ai_prompt_is_byte_identical_when_only_holdout_derived_fields_change():
    safe_row = {
        "name": "candidate__rank_linear",
        "candidate_id": "candidate",
        "status": "panel_factor_pass",
        "rank_ic": {"Val": {"mean_rank_ic": 0.03}, "Holdout": {"mean_rank_ic": 0.40}},
        "long_short": {
            "Val": {"sharpe": 1.1, "total_return": 0.02},
            "Holdout": {"sharpe": 4.0, "total_return": 0.50},
        },
        "failed_checks": [],
    }
    adverse_row = {
        **safe_row,
        "status": "panel_factor_reject",
        "rank_ic": {"Val": {"mean_rank_ic": 0.03}, "Holdout": {"mean_rank_ic": -0.40}},
        "long_short": {
            "Val": {"sharpe": 1.1, "total_return": 0.02},
            "Holdout": {"sharpe": -4.0, "total_return": -0.50},
        },
        "failed_checks": [
            "holdout_noncollapse",
            "rolling_sharpe_not_fragile",
            "robust_crash_loss_contained",
            "robust_bucket_holdout_not_single_bucket",
        ],
    }

    safe_prompt = registry.build_ai_generation_prompt("source text", {"factors": [safe_row]})
    adverse_prompt = registry.build_ai_generation_prompt("source text", {"factors": [adverse_row]})

    assert safe_prompt == adverse_prompt
    assert "panel_factor_pass" not in safe_prompt
    assert "panel_factor_reject" not in adverse_prompt
    assert "rolling_sharpe_not_fragile" not in adverse_prompt
    assert "robust_crash_loss_contained" not in adverse_prompt


def test_ai_prompt_selection_is_independent_of_holdout_ordering_with_more_than_twelve_rows():
    rows = [
        {
            "name": f"candidate_{number:02d}",
            "candidate_id": f"candidate_{number:02d}",
            "rank_ic": {
                "Val": {"mean_rank_ic": number / 100.0},
                "Holdout": {"mean_rank_ic": (12 - number) / 10.0},
            },
            "long_short": {
                "Val": {"sharpe": number / 10.0, "total_return": number / 1000.0},
                "Holdout": {"sharpe": float(12 - number)},
            },
            "failed_checks": [],
        }
        for number in range(13)
    ]
    holdout_best_first = sorted(rows, key=lambda row: row["long_short"]["Holdout"]["sharpe"], reverse=True)
    holdout_worst_first = list(reversed(holdout_best_first))

    first = registry.build_ai_generation_prompt("source text", {"factors": holdout_best_first})
    second = registry.build_ai_generation_prompt("source text", {"factors": holdout_worst_first})

    assert first == second
    assert "candidate_12" in first
    assert "candidate_00" not in first


def test_ai_prompt_prioritizes_candidate_rows_over_baseline_rows():
    baselines = [
        {
            "name": f"baseline_{i}",
            "rank_ic": {"Val": {"mean_rank_ic": 0.0}},
            "long_short": {"Val": {"sharpe": 0.0, "total_return": 0.0}},
            "failed_checks": [],
        }
        for i in range(12)
    ]
    candidate = {
        "name": "candidate_priority",
        "candidate_id": "candidate_priority",
        "rank_ic": {"Val": {"mean_rank_ic": 0.02}},
        "long_short": {"Val": {"sharpe": 0.5, "total_return": 0.01}},
        "failed_checks": [],
    }

    prompt = registry.build_ai_generation_prompt("source text", {"factors": baselines + [candidate]})

    assert "candidate_priority" in prompt


def test_freeze_candidates_from_json_writes_batch_and_trial_registry(tmp_path, monkeypatch):
    source_file = tmp_path / "literature.md"
    source_file.write_text("- id: PERP_FUNDING_BASIS\n", encoding="utf-8")
    monkeypatch.setattr(registry, "REGISTRY_PATH", source_file)
    input_path = tmp_path / "candidates.json"
    input_path.write_text(json.dumps({"candidates": [_candidate()]}, ensure_ascii=False), encoding="utf-8")

    batch_path = registry.freeze_candidates_from_json(input_path, log_dir=tmp_path)
    batch = json.loads(batch_path.read_text(encoding="utf-8"))

    assert batch["candidates"][0]["candidate_id"] == "cand_basis_001"
    assert (tmp_path / "panel_trial_registry.jsonl").exists()
def test_approximate_signature_ignores_source_packaging():
    first = {"source_ids": ["A"], "panel_formula": "same_formula", "direction": "long"}
    second = {"source_ids": ["B", "C"], "panel_formula": "same_formula", "direction": "short"}

    assert registry.candidate_signature(first, approximate=True) == registry.candidate_signature(second, approximate=True)


def test_guardrail_rejection_counts_as_trial_but_does_not_poison_formula(tmp_path):
    path = tmp_path / "panel_trial_registry.jsonl"
    candidate = _candidate("bad_direction")
    registry.append_trial_event(
        candidate,
        event="guardrail_rejected",
        status="rejected",
        reason="formula_direction_mismatch:short",
        log_dir=tmp_path,
    )

    assert registry.trial_variant_count(path) == 2
    assert registry.historical_candidate_signatures(path) == set()


def test_source_variant_budget_counts_rejected_candidates_once(tmp_path):
    candidate = _candidate("rejected_source_attempt")
    registry.append_trial_event(
        candidate,
        event="guardrail_rejected",
        status="rejected",
        variant_count=2,
        log_dir=tmp_path,
    )
    registry.append_trial_event(
        candidate,
        event="evaluated",
        status="panel_factor_reject",
        variant_count=2,
        log_dir=tmp_path,
    )

    counts = registry.historical_source_variant_counts(
        tmp_path / "panel_trial_registry.jsonl"
    )

    assert counts["PERP_FUNDING_BASIS"] == 2
