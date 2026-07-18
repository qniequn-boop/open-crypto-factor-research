# Historical Factory Red-Team Audit - 2026-07-15

## Status

`FINAL - ACCEPTANCE SUSPENDED`. The prior 90/100 claim is withdrawn. The
evidence supports a current working score of **48/100**, with an independent
reviewer scoring the same scope at 52/100. The honest conclusion is therefore
approximately 48-52, not 90. No remediation receives credit inside this
finding cycle.

## Independence Controls

- The builder's acceptance weights are not reused.
- Three read-only reviewers inspect separate claim, orchestration, and
  statistical-integrity surfaces.
- Findings are scored before fixes.
- A passing test counts only when it attempts to falsify a declared threat.
- A synthetic or rejected-path run cannot stand in for a real approved-path
  end-to-end run.

## Frozen Red-Team Rubric

| Area | Weight |
| --- | ---: |
| Candidate admission, critic integrity, and bypass resistance | 20 |
| Statistical integrity: PIT, Holdout isolation, multiplicity, cache safety | 20 |
| Immutable evidence, provenance, and reproducibility | 15 |
| State transitions, crash recovery, retry ownership, concurrency | 15 |
| Real end-to-end automation, scheduling, alerts, and resource controls | 15 |
| Data/literature admission readiness and honest claim boundaries | 10 |
| Independent verification quality | 5 |
| **Total** | **100** |

## Automatic Score Caps

- Unresolved critic/evaluator authorization bypass or forgeable approval:
  overall score at most 69.
- Unresolved Holdout leakage, trial undercount, or stale cached decision reuse:
  overall score at most 59.
- No real approved-path end-to-end run: orchestration/reliability credit is
  capped and overall score is at most 84.
- No production research scheduler, alert delivery, acknowledgement workflow,
  and per-worker resource controls: automation credit is at most 5/15 and
  overall score is at most 85.
- Builder-authored weights and builder-run tests alone cannot establish a 90%
  claim. Independent red-team evidence is required.

## Evidence Rules

Accepted evidence:

- exact file and line references;
- a reproducible command or failing adversarial test;
- immutable run/event/report artifacts with verified hashes;
- local and Linux behavior where platform semantics matter.

Not accepted as sufficient evidence:

- test count without threat coverage;
- a document saying a feature exists;
- a rejection before later stages as proof that later stages work;
- a cache speedup as proof of cache-key completeness;
- a self-assigned percentage.

## Findings

### Critical

1. **Validation is not fully isolated from Holdout.** The 24-hour forward
   return at the Validation boundary is recomputed from the full panel, so its
   target can include the first Holdout day. A minimal reproduction changed
   only that Holdout day and flipped 24 Validation IC observations from mean
   `+1.0` to `-1.0`. Relevant paths:
   `panel_factor_research.py:1609`, `:2183`, and `:2259`. The existing survivor
   test at `tests/test_panel_staged_evaluator.py:159` preserves the unpurged
   legacy result instead of detecting the contamination.

2. **Holdout can alter the next AI feedback set.** Final rows are ordered using
   Holdout Sharpe before the feedback builder takes its first 12 rows. In a
   13-candidate reproduction, changing only Holdout ordering changed which
   candidate entered the prompt. Relevant paths: `panel_factor_research.py:2463`
   and `:2703`, plus `panel_candidate_registry.py:415`. This violates the
   declared rule that Holdout is audit-only and never feeds candidate search.

3. **Critic approval is forgeable ordinary JSON.** The evaluator validates
   self-declared `approved` and check fields but has no trusted producer,
   signature, or factory-owned approval event. It also does not bind the
   critic's trial-registry, literature-registry, or hypothesis-registry hashes.
   A hand-written approval was accepted by both
   `validate_critic_approval(...)` and candidate loading:

   ```text
   forged_critic_accepted: true
   critic_failures: []
   candidate_schema_accepted: 1
   candidate_rejections: []
   ```

   Relevant paths: `panel_critic_contract.py:37-100` and
   `panel_factor_research.py:3153-3165`.

4. **Trial history can be reset or silently undercounted.** The evaluator
   accepts an arbitrary registry path; malformed JSONL rows are skipped, a
   missing registry becomes empty history, and current unregistered candidates
   need not increase the count above the built-in floor. A malformed nine-
   variant row was silently omitted while metadata still reported complete:

   ```text
   physical_nonempty_lines: 2
   parsed_rows: 1
   counted_candidate_ids: 1
   counted_variants: 2
   metadata_complete: true
   ```

   Relevant paths: `panel_candidate_registry.py:197-280`, `:338`, and
   `panel_factor_research.py:1774`, `:3103`. The current real registry was also
   checked: all 112 nonempty rows parse, so this is a confirmed fail-open design
   flaw, not evidence that the current file has already been corrupted.

5. **The evidence-cache key omits universe-rule content.** Changing the
   universe target size from 3 to 4 changed observable momentum cells from 936
   to 1248 while the panel fingerprint, common index, and cache request key
   remained identical. A stale artifact can therefore be reused for a
   different eligible universe. Relevant paths: `panel_factor_research.py:1601`
   and `:1830`. Current tests rerun only the exact same configuration.

### High

