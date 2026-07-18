# Literature Hypothesis Registry

This registry constrains the AI panel factor factory. A candidate without one
or more valid `id` references from this file is not eligible for panel audit.

## Research Budget Policy

- Current objective: discover and explain economically useful, net-of-cost
  crypto return relations. The automation/audit loop is supporting
  infrastructure and is no longer the primary research deliverable.
- Maximum default batch size: 20 candidates.
- Maximum default budget per mechanism family: 20 candidates before freeze and
  review.
- A normal first economic batch should contain only the canonical source path
  plus at most two economically motivated parameter/neutralization paths.
- Parameter variants must represent signal decay, cost, capacity, or an
  identified confounder; arbitrary lookback/threshold grids are not authorized.
- If a family repeatedly fails on Val, rolling stability, or multiple testing,
  it should be frozen until new data fields or literature evidence are added.
- Holdout results must not be used to ask the AI for revised candidates.

## Source Entries

- id: CRYPTO_FACTOR_ZOO_MICROSTRUCTURE
  source: Mercik, Zaremba, and Demir (2026), "Crypto Factor Zoo";
    Corwin and Schultz (2012); Abdi and Ranaldo (2017).
  mechanism: Cross-sectional compensation for trading frictions and unstable
    participation may be summarized by turnover volatility and low-frequency
    spread estimates. The relation may also be a small/illiquid risk premium
    that cannot be harvested after realistic execution costs.
  data_fields: daily high, low, close, exchange-aggregated dollar volume,
    point-in-time market capitalization, point-in-time eligibility, L2 spread
    and depth for external proxy validation
  formula_family: 30-day turnover volatility; 30-day bid-ask proxy equal to
    the simple average of Corwin-Schultz and two-day-corrected Abdi-Ranaldo
    estimates
  expected_direction: long the lowest characteristic quartile and short the
    highest characteristic quartile, rebalanced weekly; equal- and point-in-time
    market-cap-weighted results must be reported separately
  baseline: market, size, dollar-volume liquidity, Amihud illiquidity, random
    quartiles, and direct L2 quoted/effective spread
  failure_conditions: The OHLC spread proxy does not preserve cross-sectional
    ordering against predeclared L2 samples; the relation disappears inside the
    large/liquid universe; net return is nonpositive; costs consume the gross
    premium; or performance is concentrated in an untradeable short leg.
  evidence_links: https://doi.org/10.1016/j.irfa.2026.105137 ;
    https://doi.org/10.1111/j.1540-6261.2012.01729.x ;
    https://doi.org/10.1093/rfs/hhx084 ;
    https://doi.org/10.18150/IIVQQE
  claim_limits: The source uses 565 spot cryptocurrencies, exchange-aggregated
    prices and volume from more than 250 venues, active and inactive assets,
    and a 2018-2024 sample. An OKX current-perpetual adaptation is not an exact
    universe replication. No factor batch is authorized until the exact method
    audit and predeclared multi-regime L2 proxy validation are complete.

- id: CRYPTO_MARKET_SIZE_MOMENTUM
  source: Liu, Tsyvinski, and Wu, "Common Risk Factors in Cryptocurrency"
  mechanism: Cryptocurrency cross-sectional returns should be benchmarked
    against market, size, and momentum before claiming a new discovery.
  data_fields: close, volume, vol_quote
  formula_family: market, size, momentum
  expected_direction: preregistered by candidate
  baseline: market, size, momentum, random control
  failure_conditions: Does not beat simple size/momentum baselines after costs
    and multiple-testing adjustment.
  evidence_links: https://www.nber.org/papers/w25882

