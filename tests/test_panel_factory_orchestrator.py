import hashlib
import json
import os
import subprocess
import sys
import time

import pytest

import panel_critic_contract
import panel_factory_orchestrator as factory
import panel_factor_research
import panel_formula_audit


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _setup_job(tmp_path, *, max_critic_attempts=2, substrate_cutoff=None):
    batch = {
        "schema_version": 1,
        "batch_id": "batch_factory_test",
        "candidates": [{"candidate_id": "candidate_001"}],
    }
    request_contract = {"inst_ids": ["A-USDT-SWAP", "B-USDT-SWAP"]}
    if substrate_cutoff:
        request_contract.update(
            {
                "days": 365,
                "cutoff": {"mode": "explicit_as_of", "value": substrate_cutoff},
            }
        )
    substrate = {"request_contract": request_contract}
    trial = tmp_path / "source" / "trial.jsonl"
    trial.parent.mkdir(parents=True)
    trial.write_text("", encoding="utf-8")
    batch_path = _write_json(tmp_path / "source" / "batch.json", batch)
    substrate_path = _write_json(tmp_path / "source" / "manifest.json", substrate)
    literature_path = _write_json(tmp_path / "source" / "literature.json", {"schema_version": 1})
    hypothesis_path = tmp_path / "source" / "hypothesis.md"
    hypothesis_path.write_text("# Registry\n", encoding="utf-8")
    root = tmp_path / "factory"
    job_id = factory.create_job(
        batch_path,
        substrate_path,
        root=root,
        trial_registry_path=trial,
        literature_registry_path=literature_path,
        hypothesis_registry_path=hypothesis_path,
        max_critic_attempts=max_critic_attempts,
    )
    return root, job_id


def _formula_runner(calls):
    def run(context):
        calls.append("formula_audit")
        path = context.job_dir / "test_artifacts" / "formula.json"
        _write_json(
            path,
            {
                "schema_version": panel_formula_audit.AUDIT_SCHEMA_VERSION,
                "candidate_batch_id": context.contract["batch_id"],
                "leakage_free": True,
                "passed": True,
                "required_factor_results": {"candidate_001": "causal_pass"},
            },
        )
        return factory.StageResult("passed", path)

    return run


def _critic_runner(calls, *, approved=True, interrupt=False):
    def run(context):
        calls.append("critic")
        if interrupt:
            raise KeyboardInterrupt()
        batch_path = context.contract["input_snapshots"]["candidate_batch"]["path"]
        formula_path = context.artifacts["formula_audit"]["path"]
        path = context.job_dir / "test_artifacts" / f"critic_{context.attempt}.json"
        review = {
            "candidate_id": "candidate_001",
            "approved": approved,
            "blockers": [] if approved else ["quality_blocker"],
            "checks": {"quality_check": approved},
        }
        report = {
            "schema_version": panel_critic_contract.CRITIC_SCHEMA_VERSION,
            "batch_id": context.contract["batch_id"],
            "decision": "critic_approved" if approved else "critic_rejected",
            "approved": approved,
            "candidate_reviews": [review],
            "batch_checks": {"all_candidates_approved": approved},
            "batch_blockers": [] if approved else ["all_candidates_approved"],
            "holdout_read_by_critic": False,
            "performance_outcomes_read_by_critic": False,
            "inputs": {
                "candidate_batch": {
                    "path": batch_path,
                    "sha256": hashlib.sha256(open(batch_path, "rb").read()).hexdigest(),
                },
                "formula_audit_report": {
                    "path": formula_path,
                    "sha256": hashlib.sha256(open(formula_path, "rb").read()).hexdigest(),
                },
            },
        }
        _write_json(path, report)
        return factory.StageResult("passed" if approved else "rejected", path)

    return run


