# AI Panel Factor Factory - Master Goal Checklist

## North Star

Discover, combine, and eventually deploy a robust crypto strategy whose
expected economic benefit remains positive after realistic fees, spread,
impact, funding, capacity, drawdown, and operational failures.

The autonomous, literature-constrained factor factory is the means, not the
final product. It must reject false alpha and preserve genuine future evidence,
but software reliability, test count, and rejection count are not economic
success. Research success requires useful net-of-cost evidence; capital still
requires historical, prospective, paper-trading, and operational risk gates.

Economic-first rule (2026-07-17): economic mechanism, parameter behavior,
factor identity, net return, and implementability are the primary work. The
factory framework is maintained only where it protects those conclusions,
acquires required data, or preserves prospective evidence. See
`ECONOMIC_RESEARCH_AGENDA_20260717.md`.

Factory-wide cost/time rule (2026-07-18): execution cost and horizon economics
are independent shared inputs governed by
`ECONOMIC_COST_AND_HORIZON_POLICY_V1.json`. They are never calibrated to rescue
or reject the 90-day factor or any other named candidate.

Alignment audit (2026-07-18):
`ECONOMIC_ALIGNMENT_SELF_AUDIT_20260718.md`. The review found no fundamental
economic direction reversal, but corrected stale engineering priorities and a
prospective contract-coupling failure.

Delivery policy: `RESEARCH_UTILITY_FIRST_POLICY_20260716.md`. The factory does
not target zero defects. R0 defects that can manufacture false alpha block a
research decision; R1/R2 provenance, reliability, and automation work proceeds
in parallel with bounded supervised discovery.

## Status Legend

- `[x]` completed and verified
- `[~]` implemented but still incomplete, nonbinding, or awaiting evidence
- `[>]` current priority
- `[ ]` not yet achieved
- `[!]` blocked until an earlier gate passes

## Economic Stage Update - 2026-07-17

Three of the four immediate economic deliverables are complete. This is not
a whole-factory completion percentage: later prospective, strategy, paper, and
live gates remain intentionally time-dependent.

- [x] Factor Identity Audit v1 reconstructed the frozen 90-day low-volatility
  portfolio exactly and excluded Holdout from every identity estimator.
- [x] The audit estimated joint market/size/momentum/liquidity spanning,
  conditional Fama-MacBeth slopes, joint neutralization, long/short legs, asset
  concentration, and market regimes across 50 registered assets.
- [~] Evidence supports continued unchanged prospective observation, but not
  promotion or combo admission. Joint-control net alpha is positive; the pooled
  conditional low-volatility slope is also positive but statistically weak.
  Returns are concentrated in market-down/high-volatility months, and the short
  high-volatility leg changes sign between IS and Validation.
- [x] The small historical OKX L2 pilot reconstructed official 400-level books
  and aligned trades for XRP, LDO, and TRX with complete nominal one-day
  coverage.
- [~] The current fixed 2 bps slippage assumption is conservative for small
  XRP/TRX orders in the pilot, but materially understates thin-asset and larger
  notional cost for LDO. One day cannot calibrate the production cost model.
- [x] The exact primary-paper turnover-volatility and OHLC bid-ask
  constructions are frozen and unit tested. The first L2 comparison preserves
  the three-asset order but overstates quoted spread by 57-135 times.
- [>] Run the frozen unseen dates and assets in
  `OKX_L2_REGIME_SAMPLE_V1.json`. No date, asset, or parameter may be replaced
  after viewing the new L2 results.

Canonical outputs:
`logs/factor_identity_audit_v1_20260717.json` and
`logs/factor_identity_audit_v1_20260717.md`; and
`logs/okx_l2_pilot_20260710.json` and
`logs/okx_l2_pilot_20260710.md`.

Verification: local and Linux suites both pass `274 passed` with the same nine
pre-existing constant-series warnings. The Linux full-data rerun also reports
an exact frozen reconstruction and the same evidence flags.

After the L2 module was added, local and Linux suites both pass `278 passed`
with the same warnings. Deployed L2 code, tests, documents, and canonical
outputs match local SHA-256 hashes; all three production timers remain active.

After the exact-method module and blocked source contract were added, local and
Linux suites both pass `284 passed` with the same warnings. Linux independently
reproduces the same proxy order, ratios, and decision; no source is admitted for
AI generation and no trial was added.

After the factory-wide cost/time scope was made machine-checkable, local and
Linux suites both pass `286 passed` with the same warnings. The 90-day track
remains unchanged and is explicitly not a cost or horizon calibration target.

