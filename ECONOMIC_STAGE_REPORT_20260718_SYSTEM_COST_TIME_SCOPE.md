# Economic Stage Report - System-Wide Cost And Time Scope

Date: 2026-07-18

## User Correction

Cost, capacity, execution, and time-horizon research belong to the economic
layer of the whole factory. They must not become a private optimization project
for the frozen 90-day low-volatility clue.

## Audit Finding

The existing L2 code did not alter the 90-day signal or use its returns to
select cost observations. However, the roadmap placed the cost work close
enough to the low-volatility discussion that future work could accidentally
become factor-specific. The scope is now explicit and machine checked.

## Changes

- Added `ECONOMIC_COST_AND_HORIZON_POLICY_V1.json` and its readable companion.
- Bound `OKX_L2_REGIME_SAMPLE_V1.json` to the factory-wide policy.
- Required identical costs for identical asset/notional/regime/order inputs,
  regardless of factor identity or performance.
- Separated signal window, formation, rebalance, holding, turnover, decay, and
  horizon-specific net return.
- Limited horizon research to the source canonical path plus at most one
  slower cost/decay-justified path; arbitrary time grids remain prohibited.
- Explicitly made the frozen 90-day track a non-priority consumer rather than
  a calibration target.

## Economic Consequence

The multi-regime L2 study remains valuable even if the proposed bid-ask factor
is rejected. Its primary product is a reusable asset/notional/regime cost
surface for all factor batches, combos, paper trading, and later re-audits.

The 90-day track continues unchanged. A future shared cost-model version may
produce a separately versioned re-audit, but cannot rewrite its old evidence or
select a friendlier cost or holding period.

## Verification

- Focused policy and economic-method suite: `15 passed`.
- Local full suite: `286 passed`, with nine unchanged constant-series warnings.
- No factor, candidate, trial, promotion, combo, or prospective contract was
  changed.
- Linux focused policy tests: `2 passed`.
- Linux full suite: `286 passed`, with the same nine warnings.
- The prospective data, prospective snapshot, and factory scheduler timers
  remained active after deployment.