def _evaluation_runner(calls, *, status="passed", interrupt=False):
    def run(context):
        calls.append("evaluation")
        if interrupt:
            raise KeyboardInterrupt()
        path = context.job_dir / "test_artifacts" / "evaluation.json"
        _write_json(path, {"candidate_batch_id": context.contract["batch_id"]})
        if status == "passed":
            event_path = factory._attempt_report_dir(context) / "panel_trial_events.jsonl"
            event_path.parent.mkdir(parents=True, exist_ok=True)
            event_path.write_text(
                json.dumps(
                    {
                        "event": "evaluated",
                        "status": "panel_factor_reject",
                        "batch_id": context.contract["batch_id"],
                        "candidate_id": "candidate_001",
                        "candidate_signature": "synthetic-signature",
                        "signal_signature": "synthetic-signal",
                        "variant_count": 1,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        return factory.StageResult(status, path, retryable=True)

    return run


def test_critic_rejection_stops_before_evaluation(tmp_path):
    root, job_id = _setup_job(tmp_path)
    calls = []
    status = factory.run_job(
        job_id,
        root=root,
        runners={
            "formula_audit": _formula_runner(calls),
            "critic": _critic_runner(calls, approved=False),
            "evaluation": _evaluation_runner(calls),
        },
    )

    assert status["state"] == "critic_rejected"
    assert calls == ["formula_audit", "critic"]


def test_approved_path_runs_each_stage_once_and_completes(tmp_path):
    root, job_id = _setup_job(tmp_path)
    calls = []
    runners = {
        "formula_audit": _formula_runner(calls),
        "critic": _critic_runner(calls),
        "evaluation": _evaluation_runner(calls),
    }

    status = factory.run_job(job_id, root=root, runners=runners)

    assert status["state"] == "completed"
    assert status["attempts"] == {"formula_audit": 1, "critic": 1, "evaluation": 1}
    assert calls == ["formula_audit", "critic", "evaluation"]


def test_job_contract_inherits_days_and_explicit_cutoff_from_substrate(tmp_path):
    cutoff = "2026-07-15T23:00:00+00:00"
    root, job_id = _setup_job(tmp_path, substrate_cutoff=cutoff)

    contract = factory.load_contract(root / job_id)

    assert contract["evaluation_parameters"]["days"] == 365
    assert contract["evaluation_parameters"]["as_of"] == cutoff


def test_evaluation_trial_commit_preserves_frozen_input_and_is_idempotent(tmp_path):
    root, job_id = _setup_job(tmp_path)
    job_dir = root / job_id
    calls = []
    frozen_input = job_dir / "inputs" / "panel_trial_registry.jsonl"
    frozen_sha256 = hashlib.sha256(frozen_input.read_bytes()).hexdigest()

    status = factory.run_job(
        job_id,
        root=root,
        runners={
            "formula_audit": _formula_runner(calls),
            "critic": _critic_runner(calls),
            "evaluation": _evaluation_runner(calls),
        },
    )
    contract = factory.load_contract(job_dir)
    destination = contract["output_sinks"]["trial_event_registry"]["path"]
    rows = [json.loads(line) for line in open(destination, encoding="utf-8") if line.strip()]

    assert status["state"] == "completed"
    assert hashlib.sha256(frozen_input.read_bytes()).hexdigest() == frozen_sha256
    assert len(rows) == 1
    assert rows[0]["event"] == "evaluated"
    commit = json.loads((job_dir / "outputs" / "trial_event_commit.json").read_text(encoding="utf-8"))
    assert commit["appended_row_count"] == 1
    assert (root / job_id / "STATUS.md").is_file()
    assert (root / "FACTORY_STATUS.md").is_file()


def test_resume_skips_completed_formula_stage(tmp_path):
    root, job_id = _setup_job(tmp_path)
    first_calls = []
    with pytest.raises(KeyboardInterrupt):
        factory.run_job(
            job_id,
            root=root,
            runners={
                "formula_audit": _formula_runner(first_calls),
                "critic": _critic_runner(first_calls, interrupt=True),
                "evaluation": _evaluation_runner(first_calls),
            },
        )
    second_calls = []
    status = factory.run_job(
        job_id,
        root=root,
        runners={
            "formula_audit": _formula_runner(second_calls),
            "critic": _critic_runner(second_calls),
            "evaluation": _evaluation_runner(second_calls),
        },
    )

    assert status["state"] == "completed"
    assert first_calls == ["formula_audit", "critic"]
    assert second_calls == ["critic", "evaluation"]
    assert status["attempts"]["formula_audit"] == 1
    assert status["attempts"]["critic"] == 2


def test_abandoned_evaluation_is_never_retried(tmp_path):
    root, job_id = _setup_job(tmp_path)
    first_calls = []
    with pytest.raises(KeyboardInterrupt):
        factory.run_job(
            job_id,
            root=root,
            runners={
                "formula_audit": _formula_runner(first_calls),
                "critic": _critic_runner(first_calls),
                "evaluation": _evaluation_runner(first_calls, interrupt=True),
            },
        )
    lease_path = root / job_id / "lease.json"
    lease_path.write_text(
        json.dumps({"owner": "dead-worker", "expires_epoch": time.time() - 10}),
        encoding="utf-8",
    )
    second_calls = []
    status = factory.run_job(
        job_id,
        root=root,
        runners={
            "formula_audit": _formula_runner(second_calls),
            "critic": _critic_runner(second_calls),
            "evaluation": _evaluation_runner(second_calls),
        },
    )

    assert status["state"] == "manual_review"
    assert second_calls == []
    assert status["attempts"]["evaluation"] == 1
    assert list((root / job_id / "lease_history").glob("stale_*.json"))


def test_mutated_frozen_input_fails_closed(tmp_path):
    root, job_id = _setup_job(tmp_path)
    contract = factory.load_contract(root / job_id)
    batch_snapshot = contract["input_snapshots"]["candidate_batch"]["path"]
    with open(batch_snapshot, "a", encoding="utf-8") as handle:
        handle.write("\n")
    calls = []

    status = factory.run_job(
        job_id,
        root=root,
        runners={
            "formula_audit": _formula_runner(calls),
            "critic": _critic_runner(calls),
            "evaluation": _evaluation_runner(calls),
        },
    )

    assert status["state"] == "manual_review"
    assert calls == []
    assert status["latest_event_type"] == "immutable_input_validation_failed"


def test_evaluation_failure_is_terminal_manual_review(tmp_path):
    root, job_id = _setup_job(tmp_path)
    calls = []
    runners = {
        "formula_audit": _formula_runner(calls),
        "critic": _critic_runner(calls),
        "evaluation": _evaluation_runner(calls, status="failed"),
    }

    first = factory.run_job(job_id, root=root, runners=runners)
    second = factory.run_job(job_id, root=root, runners=runners)

    assert first["state"] == "manual_review"
    assert second["state"] == "manual_review"
    assert calls.count("evaluation") == 1


def test_candidate_evaluator_cli_requires_critic_before_run_registration(tmp_path):
    batch_path = _write_json(
        tmp_path / "batch.json",
        {"batch_id": "batch_guard_test", "candidates": [{"candidate_id": "candidate_001"}]},
    )

    with pytest.raises(SystemExit) as error:
        panel_factor_research.main(["--candidate-batch", str(batch_path)])

    assert error.value.code == 2


def test_report_discovery_falls_back_to_attempt_report_directory(tmp_path):
    report_dir = tmp_path / "reports"
    report_path = _write_json(report_dir / "panel_formula_audit_test.json", {"passed": False})

    discovered = factory._discover_report_path(
        "WROTE Z:/not-visible/report.json\n",
        report_dir,
        started_epoch=time.time() - 1,
        timeout_seconds=0,
    )

    assert discovered == report_path


def test_exact_frozen_batch_and_substrate_can_only_create_one_job(tmp_path):
    root, first_job_id = _setup_job(tmp_path)

    with pytest.raises(factory.DuplicateBatchJob) as error:
        factory.create_job(
            tmp_path / "source" / "batch.json",
            tmp_path / "source" / "manifest.json",
            root=root,
        )

    assert first_job_id in str(error.value)
    claims = list((root / "batch_claims").glob("claim_*.json"))
    assert len(claims) == 1
    assert [path.name for path in root.glob("job_*")] == [first_job_id]


def test_dead_owner_state_lock_is_archived_and_recovered(tmp_path):
    lock_path = tmp_path / ".state.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": 99999999,
                "hostname": factory.socket.gethostname(),
                "created_epoch": time.time() - 120,
                "token": "dead-owner",
            }
        ),
        encoding="utf-8",
    )

    with factory._exclusive_lock(
        lock_path,
        timeout_seconds=0.5,
        stale_after_seconds=0.0,
    ):
        assert lock_path.is_file()

    assert not lock_path.exists()
    assert len(list((tmp_path / "stale_locks").glob("state.lock_*.json"))) == 1