The 2026-07-18 alignment self-audit found that v1 prospective evidence was
blocked by an over-broad evaluator fingerprint. V1 remains invalid with zero
formal factor days; unchanged v2 starts on 2026-07-18 under a semantic contract.
Local and Linux suites both pass `288 passed`, server factor-shadow integrity is
true, all three timers are active, and no historical return, candidate, trial,
cost, Holdout, or promotion threshold changed.

## 1. Research Integrity And Governance

- [x] Literature hypothesis and replication registries exist.
- [x] Candidate schema, frozen batches, append-only trial registry, and family
  FDR accounting exist.
- [x] Forward-return targets crossing split boundaries are purged, and AI
  feedback ordering is independent of Holdout values and input row order.
- [x] Failed, rejected, and syntax-invalid attempts remain auditable.
- [x] Historical evidence cannot directly create `panel_factor_pass`.
- [~] Gate v3 and the independent red-team audit exist but final promotion
  thresholds remain nonbinding until prospective evidence matures.
- [x] Candidate and family variant budgets are enforced from the append-only
  trial history; exhausted families are rejected before batch admission.
- [ ] Replace forgeable free-form critic JSON with a factory-owned approval
  bound to the exact candidate, registries, formula, substrate, trial snapshot,
  and code bundle. This is off the economic critical path until a real source
  is ready for unattended generation.

Exit condition: no candidate can bypass source registration, budget limits,
batch freezing, trial accounting, or Holdout isolation.

## 2. Point-In-Time Data Substrate

- [x] Fifty registered OKX perpetual assets and a point-in-time top-40 eligible
  panel are available.
- [x] OHLCV, sparse real funding, market cap, open interest, spot basis,
  listing age, and asset labels are supported.
- [x] Missing funding, basis, returns, and pre-listing history are preserved as
  missing rather than silently filled.
- [x] Current 730-day historical substrate and cache audits pass.
- [x] Resolved panel inputs can be stored as content-addressed immutable
  substrate objects; explicit frozen manifests bypass all panel source loaders
  and verify exact round-trip fingerprints.
- [x] Perpetual basis/funding applicability is audited as a two-leg spot-perp
  mechanism rather than an outright perp-return sign.
- [x] The frozen 90-day low-volatility signal passed a separate perpetual
  execution-translation audit after sparse realized funding, standard and
  double costs, current 100 USDT sizing, and independent reconstruction. This
  is product evidence only; it does not promote the factor.
- [ ] Expand toward three to five years where source and exchange history allow.
- [ ] Add historical delisted instruments or another broad point-in-time source
  before making claims about the illiquid crypto majority.
- [>] Calibrate a factory-wide asset/notional/regime cost surface, capacity,
  spread, market impact, and stress assumptions from independent executable
  evidence. The surface is factor-neutral and frozen before use.
- [ ] Standardize source horizon, rebalance, holding period, signal decay, and
  horizon-specific net return reporting across daily, weekly, and monthly
  research without permitting arbitrary horizon grids.

Exit condition: every tested mechanism has sufficient point-in-time breadth,
history, field coverage, and an explicit claim ceiling.

## 3. Canonical Literature Benchmarks

- [x] Liu-Tsyvinski-Wu weekly CMOM adaptation completed: 2/2 historical rejects.
- [x] Zaremba large/liquid daily momentum adaptation completed: 4/4 historical
  rejects.
- [x] Negative benchmark results are closed and cannot be sign-flipped or tuned
  from their Holdout outcomes.
- [x] Perpetual basis/funding literature and data applicability audit completed.
- [x] Batches 003 and 004 evaluated 12 frozen spot-perp paths: 12 historical
  rejects, zero Holdout accesses, zero prospective clues. Gross convergence
  and funding were positive, but two-leg costs dominated even after standard
  10/20 and 10/50 sS turnover mitigation.
- [x] The perpetual basis/funding family is frozen on the current sample; no
  sign flip, holding-period search, threshold search, or renamed retry is
  allowed.
- [ ] Maintain market, size, momentum, liquidity, random, naive momentum, and
  mean-reversion controls in every relevant report.

Exit condition: the main economically plausible benchmark families are either
validly rejected, prospectively eligible, or explicitly blocked by unavailable
data. There is no pressure to manufacture a positive benchmark.

## 4. High-Quality AI Candidate Generation

- [x] AI candidates are constrained to registered sources and panel formulas.
- [x] Generated candidates can be validated, frozen, evaluated, and logged.
- [x] AI feedback is rebuilt and sorted only from IS/Validation evidence;
  Holdout metrics and ordering cannot affect the prompt subset.
