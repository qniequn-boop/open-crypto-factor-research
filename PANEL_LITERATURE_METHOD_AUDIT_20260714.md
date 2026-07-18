# Panel Literature Method Audit - 2026-07-14

## Decision

The factory will use a literature-first, evidence-tiered workflow:

1. Reproduce a source paper's construction as faithfully as the registered
   perpetual-swap universe permits.
2. Label every unavoidable market or sample change as an adaptation.
3. Use the adapted literature factors as benchmarks before asking AI for
   mechanism extensions.
4. Allow historical evidence to authorize only a frozen prospective track.
   Historical evidence alone can never produce `panel_factor_pass`.

This is deliberately different from generating many formulas and looking for
one that survives. The first objective is to make the evidence interpretable.

## Knowledge Retained

### Cross-sectional crypto benchmarks

Liu, Tsyvinski, and Wu define cryptocurrency market, size, and momentum factors
over a broad spot universe. Their canonical momentum construction uses a
three-week signal, weekly formation, 30/40/30 portfolios, and value weighting.
These details are now frozen in `LITERATURE_REPLICATION_BATCH_001.json` rather
than replaced by convenient local defaults.

Source: https://www.nber.org/papers/w25882

### Liquidity-dependent momentum and reversal

Zaremba et al. report that daily reversal is concentrated in illiquid assets,
while the largest and most liquid cryptocurrencies exhibit daily momentum.
The useful lesson is conditionality: pooled reversal or momentum is not enough.
The factory must report liquidity buckets and a large/liquid scope.

Source: https://doi.org/10.1016/j.irfa.2021.101908

### Futures basis and perpetual funding

Chi et al. find that basis is a strong cross-sectional predictor in
cryptocurrency futures. That result comes from dated futures; using perpetual
basis is therefore an adaptation, not an exact replication. Perpetual-futures
research further treats funding as a price-alignment transfer under constrained
arbitrage. Funding is kept as a cost and crowding state, not described as free
carry alpha.

Sources: https://doi.org/10.1002/fut.22425 and
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5036933

### Multiple testing and automation

Family-level FDR is useful for discovery triage, while DSR/PBO remain appropriate
for higher-stakes strategy or combination promotion. Qlib, RD-Agent,
FactorEngine, and FactorMiner contribute engineering patterns such as structured
factor representations, experiment memory, and staged evaluation. They do not
constitute evidence that a generated factor has economic value.

Sources: https://doi.org/10.1093/rapstu/raaa003,
https://github.com/microsoft/qlib, https://arxiv.org/abs/2505.15155, and
https://arxiv.org/abs/2604.26747

## Knowledge Rejected Or Limited

- A source with code-generation or agent architecture can authorize an
  implementation pattern, but cannot authorize factor direction.
- A result from a broad historical spot universe cannot be called replicated
  on the current-survivor OKX perpetual universe.
- A dated-futures basis result cannot be silently renamed a perpetual-basis
  result.
- Daily market-cap data cannot be used at the same day's opening. The panel
  applies a one-day information lag and does not fill missing daily events.
- Syntax-rejected AI outputs belong in the audit registry, but they are not
  outcome-seen statistical trials. Trial accounting now reports these counts
  separately.
- Historical Holdout evidence is one frozen non-collapse audit, not a reusable
  tuning target.

## Implemented Controls

- `LITERATURE_REPLICATION_REGISTRY.json` records source quality, original
  sample, exact construction, blockers, and permitted next action.
- `panel_gate_policy_v3.py` separates `historical_reject`, `historical_clue`,
  and `prospective_eligible`. None is a formal pass.
- A complete family p-value ledger is required for FDR. Missing p-values are
  evidence-insufficient, never favorable.
- The locked OI re-audit left all four paths at `historical_reject`; the revised
  policy did not rescue a candidate.
- Coin Metrics estimated market cap is cached for all 50 registered assets.
  The audit reports 99.8632% global coverage and applies a one-day lag.
- Factor economics now use internally consistent 1x notional exposure for
  price PnL, funding, and transaction costs. Leverage belongs only at the later
  strategy layer. The old OI shadow contract was deprecated because it used
  the inconsistent accounting contract and had zero eligible factor days.

## First Frozen Replication

`LITERATURE_REPLICATION_BATCH_001.json` freezes a method-faithful perpetual-
universe adaptation of the Liu-Tsyvinski-Wu CMOM construction:

