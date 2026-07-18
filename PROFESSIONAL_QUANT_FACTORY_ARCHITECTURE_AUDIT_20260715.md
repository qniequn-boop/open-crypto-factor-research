# Professional Quant Factory Architecture Audit - 2026-07-15

## Decision

The factory should adopt a staged, artifact-driven research architecture. It
should not increase throughput by generating more candidates or by adding
parallel workers before redundant computation and weak stage boundaries are
removed.

The target design is:

1. point-in-time data assets;
2. content-addressed substrate and feature artifacts;
3. a queryable experiment/run recorder;
4. a cheap-to-expensive evaluation funnel;
5. immutable prospective evidence;
6. one event-driven strategy implementation for simulation and live execution.

The project should borrow these patterns without installing a large platform
whose operational cost exceeds the needs of one `t3.micro` research server.

## Primary Systems Reviewed

### Microsoft Qlib

Qlib separates its data layer, expression engine, dataset, workflow, recorder,
task management, portfolio strategy, and online serving. Its data layer offers
memory, expression, and dataset caches. Its recorder groups runs into
experiments and stores parameters, metrics, and artifacts. Its task manager
uses explicit waiting, running, partial, and done states.

Adopt:

- separate data, feature, evaluation, and online layers;
- durable expression/dataset caching;
- one run recorder per immutable evaluation;
- explicit task states and retry ownership.

Do not adopt now:

- the full Qlib storage format, MongoDB task manager, or model stack;
- stock-specific assumptions that do not match sparse funding and perpetual
  execution accounting.

Sources:
https://qlib.readthedocs.io/en/latest/component/data.html,
https://github.com/microsoft/qlib/blob/main/docs/component/recorder.rst,
https://qlib.readthedocs.io/en/v0.9.6/advanced/task_management.html, and
https://qlib.readthedocs.io/en/stable/advanced/PIT.html.

### R&D-Agent-Quant

R&D-Agent-Quant separates Research from Development and connects them through
structured experimental feedback. This supports our decision to keep a
hypothesis agent distinct from a deterministic implementation/evaluation
system.

Adopt:

- separate Research, Development, and Critic responsibilities;
- convert a hypothesis into a frozen, executable task contract;
- preserve experiment traces and implementation errors as reusable memory.

Do not adopt now:

- adaptive direction selection from reusable Holdout outcomes;
- factor-model co-optimization before a factor has credible evidence;
- reported returns as evidence that the architecture will find crypto alpha.

Sources: https://papers.nips.cc/paper_files/paper/2025/hash/ac5c2b6e423883cbcacbcccf88491b78-Abstract-Datasets_and_Benchmarks_Track.html
and https://github.com/microsoft/RD-Agent.

### QuantConnect LEAN And NautilusTrader

LEAN models historical analysis as a fast-forward event stream and uses the
same algorithm interface for backtesting and live trading. NautilusTrader uses
the same strategies and execution algorithms in backtest and live nodes, with
deterministic time and execution semantics.

Adopt later at the strategy layer:

- one event-driven strategy contract for paper and live operation;
- explicit order, fill, fee, slippage, latency, portfolio, and reconciliation
  models;
- configuration-driven runs rather than separate research/live code copies.

Do not adopt yet:

- an execution engine while no factor is prospectively promoted;
- event-driven simulation as the cheap factor-screening engine.

Sources:
https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/algorithm-engine,
https://nautilustrader.io/docs/latest/concepts/backtesting/, and
https://nautilustrader.io/docs/latest/concepts/live/.

### MLflow, Feast, Dagster, And Freqtrade

MLflow records code versions, parameters, metrics, artifacts, and dataset
digests for each run. Feast formalizes point-in-time-correct historical joins.
Dagster models data products as assets with lineage and quality checks.
Freqtrade performs differential lookahead analysis by comparing a baseline run
with sliced signal runs rather than trusting code inspection alone.

Adopt:

- a lightweight SQLite run index plus immutable JSON/Parquet artifacts;
- dataset and code digests on every run;
- declared point-in-time feature contracts and asset checks;
- a differential truncation test for every candidate formula.

Do not adopt now:

- an MLflow server, Feast service, or Dagster daemon on the small server;
- a second copy of metadata already recorded in immutable artifacts;
- dataframe-wide parameter mining merely because vectorization makes it fast.

Sources: https://mlflow.org/docs/latest/ml/tracking/,
https://docs.feast.dev/getting-started/concepts/point-in-time-joins,
https://docs.dagster.io/, and
https://docs.freqtrade.io/en/stable/lookahead-analysis/.

## Current Factory Strengths

