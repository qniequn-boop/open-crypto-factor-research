# Research Alignment Red-Team Audit

Date: 2026-07-17

## Scope

This audit asks a narrower question than a software review:

> Is the factory still aimed at finding usable, repeatable crypto factors, and
> does its scientific logic materially conflict with authoritative empirical
> asset-pricing and backtest-overfitting research?

The audit does not change any frozen signal, historical outcome, prospective
track, promotion policy, or trial record.

## Verdict

The project has **not fundamentally drifted away from its objective**. Its
preregistration, trial accounting, Holdout isolation, point-in-time rules,
cost accounting, and prospective evidence policy are directionally consistent
with the strongest warnings in the factor-zoo and backtest-overfitting
literature.

There is, however, a material sequencing imbalance:

- the experiment-execution and governance system is substantially more mature
  than the economic evidence;
- the current code can test a frozen return relation, but it cannot yet prove
  that the relation is an independent factor rather than a repackaged market,
  size, momentum, liquidity, or defensive-beta exposure;
- the current "AI generator" selects from known formula templates rather than
  inventing and compiling new literature-constrained expressions;
- the current-live OKX top-40 universe supports claims about liquid surviving
  perpetual markets, not the broad cryptocurrency cross-section studied in
  papers using hundreds or thousands of active and defunct assets.

The correct response is **not to loosen the gates** and **not to add more
generic infrastructure indefinitely**. The next scientific priority is a
factor-identity and incremental-explanatory-power audit, followed by better
population coverage and execution evidence.

## Alignment Scorecard

| Area | State | Red-team conclusion |
| --- | --- | --- |
| North Star | Green | The stated objective remains usable future evidence, not a pretty backtest. |
| Preregistration and Holdout discipline | Green | Strongly aligned with multiple-testing and backtest-overfitting literature. |
| Trial accounting | Amber | Counts are broad, but DSR/PBO do not yet contain return paths for the full historical search. |
| Point-in-time data | Amber | Eligibility is point-in-time, but the initial asset pool is current-live and survivor conditioned. |
| Factor identity | Red | A Validation Sharpe gap to the best baseline is not a factor-model alpha or incremental pricing test. |
| Low-volatility evidence | Amber | Promising frozen transportability clue; independence and long future persistence remain unproved. |
| AI candidate generation | Amber/Red | Safe template selection exists; genuine constrained formula discovery does not. |
| Execution realism | Amber | Costs and realized funding are included, but spread, depth, impact, outages, and short constraints are not historically calibrated. |
| Strategy readiness | Red by design | There is no promoted factor, combo, paper strategy, or capital permission. |

## Findings

### A1 - High: `baseline_incremental_evidence` does not establish an independent factor

`panel_factor_research.py:1408-1437` compares each candidate's Validation
Sharpe with the best standalone baseline Sharpe. At
`panel_factor_research.py:2510-2512`, any positive difference becomes
`baseline_incremental_evidence = true`.

This is a useful diagnostic, but it is not the empirical claim implied by the
name. A candidate can beat a standalone momentum portfolio while still being
fully explained by a combination of market, size, momentum, liquidity, and
volatility exposures.

This is the largest scientific gap relative to the literature:

- Liu, Tsyvinski, and Wu report that market, size, and momentum account for
  multiple successful crypto long-short strategies.
- Feng, Giglio, and Xiu define a new factor by its contribution beyond a
  high-dimensional existing factor set, not by a standalone Sharpe contest.
- The 2026 crypto factor-zoo study uses iterative alpha reduction and GRS
  tests, finding that a compact set of two or three factors beyond the market
  can eliminate the remaining significant alphas.

Required correction:

1. Relabel the current field as `standalone_baseline_sharpe_gap` in future
   report schemas, retaining backward-compatible reading for frozen reports.
2. Add `Factor Identity Audit v1` before a promoted factor may enter a combo.
3. Test time-series alpha and betas against crypto market, size, momentum, and
   liquidity factors with dependence-aware errors.
4. Add cross-sectional Fama-MacBeth or a predeclared portfolio-alpha analogue
   where the sample size permits it.
5. Report incremental GRS, spanning, or dependence-aware bootstrap evidence
   at combo construction; do not use a positive Sharpe gap as a substitute.

This new gate must not retroactively change the frozen low-volatility signal or
its promotion policy. It is a separate factor-identity prerequisite for combo
admission.

### A2 - High: the tested population is much narrower than the literature population

`PANEL_UNIVERSE_REGISTRY.json:3-19` accurately declares that the registered
pool contains current-live contracts, omits previously delisted instruments,
and is survivor conditioned. `panel_universe.py:73-101` correctly caps
retrospective promotion, and `panel_data_audit.py:381-400` explicitly refuses
to treat data readiness as a survivorship waiver.