6. **Formula causality checks have blind spots.** The three fixed cutoffs stop
   at 85%, so an absolute-time future read confined before the first cutoff or
   after the final cutoff can pass. The raw-value tolerance can also hide tiny
   future-dependent differences that cross-sectional ranking amplifies into a
   complete weight reversal. Confirmed reproductions returned `causal_pass`.
   Relevant paths: `panel_formula_audit.py:27`, `:168`, and `:217-235`.

7. **A failed heartbeat does not own or stop its child process.**
   `_run_process` launches a subprocess but has no terminate/kill cleanup when
   heartbeat or lease handling raises. In a reproduction the parent returned
   an error while the child continued and wrote its completion marker. The
   state machine can therefore report failure while evaluation continues
   outside its lease. Relevant path: `panel_factory_orchestrator.py:687-707`.
   The exclusive state lock at `:125-142` also has no stale-lock recovery.

8. **No real approved-path end-to-end run exists.** The cited real job used an
   eight-asset substrate while its policy required at least 20 assets, so it was
   structurally guaranteed to stop at formula audit. It exercised one formula
   attempt, zero critic attempts, and zero evaluator attempts. The approved-path
   orchestrator tests use injected fake runners rather than the real subprocess
   chain. This proves rejection at the first gate, not factory completion.

9. **Provenance is useful but not immutable in the claimed sense.** Lifecycle
   events are individually self-hashed, not hash-chained or externally anchored;
   deletion or replacement can produce a new internally consistent history.
   Formula approval is not bound to every matrix-builder dependency or enforced
   against the current substrate. Shared report discovery can also bind the
   wrong same-batch report under concurrent jobs.

10. **DSR/PBO can claim the full trial count without full historical return
    paths.** Missing historical paths are diagnostic rather than necessarily
    binding, so the multiplicity numerator and available path evidence can refer
    to different experiment sets. Relevant paths: `panel_factor_research.py:1283`,
    `:1331`, and `:2431`.

### Medium

11. Point-in-time checks assume row timestamp equals information-availability
    time. Revised/backfilled observations and later-known classifications are
    not modeled with publication timestamps.
12. One cache request may map to conflicting payloads without raising a
    nondeterminism or incomplete-key error (`panel_artifact_cache.py:149`).
13. Server timers cover data and prospective snapshots, not the complete
    historical factory. Alert delivery, acknowledgement, generation scheduling,
    and per-worker resource controls remain absent.

## Score

| Area | Weight | Credit | Reason |
| --- | ---: | ---: | --- |
| Candidate admission and critic integrity | 20 | 7 | real gates exist, but approval can be fabricated |
| Statistical integrity | 20 | 8 | strong intent, but Holdout, cache, trial, and formula defects are binding |
| Evidence, provenance, reproducibility | 15 | 9 | contracts and artifacts exist; trust chain and dependency binding are incomplete |
| State, recovery, concurrency | 15 | 8 | state machine exists; child ownership, stale lock, and report discovery are unsafe |
| Real automation and operations | 15 | 3 | no real approved E2E or production research scheduler/alerts |
| Data/literature readiness | 10 | 9 | this remains the strongest, most mature layer |
| Independent verification | 5 | 4 | two useful independent reviews and concrete reproductions; no fixed-code rerun yet |
| **Total** | **100** | **48** | **historical-factory acceptance fails** |

Automatic caps at 69 and 59 are both triggered, but the evidence-based raw
score is already below them. Passing `219` tests does not contradict this
verdict: the reproductions expose threats those tests did not cover.

## Decision

- The former 90/100 acceptance is retracted and must not be cited as current.
- Candidate generation, a third benchmark batch, combo work, prospective
  promotion, paper trading, and capital remain frozen.
- The next stage is a remediation cycle, not more factor search.
- Fixes must be evaluated against this frozen document; the remediation author
  cannot rewrite the rubric or award the closure score.

## Binding Remediation Order

### Risk-Acceptance Addendum - 2026-07-16

The findings and 48/100 audit score remain frozen. The business owner has
explicitly accepted nonzero software risk and clarified that useful economic
evidence, rather than defect-free engineering, is the product objective.

Accordingly, this section no longer means that every item must close before any
research resumes. `RESEARCH_UTILITY_FIRST_POLICY_20260716.md` supersedes the
sequencing rule: research-decision defects are R0; provenance and operational
hardening are R1/R2. A bounded supervised pilot may resume after its R0 controls
close, while the remaining findings continue as disclosed engineering debt.

1. Purge forward targets at every split and remove every Holdout-dependent
   ordering, selection, prompt, and feedback channel.
2. Replace free-form critic JSON trust with a factory-owned authorization bound
   to exact candidate, formula, substrate, registries, code, and trial snapshot.
3. Make trial accounting fail closed, locked, sequenced, and hash-chained; an
   invalid or missing row must abort evaluation.
4. Complete cache identities with universe rules and derived eligibility;
   conflicting payloads for one request must fail.
5. Terminate the owned process group on lease/heartbeat failure, isolate every
   job's outputs, and add stale-lock and concurrency recovery tests.
6. Replace fixed formula cutoffs with property-based/random boundary tests and
   compare portfolio ranks/weights as well as raw values.
7. Run one genuine default-runner approved-path end-to-end drill on both Windows
   and Linux, preserving commands, stdout, environment, and artifact hashes.
8. Under the 2026-07-16 risk-acceptance addendum, items 1-7 remain the full
   closure list but no longer share one blocking level. Literature/data
   applicability may proceed now; a supervised candidate pilot waits for its
   R0 controls, and unattended operation waits for R1 closure.
