# Research Next Steps

Current objective: produce genuinely usable crypto trading research, not a
single attractive backtest.

Master direction and completion checklist:
`FACTORY_MASTER_ROADMAP.md`.

Latest independent-style alignment review:
`ECONOMIC_ALIGNMENT_SELF_AUDIT_20260718.md`.

Utility-first delivery and risk policy:
`RESEARCH_UTILITY_FIRST_POLICY_20260716.md`.

Professional architecture and measured-efficiency audit:
`PROFESSIONAL_QUANT_FACTORY_ARCHITECTURE_AUDIT_20260715.md`.

## Economic Research Priority Override - 2026-07-17

`ECONOMIC_RESEARCH_AGENDA_20260717.md` is now the primary work order. Economic
mechanism, parameter behavior, factor identity, net return, and realistic
implementation take precedence over further generic factory hardening.

`ECONOMIC_COST_AND_HORIZON_POLICY_V1.json` now makes cost and time research a
factory-wide economic layer. The 90-day low-volatility clue is not its target
and cannot choose assets, dates, notionals, regimes, costs, or horizons.

Immediate sequence:

1. explain the frozen 90-day low-volatility return with joint factor controls,
   long/short attribution, regimes, concentration, costs, and capacity;
2. pilot OKX historical L2 data for spread, depth, turnover volatility, and
   price impact;
3. freeze one exact literature microstructure construction and at most two
   economically motivated parameter paths;
4. keep blockchain-native value/adoption on the research list, but do not test
   it on inadequate current data: the live Coin Metrics community catalog
   covered daily active addresses for only 19/50 registered assets and no
   community new-address metric;
5. keep the low-volatility prospective track collecting without changes.

Stage update: items 1 and 2 are complete. `panel_factor_identity_audit.py` exactly
reconstructed the frozen 90-day portfolio before running any attribution and
did not load Holdout into an identity estimator. Across the pooled IS and
Validation selection sample:

- annualized joint-control daily net alpha was 17.98% with HAC t=2.01;
- monthly net alpha was 16.70% annualized with HAC t=1.75;
- the conditional low-volatility coefficient was positive, but HAC t=1.47 and
  two-sided p=0.141 did not establish a clean independent factor identity;
- joint-neutralized net return remained positive in IS and Validation, but the
  Validation diagnostic was weak;
- market-up and low-volatility months were negative in aggregate, while the
  return was concentrated in market-down and high-volatility months;
- the short high-volatility leg lost 39.11% in IS and made 16.61% in
  Validation, so its economics are unstable.

Decision: keep the prospective contract unchanged, do not promote, do not
admit to a combo, and retain the clue only for unchanged future observation.
Canonical reports are `logs/factor_identity_audit_v1_20260717.json` and
`logs/factor_identity_audit_v1_20260717.md`. Local and Linux verification both
pass `274 passed` with the same nine pre-existing constant-series warnings;
the Linux real-data rerun exactly matches the frozen reference.

The bounded OKX L2 pilot then reconstructed the official 400-level book and
aligned trades for XRP, LDO, and TRX on 2026-07-10 UTC. All three produced
8,640 valid 10-second samples. Median quoted spreads were 0.91, 3.28, and 0.30
bps respectively. At 100 USDT, the current 7 bps one-way model exceeded median
visible-book all-in cost for all three; at 10,000 USDT, LDO median and p95 cost
rose to 12.40 and 14.76 bps. This proves the data path and shows that one fixed
slippage number cannot represent asset and notional heterogeneity. It does not
calibrate a long-run cost model and authorizes no factor batch.

Item 3 is now complete. The exact source `bidask` measure is a simple average
of 30-day Corwin-Schultz and two-day-corrected Abdi-Ranaldo OHLC estimators;
turnover volatility is the 30-day standard deviation of dollar volume divided
by point-in-time market value. Both are weekly low-minus-high quartile sorts.
On the pilot date, the OHLC proxy preserved the LDO/XRP/TRX order but exceeded
direct quoted spread by 57-135 times, so it cannot be used as execution cost.

Active work is now the frozen multi-regime study in
`OKX_L2_REGIME_SAMPLE_V1.json`. Its first product is a reusable
asset/notional/regime cost surface for every factor and later strategy. Its
second, separate product is the spread-proxy rank check. Five unseen BTC-defined
dates and five assets were selected without factor returns, along with fixed
coverage and rank gates. No candidate batch is authorized yet. The exact reading note is
`CRYPTO_FACTOR_ZOO_EXACT_METHOD_20260717.md`; canonical method-audit outputs are
`logs/crypto_factor_zoo_method_audit_20260717.json` and
`logs/crypto_factor_zoo_method_audit_20260717.md`.

Prospective collection correction: the 2026-07-17 factor snapshot failed
closed because the v1 evaluator contract included unrelated shared code. V1
therefore has zero valid factor days and is permanently excluded. The unchanged
factor restarts as `monthly_low_vol_90d_prospective_v2` on 2026-07-18 under a
semantic evaluator contract. No return, formula, parameter, cost, Holdout
result, or promotion threshold was changed, and the invalid day is not
backfilled. Incident record:
`logs/prospective_track_contract_incident_20260718.json`.

Scheduler alerts, approval ergonomics, typed AI formula generation, and other
R1/R2 engineering are maintenance work. They do not precede supervised
economic research unless they block valid evidence.