- [~] Candidate generation is intentionally frozen while benchmark and data
  applicability work is unresolved.
- [ ] Improve prompts with source mechanism, baseline gap, IS/Val evidence,
  coverage, rolling diagnostics, and allowed operators only.
- [x] Small budgets per round and per mechanism family are enforced in code.
- [~] Exact and approximate structural signatures reject duplicate candidates;
  algebraically equivalent formula detection is still pending.
- [x] Require a hash-bound independent critic approval before a frozen
  generated batch can enter historical evaluation.

Exit condition: AI can produce a small, diverse, falsifiable batch without
leakage, duplicate mining, unsupported direction changes, or unlimited retries.

## 5. Historical Factor Audit

- [x] IS, Val, frozen Holdout, real funding, costs, slippage, turnover,
  drawdown, rolling windows, liquidity scopes, and crash checks exist.
- [x] Family FDR, DSR, and CSCV-PBO implementations exist at their declared
  research stages.
- [x] Missing held returns invalidate evidence rather than becoming zero PnL.
- [x] Synthetic calibration shows the gate is satisfiable for sufficiently
  strong full-panel effects.
- [x] Staged Evaluator v1 physically truncates candidate Stage 2 and purges
  forward-return targets at every IS/Validation/Holdout boundary.
- [~] Differential Point-In-Time Formula Audit v1 exists, but fixed cutoffs and
  raw-value tolerance leave confirmed causality blind spots. Further hardening
  is backlog unless a supervised economic decision depends on the blind spot.
- [x] Evidence-cache identity includes universe rules and actual eligibility;
  conflicting payloads fail closed and cache reuse is opt-in.
- [x] Batch 005 tested the contradictory crypto low-volatility literature as
  two frozen monthly spot paths. The 60-day path was rejected; the 90-day path
  earned permission for prospective observation, not historical promotion.
- [ ] Stress calibration with correlated candidate families, regime-varying
  alpha, delistings, missing fields, liquidity shocks, and escalating costs.
- [x] Prospective Factor Promotion Policy v1 was frozen and hash-bound to the
  first eligible track before its first observation. It cannot be changed
  retroactively for that track.

Exit condition: a frozen candidate can receive one of three honest outcomes:
reject, non-promotional clue, or permission to begin prospective observation.
Historical results alone still cannot authorize capital.

## 6. Prospective Factor Evidence

- [x] Immutable universe snapshots, factor snapshots, manifests, hashes,
  completeness checks, and server timers exist.
- [x] Readiness stages are coded: 30 days at 95% coverage for operational
  observation, 90 days at 98% for non-promotional re-audit, and 365 days at 99%
  for a formal promotion audit.
- [~] The old OI shadow track is deprecated and supplies zero formal evidence.
- [x] The frozen 90-day monthly low-volatility path earned
  `prospective_shadow_strong`; this is a historical clue, not a pass.
- [x] Track `monthly_low_vol_90d_prospective_v1` failed closed on its first
  eligible day because its evaluator hash included unrelated shared modules.
  It has zero valid factor days, is permanently invalidated, and cannot be
  backfilled.
- [x] Replacement track `monthly_low_vol_90d_prospective_v2` activates on
  2026-07-18 with the same factor, inputs, costs, and promotion policy. Its
  semantic evaluator contract ignores unrelated candidate-factory edits.
- [x] Execution translation for this track is historically plausible through
  matching perpetuals. Factor-specific development is now frozen in favor of
  sustainable factory work.
- [>] Accumulate at least 365 complete, hash-valid paired universe/factor days
  under v2. The count remains zero until the closed 2026-07-18 bar is captured.
- [ ] Run the formal prospective promotion audit without changing the factor.

Exit condition: at least one factor survives a full year of genuine future
observations with 99% coverage and passes the frozen promotion audit.

## 7. Factor Combination And Strategy Construction

- [!] Combo research remains blocked while no factor has formal prospective
  promotion evidence.
- [x] Factor Identity Audit v1 is implemented and complete for the frozen
  low-volatility clue. It finds partial incremental historical evidence but
  classifies factor identity as unresolved because the conditional
  cross-sectional result is weak and regime dependence is material. This does
  not admit the factor to a combo.
- [ ] Combine only independently promoted factors; rejected and clue-only
  factors are prohibited inputs.
- [ ] Test correlation, incremental contribution, concentration, regime
  dependence, and combo-level DSR/PBO.
