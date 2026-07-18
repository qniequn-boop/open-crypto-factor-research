# Panel Gate Red-Team Audit (2026-07-14)

## Decision

Candidate generation remains frozen. Gate v1 is useful as a conservative
diagnostic system, but it is not yet a calibrated promotion system. Historical
metrics remain evidence; v1 status labels must not be treated as final until
the incompatible and uncalibrated gates below are resolved.

No threshold may be changed because a named candidate failed it. Gate v2 must
be specified from literature, null controls, planted-alpha controls, and the
declared role of each research layer. Holdout outcomes remain unavailable for
gate calibration.

## Independent Review Checklist

Every new gate, factor policy, and report must pass these questions before it
can affect status:

1. **Satisfiability:** Can at least one valid input pass the rule?
2. **Applicability:** Does the rule measure something the candidate claims to
   cover, or should the result be `not_applicable`?
3. **Statistical power:** Does a planted moderate signal pass often enough at
   the actual asset count, history length, missingness, and cost level?
4. **False-positive control:** Do null and randomized controls stay below the
   declared false-promotion budget?
5. **Multiplicity ownership:** Is the same search risk being penalized by
   Sidak, DSR, PBO, and correlated slice gates more than once without an
   explicit reason?
6. **Evidence completeness:** Does a statistic use every path or trial its
   report claims to cover?
7. **Layer ownership:** Is the rule appropriate for a factor, a combo, or an
   executable strategy?
8. **Outcome blindness:** Was the rule fixed without looking at the candidate's
   Holdout or prospective outcome?
9. **Failure meaning:** Does failure identify weak economics, insufficient
   evidence, an inapplicable test, or a software/data defect?
10. **Counterfactual:** What observation would make the reviewer reverse the
    conclusion?

## Blocking Findings

### GATE-001: Large/liquid candidates face an impossible bucket-breadth gate

- Severity: critical
- State: confirmed
- Evidence: `bucket_policy = large_liquid_only` masks the signal outside the
  point-in-time top-8 assets. Status v1 still requires positive IC in at least
  two of the low/mid/high liquidity buckets.
- Consequence: low and mid buckets are structurally empty, so this candidate
  class cannot become pass or watchlist regardless of signal quality.
- Required change: introduce `pass`, `fail`, and `not_applicable`; liquidity
  breadth is not applicable to a deliberately top-8-only estimand. Test the
  signal inside its declared top-8 scope instead.

### GATE-002: Watchlist semantics do not match the research plan

- Severity: high
- State: confirmed
- Evidence: the plan defines watchlist as a Val clue that lacks robustness.
  Code v1 requires Val profitability plus rolling stability and most large,
  bucket, family-neutral, crash, and Holdout robustness checks.
- Consequence: an uncertain but legitimate clue is labeled reject, erasing the
  distinction between `no evidence` and `evidence needing prospective study`.
- Required change: watchlist must require valid data, positive preregistered
  Val evidence, and no catastrophic contradiction. Missing robustness belongs
  in `failed` or `insufficient` evidence fields, not an automatic reject.

### GATE-003: CSCV-PBO scope is incomplete

- Severity: high
- State: confirmed
- Evidence: PBO receives only the current run's unique IS+Val return paths,
  while the report also displays the full historical trial count. Prior search
  paths are not in the CSCV matrix.
- Consequence: the statistic is a current-batch PBO, not a full-search PBO. It
  must not be described as paper-aligned full-trial evidence or used as a hard
  promotion gate yet.
- Required change: mark current PBO `provisional_current_batch`; build an
  immutable return-path archive for every future trial and require path
  coverage before full-search PBO can become binding.

### GATE-004: DSR trial-dispersion evidence is incomplete

- Severity: high
- State: confirmed
- Evidence: DSR uses the full numerical trial count, but the observed Sharpe
  dispersion is estimated from current-run Val paths only.
- Consequence: the expected maximum Sharpe is conservative in trial count but
  not fully reproducible from the complete historical search distribution.
- Required change: report trial-count coverage and path-dispersion coverage;
  keep DSR provisional until the archived path set is complete enough under a
  preregistered coverage rule.

### GATE-005: Conjunctive gate power is unknown

- Severity: high
- State: confirmed
- Evidence: v1 requires 18 base/robustness booleans, positive Holdout Sharpe and
  IC, DSR, and PBO before unrestricted pass, followed by the evidence ceiling.