def test_live_owner_state_lock_is_never_stolen(tmp_path):
    lock_path = tmp_path / ".state.lock"

    with factory._exclusive_lock(
        lock_path,
        timeout_seconds=0.5,
        stale_after_seconds=0.0,
    ):
        with pytest.raises(TimeoutError):
            with factory._exclusive_lock(
                lock_path,
                timeout_seconds=0.1,
                stale_after_seconds=0.0,
            ):
                raise AssertionError("unreachable")


def test_unexpired_job_lease_rejects_a_second_worker(tmp_path):
    root, job_id = _setup_job(tmp_path)
    job_dir = root / job_id
    factory._acquire_lease(job_dir, "worker-one", ttl_seconds=60.0)

    with pytest.raises(factory.JobLeaseBusy, match="worker-one"):
        factory._acquire_lease(job_dir, "worker-two", ttl_seconds=60.0)

    factory._release_lease(job_dir, "worker-one")


def test_attempt_report_directories_are_isolated(tmp_path):
    job_dir = tmp_path / "job_test"
    first = factory.StageContext(
        stage="critic",
        attempt=1,
        contract={"job_id": "job_test", "batch_id": "batch_test"},
        job_dir=job_dir,
        artifacts={},
        heartbeat=lambda: None,
        lease_owner="owner-1",
    )
    second = factory.StageContext(
        stage="critic",
        attempt=2,
        contract={"job_id": "job_test", "batch_id": "batch_test"},
        job_dir=job_dir,
        artifacts={},
        heartbeat=lambda: None,
        lease_owner="owner-2",
    )

    assert factory._attempt_report_dir(first) != factory._attempt_report_dir(second)
    assert factory._attempt_report_dir(first).name == "attempt_0001"
    assert factory._attempt_report_dir(second).name == "attempt_0002"


