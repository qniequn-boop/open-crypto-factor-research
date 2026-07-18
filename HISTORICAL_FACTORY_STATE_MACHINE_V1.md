# Historical Factory State Machine v1

## Purpose

`panel_factory_orchestrator.py` is the single supported path from a frozen
candidate batch to historical evaluation. It is intentionally lightweight for
the current server and borrows explicit state, cache-key, lease, and recovery
ideas from Prefect without installing a distributed orchestration platform.

## Lifecycle

The fixed state path is:

1. `formula_audit_pending`;
2. `formula_audit_running`;
3. `critic_pending`;
4. `critic_running`;
5. `evaluation_pending`;
6. `evaluation_running`;
7. `completed`.

Valid fail-closed terminal states are `formula_rejected`, `critic_rejected`,
and `manual_review`. Rejected jobs never advance to the next stage.

## Durable Evidence

Each job contains:

- a self-hashing immutable `job_contract.json`;
- byte-frozen candidate, trial, hypothesis, and replication registries;
- hashes for the immutable panel substrate, universe registry, and code;
- one immutable JSON file per append-only state transition;
- derived `status.json` and `STATUS.md` projections;
- aggregate `factory_status.json` and `FACTORY_STATUS.md` projections;
- stage reports and captured stdout/stderr.

Derived status can be rebuilt from the contract and event files. It is not the
evidence authority.

## Retry And Recovery Policy

- Formula-audit and critic infrastructure failures have small fixed attempt
  budgets; scientific rejection is never retried.
- The evaluation attempt budget is exactly one.
- An evaluation failure becomes `manual_review`, even if a runner labels it
  retryable.
- An abandoned formula or critic stage may resume within its original budget.
- An abandoned evaluation stage becomes `manual_review` and is never rerun.
- A lease has an owner, expiry, and heartbeat. An expired lease is archived
  before recovery.
- Every stage revalidates all frozen input and code hashes before execution.

These rules prevent a crash or an observed bad result from silently creating a
new statistical trial.

## CLI

Create and run a frozen job:

```text
python panel_factory_orchestrator.py create-run \
  --candidate-batch <batch.json> \
  --substrate-manifest <manifest.json>
```

Resume or inspect:

```text
python panel_factory_orchestrator.py run --job-id <job_id>
python panel_factory_orchestrator.py status --job-id <job_id>
python panel_factory_orchestrator.py status
```

## Verified Behavior

Integration tests prove critic rejection stops before evaluation, approved
jobs execute each stage once, resume skips completed stages, stale leases are
archived, abandoned evaluation is not retried, evaluation failure is terminal,
and mutated frozen input stops before any runner executes.

Real acceptance job `job_20260715T152405352977Z_5951c16c12` used the frozen
OI batch and 730-day substrate. It ended `formula_rejected` after one attempt,
with zero critic attempts, zero evaluation attempts, and no evaluation event or
stage log.

## Deferred Operations

- A production timer/service for autonomous batch admission;
- external alerts and operator acknowledgement workflow;
- OS-level CPU, memory, and disk quotas around each worker;
- multi-worker scheduling, which is unnecessary until one worker is measured
  as a throughput bottleneck.