## Scientific Alignment Override - 2026-07-17

The independent alignment review in
`RESEARCH_ALIGNMENT_RED_TEAM_AUDIT_20260717.md` found no fundamental direction
error, but it found that engineering maturity is ahead of economic
identification.

**Factor Identity Audit v1** is now complete. It confirms that the former
`baseline_incremental_evidence` was insufficient by itself: joint spanning
finds positive alpha, but conditional cross-sectional and regime evidence do
not establish a stable independent factor. The completed audit remains a
separate combo-admission prerequisite and did not alter the frozen signal or
its prospective promotion policy. The first historical L2 feasibility check is
complete; exact method replication and multi-regime execution economics are
now the next scientific bottlenecks.

The scientific findings remain binding, but their former engineering-first
sequence is superseded by the Economic Research Priority Override above.
Factor identity and microstructure economics now precede alerts, approval
ergonomics, global historical-path reconstruction, and typed AI generation.

The cost/time work is not a continuation of 90-day factor tuning. That frozen
track only collects prospective evidence until a factor-neutral shared model is
independently complete.

The project must not respond to the lack of passes by loosening gates, creating
more low-volatility variants, or adding generic orchestration indefinitely.

## Red-Team Override - 2026-07-15

The former historical-factory 90/100 acceptance is withdrawn. The frozen
independent audit in `HISTORICAL_FACTORY_RED_TEAM_AUDIT_20260715.md` scores the
current evidence at 48/100 (independent comparison: 52/100) and takes precedence
over every older status statement below.

Sequencing was updated on 2026-07-16. The red-team findings remain valid, but
not every defect blocks useful research. Only R0 defects that can manufacture a
false economic conclusion block the next decision. R1/R2 provenance,
reliability, and unattended-automation work continues in parallel under
`RESEARCH_UTILITY_FIRST_POLICY_20260716.md`.

## Current Update - 2026-07-16

- R0 split-boundary contamination, Holdout-dependent AI ordering, fail-open
  trial accounting, and evidence-cache identity/rebinding are fixed. The cache
  is opt-in for supervised research.
- Local and Linux regression suites passed after the fixes. The later
  basis/funding work also corrected missing initial-entry transaction costs.
- Perpetual basis/funding was tested as a long-spot/short-perp mechanism, not
  as an unsupported outright perp-return sign.
- Batch 003: 6/6 net historical rejects. Gross convergence plus funding was
  positive, but daily two-leg costs dominated.
- Batch 004: the literature-prescribed 10/20 and 10/50 sS hold bands reduced
  turnover but still produced 6/6 net historical rejects.
- Holdout was not accessed by any of the 12 paths. The family is frozen on the
  current sample.
- Monthly low-volatility Batch 005 tested only the literature-prescribed 60-
  and 90-day paths. The 60-day path was rejected because IS net return was
  negative. The 90-day path earned `prospective_shadow_strong`, with positive
  IS/Validation economics, family FDR, permutation, liquid-only, rolling, and
  short post-source non-collapse checks.
- The 90-day result is a factor clue, not a pass. It has an IS max drawdown of
  45.08%, current-live-universe survivor conditioning, only 40 source-period
  formations, and only about seven source-out-of-sample months.
- An immutable promotion-eligible factor track activates on 2026-07-17. Its
  formula, evaluator bundle, costs, and promotion policy were frozen before the
  first future observation. Confirmed future-day count is currently zero.
- Server deployment is verified: 50/50 daily spot caches are ready, both
  prospective systemd timers are enabled and active, readiness integrity is
  true, and the action remains `collect_only`.
- Final local and Linux regression status is 270 passed with the same nine
  pre-existing constant-series warnings.
- The append-only registry now contains 46 candidate IDs and 140 total events.
  Any next batch must use an independent mechanism or materially new data.
- A separately frozen execution audit translated the unchanged 90-day spot
  signal to matching OKX perpetuals. It passed only for later paper design:
  +49.67% arithmetic net after realized funding and standard costs, +48.65% at
  double cost, 22.85% max drawdown, and 11/12 current 100 USDT legs within the
  sizing tolerance. The factor remains unpromoted and receives no extra tuning.
- The next construction priority is sustainable factory reliability and bounded
  autonomous scheduling, not more factor-specific engineering.

Confirmed findings included Validation/Holdout boundary contamination, an
indirect Holdout-to-AI feedback channel, forgeable critic approval, fail-open
trial accounting, an incomplete universe cache key, formula causality blind
spots, orphaned evaluator processes after heartbeat failure, and no genuine
approved-path end-to-end drill. The binding R0 defects and approved-path drill
are now closed. Source-admission provenance, alerting, and long-run evidence
remain open; no candidate family is reopened by these engineering results.

Historical-factory engineering update (2026-07-15, current stage):

- Differential Point-In-Time Formula Audit v1 is implemented. The real
  eight-asset/730-day run made 378 comparisons over 63 frames, found zero
  leakage frames, and correctly failed both unobservable OI candidates rather
  than treating missing evidence as a pass.
- Persistent Panel Evidence Artifact Cache v1 is implemented. On the same
  frozen workload, warm legacy evaluation was 65.5% faster than cold and warm
  staged evaluation was about 63% faster than the previous staged run. Trial
  counts and all classifications still recompute.
- Independent Research Critic v1 is implemented. Candidate evaluation now
  requires a critic report bound to the exact candidate and formula-audit
  hashes, checked before run registration and again before evaluation.