- Consequence: correlated noisy diagnostics can create a very high false-
  rejection rate. No simulation currently proves that a moderate true signal
  can pass at 50 assets, 730 days, top-8 scope, and observed missingness.
- Required change: calibrate the whole decision rule, not each threshold in
  isolation, using null and planted-alpha panels.

## Important Non-Blocking Findings

### GATE-006: Multiple-testing penalties may overlap

Sidak-adjusted Val RankIC, DSR, CSCV-PBO, and many correlated robustness slices
all constrain the same candidate. They answer different questions, but making
all of them hard `AND` gates has not been justified. Gate v2 must declare one
primary multiplicity control and treat complementary diagnostics according to
their distinct failure meaning.

### GATE-007: Crash limits may belong at combo/strategy level

A standalone factor is currently required to keep its worst registered crash
return above -5% and drawdown below 12%. This is useful evidence, but it may be
too close to a deployable-strategy constraint for a raw factor whose intended
role is diversification inside a combo. Calibration must test whether this is
a hard factor contradiction or a strategy-layer risk limit.

### GATE-008: Baseline comparison is reported but not binding

Reports calculate the gap to registered baselines, but v1 pass status does not
require the candidate to add evidence beyond them. Gate v2 must define whether
incremental IC, spanning, or portfolio diversification is the relevant
baseline test; headline Sharpe alone is insufficient.

### GATE-009: Trial counting is conservative but not an exact search ledger

The current count adds all built-in factor variants to unique candidate
variants. Formula-library entries, evaluated built-ins, and candidate-controlled
versions can overlap. The ledger is safe against undercounting, but exact trial
identity and return-path coverage need separate fields.

### GATE-010: Hourly RankIC t-stat treats overlapping horizons as independent

- Severity: critical
- State: confirmed
- Evidence: each hourly RankIC uses a forward 24-hour return, but the ordinary
  t-stat uses every adjacent hourly IC as an independent observation.
- Consequence: adjacent targets overlap for 23 of 24 hours, so the nominal
  sample size and Sidak-adjusted significance can be severely overstated. This
  is an anti-conservative error even though the surrounding gate system is
  otherwise strict.
- Required change: publish naive and dependence-aware inference separately.
  Gate v2 will use one daily formation observation and a preregistered HAC or
  block standard error. Historical naive p-values remain diagnostics only.

### GATE-011: AI feedback had indirect Holdout side channels

- Severity: critical
- State: fixed locally; regression tests added
- Evidence: prompt v1 suppressed fields whose names contained `holdout`, but
  still exposed final status, full-sample rolling failures, and full-sample
  crash failures. Final status itself depends on Holdout.
- Consequence: two reports with identical IS/Val and different Holdout could
  produce different AI prompts, allowing indirect adaptation to Holdout.
- Change: prompt feedback now uses an explicit IS/Val-safe allowlist, removes
  final status, derives a Val-only clue label, and is tested for byte-identical
  output under adversarial Holdout changes.

### GATE-012: Hourly Sharpe annualization assumes serial independence

- Severity: high
- State: open
- Evidence: portfolio metrics annualize hourly net returns with a square-root
  time multiplier. Positions are held across hours and crypto returns can be
  serially dependent.
- Consequence: Sharpe magnitudes and threshold distances can be distorted even
  when the sign is unchanged.
- Required change: make daily aggregated net-return Sharpe the primary report;
  retain hourly Sharpe as a diagnostic and add dependence-aware uncertainty.

### GATE-013: Missing held-asset returns are converted to zero

- Severity: high
- State: open
- Evidence: split returns are reindexed and filled with zero before portfolio
  PnL. A position formed before an intraday data gap can therefore appear flat
  instead of unpriceable.
- Consequence: missing bars may suppress volatility, loss, turnover, and
  drawdown exactly when execution evidence is weakest.
- Required change: report weighted missing-return exposure and invalidate or
  conservatively mark affected PnL under a preregistered tolerance.

### GATE-014: Candidate feedback could be displaced by baseline ordering

- Severity: medium
- State: fixed locally; regression test added
- Evidence: prompt v1 used the first 12 report rows. Formal runs contain 12
  baseline variants, so candidate rows could be absent.
- Change: candidate rows are selected first, then remaining capacity is filled
  with baselines.

### GATE-015: One trial count was used for different statistical units