- Point-in-time top-40 eligibility and one-day-lagged daily market cap exist.
- Missing basis, funding, OI, price, and pre-listing history remain missing.
- Candidate batches, literature batches, code hashes, data hashes, and trial
  events are immutable or append-only.
- Holdout feedback is excluded from AI prompts.
- Candidate and family budgets are enforced in the generator.
- Exact and approximate structural signatures reject many duplicates.
- Full evaluator runs cache IC, inference, weights, split metrics, rolling
  diagnostics, and cross-sectional robustness inside one process.
- Systemd timers use `flock`, resource limits, and fail-closed shell settings.
- Prospective universe and factor snapshots have manifests and hashes.

## Measured Efficiency Evidence

The same eight-asset, 60-day smoke workload was profiled locally. It is a
runtime benchmark only; its sample is too short to be economic evidence.

Cold cache:

- 45.121 seconds total;
- 38.848 seconds in panel loading;
- 16 remote requests for missing OI and market-cap caches dominated runtime.

Warm cache, all built-in definitions:

- 6.440 seconds total;
- 4.847 seconds in `_evaluate`;
- 2.475 seconds in `_build_matrices`.

Warm cache, baseline-only scope before correction:

- 4.488 seconds total;
- 3.063 seconds in `_evaluate`;
- 2.471 seconds in `_build_matrices`;
- the builder still computed unrequested factor families.

The evaluator now forwards the requested baseline/candidate scope to the matrix
builder. Under the identical warm-cache benchmark after correction:

- total runtime fell from 4.488 to 1.982 seconds, a 55.8% reduction;
- `_evaluate` fell from 3.063 to 0.631 seconds, a 79.4% reduction;
- function calls fell from about 8.35 million to 2.52 million.

Local and server regression suites both pass 173 tests after the correction.
The nine warnings remain the existing constant-series correlation warnings.

Because `LITERATURE_REPLICATION_BATCH_002.json` locked the prior evaluator
hash, its exact source was archived before this optimization at
`logs/frozen_code/literature_replication_002_locked_code_20260715.tar.gz`.
The archive SHA256 is
`6797429979b90f4c7637255a2385acc27f4891b71643bf482b8361493b134bab`.
The current source is intentionally not allowed to masquerade as the old frozen
implementation.

Profiles:

- `logs/panel_factor_profile_8asset_60d_20260715.prof`;
- `logs/panel_factor_profile_8asset_60d_warm_20260715.prof`;
- `logs/panel_factor_profile_8asset_60d_baselines_warm_20260715.prof`;
- `logs/panel_factor_profile_8asset_60d_baselines_optimized_20260715.prof`.

## Main Gaps

### 1. Panel substrate cache lifetime was too short - v1 closed 2026-07-15

IC, weights, and robustness caches disappear when a process exits. A new batch
reloads the same 50 assets, rebuilds the same matrices, and recomputes the same
baselines.

The resolved panel substrate is now persisted as per-asset/per-field Parquet
blobs and a self-hashing object manifest keyed by data cutoff, panel
fingerprint, universe registry, field contract, missingness policy, and loader
code. Explicit frozen manifests make zero panel network requests. Persistent
feature and baseline artifacts remain implementation item 5.

### 2. Evaluation is still too monolithic

Every evaluated path currently receives expensive rolling, robustness,
DSR/PBO, and Holdout work even when coverage or Val IC already makes promotion
impossible.

Required correction: use a fixed multi-fidelity funnel while retaining every
outcome-seen candidate in multiplicity accounting.

### 3. Experiment metadata was fragmented - v1 closed 2026-07-15

JSON artifacts are strong evidence, but there is no single queryable run table
for state, parent batch, data fingerprint, code version, stage, duration,
failure reason, and artifact paths.

Correction implemented in `panel_run_registry.py` and documented in
`RUN_CONTRACT_SQLITE_INDEX_V1.md`. Each panel evaluation now has a self-hashing
immutable contract, append-only lifecycle evidence, immutable artifact
manifests, a frozen effective trial-registry snapshot, and a rebuildable SQLite
projection. JSON artifacts remain the evidence authority. Local Windows and
server Linux regression suites both pass 182 tests.

### 4. Generic differential leakage audit - v1 closed 2026-07-15

`panel_formula_audit.py` now physically truncates and separately perturbs
future panel inputs, rebuilds every core/formula/factor frame, and compares the
complete historical prefix at multiple cutoffs. A planted `shift(-1)` leak is
detected, while unobservable required formulas fail closed. Contract:
`PANEL_FORMULA_AUDIT_V1.md`.

### 5. Persistent path-evidence cache - v1 closed 2026-07-15