- Historical Factory State Machine v1 is implemented with immutable input
  snapshots, append-only transitions, lease/heartbeat recovery, bounded
  formula/critic retries, an evaluation attempt budget of one, and generated
  machine/human status files.
- The old AI-generator smoke path no longer bypasses compilation and critic
  review; it routes through the orchestrator and requires a frozen substrate.
- Acceptance contracts:
  `PANEL_FORMULA_AUDIT_V1.md`,
  `PANEL_EVIDENCE_ARTIFACT_CACHE_V1.md`,
  `PANEL_RESEARCH_CRITIC_V1.md`,
  `HISTORICAL_FACTORY_STATE_MACHINE_V1.md`, and
  `HISTORICAL_FACTORY_90_PERCENT_ACCEPTANCE.md`.
- Historical-factory 90% verification was later invalidated by the red-team
  audit. The 219-test result and hash match remain useful regression evidence,
  but they do not cover the confirmed failure modes. The cited real job stopped
  before critic and evaluator execution and is not approved-path E2E evidence.
- This historical note is superseded by the 2026-07-16 update above: the named
  R0 controls and the bounded basis/funding cycle are complete.

Execution update (2026-07-15):

- Professional architecture item 2 is implemented: content-addressed panel
  substrates preserve the exact resolved panel and are attached to each run.
  Explicit frozen manifests verify all blobs and bypass every panel source
  loader. Contract: `PANEL_SUBSTRATE_CACHE_V1.md`.
- Real three-mode acceptance used the same eight-asset/60-day panel under one
  explicit cutoff. Materialization, automatic alias hit, and explicit frozen
  load produced identical data fingerprints and factor rows: 12 variants,
  PASS 0, WATCHLIST 0. Wall times were 2.096s, 1.955s, and 1.870s.
- Local and server regressions are both 191 passed with the existing 9
  constant-series warnings. Content-Addressed Panel Substrate Cache v1 is
  closed.
- Server-native acceptance also materialized a 730-day substrate and reloaded
  its explicit manifest with the panel loader disabled; fingerprints and
  failure records were identical.
- Run contracts now preserve the exact evaluated source in a deterministic
  `code_snapshot.zip`; hashes without recoverable code are no longer treated as
  sufficient reproducibility evidence. The last pre-substrate server source
  was archived before replacement.
- Professional architecture item 1 is complete: `panel_run_registry.py` now
  creates immutable run contracts and lifecycle evidence, freezes the effective
  trial registry before multiplicity is calculated, hashes run artifacts, and
  maintains a rebuildable SQLite query index. Contract:
  `RUN_CONTRACT_SQLITE_INDEX_V1.md`.
- The real eight-asset/60-day smoke path completed under the new lifecycle.
  Two runs with the same data fingerprint produced byte-equivalent factor rows:
  12 variants, PASS 0, WATCHLIST 0. Warm-cache wall time including process
  startup was 1.733 seconds.
- The initial smoke took 146 seconds because WLD, ARB, and PEPE 60-day caches
  were genuinely absent and were downloaded. It is not used as a warm-cache
  performance number. This directly motivates architecture item 2, the
  content-addressed panel substrate cache.
- Local and server regression after the run-index work are both 182 passed with
  the same 9 existing constant-series warnings. Run Contract and SQLite Run
  Index v1 is closed.
- The server now has complete zero-network replication inputs for all 50
  registered assets. The first frozen literature batch ran without changing
  its formula or thresholds.
- Both Liu-Tsyvinski-Wu CMOM adaptation paths are valid
  `historical_reject` results. Validation was mildly positive, but neither path
  passed family FDR and both reversed sharply in the frozen Holdout. Report:
  `logs/panel_literature_replication_20260715T113600Z.json`.
- The failed CMOM result is closed evidence. It must not be tuned from Holdout
  or revived under the same mechanism with a new candidate ID.
- The second frozen literature batch also completed with 4/4
  `historical_reject` classifications. Large-segment Val RankIC was -0.0206;
  most-liquid-segment Val RankIC was -0.0426. All family-FDR adjusted p-values
  were 0.9118 and every Holdout portfolio lost money. Report:
  `logs/panel_literature_replication_batch002_20260715.json`.
- Batch 002 had valid evidence coverage: 656 large-segment and 516 liquid-
  segment formation days, exactly 20 assets at every post-warmup formation, and
  zero missing return observations while held. This is an economic rejection,
  not an implementation-invalid zero-result.
- Do not flip the rejected momentum direction into a reversal candidate from
  these results. That would be outcome-driven reuse of the same historical
  sample. Any reversal test requires an independently justified source and a
  broad illiquid point-in-time universe that the current substrate does not
  contain.
- No literature factor is historically eligible for prospective promotion.
  The next work is a mechanism/data applicability audit of perpetual basis and
  funding sources before deciding whether a third frozen batch is justified.

Latest meta-audit:

- Literature-method audit: `PANEL_LITERATURE_METHOD_AUDIT_20260714.md`.
- The literature layer is now machine-readable in
  `LITERATURE_REPLICATION_REGISTRY.json`; exact replication evidence,
  adaptation evidence, and engineering-only sources are no longer mixed.
- Gate v3 is implemented as a nonbinding shadow policy. It separates
  `historical_reject`, `historical_clue`, and `prospective_eligible`, and never
  converts historical evidence into `panel_factor_pass`.
