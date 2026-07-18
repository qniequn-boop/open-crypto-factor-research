import hashlib
import json
from datetime import datetime, timezone

import panel_factory_scheduler as scheduler


NOW = datetime(2026, 7, 16, 16, 0, tzinfo=timezone.utc)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _candidate(candidate_id="scheduled_momentum_001", source_id="SOURCE_ONE"):
    return {
        "candidate_id": candidate_id,
        "source_ids": [source_id],
        "hypothesis": "A preregistered liquid-panel momentum effect should persist.",
        "family": "renaming_this_cannot_evade_source_budget",
        "required_fields": ["close"],
        "panel_formula": "momentum_7d",
        "direction": "long",
        "neutralization": "none",
        "bucket_policy": "none",
        "weighting_modes": ["rank_linear"],
        "generated_by": "ai_panel_generator",
    }


def _environment(tmp_path, *, admitted):
    literature = tmp_path / "literature.md"
    literature.write_text("# Registry\n\n- id: SOURCE_ONE\n  source: Test source\n", encoding="utf-8")
    admission = {
        "schema_version": 1,
        "policy": {
            "default_admission": False,
            "human_review_required_to_change": True,
            "evaluation_outcomes_cannot_change_admission": True,
            "holdout_cannot_change_admission": True,
        },
        "sources": [
            {
                "source_id": "SOURCE_ONE",
                "status": "approved_small_budget" if admitted else "frozen",
                "allowed_for_generation": admitted,
                "allowed_panel_formulas": ["momentum_7d"] if admitted else [],
                "max_lifetime_variants": 5 if admitted else 0,
                "reason": "Synthetic scheduler test.",
            }
        ],
    }
    admission_path = _write_json(tmp_path / "admission.json", admission)
    policy = {
        "schema_version": 1,
        "policy_id": "test_scheduler_policy",
        "max_generation_cycles_per_utc_day": 1,
        "cooldown_hours": 24,
        "max_candidates_proposed_per_cycle": 3,
        "max_candidates_accepted_per_cycle": 2,
        "max_active_jobs": 1,
        "one_source_per_cycle": True,
        "source_selection": "lowest_lifetime_variant_count_then_source_id",
        "holdout_feedback_to_ai": False,
        "automatic_admission_changes": False,
        "run_job_after_freeze": True,
        "incomplete_intent_requires_manual_review": True,
        "idle_when_no_source_is_admitted": True,
    }
    policy_path = _write_json(tmp_path / "policy.json", policy)
    substrate = _write_json(
        tmp_path / "substrate.json",
        {"request_contract": {"inst_ids": ["A-USDT-SWAP", "B-USDT-SWAP"]}},
    )
    return {
        "source_admission_path": admission_path,
        "policy_path": policy_path,
        "literature_path": literature,
        "trial_registry_path": tmp_path / "panel_trial_registry.jsonl",
        "scheduler_root": tmp_path / "scheduler",
        "factory_root": tmp_path / "factory",
        "substrate_manifest": substrate,
    }


def _no_jobs(**_):
    return {"jobs": []}


def test_production_admission_registry_is_complete_and_currently_closed():
    entries = scheduler.load_source_admission_registry()

    assert len(entries) == 10
    assert entries["CRYPTO_FACTOR_ZOO_MICROSTRUCTURE"]["allowed_for_generation"] is False
    assert not any(row["allowed_for_generation"] for row in entries.values())


def test_no_admitted_source_idles_without_llm_or_trial_write(tmp_path):
    environment = _environment(tmp_path, admitted=False)

    class ForbiddenClient:
        def _call(self, *_):
            raise AssertionError("LLM must not be called")

    result = scheduler.run_scheduler_once(
        **environment,
        client=ForbiddenClient(),
        now=NOW,
        factory_status_fn=_no_jobs,
    )

    assert result["status"] == "idle_no_admitted_source"
    assert result["generation_attempted"] is False
    assert not environment["trial_registry_path"].exists()
    assert list((environment["scheduler_root"] / "runs").glob("*.json"))


