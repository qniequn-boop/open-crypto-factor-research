# Staged Panel Evaluator v1

## Purpose

The staged evaluator separates cheap historical selection from expensive audit
work without changing the multiplicity ledger. Its primary v1 benefit is
scientific isolation, not a claim that every small batch becomes faster.

## Execution Contract

Candidate-batch CLI runs default to `--evaluation-funnel staged_v1`. Direct
library calls remain on `legacy_full` unless the staged funnel is requested.

Stage 2:

- determines the IS/Validation boundary from the declared panel contract;
- truncates the panel to the final Validation timestamp before rebuilding any
  candidate formula;
- therefore leaves forward-return targets crossing the Validation/Holdout
  boundary absent rather than reading future Holdout prices;
- evaluates only IS/Validation coverage, IC, long-short economics, turnover,
  sign consistency, and held-return completeness;
- cannot receive a `Holdout` key under `panel_stage_policy.py`;
- rejects a path before rolling, robustness, DSR, gate v2/v3, or Holdout audit.

Registered baselines bypass Stage 2 and always receive the complete Stage 3
audit. Candidate paths that satisfy every Stage-2 necessary condition receive
the same full evaluator used by the legacy control.

## Multiplicity And Evidence

Early stopping does not erase a trial:

- every original candidate id and weighting variant remains in the trial count;
- every Stage-2 IS/Validation net-return path is retained for run-level DSR/PBO
  dispersion and the immutable selection-return archive;
- Stage-2 rejects receive explicit `stage_3.executed = false` and
  `holdout_accessed = false` fields rather than zero-filled Holdout metrics;
- candidate trial-registry events distinguish `stage_2_objective_failure` from
  complete staged audit.

## Verification

Local Windows and server Linux regression on 2026-07-15:

- both environments: `194 passed, 9 warnings`;
- Stage-2 policy rejects any object containing a Holdout split;
- a rejected path is absent from the candidate definitions passed to Stage 3;
- a forced survivor matches the legacy evaluator exactly on status, checks,
  IC, split economics, rolling audit, robustness, trial adjustment, DSR/PBO,
  and the selection-return archive.

Real frozen 8-asset/730-day comparison used candidate batch
`20260713T150601Z` and substrate
`541736a96b96be090e7a28d8e37c52ef73ab90d4b85277a1db5a599fdfc7ae7d`:

- four AI candidate paths entered Stage 2;
- all four failed before Holdout, so candidate Holdout access count was zero;
- trial count remained 100 and observed PBO path count remained 16;
- PBO remained 0.6984126984 and the archived selection paths matched legacy;
- all 12 baseline rows matched legacy across every audited economic field;
- staged wall time was 101.9 seconds: Stage 2 6.23 seconds and Stage 3 93.81
  seconds;
- legacy wall time was 94.6 seconds.

The small all-zero candidate batch did not produce a speedup because mandatory
baseline Stage 3 work dominates and physically rebuilding the truncated Stage-2
panel has a fixed cost. This is an accepted, disclosed v1 limitation. A
content-addressed baseline/formula artifact cache is required for material
throughput gains; larger nontrivial candidate batches may benefit earlier, but
that claim has not yet been benchmarked.

## Non-Claims

- Stage 2 is not a promotion gate.
- A Stage-2 survivor is not a valid factor.
- Historical Holdout still cannot create formal promotion evidence.
- This implementation does not authorize a combo, paper trading, or capital.