- id: CRYPTO_LIQUIDITY_ILLIQUIDITY
  source: Cross-sectional cryptocurrency return literature on liquidity and
    illiquidity characteristics.
  mechanism: Apparent alpha may come from liquidity segmentation, price impact,
    and small-asset effects rather than a deployable premium.
  data_fields: close, volume, vol_quote
  formula_family: liquidity, illiquidity, bucket-neutral momentum/reversal
  expected_direction: lower price impact and stable liquidity are preferred
  baseline: liquidity size, Amihud-style illiquidity, large/liquid-only subset
  failure_conditions: Effect disappears inside liquidity buckets or only exists
    in illiquid names.
  evidence_links: https://doi.org/10.1016/j.irfa.2021.101908

- id: PERP_FUNDING_BASIS
  source: Chi et al. dated-futures evidence; Gornall-Rinaldi-Xiao and
    Ackerer-Hugonnier-Jermann perpetual-futures mechanisms; official OKX
    funding settlement rules.
  mechanism: Funding is a cash transfer tied to perp-spot dislocation, not a
    standalone free alpha signal. Perpetual basis has no fixed maturity and
    therefore cannot inherit the dated-futures basis sign without adaptation.
  data_fields: close, spot_close, basis, funding_signal, funding_cost
  formula_family: delta-neutral long-spot/short-perp carry and convergence;
    outright perp funding/basis scores remain diagnostic only
  expected_direction: when basis and lagged realized funding are positive, a
    long-spot/short-perp pair receives positive funding and has convergence
    exposure; no standalone direction is authorized for future perp returns
  baseline: positive-basis pair, positive-funding pair, aligned basis-funding
    pair, random pair control
  failure_conditions: Fails after two-leg costs, sparse real funding payments,
    missing spot returns, rolling stability, or IS/Validation economic checks.
  evidence_links: https://doi.org/10.1002/fut.22425 ;
    https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5036933 ;
    https://doi.org/10.1111/mafi.70018 ;
    https://www.okx.com/en-gb/help/perps-funding-fee-mechanism

- id: TRANSACTION_COST_MITIGATION
  source: Novy-Marx and Velikov (2016); Garleanu and Pedersen (2013).
  mechanism: Predictable gross returns can be destroyed by turnover. A
    buy/hold spread or partial movement toward an aim portfolio introduces a
    no-trade region without changing the economic signal's direction.
  data_fields: signal_rank, current_position, transaction_cost, turnover
  formula_family: execution policy only; sS entry/hold hysteresis
  expected_direction: none; the source can reduce turnover but cannot authorize
    an alpha sign
  baseline: full daily rebalance using the same frozen signal
  failure_conditions: Net IS or Validation remains nonpositive, turnover does
    not fall materially, or gross signal exposure disappears.
  evidence_links: https://doi.org/10.1093/rfs/hhv063 ;
    https://doi.org/10.1111/jofi.12080

- id: CRYPTO_LOW_VOLATILITY_MONTHLY
  source: Burggraf and Rudolf (2021), "Cryptocurrencies and the Low
    Volatility Anomaly"; Pyo and Jang (2026), "Revisiting the Low-Volatility
    Anomaly in Cryptocurrency Markets".
  mechanism: Investor demand for lottery-like high-volatility assets and
    leverage or short-sale constraints can depress their subsequent returns,
    but the sign is historically unstable in cryptocurrency. The 2021 study
    finds no low-volatility premium through 2019, while the 2026 study reports
    a negative volatility-return relation in the more mature post-2017 market.
  data_fields: spot_close, spot_vol_quote, listing_time,
    point_in_time_eligibility
  formula_family: month-end realized volatility sort using daily spot returns
  expected_direction: long the lowest-volatility quintile and short the
    highest-volatility quintile; only 60-day and 90-day formation windows with
    a one-month holding horizon are authorized for the first adaptation
  baseline: market-neutral random quintiles, the previously rejected 7-day
    perpetual low-volatility diagnostic, and the high-minus-low sign implied by
    the early-market evidence
  failure_conditions: Net IS or Validation low-minus-high return is
    nonpositive, the monthly cross-sectional rank relation is not positive,
    the result is dominated by one subperiod, or the effect cannot survive the
    current large/liquid point-in-time universe and conservative execution
    costs.
  evidence_links: https://doi.org/10.1016/j.frl.2020.101683 ;
    https://doi.org/10.1016/j.frl.2026.109851
  claim_limits: The source uses 432 Binance spot assets from 2018-2025; the
    first factory adaptation uses a survivor-conditioned OKX pool with about
    40 eligible assets and 48 monthly formations. Results through 2025-11
    overlap the newer paper's source period. Data after 2025-11 are a small
    source-out-of-sample audit, not enough for formal promotion.

