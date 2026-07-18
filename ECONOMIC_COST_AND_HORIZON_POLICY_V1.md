# Factory-Wide Cost And Horizon Economics

Date: 2026-07-18

## Governing Decision

Execution cost and time horizon are shared economic inputs for the entire
factory. They are not supporting parameters for the 90-day low-volatility clue
or any other named factor.

The same asset, notional, regime, venue, and order type must receive the same
cost assumption regardless of which factor produced the order. A factor cannot
receive a cheaper cost because its backtest is attractive, and a rejected
factor cannot receive a different holding period merely to improve its return.

The machine-readable policy is
`ECONOMIC_COST_AND_HORIZON_POLICY_V1.json`.

## Shared Cost Surface

The factory-wide cost surface must condition on:

- exchange and fee tier;
- asset and order notional;
- quoted and effective spread;
- visible-book price impact;
- turnover and rebalance size;
- actual sparse funding when a perpetual position is held;
- calm, stressed, high-volume, and low-volume regimes;
- a separate stress buffer for latency, rejection, and unavailable liquidity.

It must report median, p95, round-trip, capacity, break-even-turnover, and
stress-cost outputs. L2 data calibrates execution; an OHLC spread proxy may
rank liquidity but may not set transaction cost.

The model is frozen before factor returns are evaluated. A later cost-model
improvement creates a new versioned audit and never silently overwrites the
old conclusion.

## Shared Time Model

Time research separates seven quantities that are often incorrectly mixed:

1. signal measurement window;
2. portfolio formation frequency;
3. rebalance frequency;
4. intended holding period;
5. realized turnover;
6. signal decay across forward horizons;
7. net return after horizon-specific cost.

Every factor starts from the source paper's canonical horizon. One slower or
lower-turnover path is allowed only when the economic decay/cost trade-off
justifies it. Daily, weekly, and monthly buckets are common reporting scales,
not permission for a parameter grid.

IS may estimate signal decay. Validation decides whether the already frozen
horizon is worth future observation. Holdout cannot choose a horizon.

## Relationship To The 90-Day Track

The 90-day low-volatility track is only one frozen consumer of the future
shared model:

- it is not a calibration target;
- it does not choose L2 assets, dates, notionals, or regimes;
- its signal and prospective contract remain unchanged;
- it receives no special cost or holding-period treatment;
- after the shared model is frozen, any re-audit is a new versioned report and
  does not replace the original historical evidence.

This preserves the clue without allowing the project to become a single-factor
rescue exercise.

## Current Deliverable

The current multi-regime L2 work has two outputs:

1. a reusable asset/notional/regime execution-cost surface for all factors;
2. a separate check of whether the Crypto Factor Zoo OHLC spread proxy preserves
   liquidity ordering.

Only the second output controls admission of the proposed `bidask` factor. The
first output belongs to the whole economic system even if that factor is
rejected.