- Locked OI gate-v3 re-audit: 4/4 paths remain `historical_reject`. FDR did not
  rescue either candidate family, so the redesign did not manufacture output.
- Market-cap substrate: Coin Metrics estimated market cap loaded for 50/50
  registered assets, 99.8632% global coverage, one-day information lag, no
  forward filling across missing daily events. Audit:
  `logs/panel_market_cap_audit_20260714.json`.
- A factor-accounting defect was corrected: price PnL, funding, and transaction
  costs now all use 1x notional at the factor layer. Configured leverage is
  reserved for the later strategy layer. The old OI operational shadow contract
  is deprecated and contributes no prospective evidence.
- First literature batch: `LITERATURE_REPLICATION_BATCH_001.json`, completed as
  two historical rejects. It remains a perpetual-universe adaptation, not an
  exact spot-universe replication, and cannot produce a formal pass.
- The earlier SSH/cache blocker is resolved. Remote regression and the frozen
  50-asset preflight both pass; incomplete local caches are not used for formal
  replication runs.
- `RESEARCH_META_AUDIT_20260705.md`
- Independent red-team superseding note: `PANEL_GATE_RED_TEAM_AUDIT_20260714.md`
- Previous local regression status: 173 passed, with 9 existing constant-series
  warnings.
- Candidate generation remains frozen. Gate v1 historical labels are retained;
  gate-v2 is synthetically calibrated but remains nonbinding pending mature
  preregistered prospective evidence.
- Outcome-blind calibration established that the policy is satisfiable: a
  planted full-panel IC near 0.05 can reach watchlist frequently and pass in a
  meaningful minority of paths. Top-8 pass power is much lower, reflecting the
  information limit of an eight-asset cross-section rather than a reason to
  manufacture output by weakening pass.
- The daily automation target is now a three-part chain: immutable universe
  snapshot, immutable frozen-factor shadow returns, then readiness. Universe
  days alone no longer advance factor evidence maturity.
- Locked gate-v2 re-audit completed in
  `logs/panel_factor_report_20260713T170357Z.json`; the independent comparison
  manifest `logs/panel_gate_v2_reaudit_comparison_20260714.json` confirms exact
  structural and legacy-output equality with the v1 reference. Draft v2 still
  rejects all 16 paths. The OI price-crowding signal has a weak daily Val clue
  but collapses in Holdout; the OI funding-crowding signal's large hourly
  t-stat disappears under daily block inference.
- Server readiness now reports 2 complete universe days, 0 eligible frozen-factor
  days, and `collect_only`. The current OI track is operational-only and can
  never unlock formal promotion.
- Decision: quality gates v1 and panel data substrate v2 are complete. Historical
  research remains exploration-only; formal evidence is prospective.
- Final panel data substrate v2 audit completed on 2026-07-12:
  - `logs/panel_data_audit_20260712T115651Z.json`
  - 50/50 assets loaded with no load failures
  - 48 assets were eligible at least once; EGLD and YFI never cleared the
    registered point-in-time liquidity/top-40 rule
  - median and p10 point-in-time eligible breadth are both 40 in the analyzable
    period; top/bottom 30% supplies 12 assets per side
  - basis coverage 99.994%, OI coverage 100%, 111,881 sparse funding events
  - no asset failed the 90%-of-requested-span funding-history gate
  - `data_substrate_v2_pass = true`
  - `formal_promotion_allowed = false` because the historical pool contains
    only contracts still live at the 2026-07-10 freeze date
  - retrospective results are exploration-only and have a hard promotion
    ceiling of `panel_factor_watchlist`
  - formal pass evidence begins prospectively at `2026-07-10T00:00:00Z`
  - the first 2026-07-11 snapshot was a bootstrap intraday snapshot and is not
    a complete-day formal observation; future snapshots record `day_complete`
- First panel data audit:
  - `logs/panel_data_audit_20260705T061505Z.json`
  - 16 loaded assets, 17,700 common hourly bars
  - close coverage 99.95%, basis coverage 99.93%
  - funding events 34,926, sparse by design at roughly 8h cadence
  - 5 crash/stress windows identified
  - `data_audit_pass_for_batch1 = true`
  - caution: the large/liquid subset has a low minimum-availability edge case
- Robustness diagnostics now participate directly in pass/watchlist decisions:
  - `robustness.large_liquid`
  - `robustness.liquidity_buckets`
  - `robustness.crash_windows`
  - full server report: `logs/panel_factor_report_20260710T105926Z.json`
  - 730d / 16 assets / 45 variants / PASS 0 / WATCHLIST 0
  - all 5 AI batch0 candidates remain rejected
  - the 4 former funding/carry watchlist rows were correctly demoted by
    rolling, liquidity-bucket, multiple-testing, or crash-loss gates
  - no combo is allowed

## Independent Red-Team Closure (2026-07-14)

- `deflated_sharpe_pass` is now an explicit required pass gate. A failed or
  evidence-insufficient DSR can no longer produce `panel_factor_pass`.
- Every active prospective factor track now freezes a complete contract hash:
  candidate batch, candidate ids, all expected path ids, baselines, weighting
  modes, rebalance, minimum breadth, cost, slippage, leverage, universe hash,
  and evaluator bundle hash.
