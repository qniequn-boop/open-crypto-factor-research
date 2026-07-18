import json

import panel_ai_candidate_generator as generator


def _candidate(candidate_id="ai_basis_001", source_ids=None):
    return {
        "candidate_id": candidate_id,
        "source_ids": source_ids or ["CRYPTO_MARKET_SIZE_MOMENTUM"],
        "hypothesis": "Medium-horizon momentum should persist across the liquid panel.",
        "family": "momentum",
        "required_fields": ["close"],
        "panel_formula": "momentum_7d",
        "direction": "long",
        "neutralization": "none",
        "bucket_policy": "none",
        "weighting_modes": ["rank_linear"],
        "generated_by": "ai_panel_generator",
    }


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def _call(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        return json.dumps(self.payload)


def test_generate_raw_candidates_caps_budget(tmp_path):
    literature = tmp_path / "literature.md"
    literature.write_text("- id: CRYPTO_MARKET_SIZE_MOMENTUM\n", encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"factors": []}), encoding="utf-8")
    payload = {"candidates": [_candidate(f"ai_basis_{idx:03d}") for idx in range(15)]}

    candidates = generator.generate_raw_candidates(
        max_candidates=12,
        client=FakeClient(payload),
        literature_path=literature,
        recent_report_path=report,
    )

    assert len(candidates) == generator.DEFAULT_MAX_CANDIDATES


def test_prompt_exposes_forbidden_ids_and_expected_direction(monkeypatch, tmp_path):
    literature = tmp_path / "literature.md"
    literature.write_text("- id: PERP_OPEN_INTEREST_CROWDING\n", encoding="utf-8")
    monkeypatch.setattr(
        generator.registry,
        "load_trial_rows",
        lambda: [
            {
                "candidate_id": "used_oi_001",
                "panel_formula": "oi_price_crowding_reversal_v2",
                "status": "rejected",
            }
        ],
    )

    _, prompt = generator.build_candidate_generation_prompts(
        max_candidates=2,
        literature_path=literature,
        recent_report_path=None,
    )

    assert "used_oi_001" in prompt
    assert '"expected_direction": "short"' in prompt
    assert '"basis_carry"' not in prompt