- Severity: high
- State: partially fixed locally; legacy enrichment applied
- Evidence: the headline 94 counts portfolio weighting variants. RankIC is a
  property of a signal and is identical across rank-linear and top/bottom
  portfolio implementations. PBO, by contrast, needs every portfolio path.
  Legacy registry rows also omitted direction, neutralization, and bucket
  policy, preventing exact signal reconstruction.
- Change: new events persist candidate and signal signatures plus payload hash.
  Twenty legacy candidates were enriched append-only from authoritative frozen
  batches; six unrecoverable rejected candidates remain explicitly unknown.
  Candidate portfolio-variant count stayed 44.
- Required change: reports must separate signal-attempt, unique known signal,
  and portfolio-path counts. Repeated attempts remain penalized even when their
  signatures duplicate an earlier test.

## Required Gate-v2 Evidence

Gate v2 cannot be activated until all of the following exist:

- A machine-readable gate catalog with owner layer, applicability predicate,
  evidence source, and failure meaning.
- Unit tests proving every supported candidate policy has at least one
  satisfiable status path.
- Null simulations that estimate false watchlist and false pass rates.
- Planted weak/moderate/strong alpha simulations that estimate decision power.
- Missing-data, sparse-funding, basis-unavailable, top-8, and family-label
  stress cases.
- Daily/HAC RankIC inference that does not count overlapping 24-hour targets as
  independent observations.
- A declared calibration target fixed before historical candidates are
  reclassified.
- A versioned re-audit that keeps formulas, candidate IDs, trial counts, and
  Holdout isolation unchanged.

## Calibration And Remediation Update

The following changes were fixed without using named candidate Holdout outcomes:

- `panel_gate_policy.py` now records gate owner, evidence phase,
  applicability, and `pass/fail/not_applicable/insufficient` state.
- A declared top-8 candidate no longer fails an impossible cross-bucket breadth
  rule. The top-8 estimand still needs direct top-8 and family-neutral evidence.
- Watchlist and pass have separate meanings. Watchlist requires a positive,
  dependence-aware Val clue and no clear audit collapse; pass retains the full
  multiplicity, robustness, baseline, and prospective requirements.
- AI feedback is byte-identical when only Holdout outcomes change. Candidate
  rows are prioritized ahead of baseline rows.
- Gate-v2 RankIC uses one fixed UTC formation observation per day and a
  seven-day non-overlapping-block empirical null. The hourly overlapping t-stat
  remains labeled as a legacy v1 diagnostic.
- Daily portfolio Sharpe and held-position missing-return exposure are now
  explicit. Missing held returns invalidate prospective path observations.
- Trial reporting separates signal attempts from portfolio weighting paths;
  legacy candidate metadata was enriched append-only where frozen batches made
  reconstruction possible.
- Prospective readiness now requires both immutable universe snapshots and
  complete frozen factor-return paths. An operational-only track can never
  create formal promotion evidence.

Outcome-blind synthetic calibration is stored in
`logs/panel_gate_synthetic_calibration_20260714.json`. Under its idealized
40-asset, 730-day, 7 bps assumptions:

- full-panel planted IC about 0.05 reached calibrated watchlist-or-pass in 94%
  of 100 paths and pass in 37%;
- full-panel planted IC about 0.10 reached watchlist-or-pass in 100% and pass in
  99%;
- top-8 planted IC about 0.05 reached watchlist-or-pass in 50% but pass in 0%;
- top-8 planted IC about 0.10 reached watchlist-or-pass in 92% and pass in 21%;
- the calibrated watchlist screen admitted 0 of 100 null paths in both scopes;
  this small Monte Carlo count is not a precise false-positive estimate.

Interpretation: the policy is satisfiable and is not globally too strict, but
top-8 pass evidence is intentionally difficult because the cross-section has
low power. Top-8 clues may enter non-promotional shadow tracking; the pass gate
must not be relaxed merely to increase output.

## Additional Independent Findings

### GATE-016: Plaintext API credentials existed in utility scripts

- Severity: critical
- State: fixed locally; credential rotation still required
- Change: `config.py` reads `LLM_API_KEY` only from the environment, and two
  obsolete scripts that embedded and rewrote the credential were removed.
- Residual action: treat the old credential as exposed and rotate it outside
  the repository before candidate generation is enabled again.

### GATE-017: Readiness counted universe days without factor paths

- Severity: critical
- State: fixed locally
- Consequence before fix: the 90/365-day clock could mature even if no frozen
  factor return path was successfully observed.
- Change: every active track now needs hash-valid, complete factor snapshots,
  eligible held-return evidence, calendar coverage, and freshness.