- The active OI operational track contract is
  `b0c495402eb3c48e225e77bc4ab9f2196251f76cbc27cbd0e3404a5b57109c28`
  and declares exactly 16 paths.
- A factor day counts only when its contract and exact path set match the
  registry and a formal universe snapshot exists for the same UTC date.
- A path day now requires 24 active hourly bars, complete held-position return
  evidence, and complete expected funding events. Missing expected funding is
  no longer treated as a valid zero payment.
- Same-date recomputation is append-only only when economic evidence is
  identical. Changed evidence raises a conflict and is written to
  `prospective_factor_snapshots/conflicts.jsonl`.
- Complete synthetic gate calibration now invokes production DSR and CSCV-PBO
  over 51 correlated trial paths instead of assuming those gates pass:
  - `logs/panel_gate_complete_calibration_20260714.json`
  - `logs/panel_gate_null_confirmation_20260714.json`
  - `logs/panel_gate_complete_calibration_summary_20260714.json`
- Pure-noise confirmation used 100 replications per scope: 0 formal passes in
  both scopes, with a maximum Wilson 95% false-positive upper bound of 3.70%.
- The gate is not logically deadlocked. At planted stationary IC 0.20, the
  formal pass rate was 100% for the full panel and 70% for the predeclared
  top-8 large/liquid scope.
- Power is intentionally much lower in the eight-asset scope: pass rates were
  2% at IC 0.10 and 22% at IC 0.15, with DSR the dominant blocker. Do not hide
  this information limit by silently weakening DSR.
- Decision: retain current thresholds, keep policy nonbinding, keep candidate
  generation frozen, and collect prospective evidence.

## Corrective Batch Audit (2026-07-13)

- The 50-asset audit of frozen batch `20260711T123241Z` completed in:
  - `logs/panel_factor_report_20260712T130059Z.json`
  - 60 variants, PASS 0, WATCHLIST 0, trial count 90
- That report is partially invalidated by:
  - `logs/panel_factor_report_20260712T130059Z_partial_invalidation.json`
  - `ai_carry_003` and `ai_carry_reversal_001` preregistered a point-in-time
    top-8 `large_liquid_only` subpool, but the evaluator incorrectly required
    the full-panel minimum of 20 assets. Their zero observations and zero active
    bars were software-invalid outcomes, not economic failures.
  - The other three candidates remain valid rejects: `ai_momentum_003`,
    `ai_composite_001`, and `ai_liquidity_001`.
- The evaluator now derives a candidate-specific minimum breadth. A registered
  top-8 subpool requires 8 assets while the full panel still requires 20.
- The unchanged two candidates were rerun in corrective batch
  `20260711T123241Z_corrective1`:
  - `logs/panel_factor_report_20260713T142741Z.json`
  - 50 assets, 54 variants, PASS 0, WATCHLIST 0, trial count 90
  - both candidates had 8/8/8 median split coverage, 2,676 Val IC
    observations, and nonzero active bars, proving the corrective evaluation
    was operationally valid
  - `ai_carry_003`: Val RankIC 0.0147; Val Sharpe 0.95/0.64; adjusted p 0.9405;
    rank-linear Holdout Sharpe -0.53; both modes failed liquidity-bucket breadth
  - `ai_carry_reversal_001`: Val RankIC 0.0158; Val Sharpe -0.51/-0.54;
    adjusted p 0.8446; both modes failed Val portfolio profitability,
    liquidity-bucket breadth, and crash containment
  - final result: both are valid `panel_factor_reject`; no combo is allowed
- Trial registry records both the invalid evaluation and corrective rerun. The
  corrective run does not create a new formula trial.
- Local and server regression status: 92 passed, with the same 9 existing
  constant-series warnings.

## Research Budget Freeze

- The generic `overfit.py` DSR/PBO functions remain excluded from panel
  evidence. A separate paper-aligned implementation now exists in
  `panel_overfit_audit.py`.
- Implemented and verified:
  - DSR uses daily Val net returns, unannualized Sharpe units, the full unique
    trial count, expected-maximum Sharpe, skewness, and Pearson kurtosis;
  - PBO uses IS+Val daily net returns, 10 contiguous segments, and all 252 CSCV
    half-sample combinations;
  - an adversarial test injects extreme Holdout returns and proves neither DSR
    nor PBO receives them;
  - factor reports explicitly record `holdout_used_for_selection = false` and
    zero Holdout selection observations;
  - formal candidate runs use `candidates_and_baselines` scope while retaining
    the full trial penalty.
- Final corrective statistical audit:
  - `logs/panel_factor_report_20260713T145918Z.json`
  - 27 available definitions; 8 evaluated definitions (6 baselines plus 2
    frozen candidates); 16 variants; trial count 90
  - runtime about 16 minutes versus about 32 minutes for the prior all-factor
    run
  - PBO 0.4325 versus a preregistered pass threshold of 0.20; failed
  - both corrective candidates failed DSR, with DSR probabilities from about
    0.006 to 0.047; PASS 0, WATCHLIST 0
- The next budget has been reopened for exactly one new mechanism family:
  - frozen batch `logs/panel_candidate_batch_20260713T150601Z.json`
  - family `open_interest_crowding`
  - 2 candidates, 4 total weighting variants, 0 generation rejects
  - formulas use 24-hour-lagged OI growth interacted with price direction or
    funding-side crowding, plus liquidity residualization and the registered
    point-in-time top-8 large/liquid subpool
  - full trial penalty increases from 90 to 94