- [ ] Convert the combo into target weights with leverage, liquidity, turnover,
  capacity, exposure, and drawdown constraints.
- [ ] Freeze rebalancing, execution, risk, and emergency-stop rules.

Exit condition: one frozen strategy passes a stricter strategy-level audit and
has no dependence on a single asset, regime, exchange anomaly, or unrealistic
cost assumption.

## 8. Paper Trading And Live Shadow Execution

- [!] Strategy paper trading starts only after the combo gate passes. Factor
  prospective tracking is evidence collection, not strategy paper trading.
- [ ] Generate live signals on schedule without placing orders.
- [ ] Simulate orders against contemporaneous spreads, depth, latency, funding,
  rejects, partial fills, and exchange outages.
- [ ] Reconcile expected versus simulated positions, PnL, fees, and risk daily.
- [ ] Require a frozen observation horizon and pass/fail criteria before the
  paper account starts.
- [ ] Complete incident drills for stale data, duplicate orders, bad prices,
  lost connectivity, and exchange/API failure.

Exit condition: the frozen strategy behaves operationally and economically as
expected in future market conditions, with no unresolved reconciliation or risk
control failures.

## 9. Limited Live Deployment

- [!] No live capital is allowed before paper trading and operational audit pass.
- [ ] Rotate and isolate credentials, use least privilege, and prohibit
  withdrawal permission.
- [ ] Deploy with tiny predefined risk capital and hard position/loss limits.
- [ ] Enable independent monitoring, kill switch, alerting, and immutable logs.
- [ ] Predefine scale-up, pause, rollback, and permanent-retirement rules.
- [ ] Increase capital only from future live evidence, never from a new backtest.

Exit condition: limited live behavior matches the paper contract within
predeclared tolerances and survives the minimum live observation period.

## 10. Autonomous Factory Operation

- [x] Server data updates and prospective snapshots can run on timers.
- [x] Core candidate validation, frozen evaluation, reporting, and registry
  components exist.
- [x] Immutable run contracts, append-only lifecycle evidence, frozen effective
  trial-registry snapshots, and a rebuildable SQLite run index exist for panel
  evaluations.
- [x] Content-addressed panel substrate manifests are integrated into run
  contracts, reports, artifact hashes, and fail-closed zero-loader audits.
- [x] Candidate-batch runs default to the versioned staged evaluator; each path
  reports whether Stage 3 and Holdout were executed.
- [x] One fail-closed frozen-batch state machine now owns formula audit, critic
  review, historical evaluation, terminal classification, and archiving.
- [x] Process Ownership and Concurrency v1 terminates full child process groups
  on heartbeat/lease failure, recovers dead-owner locks, rejects duplicate exact
  batches, isolates attempt reports, and preserves one-shot evaluation.
- [x] Generate human-readable and machine-readable per-job and aggregate
  factory status projections from append-only evidence.
- [x] Machine-readable source admission now binds each literature source to an
  explicit open/closed state, exact formula whitelist, and lifetime variant
  budget. Historical outcomes cannot change admission.
- [x] The bounded scheduler enforces one source, at most five proposals and
  three accepted candidates, one cycle per UTC day, a 24-hour cooldown, one
  active job, immutable intents/results, and fail-closed interrupted-cycle
  handling before the frozen-batch state machine.
- [x] A daily Linux timer is installed. With all nine current sources closed it
  records `idle_no_admitted_source` and makes no AI call.
- [x] The synthetic approved-source Linux drill reached terminal completion
  after one intentional schema rejection and one interrupted-worker retry,
  without opening a real economic source or changing production trial history.
- [x] Unattended jobs are bound to an exact 50-asset content-addressed runtime
  substrate. Evaluation trial events use a validated two-stage commit instead
  of mutating the frozen input snapshot.
- [ ] Route alerts and produce daily scheduler/job health and throughput
  summaries from immutable evidence.
- [ ] Record source-admission changes as append-only, human-approved provenance
  before opening the first real mechanism for unattended generation.
- [ ] Require explicit human approval only at high-risk boundaries: changing a
  binding gate, activating a formal prospective track, creating a combo, and
  enabling or scaling live capital.

Exit condition: routine research and evidence collection run unattended and
fail closed, while capital and research-policy changes remain deliberate.

## Progress Snapshot - 2026-07-16

- Active big phase: sections 2-6. Historical audit continues while the first
  eligible factor begins genuine future observation. The project has not
  entered strategy construction or paper trading.
