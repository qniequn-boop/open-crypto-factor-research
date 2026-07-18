# Economic Research Agenda

Date: 2026-07-17

## Governing Decision

Economic discovery is now the main workstream. The factory is supporting
infrastructure, not the product.

The research question is not "can the framework reject this candidate?" It is:

> What economically coherent, parameter-stable, net-of-cost relation can be
> measured in our tradable market, and what risk or behavioral mechanism pays
> for its return?

Engineering work is justified only when it:

1. prevents a false economic conclusion;
2. acquires data needed by an economic hypothesis;
3. makes a selected factor executable or measurable;
4. keeps an already frozen prospective track collecting valid evidence.

Generic orchestration, dashboards, reliability polishing, and unattended AI
operation are not current research priorities.

Cost and time-horizon research is factory-wide. It is governed by
`ECONOMIC_COST_AND_HORIZON_POLICY_V1.json` and must not be calibrated to the
90-day low-volatility clue or any named factor.

## Current Economic Position

- Funding/basis was economically rejected because two-leg turnover costs
  dominated gross convergence and funding receipts.
- Canonical market/momentum adaptations did not survive the current sample.
- The 90-day monthly low-volatility relation is the only strong historical
  clue. Factor Identity Audit v1 finds partial incremental alpha, but also
  material market-down/high-volatility concentration and an unstable short
  leg. It remains frozen for prospective collection and is not an independent
  promoted factor.
- There is no promoted factor, combo, paper strategy, or capital permission.
- The main missing evidence is economic attribution, not another software
  control layer.

## Workstream 1 - Explain The Low-Volatility Return

The first task is to determine what the existing clue is economically earning.
This is not a parameter search and does not alter the frozen signal.

### Questions

1. Does the return remain after joint crypto market, size, momentum, and
   liquidity controls?
2. Is performance primarily a long-leg effect, an expensive short-leg effect,
   or ordinary defensive beta?
3. How much comes from a few coins, listings, market regimes, or crash months?
4. Does liquidity/size neutralization preserve the relation or remove it?
5. Is the perpetual translation still attractive after actual funding and a
   spread/depth-based cost model?
6. Is a long-only low-volatility sleeve economically useful even if the
   high-volatility short leg is not executable?

### Required outputs

- time-series alpha and betas against market, size, momentum, and liquidity;
- dependence-aware alpha uncertainty, not only a Sharpe comparison;
- long-leg, short-leg, asset, and regime contribution tables;
- beta-neutral and liquidity/size-neutral diagnostic portfolios;
- turnover, funding, spread, depth, drawdown, concentration, and estimated
  capacity;
- a plain conclusion: independent alpha, compensated risk, defensive exposure,
  short-leg anomaly, or unresolved.

### Stage result - 2026-07-17

Completed. The plain conclusion is **defensive low-volatility relation with
partial incremental alpha, identity unresolved**. The exact frozen
reconstruction passed; pooled joint-control net alpha was positive, but the
conditional cross-sectional coefficient was statistically weak and the return
was regime-concentrated. Continued unchanged observation is justified;
promotion, combo admission, and parameter changes are not.

Historical Holdout and post-source evidence may audit the frozen relation, but
must not choose a different lookback, sign, or portfolio definition.

## Workstream 2 - Select One New Economic Mechanism

Two recent peer-reviewed research directions are economically credible:

### Priority A - Liquidity and market microstructure

Mercik, Zaremba, and Demir (2026) evaluate 36 factors over 565
cryptocurrencies. Their compact factor structure is dominated by turnover
volatility, bid-ask spread, and other liquidity variables; the study also finds
that trading costs sharply narrow the viable set.

This direction fits the product we can trade. OKX officially provides:

- tick trades from September 2021;
- high-resolution L2 order books from March 2023;
- public batch access to order-book modules and daily/monthly files.

The first economic data pilot should therefore measure, for a representative
subset of the registered universe:

- quoted and effective spread;
- depth within fixed basis-point bands;
- turnover level and turnover volatility;
- price impact for 100, 1,000, and 10,000 USDT notionals;
- coverage, listing boundaries, and cross-asset comparability from 2023 onward.

No factor sign or parameter is admitted until the exact source construction is
read and the feasible fields are known. Prior rejected daily momentum is a
benchmark, not permission to retry it.

### Stage result - 2026-07-17

The bounded OKX archive pilot is complete for XRP, LDO, and TRX on one UTC day.
All three produced complete nominal 10-second book samples and every retained
trade matched a preceding quote. Median quoted spreads ranged from 0.30 bps for
TRX to 3.28 bps for LDO. The current 7 bps one-way model was conservative at
the 100 USDT median, but LDO visible-book all-in cost reached 12.40 bps median
and 14.76 bps p95 at 10,000 USDT.