- id: VOL_MANAGED_CRYPTO_MOMENTUM_CARRY
  source: Cryptocurrency momentum and managed-volatility evidence.
  mechanism: Momentum and carry signals can be crash-prone; volatility scaling
    should reduce exposure to unstable trends and crowded carry.
  data_fields: close, realized_vol, funding_signal
  formula_family: volatility-managed momentum, volatility-managed carry
  expected_direction: trend or carry score scaled down by realized volatility
  baseline: unmanaged momentum and unmanaged funding carry
  failure_conditions: Managed version does not improve drawdown, rolling Sharpe,
    or large/liquid-only robustness.

- id: AI_FACTOR_ENGINEERING_PATTERNS
  source: Qlib/RD-Agent, FactorEngine, FactorMiner, and related factor-agent
    engineering research.
  mechanism: Structured factor representations, experiment memory, validation,
    and staged evaluation can improve factory reliability and reproducibility.
  data_fields: candidate_schema, experiment_registry, evaluator_logs
  formula_family: engineering method only; cannot authorize a tradable factor
  expected_direction: none
  baseline: manual candidate serialization and unstructured experiment logs
  failure_conditions: The source is used as economic evidence or to authorize
    a candidate's sign, family, or promotion.
  evidence_links: https://github.com/microsoft/qlib ;
    https://arxiv.org/abs/2505.15155 ; https://arxiv.org/abs/2604.26747

- id: PERP_OPEN_INTEREST_CROWDING
  source: OKX contract open-interest history definitions; Bessembinder and
    Seguin-style futures evidence on return interactions with lagged changes in
    open interest; Alexander and Heck on reconciling reported perpetual-swap
    open interest with traded volume.
  mechanism: Open interest measures outstanding leveraged contracts but has no
    directional sign by itself. Growth in lagged OI is only interpretable when
    interacted with price direction or funding-side crowding. Measurement error
    requires clipping and robustness checks rather than treating raw OI level
    as size or conviction.
  data_fields: close, open_interest, funding_signal, liquidity_size
  formula_family: OI-confirmed trend, price-OI crowding reversal,
    funding-OI crowding reversal
  expected_direction: fade price or funding direction when lagged OI growth
    indicates leveraged crowding
  baseline: momentum, funding carry, OI change alone, liquidity size
  failure_conditions: Effect disappears after a 24-hour OI publication lag,
    liquidity neutralization, large/liquid-only audit, or crash-period audit.
  evidence_links: https://www.okx.com/docs-v5/en/#trading-data-rest-api-get-contract-open-interest-history ;
    https://arxiv.org/abs/2310.14973 ;
    https://doi.org/10.1016/S0378-4266(03)00120-Trading activity and price reversals in futures markets

- id: BACKTEST_OVERFITTING_DSR_PBO
  source: Bailey and Lopez de Prado, Deflated Sharpe Ratio and Probability of
    Backtest Overfitting.
  mechanism: Exploratory research inflates performance through selection bias,
    non-normal returns, and repeated trials.
  data_fields: trial_registry, returns, validation_metrics
  formula_family: audit method, not a tradable factor
  expected_direction: stricter acceptance as trial count grows
  baseline: unadjusted Sharpe and naive validation ranking
  failure_conditions: Candidate is only significant before trial-count or
    overfitting adjustment.
  evidence_links: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 ;
    https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