The disclosure and fail-closed ceiling are good. The remaining problem is
scientific power and external validity. Broad crypto studies use hundreds or
thousands of assets. The 2026 crypto factor-zoo paper uses 565 currencies and
finds that liquidity and blockchain-native variables dominate a compact
factor set. Machine-learning evidence also emphasizes that predictive profits
often concentrate in difficult-to-arbitrage small, illiquid, volatile assets.

Our top-40 liquid subset therefore makes an intentional trade:

- it is closer to something a small account might execute;
- it is less likely to contain the large anomaly magnitudes reported in broad
  crypto samples;
- it cannot support statements about the whole crypto market.

Required correction: either acquire a broad point-in-time/delisted archive, or
permanently phrase the research target as **liquid OKX perpetual factor
research**. Broad-universe discovery and liquid-universe implementation should
be treated as two different stages, not silently merged.

### A3 - High: the low-volatility result is a clue, not yet an identified factor

The result document already says that Batch 005 is not a pass. That is honest.
The machine label `prospective_shadow_strong` can nevertheless be misread.

Adverse evidence in the frozen report includes:

- only 26 IS and 14 Validation formations for the 90-day path;
- only eight post-source formations;
- IS net-return HAC p-value of 0.295 and IS max drawdown of 45.08%;
- top-20 liquid-only IS net return of only 3.84%, with a 61.22% drawdown;
- a current-live survivor-conditioned universe;
- no historical control equivalent to the source paper's Fama-MacBeth,
  market-exposure, extreme-Bitcoin-period, and fixed-cohort checks.

The within-formation permutation test at
`panel_literature_replication.py:396-440` is a useful placebo. It does not by
itself establish exchangeability across persistent coin characteristics or
factor independence. A positive crash-period result is consistent with a
defensive mechanism, but is not proof that ordinary market or volatility beta
cannot explain the return spread.

Required interpretation:

> `monthly_low_vol_90d` is a promising, frozen transportability clue with
> factor independence unproved. Its only current job is to accumulate genuine
> future evidence without formula or policy changes.

The prospective track should continue exactly as frozen. The first eligible
closed activation-day bar can only be captured after 2026-07-17 closes, so a
zero factor-day count before the 2026-07-18 UTC snapshot is expected rather
than a failure.

### A4 - High: global overfitting evidence is incomplete despite broad trial counts

The registry trial count is conservative and includes failed/rejected work.
That is aligned with the literature. The remaining mismatch is between the
count and the return-path matrix:

- `panel_factor_research.py:1327-1352` builds DSR dispersion and CSCV-PBO from
  current-run unique paths;
- `panel_factor_research.py:1355-1368` attaches the full historical trial count;
- `panel_factor_research.py:2496-2525` correctly marks DSR/PBO evidence as
  insufficient when observed paths do not cover that count.

Therefore the implementation is not currently manufacturing a pass, but DSR
and PBO must not be described as global proof that the complete adaptive
research history is free of overfitting. Bailey et al. specifically require a
matrix of tried configurations for CSCV; a trial count without corresponding
paths cannot reconstruct the selection process.

Required correction: preserve IS/Validation net-return paths for every
evaluable historical trial and build a project-level archive. Where old paths
cannot be reconstructed exactly, report global DSR/PBO as unavailable rather
than impute them. The one-path frozen prospective track remains the strongest
remedy for the historical adaptation problem.

### A5 - Medium: the AI component is a constrained template selector

`panel_ai_candidate_generator.py:65-84` exposes a catalog from
`FACTOR_DEFINITIONS`; the prompt forbids formulas outside that catalog at
`panel_ai_candidate_generator.py:88-128`; and validation rejects unknown
formulas at `panel_candidate_registry.py:130-134`.

All nine source-admission entries are currently closed and have empty formula
whitelists in `PANEL_SOURCE_ADMISSION_REGISTRY_V1.json:12-83`. Production
correctly idles and makes no AI call.

This is safe and useful, but the current capability is:

> AI-assisted hypothesis wording and selection among human-coded templates.

It is not yet:

> AI generation of new factor formulas under a typed, point-in-time DSL.

Required correction: keep the current honest idle state. After a specific
source and canonical mechanism are admitted, either describe the component as
a template selector or implement a small operator/type DSL that can compile,
causality-audit, hash, budget, and reject new expressions. Do not open
free-form code generation.

### A6 - Medium: execution evidence has a valid but narrow claim ceiling

The frozen factor work includes transaction costs and sparse realized funding,
which is materially better than gross-return-only research. The execution
translation also explicitly states that it lacks historical order-book depth,
spread, impact, partial fills, latency, exchange outages, maintenance margin,
and liquidation behavior.

This is consistent with transaction-cost literature, not a contradiction.
However, a fixed 7 bp one-way assumption and double-cost sensitivity cannot
authorize paper or live profitability. The 2026 crypto factor-zoo evidence also
finds that trading frictions materially narrow the set of viable factors.