- The OI batch completed:
  - `logs/panel_factor_report_20260713T151940Z.json`
  - `logs/panel_failure_analysis_20260713T150601Z.json`
  - 50 assets, 8 evaluated definitions, 16 variants, PASS 0, WATCHLIST 0
  - CSCV-PBO 0.5794 versus the 0.20 pass threshold; DSR failed for all four
    candidate variants
  - `ai_oi_crowding_003` (price x OI): Val RankIC 0.0386 and Val Sharpe
    0.50/1.11, but Holdout Sharpe -0.78/-0.93 and Holdout drawdown 44%/52%;
    valid reject
  - `ai_oi_crowding_004` (funding x OI): Val RankIC 0.0436 and Holdout RankIC
    0.0279, but the effect existed only in the high-liquidity bucket, had
    negative family-neutral Val IC, failed rolling stability, and lost about 6%
    in its worst registered crash window; valid reject
- Candidate generation is frozen again. The OI crowding family is frozen until
  new literature or genuinely new data changes the mechanism; do not tune these
  formulas from their Holdout behavior and do not revive any rejected candidate.
- Next work is prospective evidence operations, not another retrospective
  candidate batch: verify complete-day snapshots, archive daily signal/return
  paths for future PBO coverage, and define a minimum prospective observation
  threshold before any automated re-audit can run.

## Evidence So Far

- Single BTC strategy grid did not produce an exportable strict-audit strategy.
- Full historical OKX funding coverage fixed the earlier partial-funding false
  positive.
- A 2-year BTC funding/carry direction signal was stage-dependent and failed
  strict rolling/baseline audit.
- A 3-year BTC check removed most of the apparent funding/carry edge.
- The first 730-day OKX 7-asset panel run completed:
  - `panel_factor_report_20260704T104737Z.json`
  - 7 assets, 9 pre-declared factors
  - 0 pass, 1 watchlist
  - `liquidity_size` watchlist: Val RankIC 0.0673, Val Sharpe 0.04,
    Holdout RankIC 0.0719, Holdout Sharpe 0.77, very low turnover 0.0008
  - `funding_carry`, `momentum_24h`, `momentum_7d`, and reversal variants did
    not pass.

## Interpretation

The project should not return to repeated BTC-only strategy-grid search. The
first panel run suggests liquidity/size may be a weak but persistent cross-
sectional state variable, while simple funding, momentum, and reversal need
better definitions or broader data before being useful.

The literature points in the same direction:

- Crypto cross-sectional factor work repeatedly highlights market, size, and
  momentum as the core benchmark factors. Our panel must treat these as
  baselines to beat, not discoveries.
- Momentum/reversal evidence is strongly liquidity-dependent. Large, liquid
  coins can behave differently from small illiquid coins, so the next tests need
  explicit liquidity buckets and not just one pooled long-short spread.
- Perpetual futures funding is not a free alpha line. It is part carry, part
  basis/spot-perp convergence risk, and part crowding/leverage state. Funding
  factors should be tested with sparse real funding payments, spot-perp basis,
  duration/persistence, and crash controls.
- Recent large-cap momentum evidence warns about tail risk and sample
  dependence. Volatility management and drawdown audits should be first-class
  gates, not post-hoc polish.

## Superseded Technical Sequence

This section is retained as a historical record. The Economic Research
Priority Override and the 2026-07-18 alignment audit above control current
work.

1. Accumulate complete-day prospective evidence for the frozen 90-day monthly
   low-volatility track.
   - The 50-asset registry, point-in-time top-40 eligibility, OI, listing age,
     and asset-family labels are implemented.
   - Daily incremental data and immutable universe snapshot timers are enabled
     on the server; the latest data update passed 50/50 assets.
   - V1 collected zero valid factor days. V2 can capture its first day only
     after the 2026-07-18 daily bar closes; no v1 day may be backfilled.
   - The track needs 365 complete days at 99% coverage before a formal factor
     promotion audit. Its frozen policy permits combo research only, not capital.
   - Preserve failed loads and missingness; never backfill unavailable basis,
     funding events, OI events, or pre-listing history.
   - Historical 730-day runs may triage literature hypotheses, but cannot
     produce `panel_factor_pass` or enter a combo.

2. Operate the completed Process Ownership and Concurrency v1 controls.
   - Full process-tree termination, stale-lock recovery, exact-batch claims, and
     attempt report isolation pass on Windows and Linux.
   - Evaluation remains one-shot after worker failure.

3. Add bounded automatic source and candidate scheduling.
   - Admit only registered literature mechanisms and enforce family/round quotas.
   - Freeze each small batch before evaluation and alert on fail-closed stops.
   - Treat execution audit 001 as a completed product sample, not prompt feedback.

4. Keep the current funding/carry results as rejected research evidence.
   - Funding persistence failed Val liquidity-bucket breadth.
   - Funding carry failed Holdout liquidity-bucket breadth.
   - Liquidity-neutral funding carry failed the crash-loss and
     multiple-testing gates.
   - Do not tune on Holdout; only use literature and IS/Val feedback for a new
     preregistered candidate ID.