def test_normal_child_exit_is_recorded_and_clears_active_marker(tmp_path, monkeypatch):
    job_dir = tmp_path / "job_normal_process"
    job_dir.mkdir()
    context = factory.StageContext(
        stage="formula_audit",
        attempt=1,
        contract={"job_id": "job_normal_process", "batch_id": "batch_normal_process"},
        job_dir=job_dir,
        artifacts={},
        heartbeat=lambda: None,
        lease_owner="normal-owner",
    )
    monkeypatch.setattr(factory, "PROCESS_HEARTBEAT_INTERVAL_SECONDS", 0.02)

    returncode, stdout, stderr = factory._run_process(
        [sys.executable, "-c", "print('normal-child-output')"],
        context,
    )

    assert returncode == 0
    assert stdout.strip() == "normal-child-output"
    assert stderr == ""
    assert not (job_dir / "active_process.json").exists()
    final = json.loads(
        (job_dir / "processes" / "formula_audit_attempt_1_final.json").read_text(
            encoding="utf-8"
        )
    )
    assert final["outcome"] == "exited"
    assert final["returncode"] == 0


def test_heartbeat_failure_terminates_the_full_child_process_tree(tmp_path, monkeypatch):
    job_dir = tmp_path / "job_process_test"
    job_dir.mkdir()
    pid_path = tmp_path / "tree_pids.json"
    script = tmp_path / "spawn_tree.py"
    script.write_text(
        "\n".join(
            [
                "import json, os, subprocess, sys, time",
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])",
                "with open(sys.argv[1], 'w', encoding='utf-8') as handle:",
                "    json.dump({'parent': os.getpid(), 'child': child.pid}, handle)",
                "time.sleep(60)",
            ]
        ),
        encoding="utf-8",
    )

    def failing_heartbeat():
        if pid_path.is_file():
            raise RuntimeError("synthetic_lease_loss")

    context = factory.StageContext(
        stage="formula_audit",
        attempt=1,
        contract={"job_id": "job_process_test", "batch_id": "batch_process_test"},
        job_dir=job_dir,
        artifacts={},
        heartbeat=failing_heartbeat,
        lease_owner="test-owner",
    )
    monkeypatch.setattr(factory, "PROCESS_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(factory, "PROCESS_TERMINATION_GRACE_SECONDS", 1.0)

    with pytest.raises(RuntimeError, match="synthetic_lease_loss"):
        factory._run_process([sys.executable, str(script), str(pid_path)], context)

    pids = json.loads(pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 3.0
    while any(factory._pid_exists(pid) for pid in pids.values()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not factory._pid_exists(pids["parent"])
    assert not factory._pid_exists(pids["child"])
    assert not (job_dir / "active_process.json").exists()
    final = json.loads(
        (job_dir / "processes" / "formula_audit_attempt_1_final.json").read_text(
            encoding="utf-8"
        )
    )
    assert final["outcome"] == "terminated_on_orchestrator_exception"
    assert final["termination"]["success"] is True


def test_stale_lease_terminates_recorded_process_before_retry(tmp_path):
    root, job_id = _setup_job(tmp_path)
    job_dir = root / job_id
    contract = factory.load_contract(job_dir)
    factory.append_event(
        job_dir,
        "stage_started",
        "formula_audit_running",
        stage="formula_audit",
        attempt=1,
    )
    popen_options = {}
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        **popen_options,
    )
    record = {
        "schema_version": factory.PROCESS_SCHEMA_VERSION,
        "process_token": "stale-process-token",
        "job_id": job_id,
        "batch_id": contract["batch_id"],
        "stage": "formula_audit",
        "attempt": 1,
        "lease_owner": "dead-worker",
        "pid": process.pid,
        "process_group_id": process.pid,
        "isolated_process_group": True,
        "started_at_utc": factory._utc_now(),
        "command_sha256": "synthetic",
    }
    _write_json(job_dir / "active_process.json", record)
    _write_json(
        job_dir / "lease.json",
        {"owner": "dead-worker", "expires_epoch": time.time() - 10},
    )
    calls = []

    status = factory.run_job(
        job_id,
        root=root,
        owner="replacement-worker",
        runners={
            "formula_audit": _formula_runner(calls),
            "critic": _critic_runner(calls),
            "evaluation": _evaluation_runner(calls),
        },
    )
    process.wait(timeout=3)

    assert status["state"] == "completed"
    assert calls == ["formula_audit", "critic", "evaluation"]
    assert status["attempts"]["formula_audit"] == 2
    assert not factory._pid_exists(process.pid)
    assert not (job_dir / "active_process.json").exists()
    event_types = [row["event_type"] for row in factory.read_events(job_dir)]
    assert "stale_process_group_terminated" in event_types
    assert "stage_abandoned_recoverable" in event_types