def test_freeze_generated_candidates_logs_accepted_and_rejected(tmp_path):
    literature = tmp_path / "literature.md"
    literature.write_text("- id: CRYPTO_MARKET_SIZE_MOMENTUM\n", encoding="utf-8")
    bad = _candidate("ai_bad_source", source_ids=["MADE_UP_SOURCE"])

    batch_path, accepted, rejected = generator.freeze_generated_candidates(
        [_candidate(), bad],
        log_dir=tmp_path,
        literature_path=literature,
        batch_id="batch_unit",
    )

    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    trial_rows = [
        json.loads(line)
        for line in (tmp_path / "panel_trial_registry.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert len(accepted) == 1
    assert len(rejected) == 1
    assert batch["batch_id"] == "batch_unit"
    assert batch["candidates"][0]["candidate_id"] == "ai_basis_001"
    assert [row["event"] for row in trial_rows] == ["generated", "schema_rejected"]
    assert "unknown_source_ids" in trial_rows[1]["reason"]


def test_freeze_rejects_duplicate_candidate_in_same_batch(tmp_path):
    literature = tmp_path / "literature.md"
    literature.write_text("- id: CRYPTO_MARKET_SIZE_MOMENTUM\n", encoding="utf-8")

    batch_path, accepted, rejected = generator.freeze_generated_candidates(
        [_candidate("ai_dup_001"), _candidate("ai_dup_001")],
        log_dir=tmp_path,
        literature_path=literature,
        batch_id="batch_dup",
    )

    assert batch_path.exists()
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert "duplicate_candidate_id_in_batch" in rejected[0]["errors"]


def test_freeze_rejects_previously_rejected_candidate_id(tmp_path):
    literature = tmp_path / "literature.md"
    literature.write_text("- id: CRYPTO_MARKET_SIZE_MOMENTUM\n", encoding="utf-8")
    generator.registry.append_trial_event(
        _candidate("ai_rejected_001"),
        event="evaluated",
        status="panel_factor_reject",
        log_dir=tmp_path,
    )

    _, accepted, rejected = generator.freeze_generated_candidates(
        [_candidate("ai_rejected_001")],
        log_dir=tmp_path,
        literature_path=literature,
        batch_id="batch_reject_id",
    )

    assert accepted == []
    assert len(rejected) == 1
    assert "candidate_id_previously_rejected" in rejected[0]["errors"]


def test_freeze_rejects_family_budget_excess(tmp_path):
    literature = tmp_path / "literature.md"
    literature.write_text("- id: CRYPTO_MARKET_SIZE_MOMENTUM\n", encoding="utf-8")
    candidate = _candidate("ai_budget_001")
    candidate["weighting_modes"] = ["rank_linear", "top_bottom_30"]

    _, accepted, rejected = generator.freeze_generated_candidates(
        [candidate],
        log_dir=tmp_path,
        literature_path=literature,
        batch_id="batch_budget",
        max_family_variants=1,
    )

    assert accepted == []
    assert len(rejected) == 1
    assert any(error.startswith("family_budget_exceeded") for error in rejected[0]["errors"])


def test_generation_prompt_filters_audit_split_details(tmp_path):
    literature = tmp_path / "literature.md"
    literature.write_text("- id: PERP_FUNDING_BASIS\n", encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "factors": [
                    {
                        "name": "basis_carry__rank_linear",
                        "status": "panel_factor_reject",
                        "rank_ic": {
                            "Val": {"mean_rank_ic": 0.01},
                            "Holdout": {"mean_rank_ic": -0.99},
                        },
                        "long_short": {
                            "Val": {"sharpe": 0.4},
                            "Holdout": {"sharpe": -9.9},
                        },
                        "failed_checks": ["holdout_noncollapse", "rolling_sharpe_not_fragile"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    _, user_prompt = generator.build_candidate_generation_prompts(
        max_candidates=3,
        literature_path=literature,
        recent_report_path=report,
    )

    assert "Holdout" not in user_prompt
    assert "holdout" not in user_prompt.lower()
    assert "-9.9" not in user_prompt
    assert "rolling_sharpe_not_fragile" not in user_prompt
    assert "ValIC=0.01" in user_prompt
    assert "ValSR=0.4" in user_prompt
    assert "Generate at most 3 candidates" in user_prompt


def test_generation_prompt_contains_only_admitted_source_and_formula():
    _, user_prompt = generator.build_candidate_generation_prompts(
        max_candidates=2,
        literature_path="LITERATURE_HYPOTHESIS_REGISTRY.md",
        recent_report_path=None,
        allowed_source_ids={"CRYPTO_MARKET_SIZE_MOMENTUM"},
        allowed_panel_formulas={"momentum_7d"},
    )

    assert "CRYPTO_MARKET_SIZE_MOMENTUM" in user_prompt
    assert "PERP_FUNDING_BASIS" not in user_prompt
    assert '"momentum_7d"' in user_prompt
    assert '"oi_price_crowding_reversal"' not in user_prompt


def test_freeze_enforces_source_formula_and_accepted_batch_budgets(tmp_path):
    literature = tmp_path / "literature.md"
    literature.write_text(
        "- id: CRYPTO_MARKET_SIZE_MOMENTUM\n- id: PERP_OPEN_INTEREST_CROWDING\n",
        encoding="utf-8",
    )
    first = _candidate("ai_admitted_001")
    second = _candidate("ai_admitted_002")
    wrong_source = _candidate(
        "ai_wrong_source_001", source_ids=["PERP_OPEN_INTEREST_CROWDING"]
    )

    _, accepted, rejected = generator.freeze_generated_candidates(
        [first, second, wrong_source],
        log_dir=tmp_path / "batches",
        literature_path=literature,
        trial_registry_path=tmp_path / "trials.jsonl",
        batch_id="batch_admission",
        allowed_source_ids={"CRYPTO_MARKET_SIZE_MOMENTUM"},
        allowed_panel_formulas={"momentum_7d"},
        source_variant_budgets={"CRYPTO_MARKET_SIZE_MOMENTUM": 10},
        max_accepted_candidates=1,
    )

    assert [row["candidate_id"] for row in accepted] == ["ai_admitted_001"]
    assert "accepted_batch_budget_exceeded:2>1" in rejected[0]["errors"]
    assert any(
        error == "source_not_admitted_for_generation:PERP_OPEN_INTEREST_CROWDING"
        for error in rejected[1]["errors"]
    )
    assert len((tmp_path / "trials.jsonl").read_text(encoding="utf-8").splitlines()) == 3
def test_guardrail_rejects_formula_direction_mismatch(tmp_path):
    candidate = {
        "candidate_id": "oi_wrong_direction",
        "source_ids": ["PERP_OPEN_INTEREST_CROWDING"],
        "hypothesis": "fade crowded price moves",
        "family": "open_interest_crowding",
        "required_fields": ["close", "open_interest"],
        "panel_formula": "oi_price_crowding_reversal",
        "direction": "long",
        "neutralization": "none",
        "bucket_policy": "none",
        "weighting_modes": ["rank_linear"],
        "generated_by": "test",
    }
    errors = generator._guardrail_errors(
        candidate,
        registry_path=tmp_path / "trials.jsonl",
        accepted_so_far=[],
        seen_candidate_ids=set(),
        seen_signatures=set(),
        family_counts={},
        max_family_variants=10,
    )

    assert "formula_direction_mismatch:short" in errors


def test_guardrail_enforces_direction_for_all_registered_formulas(tmp_path):
    candidate = _candidate("momentum_wrong_direction")
    candidate["direction"] = "short"

    errors = generator._guardrail_errors(
        candidate,
        registry_path=tmp_path / "trials.jsonl",
        accepted_so_far=[],
        seen_candidate_ids=set(),
        seen_signatures=set(),
        family_counts={},
        max_family_variants=10,
    )

    assert "formula_direction_mismatch:long" in errors


def test_guardrail_rejects_legacy_directional_basis_formula(tmp_path):
    candidate = _candidate("legacy_basis")
    candidate.update(
        {
            "source_ids": ["PERP_FUNDING_BASIS"],
            "family": "carry",
            "required_fields": ["close", "spot_close", "basis", "funding_cost"],
            "panel_formula": "basis_carry",
            "direction": "short",
        }
    )

    errors = generator._guardrail_errors(
        candidate,
        registry_path=tmp_path / "trials.jsonl",
        accepted_so_far=[],
        seen_candidate_ids=set(),
        seen_signatures=set(),
        family_counts={},
        max_family_variants=10,
    )

    assert "formula_deprecated_for_candidates" in errors