4. Add validation gates before strategy conversion.
   - Implemented first pass: rolling 90d IC/Sharpe stability.
   - Implemented first pass: Sidak multiple-testing adjustment over the factor
     registry using Val RankIC t-stat.
   - Implemented quality gates v1: large/liquid-only, liquidity-bucket breadth,
     and crash-window containment now block pass and watchlist promotion.
   - Still needed: sector/asset-family robustness where labels are available.
  - Implemented: paper-aligned panel DSR and CSCV-PBO using IS/Val daily net
    returns only and the full unique trial count for DSR deflation.
   - Trial registry for every factor variant.

5. Only after panel factors receive formal prospective promotion:
   - Build a factor combo.
   - Convert combo score to target weights.
   - Add capacity, turnover, funding, slippage, max drawdown, and execution
     rules.

6. Literature-driven next factor/data upgrades.
   - Add spot-vs-perp basis where available, not only funding rate.
   - Add liquidity buckets and require a factor to survive within large/liquid
     names, not only in pooled cross-section.
   - Add volatility-managed versions of momentum/carry candidates.
   - Add asset-family labels, exchange listing age, and market-cap/open-interest
     proxies before expanding the factor registry.
   - Keep the candidate registry small and pre-declared; multiple-testing should
     get harder as variants are added.

## Current Non-Pass State

No factor or strategy is currently deployable. There are no formal pass or
watchlist factors. One 90-day monthly low-volatility path is a frozen
`prospective_shadow_strong` clue. Its invalid v1 track has zero usable days;
the unchanged v2 track begins future observation on 2026-07-18 and has no
confirmed prospective days yet. Funding/carry and the 60-day
low-volatility path remain rejected research evidence, not strategies.

## Latest Server Run State

- The final 50-asset data/power audit completed:
  - `logs/panel_data_audit_20260712T115651Z.json`
  - substrate pass, formal promotion blocked only by survivorship scope
  - IS/Val/Holdout median and p10 breadth: 40/40/40
  - conservative Val RankIC MDE at 80% power and 10-trial budget: 0.1368
  - lightweight audit runtime after caching: about 131 seconds
- Staged Evaluator v1 completed on 2026-07-15:
  - candidate Stage 2 rebuilds a physically Validation-truncated panel;
  - Stage-2 rejects expose no Holdout metrics and skip rolling/robustness;
  - all observed IS/Val return paths remain in DSR/PBO and immutable archives;
  - real 8-asset/730-day batch: 4/4 AI paths rejected before Holdout, trial
    count 100, PBO paths 16, PBO 0.6984126984;
  - 12/12 baseline rows and the full overfit archive matched legacy exactly;
  - staged 101.9s versus legacy 94.6s, so baseline/formula artifact caching is
    still required for material throughput improvement;
  - local regression: 194 passed, 9 warnings.
- The quality-gated 730-day expanded 16-asset panel run completed:
  - `logs/panel_factor_report_20260710T105926Z.json`
  - 45 variants including 5 preregistered AI candidates
  - 0 pass, 0 watchlist
  - both funding-persistence weighting modes failed rolling Sharpe and Val
    liquidity-bucket breadth
  - funding carry top/bottom failed rolling Sharpe and Holdout
    liquidity-bucket breadth
  - liquidity-neutral funding carry top/bottom failed rolling Sharpe,
    multiple testing, and crash-loss containment
- The old strict BTC strategy audit remains failed:
  - `strict_objective_satisfied = false`
  - `failed_reasons = ["exportable_candidate_exists"]`
  - no hard-audit-passing combo is exportable.

## Latest Local Framework State

- `panel_factor_research.py` now evaluates 20 pre-declared factors.
- Missing-price returns now use `pct_change(fill_method=None)` to avoid
  implicit forward-fill contamination.
- Data loading now supports OKX spot OHLCV for swap-to-spot basis. Spot load
  failure does not remove the perpetual asset; basis factors simply have
  missing values for that asset.
- Added first-pass basis and volatility/liquidity-conditioned factors:
  - `basis_carry`
  - `funding_persistence`
  - `basis_funding_dislocation`
  - `liquidity_bucket_momentum`
  - `liquidity_bucket_reversal`
  - `vol_managed_funding_carry`
  - `vol_managed_momentum`
- Tests cover cross-sectional dollar-neutral weights, rebalance holding,
  liquidity-neutral residualization, and missing-price return behavior.
- Tests also cover trial-count multiple-testing penalty.
- Tests now also cover no-padding spot basis and liquidity-bucket demeaning.
- Local test status: 98 passed.
- Server full test status: 98 passed.
- A 60-day 8-asset smoke run produced watchlist candidates, but it has only one
  90-day rolling window and is not evidence of deployability.
- Performance fix: factor weights are now computed once per factor/weighting
  mode and reused across splits and rolling windows.
- Latest local 730-day 16-asset expanded panel:
  - `panel_factor_report_20260704T131434Z.json`
  - 13 factor definitions x 2 weighting modes = 26 variants
  - 0 pass, 2 watchlist
  - `funding_carry__top_bottom_30`: Val RankIC 0.0256, Val Sharpe 0.23,
    Holdout Sharpe 0.50, Holdout max drawdown 22.00%, failed
    `rolling_sharpe_not_fragile`
  - `liquidity_neutral_funding_carry__top_bottom_30`: Val RankIC 0.0104,
    Val Sharpe 1.58, Holdout Sharpe 0.09, Holdout max drawdown 20.05%, failed
    `rolling_sharpe_not_fragile` and `multiple_testing_pass`