Required correction: retain current costs as screening assumptions. Before
paper strategy approval, calibrate point-in-time spread/depth/impact and short
implementation on the actual venue and position size.

### A7 - Medium: engineering work has outrun information acquisition

The 270-test suite, immutable contracts, process ownership, state machine, and
fail-closed scheduler substantially reduce false conclusions and operational
ambiguity. They are useful work.

But they cannot create economic information. At present there is:

- zero admitted source for production AI generation;
- zero current AI-generated successful factor;
- zero completed prospective factor day before the first activation-day close;
- no independent factor-model audit;
- no broad delisted universe;
- no executable-market cost archive.

After notification/health reporting and append-only source-approval provenance
are complete, new generic infrastructure should be time-boxed. Most research
effort should shift to factor identity, data breadth, execution evidence, and
one carefully selected independent literature mechanism.

## What Is Strongly Aligned With The Literature

The following parts should be retained:

- recording failed and rejected candidates, not only winners;
- freezing candidate batches before evaluation;
- separating IS, Validation, historical Holdout, genuine prospective evidence,
  paper trading, and capital;
- preventing Holdout from entering AI feedback;
- family budgets and FDR rather than unlimited variants;
- refusing sign flips or renamed retries after failure;
- distinguishing exact replication, adaptation, and engineering evidence;
- point-in-time eligibility and missing-value preservation;
- including turnover, costs, funding, drawdown, liquidity scopes, and rolling
  behavior;
- requiring future observations before formal factor promotion.

These controls are not excessive. Harvey, Liu, and Zhu show why conventional
single-test significance is inadequate after extensive factor search; Hou,
Xue, and Zhang show that most published anomalies weaken or disappear under
more credible implementation and multiple-testing standards; Bailey et al.
show why an ordinary Holdout alone is unreliable after strategy selection.

## Corrected Priority Order

1. Keep `monthly_low_vol_90d_prospective_v1` collecting unchanged future data.
2. Finish only the two near-complete operational items: health/alert summaries
   and append-only human source-admission provenance.
3. Specify and implement `Factor Identity Audit v1` as a combo-admission gate,
   not as a retroactive edit to the frozen promotion policy.
4. Build or explicitly declare unavailable the full historical
   IS/Validation return-path archive needed for global DSR/PBO.
5. Audit data availability for the most defensible new independent mechanisms:
   liquidity/microstructure and blockchain-native value/adoption. Do not admit
   a source until its exact formula, horizon, fields, endpoint, and budget are
   frozen.
6. Decide the permanent population claim: broaden to active-and-delisted
   point-in-time crypto, or deliberately target only liquid OKX perpetuals.
7. Add a typed expression DSL only after one real source is admitted and the
   factor-identity audit exists.
8. Accumulate 365 future days before treating the low-volatility relation as
   promotion evidence; promotion still authorizes combo research only.

## Do Not Do

- Do not loosen statistical or robustness gates because no factor has passed.
- Do not produce more low-volatility variants from the current sample.
- Do not call the current low-volatility clue AI-generated.
- Do not call a positive standalone baseline Sharpe gap independent alpha.
- Do not call current-run DSR/PBO a complete audit of all historical search.
- Do not claim broad cryptocurrency evidence from a current-live liquid-perp
  universe.
- Do not spend the next phase adding generic orchestration while the economic
  identity test remains absent.

## Primary Literature Used

- Liu, Tsyvinski, and Wu, [Common Risk Factors in Cryptocurrency](https://www.nber.org/papers/w25882).
- Harvey, Liu, and Zhu, [...and the Cross-Section of Expected Returns](https://academic.oup.com/rfs/article-abstract/29/1/5/1843824).
- Hou, Xue, and Zhang, [Replicating Anomalies](https://academic.oup.com/rfs/article/33/5/2019/5236964).
- Bailey et al., [The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253).
- Feng, Giglio, and Xiu, [Taming the Factor Zoo](https://www.nber.org/papers/w25481).
- Cakici et al., [Machine Learning and the Cross-Section of Cryptocurrency Returns](https://www.sciencedirect.com/science/article/pii/S1057521924001765).
- Mercik, Zaremba, and Demir, [Crypto Factor Zoo](https://www.sciencedirect.com/science/article/pii/S1057521926000645).
- Pyo and Jang, [Revisiting the Low-Volatility Anomaly in Cryptocurrency Markets](https://www.sciencedirect.com/science/article/abs/pii/S1544612326003818).
- Cong et al., [Crypto Value, Factor Pricing, and Market Segmentation](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2024.05875).

## Final Red-Team Statement

The factory is not too strict in the place that matters most. It is incomplete
in a different place: it has become good at deciding whether a frozen return
relation survives its own tests, but it is not yet good enough at deciding
whether that relation is a distinct, economically identified, implementable
factor.

The next improvement should make the positive evidence harder to misname, not
make weak candidates easier to pass.
