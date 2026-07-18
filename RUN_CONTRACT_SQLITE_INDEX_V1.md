# Run Contract And SQLite Run Index v1

## Purpose

Every panel evaluation must have an identity before it can produce market
evidence. The identity binds the declared parameters, source artifacts, code
digests, stage, batch, costs, split policy, and Holdout-access policy.

SQLite is a query projection. It is not the evidence authority.

## Evidence Layout

Each run owns an immutable directory under `logs/factory_runs/<run_id>/`:

- `run_contract.json`: self-hashing execution contract;
- `code_snapshot.zip`: exact deterministic source bundle verified against the
  contract's per-file hashes;
- `events/*.json`: append-only lifecycle and resolved-data events;
- `snapshots/*`: mutable inputs frozen immediately before use;
- `artifacts/*.json`: hashes and paths for immutable output artifacts.

The mutable trial registry is copied into the run before `_evaluate` reads it.
Multiplicity accounting therefore uses the frozen per-run snapshot, while the
global trial registry remains append-only for future runs.

## SQLite Projection

`logs/factory_run_index.sqlite3` contains:

- `runs`: current query projection;
- `run_events`: indexed immutable lifecycle events;
- `run_artifacts`: indexed immutable artifact manifests.

Runs can be queried by batch, stage, status, data fingerprint, and failure
reason. The index can be deleted and rebuilt from the immutable run evidence:

```text
python panel_run_registry.py --artifact-root logs/factory_runs \
  --index logs/factory_run_index.sqlite3 rebuild
```

## Lifecycle

Allowed state transitions are:

```text
registered -> running -> completed
registered -> failed
running -> failed
running -> interrupted -> running
interrupted -> failed
```

Economic rejection is a completed evaluation. `failed` is reserved for an
engineering or input-contract failure such as insufficient assets or an
unhandled exception.

## Fail-Closed Rules

- A contract hash mismatch invalidates the run contract.
- A code file changed between contract creation and snapshotting invalidates
  the run before evaluation starts.
- A terminal run cannot restart or change outcome.
- Re-registering the same artifact is idempotent only when its bytes match.
- An artifact content conflict raises instead of overwriting evidence.
- Index rebuilding verifies every registered output artifact hash.
- The report filename includes `run_id`, so concurrent runs cannot overwrite
  one another's primary evidence.

## Verified Acceptance

- Unit and integration tests cover contract tampering, lifecycle transitions,
  required query dimensions, failures, idempotent artifacts, mutable-input
  snapshots, rebuilds, artifact tampering, completed panel runs, and unhandled
  panel failures.
- The pre-substrate implementation was archived before server replacement at
  `logs/frozen_code/run_contract_v1_pre_substrate_code_20260715.tar.gz`, SHA256
  `cb800f9fb53364bd59cb1493649bc1868354062f49db5e43aea8ae0190cdaafc`.
- Current local and server regressions pass 194 tests with the same 9
  constant-series warnings. Server verification is rerun for every stage
  closure.
- Two warm-cache runs with the same panel data fingerprint produced identical
  12-row factor output, with 0 pass and 0 watchlist in both runs.
- Warm-cache wall time including Python startup and run registration was 1.733
  seconds for the eight-asset, 60-day baseline-only smoke workload.

## Deferred To Later Stages

- content-addressed baseline and formula feature artifacts;
- stale-run heartbeat and automatic recovery;
- worker leases and retry budgets;
- the full literature-to-archive factory state machine.