### GATE-018: Operational shadow could be mislabeled formal at top level

- Severity: high
- State: fixed locally
- Change: snapshot payloads now distinguish operational eligibility from
  formal-promotion eligibility. A plan frozen after historical Holdout was seen
  remains permanently operational-only.

### GATE-019: Synthetic calibration is still an idealized model

- Severity: high
- State: open
- Missing stresses: correlated candidate families, time-varying alpha,
  observed basis/funding/OI missingness, delistings, liquidity shocks, and cost
  escalation. Gate-v2 remains non-binding until these stresses and the
  versioned frozen-batch re-audit are complete.

### GATE-020: A gate-version re-audit could silently use a newer sample

- Severity: critical
- State: fixed and verified on the server
- Evidence: the first attempted v2 re-audit loaded the latest cache, while its
  v1 reference ended at `2026-07-12 23:00 UTC`. It was stopped before being
  accepted as evidence.
- Change: `--reference-report` now locks the exact split ranges and cutoff,
  candidate batch ID, trial count, and evaluated path identities. Any mismatch
  records `input_contract_comparable = false`; a result with that flag cannot
  be attributed to a gate-version change.
- Verification: `logs/panel_gate_v2_reaudit_comparison_20260714.json` reports
  structural contract match, exact legacy economic-output match, zero changed
  paths, and gate-only interpretation allowed.

## Locked Gate-v2 Re-audit Result

- Reference: `logs/panel_factor_report_20260713T151940Z.json`
- Re-audit: `logs/panel_factor_report_20260713T170357Z.json`
- Frozen batch: `20260713T150601Z`
- Locked trial units: 51 signal attempts and 94 portfolio paths
- Result: all 16 evaluated paths remain `panel_factor_reject` under both v1 and
  calibrated draft v2; no combo is allowed.
- `ai_oi_crowding_004`: naive overlapping-hour Val t-stat 5.24, daily
  non-overlapping-block t-stat 0.87 versus watchlist critical 1.40. The apparent
  hourly significance does not survive dependence-aware inference.
- `ai_oi_crowding_003`: daily block t-stat 1.47 clears only the weak watchlist
  clue threshold, but both portfolio modes fail Holdout non-collapse. It remains
  reject and its Holdout is not returned to candidate generation.

This is evidence that v1 contained both over-strict and anti-conservative
pieces. Correcting those errors did not rescue the named candidates, which is
the desired behavior of an outcome-blind policy revision.

### GATE-021: Legacy reports did not hash raw panel input values

- Severity: high
- State: mitigated for the locked re-audit; fixed for future reports
- Limitation: identical date ranges do not rule out an exchange-side historical
  correction. The legacy reference has no raw panel hash, so bitwise source
  equality cannot be reconstructed after the fact.
- Mitigation: the re-audit comparison requires exact equality of every stable
  legacy IC, portfolio, rolling, and trial-adjusted output before allowing a
  gate-only interpretation.
- Change for future runs: reports now hash every asset's OHLCV, spot, funding,
  OI, instrument metadata, and label, then publish per-asset and panel SHA-256
  fingerprints.

### GATE-022: Shadow snapshots hashed only one evaluator module

- Severity: high
- State: fixed locally and deployed
- Consequence before fix: changing config, universe construction, candidate
  validation, or snapshot accounting could alter a path while the recorded
  `evaluator_code_sha256` stayed unchanged.
- Change: every future shadow snapshot records a bundle hash and component
  hashes for the snapshot writer, factor evaluator, universe logic, candidate
  registry, config, and universe registry JSON. Candidate batch and tracking
  registry hashes remain separate immutable inputs.

## Literature Alignment

- Harvey, Liu, and Zhu, *...and the Cross-Section of Expected Returns*:
  multiple testing must be reflected in factor evidence, but that does not
  imply every diagnostic slice should be an uncalibrated hard conjunction.
- Bailey and Lopez de Prado, *The Deflated Sharpe Ratio*: selection bias,
  non-normality, sample length, and the distribution of tried Sharpe ratios
  matter.
- Bailey et al., *The Probability of Backtest Overfitting*: CSCV evaluates a
  set of tried strategy paths; incomplete path coverage must be disclosed.
- Dawid, *Statistical Theory: The Prequential Approach*: frozen predictions
  should be judged by later observations, which supports the prospective
  shadow-evidence track and forbids retrospective gate tuning.