- The former 90/100 claim is retracted. The frozen red-team audit scores the
  current historical factory at 48/100; an independent reviewer scored 52/100.
  See `HISTORICAL_FACTORY_RED_TEAM_AUDIT_20260715.md`.
- Percentage reporting for the complete factory is suspended until the seven
  binding red-team remediations close. Test counts and implemented modules may
  not be converted directly into completion percentages.
- Sections 7-9 remain deliberately blocked. Section 6 now has one immutable
  promotion-eligible factor track but zero confirmed future days.
- Completed professional-architecture items now also include Differential
  Point-In-Time Formula Audit v1, persistent Panel Evidence Artifact Cache v1,
  Independent Research Critic v1, and Historical Factory State Machine v1.
- The R0 split-boundary, AI-feedback, trial-accounting, and cache-identity
  defects are closed and verified locally and on Linux. Basis/funding Batches
  003 and 004 are also closed economic rejects. Remaining R1/R2 governance and
  observability work blocks real approved-source unattended operation, not
  bounded supervised research or isolated drills.
- Batch 005 and the policy-bound low-volatility tracker are deployed on Linux.
  Daily spot cache readiness is 50/50, both prospective timers are enabled and
  active, readiness integrity passes, and current local/Linux regression is
  270 passed.
- Execution audit 001 passed only for later paper design: +49.67% arithmetic
  net return after realized funding and standard costs, +48.65% at double cost,
  and 22.85% max drawdown. The factor remains unpromoted with zero future days.
- A server cache-version mismatch was caught before evaluation. The canonical
  50-file input body is now recoverable as a hash-locked immutable archive.
- Process Ownership and Concurrency v1 is deployed. Sixteen Windows/Linux fault
  tests and both 256-test full suites pass; duplicate exact batches, orphaned
  process groups, stale locks, and cross-attempt report reuse now fail closed.
- Source Admission and Scheduler v1 is implemented. Production safely idles
  with zero admitted sources, zero AI calls, and no change to the 140-row trial
  registry. The deployed daily timer resolves a frozen 50-asset/730-day runtime
  substrate.
- The synthetic approved-source unattended drill passed all 15 checks on
  Linux. It recovered from an intentionally interrupted worker, rejected an
  invalid proposal, ran the real audit stack once, committed one isolated trial
  event, rejected the economic candidate without accessing Holdout, and created
  no combo. Local and Linux full suites are both `270 passed`.

## Current Priority Order

Scientific alignment override: `RESEARCH_ALIGNMENT_RED_TEAM_AUDIT_20260717.md`.
The review found no fundamental direction error, but found that engineering
maturity is ahead of factor identity, population coverage, and execution
evidence.

1. V1 correctly failed closed but exposed an over-broad evaluator contract.
   V2 is frozen before the 2026-07-18 bar closes; verify its first valid day on
   the next scheduled snapshot without backfilling the invalid v1 day.
2. Factor Identity Audit v1 is complete. The unchanged relation has positive
   joint-control alpha and positive but weak conditional low-volatility slopes;
   it remains unpromoted and regime-concentrated.
3. The small historical OKX L2 pilot is complete. It proves archive and
   reconstruction feasibility and rejects one universal slippage number, but
   one day does not support full cost calibration or a factor batch.
4. Process the frozen multi-regime L2 sample first as a factory-wide execution
   and horizon-economic input. Separately, use its proxy evidence to decide
   whether at most one canonical and two economically motivated microstructure
   paths are allowed. The 90-day track has no calibration priority.
5. Treat blockchain-native value/adoption as data-blocked for the current
   panel: the 2026-07-17 Coin Metrics community check found daily active-address
   coverage for only 19/50 registered assets and no community new-address metric.
6. Preserve full IS/Validation return paths for future trials and construct the
   exact historical archive needed for project-level DSR/PBO. Unrecoverable old
   paths remain explicitly unavailable rather than imputed.
7. Decide whether to acquire a broad active-and-delisted point-in-time universe
   or permanently limit claims to liquid OKX perpetuals.
8. Accumulate 365 future days before combo promotion can be considered.
9. Keep alerts, append-only approvals, critic trust, typed formula generation,
   and generic reliability improvements off the economic critical path unless
   they block valid data, a supervised study, or prospective collection.

## Permanent Stop Rules

- Do not loosen a gate merely because no factor passes.
- Do not invert or modify a rejected factor after seeing Holdout.
- Do not generate unlimited variants from one mechanism.
- Do not call an adaptation an exact replication.
- Do not substitute historical Holdout for prospective evidence.
- Do not create a combo without promoted factors.
- Do not place capital behind a factor-level result.