The data mechanism is feasible; a universal fixed slippage assumption is not.
The result is insufficient for full calibration because it covers one recent
day. Exact source-method replication and predeclared multi-regime dates are
required before any factor path is admitted.

### Priority B - Blockchain-native value and adoption

Cong et al. (2026) report a value effect based on active addresses relative to
market capitalization. The 2026 crypto factor-zoo study also selects
new-address-to-price and network-activity variables.

The mechanism is attractive: network adoption relative to valuation may
capture economically distinct information unavailable in OHLCV. Current free
data, however, is not sufficient for our panel.

On 2026-07-17, a live Coin Metrics community catalog check found:

- 50 registered factory assets;
- 49 recognized asset symbols;
- only 19 with community daily `AdrActCnt`;
- zero with community `AdrNewCnt` or `AdrNewBalCnt`.

This is below the current 20-asset minimum even before token/network
comparability and revision timing are audited. The mechanism remains a
high-quality data-acquisition candidate, but it is blocked for immediate panel
testing. It may be reopened with paid/broader point-in-time data or a separately
defined economically comparable network universe.

## Parameter Research Policy

Parameter work is allowed and necessary, but every parameter must express an
economic belief rather than merely improve a backtest.

For a newly admitted mechanism, the first frozen batch may contain:

1. the paper's canonical specification;
2. one slower or lower-turnover specification justified by signal decay and
   implementation cost;
3. one normalization or neutralization specification justified by an identified
   confounder.

The batch should usually contain one to three paths, not twenty arbitrary
lookbacks. Parameters may be estimated on IS where the method requires it;
Validation chooses whether the mechanism is worth prospective observation.
Holdout never chooses a new parameter.

Parameter evaluation must report the entire economic surface around the chosen
value. A narrow isolated optimum is evidence against robustness even when its
headline return is high.

## Workstream 3 - Factory-Wide Cost And Time Economics

Execution cost and signal time are shared economic infrastructure. They are
estimated independently of factor returns and then applied consistently to
every historical factor, prospective re-audit, combo, and paper strategy.

The cost layer conditions on asset, notional, spread, visible depth, impact,
turnover, funding, and market regime. The time layer separates signal window,
formation, rebalance, holding period, realized turnover, decay, and net return.
Daily, weekly, and monthly are common reporting buckets, not a horizon grid.

The frozen 90-day low-volatility track is not the calibration target. It keeps
collecting unchanged evidence and may consume a future independently frozen
cost model only through a separately versioned re-audit.

## Economic Decision Standard

A useful historical clue does not need to be flawless. It does need:

- positive net economics under a plausible implementation;
- a mechanism that explains who pays the return and why it may persist;
- performance that is not entirely one asset, one leg, or one regime;
- a reasonable trade-off among return, drawdown, turnover, liquidity, and
  capacity;
- evidence that simple known factors do not fully explain it;
- enough stability to justify cheap prospective observation.

At the factor stage, moderate imperfection is acceptable because no capital is
authorized. At strategy and paper stages, executable net utility becomes the
binding endpoint.

## Immediate Deliverables

1. [Completed] `Factor Identity Audit v1` for the frozen 90-day low-volatility
   relation.
2. [Completed] A small OKX historical L2 data pilot and coverage/cost report.
3. [Completed] An exact-method reading note for the selected liquidity/microstructure
   source.
4. [Current] Run the predeclared multi-regime L2 work in
   `OKX_L2_REGIME_SAMPLE_V1.json`. Its primary output is a reusable
   asset/notional/regime cost surface for the whole factory; proxy validation
   separately decides whether a microstructure batch is allowed.
5. Continued unchanged prospective collection for the low-volatility track.

## Sources

- Liu, Tsyvinski, and Wu,
  [Common Risk Factors in Cryptocurrency](https://www.nber.org/papers/w25882).
- Feng, Giglio, and Xiu,
  [Taming the Factor Zoo](https://www.nber.org/papers/w25481).
- Mercik, Zaremba, and Demir,
  [Crypto Factor Zoo](https://www.sciencedirect.com/science/article/pii/S1057521926000645).
- Cong, Karolyi, Tang, and Zhao,
  [Crypto Value, Factor Pricing, and Market Segmentation](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2024.05875).
- Coin Metrics,
  [New and Active Address Metric Documentation](https://docs.coinmetrics.io/network-data/network-data-overview/addresses/new-addresses).
- OKX,
  [Historical Market Data](https://www.okx.com/historical-data).

## Stop Rule For Engineering Drift

Before beginning any new engineering epic, state the economic decision it will
change. If it cannot change data availability, economic validity,
implementability, or prospective evidence quality, defer it.