`panel_artifact_cache.py` stores content-addressed pre-multiplicity path
evidence across processes. Trial counts, DSR/PBO, FDR, and classifications are
never cached. The real 730-day warm benchmark fell from 109.875 seconds to
37.908 seconds with identical audited outputs. Contract:
`PANEL_EVIDENCE_ARTIFACT_CACHE_V1.md`.

### 6. Critic and orchestration - v1 closed 2026-07-15

The deterministic critic independently validates source authorization,
budgets, identities, formula direction, and the differential audit. Evaluator
CLI entry is hash-bound to critic approval. `panel_factory_orchestrator.py`
adds immutable job contracts, input snapshots, append-only state, leases,
heartbeats, bounded pre-evaluation retries, no evaluation retry, recovery, and
status projections. Contracts: `PANEL_RESEARCH_CRITIC_V1.md` and
`HISTORICAL_FACTORY_STATE_MACHINE_V1.md`.

### 7. Research and execution semantics are separate

This is acceptable at the factor stage, but a future combo must not be rewritten
into unrelated paper/live code.

Required correction later: select one event-driven engine and make paper/live
execution use the same strategy contract.

## Target Evaluation Funnel

### Stage 0 - Source And Power Admission

- source and mechanism registered;
- required fields and claim ceiling valid;
- minimum breadth/history/power plausible;
- family budget remains;
- no market outcome is evaluated.

### Stage 1 - Compilation And Leakage

- schema and DSL validation;
- structural and semantic duplicate checks;
- synthetic invariants;
- differential point-in-time truncation test;
- cost is seconds, no Holdout access.

### Stage 2 - Cached IS/Val Screen

- coverage and missing-held-return validity;
- daily dependence-aware RankIC;
- net return, turnover proxy, and registered baselines;
- family multiplicity ledger includes every outcome-seen path;
- objective failures stop here and never access Holdout.

### Stage 3 - Full Historical Audit

- only Stage-2 survivors run rolling, liquidity, asset-family, crash, DSR/PBO,
  and frozen Holdout non-collapse;
- no formula change is allowed;
- the maximum outcome remains permission for prospective observation.

### Stage 4 - Prospective Evidence

- immutable daily universe, signal, return, and contract artifacts;
- 30/90/365-day readiness stages remain binding;
- no feedback-driven candidate mutation.

### Stage 5 - Strategy And Execution

- promoted factors only;
- combo-level audit;
- one event-driven paper/live strategy implementation;
- order reconciliation, risk controls, and capital approval remain separate.

## Implementation Order

1. [completed] Run Contract and SQLite Run Index v1.
2. [completed] Content-Addressed Panel Substrate Cache v1.
3. [completed] Staged Evaluator v1 with physical Holdout isolation before Stage 3.
4. [completed] Differential Point-In-Time Formula Audit v1.
5. [completed] Persistent Baseline and Formula Artifact Cache v1.
6. [completed] Independent Research/Development/Critic workflow v1.
7. [completed] Fail-closed single-worker historical state machine v1.
8. Production alerts and scheduling; a multi-worker queue remains deferred
   until profiling shows one worker is insufficient.
9. Event-driven execution engine only after a combo is eligible.

## Efficiency Acceptance Criteria

- A frozen audit makes zero network requests.
- Identical data, cutoff, code, and contract do not rebuild the substrate.
- Unrequested factors are never computed.
- A Stage-2 reject never computes Holdout or Stage-3 robustness.
- Every outcome-seen reject still increases the correct multiplicity count.
- A run can be queried by batch, stage, status, fingerprint, or failure reason.
- Interrupted runs resume from immutable completed artifacts or fail closed.
- Parallel execution cannot duplicate a trial or overwrite an artifact.

## Anti-Patterns Rejected

- adding machines before eliminating repeated work;
- running every audit at maximum fidelity;
- installing a distributed orchestrator for one small server;
- allowing the AI to choose its next direction from Holdout;
- using faster parameter sweeps to increase the number of hypotheses;
- maintaining separate backtest and live strategy implementations;
- treating an experiment dashboard as evidence rather than an index to evidence.

## Next Action

Complete current-code local/server verification and a real rejected-batch stop
drill for the 90-point historical-factory acceptance matrix. Then return to the
perpetual basis/funding literature and data-applicability decision. Do not
increase candidate throughput before that scientific admission question is
resolved.

Verification completed on 2026-07-15: Windows and Linux each pass 219 tests;
20 synchronized files match by SHA256; real job
`job_20260715T152405352977Z_5951c16c12` ended `formula_rejected` with zero
critic and evaluation attempts. The next action is now the basis/funding
applicability decision.