def test_admitted_source_freezes_batch_and_registers_one_job(tmp_path):
    environment = _environment(tmp_path, admitted=True)
    calls = []

    def create_job(batch_path, substrate_path, **kwargs):
        calls.append((batch_path, substrate_path, kwargs))
        return "job_synthetic_001"

    admission_hash_before = hashlib.sha256(
        environment["source_admission_path"].read_bytes()
    ).hexdigest()
    result = scheduler.run_scheduler_once(
        **environment,
        raw_candidates=[_candidate()],
        execute_job=False,
        now=NOW,
        factory_status_fn=_no_jobs,
        create_job_fn=create_job,
    )

    assert result["status"] == "job_registered"
    assert result["accepted_candidate_count"] == 1
    assert result["selected_source_id"] == "SOURCE_ONE"
    assert result["factory_job_id"] == "job_synthetic_001"
    assert len(calls) == 1
    assert environment["trial_registry_path"].exists()
    assert hashlib.sha256(environment["source_admission_path"].read_bytes()).hexdigest() == admission_hash_before


def test_daily_quota_prevents_second_generation_cycle(tmp_path):
    environment = _environment(tmp_path, admitted=True)
    first = scheduler.run_scheduler_once(
        **environment,
        raw_candidates=[_candidate()],
        execute_job=False,
        now=NOW,
        factory_status_fn=_no_jobs,
        create_job_fn=lambda *_, **__: "job_first",
    )
    second = scheduler.run_scheduler_once(
        **environment,
        raw_candidates=[_candidate("scheduled_momentum_002")],
        execute_job=False,
        now=NOW,
        factory_status_fn=_no_jobs,
        create_job_fn=lambda *_, **__: "job_second",
    )

    assert first["status"] == "job_registered"
    assert second["status"] == "idle_daily_generation_quota"
    assert second["generation_attempted"] is False


def test_active_job_blocks_generation_before_llm_call(tmp_path):
    environment = _environment(tmp_path, admitted=True)

    class ForbiddenClient:
        def _call(self, *_):
            raise AssertionError("LLM must not be called")

    result = scheduler.run_scheduler_once(
        **environment,
        client=ForbiddenClient(),
        now=NOW,
        factory_status_fn=lambda **_: {
            "jobs": [{"job_id": "job_active", "state": "critic_pending", "terminal": False}]
        },
    )

    assert result["status"] == "idle_active_job_limit"
    assert result["active_job_ids"] == ["job_active"]


def test_incomplete_generation_intent_blocks_a_replacement_cycle(tmp_path):
    environment = _environment(tmp_path, admitted=True)
    scheduler._write_immutable_json(
        environment["scheduler_root"] / "intents" / "cycle_interrupted.json",
        {
            "cycle_id": "cycle_interrupted",
            "created_at_utc": scheduler._iso(NOW),
        },
    )

    result = scheduler.run_scheduler_once(
        **environment,
        raw_candidates=[_candidate()],
        now=NOW,
        factory_status_fn=_no_jobs,
    )

    assert result["status"] == "blocked_incomplete_generation_intent"
    assert result["incomplete_cycle_ids"] == ["cycle_interrupted"]


def test_source_budget_counts_rejected_attempt_despite_family_rename(tmp_path):
    environment = _environment(tmp_path, admitted=True)
    rows = []
    for number in range(5):
        candidate = _candidate(f"prior_reject_{number:03d}")
        candidate["family"] = f"renamed_family_{number}"
        rows.append(
            {
                **candidate,
                "event": "guardrail_rejected",
                "status": "rejected",
                "variant_count": 1,
            }
        )
    environment["trial_registry_path"].write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )

    result = scheduler.run_scheduler_once(
        **environment,
        raw_candidates=[_candidate("new_attempt")],
        now=NOW,
        factory_status_fn=_no_jobs,
    )

    assert result["status"] == "idle_source_budgets_exhausted"
    assert result["generation_attempted"] is False