- 21-day momentum signal;
- Monday 00:00 UTC formation;
- 30/40/30 cross-sectional portfolios;
- market-cap value weighting;
- one-bar execution lag and 168-hour holding period;
- 1x notional accounting, real sparse funding payments, and registered costs;
- full point-in-time eligible panel plus an above-median market-cap scope.

The claim ceiling is explicit: this is not an exact spot-universe replication,
because the historical delisted-asset universe is unavailable. Its historical
ceiling is `prospective_eligible`, never `panel_factor_pass`.

## First Replication Result - 2026-07-15

The remote zero-network preflight passed 50/50 assets for OHLCV, sparse funding,
and point-in-time market cap. The frozen batch then ran on the audited server
cache. Machine report:
`logs/panel_literature_replication_20260715T113600Z.json`.

Both preregistered paths are `historical_reject`:

- Full registered panel: Val RankIC 0.0314 and daily Sharpe 1.23, followed by
  Holdout RankIC -0.0386 and daily Sharpe -1.34.
- Above-median market-cap panel: Val RankIC 0.0724 and daily Sharpe 1.01,
  followed by Holdout RankIC -0.0877 and daily Sharpe -1.04.
- Neither path reached the preregistered dependence-aware Val clue or family
  FDR threshold. Both failed frozen Holdout non-collapse.

This is useful negative evidence. It says the source construction does not
transport cleanly into the present survivor-conditioned OKX perpetual panel.
It does not say that the original broad-spot result is false. The batch is now
closed and cannot be tuned from its Holdout outcome.

## Second Frozen Replication

`LITERATURE_REPLICATION_BATCH_002.json` freezes the permitted large/liquid part
of Zaremba et al.'s daily momentum/reversal result before evaluation:

- previous-day log return and one-day holding horizon;
- daily 00:00 UTC formation with a one-hour execution lag;
- separate point-in-time largest and trailing-20-week most-liquid segments;
- 20 assets per segment, preserving roughly the source large-group absolute
  breadth because a literal 2% cutoff is infeasible in a 40-asset panel;
- quintile high-minus-low portfolios, both equal- and value-weighted;
- four total preregistered paths in one family FDR ledger;
- seven-lag Newey-West inference, real funding, costs, slippage, and frozen
  evaluation end at 2026-07-14 23:00 UTC.

The claim ceiling is narrower than the first batch: this can test whether daily
momentum appears among our largest or most liquid perpetuals. It cannot test or
claim replication of reversal in the source paper's illiquid 98% majority.
The runner and gate code hashes are locked in the batch in addition to data-
registry hashes.

## Second Replication Result - 2026-07-15

The server preflight passed all 50 assets and both input and code hash locks.
The frozen batch then completed in
`logs/panel_literature_replication_batch002_20260715.json`. All four paths are
valid `historical_reject` results:

- largest 20, equal-weighted: Val RankIC -0.0206, Val daily Sharpe 0.90,
  Holdout daily Sharpe -1.03, Holdout return -14.04%, drawdown 36.81%;
- largest 20, value-weighted: Val RankIC -0.0206, Val daily Sharpe -1.26,
  Holdout daily Sharpe -0.72, Holdout return -10.10%;
- most liquid 20, equal-weighted: Val RankIC -0.0426, Val daily Sharpe -0.50,
  Holdout daily Sharpe -2.16, Holdout return -30.54%;
- most liquid 20, value-weighted: Val RankIC -0.0426, Val daily Sharpe -2.76,
  Holdout daily Sharpe -1.27, Holdout return -17.63%.

The large and liquid segments supplied 656 and 516 valid daily formations,
respectively. Post-warmup breadth was exactly 20, held-return missingness was
zero, and turnover passed. The primary Val HAC p-values were 0.7450 and 0.9118;
all BH-adjusted family p-values were 0.9118, and only three of eight rolling
windows had positive IC. The apparently positive equal-weighted large-segment
Val portfolio was not corroborated by IC or net-return HAC inference and then
collapsed in Holdout.

The published large/liquid daily momentum result therefore does not transport
to this frozen OKX perpetual panel. Reversing the sign after seeing these
results is prohibited. No path enters prospective observation, no combo is
created, and candidate generation remains frozen pending a separate literature
and data-applicability decision for perpetual basis/funding.