- The quality-gated full server run is complete. Its all-reject result is
  evidence that the audit loop works, not evidence that alpha exists.

## AI Panel Factory Smoke Status

- Implemented v1 literature-constrained candidate flow:
  - `LITERATURE_HYPOTHESIS_REGISTRY.md`
  - `panel_candidate_registry.py`
  - `panel_ai_candidate_generator.py`
  - frozen `panel_candidate_batch_*.json`
  - append-only `logs/panel_trial_registry.jsonl`
  - `panel_factor_research.py --candidate-batch ...`
- The AI prompt builder intentionally withholds Holdout metrics; it uses only
  literature registry content and IS/Val-style feedback. Lowercase holdout
  failure labels are also filtered out of the AI prompt.
- A manual smoke batch now exists at `examples/panel_candidate_smoke.json` with
  three preregistered candidates:
  - basis carry
  - volatility-managed momentum
  - liquidity-bucket reversal
- First real AI generation smoke completed locally:
  - `logs/panel_candidate_batch_20260704T155950Z.json`
  - 5 generated candidates
  - 5 accepted by schema
  - 0 schema rejected
  - all generated candidates were later recorded as evaluated in
    `logs/panel_trial_registry.jsonl`
- Added next-round guardrails before generating more candidates:
  - default max 10 candidates per AI batch
  - default max 20 trial variants per family
  - previously rejected candidate ids are blocked from re-entry
  - duplicate source/formula signatures are blocked
  - schema failures and guardrail failures are both recorded in
    `logs/panel_trial_registry.jsonl`
- Added batch failure analysis:
  - `panel_failure_analysis.py`
  - current batch0 failure report, now updated with the full 730d/16-asset
    audit:
    `logs/panel_failure_analysis_20260704T155950Z.json`
  - batch0 summary: 5 candidates, 5 evaluated rejects, full audit PASS 0,
    WATCHLIST 0, `combo_allowed = false`
  - recommendations: keep candidate budget small, prioritize rolling/regime
    stability, avoid near-duplicate formulas in the next AI batch
- Local 60-day / 8-asset smoke run completed:
  - `logs/panel_factor_report_20260704T152505Z.json`
  - 43 factor variants including 3 candidate variants
  - PASS 0
  - all three smoke candidates rejected
- Local 60-day / 8-asset AI-generated smoke run completed:
  - `logs/panel_factor_report_20260704T160029Z.json`
  - 45 factor variants including 5 AI candidate variants
  - PASS 0
  - all five AI candidates rejected
- Server full 730-day / 16-asset quality-gated batch0 audit completed:
  - `logs/panel_factor_report_20260710T105926Z.json`
  - 45 factor variants including 5 AI candidate variants
  - PASS 0
  - WATCHLIST 0
  - all five AI candidates rejected
  - full-audit failure checks also include large/liquid-only,
    liquidity-bucket, and crash-window quality gates
- Server 60-day / 8-asset smoke run completed:
  - `logs/panel_factor_report_20260704T153011Z.json`
  - 43 factor variants including 3 candidate variants
  - PASS 0
  - all three smoke candidates rejected
- This is a successful engineering/audit-loop result, not alpha evidence. The
  short smoke window has only one rolling 90d window and must not be interpreted
  as deployability evidence.

## Sustainable Factory Scheduler - 2026-07-16

- Added `PANEL_SOURCE_ADMISSION_REGISTRY_V1.json`. All nine current sources are
  explicitly closed for new AI generation: canonical-closed, audit-only,
  prospective-frozen, deprecated, or not yet specifically preregistered.
- Added `PANEL_FACTORY_SCHEDULER_POLICY_V1.json` and
  `panel_factory_scheduler.py`:
  - one admitted source per cycle;
  - at most five proposals and three accepted candidates;
  - one generation cycle per UTC day and a 24-hour cooldown;
  - one active historical job at a time;
  - source-level lifetime trial accounting includes rejected candidates;
  - immutable generation intents and results;
  - incomplete intent, record tampering, missing substrate, or active work
    blocks new generation.
- The generator now sees only the admitted source's literature, replication
  context, and formula whitelist. Disallowed sources and formulas are enforced
  again during batch freezing.
- First real local scheduler invocation returned `idle_no_admitted_source`.
  Trial registry rows remained 140 before and after, proving no hidden AI call
  or candidate production occurred.
- Unattended work is now bound by `PANEL_FACTORY_RUNTIME_V1.json` to an exact
  content-addressed 50-asset/730-day substrate and cutoff. Evaluator outputs use
  job-local sinks and a validated two-stage commit into trial history.
- The Linux synthetic approved-source drill passed all 15 checks. It recorded
  one accepted candidate and one schema rejection, recovered from an
  intentionally killed formula worker, ran the real audit stack once, and
  reached terminal completion. Production trial history was unchanged.
- The synthetic candidate was rejected at Stage 2, Holdout was not accessed,
  and no combo was produced. This is engineering evidence, not alpha evidence.
- Local and Linux regressions: `270 passed` with the same nine pre-existing
  constant-series warnings. Full details are in
  `FACTORY_UNATTENDED_DRILL_RESULT_20260716.md`.
- Former next factory step: notification routing, daily health/throughput
  summaries, and append-only human approval provenance. This engineering-first
  sequence is superseded; those items remain backlog unless they block an
  admitted economic study or valid prospective evidence.
