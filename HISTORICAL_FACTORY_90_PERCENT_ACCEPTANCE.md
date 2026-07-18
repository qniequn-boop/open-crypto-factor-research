# Historical Research Factory 90 Percent Acceptance

> **RETRACTED 2026-07-15.** This builder-authored acceptance is retained only
> as historical evidence. It is superseded by
> `HISTORICAL_FACTORY_RED_TEAM_AUDIT_20260715.md`, which confirmed Holdout
> leakage, forgeable critic approval, fail-open trial accounting, an incomplete
> cache identity, formula-audit blind spots, and no real approved-path E2E run.
> The current working score is 48/100; this document must not be cited as a
> current acceptance.

## Scope

This score covers engineering for literature-constrained historical panel
research. It does not score the probability of finding alpha and does not
include the future 365-day prospective period, combo construction, paper
execution, or live capital.

The percentage is a weighted acceptance matrix, not an intuition-based status
number. Credit requires implementation, tests, and an inspectable artifact.

## Acceptance Matrix

| Area | Weight | Verified credit | Evidence |
| --- | ---: | ---: | --- |
| Governance, preregistration, budgets, Holdout feedback ban | 10 | 10 | candidate/trial registries and prompt tests |
| Point-in-time data substrate and missingness | 12 | 10 | immutable substrate v1; longer/delisted history remains |
| Run provenance and reproducibility | 10 | 10 | run contracts, code snapshots, JSON evidence, SQLite projection |
| Differential point-in-time formula gate | 10 | 10 | truncation/perturbation audit and planted-leak tests |
| Independent critic and no-bypass enforcement | 10 | 9 | deterministic critic; algebraic equivalence remains |
| Staged evaluation, Holdout isolation, multiplicity | 12 | 11 | physical Val truncation; final gate freeze remains |
| Persistent evidence cache and measured efficiency | 10 | 9 | 63-65% warm speedup; retention/GC remains |
| State machine, lease, recovery, retry ownership, status | 12 | 10 | fail-closed orchestrator; external alerting/quotas remain |
| Local and server regression plus real rejection drill | 8 | 8 | 219 tests on each OS; real job stopped before evaluator |
| Unattended production scheduling and alerts | 6 | 3 | data timers exist; research-job timer/alerts remain |
| **Total** | **100** | **90** | historical-factory engineering threshold |

## Binding 90 Percent Conditions

The score is valid only when all of these are true on the current code:

- complete local test suite passes;
- complete server test suite passes after hash-matched sync;
- a real frozen rejected batch stops before evaluator execution;
- a candidate CLI cannot run without a bound critic approval;
- current module documentation matches code behavior;
- no pass, combo, prospective promotion, paper trade, or capital claim is made.

If any condition is false, the verified score falls below 90 until corrected.

## Final Verification - 2026-07-15

- Local Windows: `219 passed, 9 warnings` in 50.84 seconds.
- Server Linux: `219 passed, 9 warnings` in 156.21 seconds.
- Synced implementation/test/document set: 20/20 SHA256 matches.
- Real frozen rejection job:
  `job_20260715T152405352977Z_5951c16c12`.
- Real job state: `formula_rejected` after one formula-audit attempt.
- Critic attempts: 0; evaluation attempts: 0; evaluation events: 0.
- Event chain: registration, formula start, formula rejection.
- The first operational drill correctly entered `manual_review` when the
  parent worker failed to discover an already-written report. That evidence
  remains immutable. Artifact discovery was corrected, covered by a regression
  test, and the second frozen job produced the expected scientific rejection.

This conclusion was withdrawn by the independent red-team audit on 2026-07-15.
It overcredited builder-authored tests and a first-stage rejection drill, and
did not test several binding failure modes. Historical claim only: **90/100
was not established**.

## Remaining Ten Percent

- Freeze the final binding historical gate after broader synthetic stress.
- Add algebraic/semantic duplicate detection beyond approximate signatures.
- Add production research-job timer, alert delivery, acknowledgement, and
  resource quotas.
- Add cache retention and garbage collection policy.
- Expand historical breadth/length and delisted coverage where honest data are
  available.

These are the next engineering improvements. They are not permission to start
another candidate batch before the basis/funding applicability decision.
