# Economic Stage Report - Exact Microstructure Method

Date: 2026-07-17

## Completed

- Read the accepted primary manuscript rather than relying on the abstract.
- Froze the exact 30-day turnover-volatility and OHLC bid-ask constructions.
- Verified the Corwin-Schultz and Abdi-Ranaldo equations against their primary
  papers and implemented causal estimators with unit tests.
- Registered the source mechanism and a blocked replication contract without
  generating a factor or adding a trial.
- Compared the exact OHLC proxy with direct L2 for XRP, LDO, and TRX.
- Froze unseen regime dates, assets, measurements, admission gates, and a 2 GB
  budget before downloading the next L2 observations.

## Economic Finding

The source proxy preserves the three-asset liquidity order on the pilot date,
but overstates direct quoted spread by 57 to 135 times. Therefore the OHLC
measure may be a liquidity-ranking characteristic, but it is not an execution
cost. Direct L2 remains binding for cost and capacity.

## Decision

The exact-method deliverable is complete. A new factor batch remains blocked.
The next stage is the predeclared multi-regime L2 comparison. If it fails, the
bid-ask adaptation is rejected without searching alternative windows or dates;
turnover volatility can still be considered separately under the same cost
sample.

## Verification

- Focused method and policy tests pass.
- Local full regression: `284 passed`, with nine unchanged constant-series
  warnings.
- Linux full regression: `284 passed`, with the same nine warnings.
- Linux recomputation reproduced the same source-proxy ordering, ratios, and
  decisions. The only numeric difference was approximately `7e-15` in one TRX
  floating-point value across NumPy/Python environments.
- The prospective data, prospective snapshot, and factory scheduler timers
  remained active throughout deployment.
