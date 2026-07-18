# Economic Stage Report - OKX Historical L2 Pilot

Date: 2026-07-17

## Decision

The bounded historical L2 pilot is complete. It establishes that the official
OKX archive can support reproducible order-book reconstruction and
notional-specific execution diagnostics. It does **not** establish a stable
backtest cost calibration and does not authorize a new factor batch.

- Data pipeline feasibility: passed.
- Full execution-cost calibration: not passed; one UTC day is insufficient.
- Microstructure factor admission: not yet authorized.
- Promotion, combo, and prospective contracts: unchanged.

Canonical outputs:

- `logs/okx_l2_pilot_20260710.json`
- `logs/okx_l2_pilot_20260710.md`

## Frozen Pilot Design

- Observation date: 2026-07-10 UTC.
- Instruments: XRP-USDT-SWAP, LDO-USDT-SWAP, and TRX-USDT-SWAP.
- Source: official OKX daily 400-level L2 and trade archives.
- Book sampling: every 10 seconds after incremental reconstruction.
- Depth bands: 5, 10, 25, and 50 basis points from midpoint.
- Market-order notionals: 100, 1,000, and 10,000 USDT.
- Current comparison model: 5 bps taker fee plus fixed 2 bps one-way
  slippage.
- Search status: no factor sign, lookback, threshold, or portfolio parameter
  was searched.

The downloader records source URLs, byte counts, and SHA-256 hashes. The
reconstructor streams compressed NDJSON, applies zero-size deletions, uses the
OKX contract value to translate contracts into quote notional, and aligns each
trade to the latest preceding reconstructed midpoint.

## Observed Economics

| Asset | Median quoted spread | Volume-weighted effective slippage | Median bid depth within 5 bps | 100 USDT all-in median / p95 | 10,000 USDT all-in median / p95 |
|---|---:|---:|---:|---:|---:|
| XRP | 0.91 bps | 1.11 bps | 345,415 USDT | 5.45 / 5.46 bps | 5.45 / 6.19 bps |
| LDO | 3.28 bps | 4.92 bps | 3,615 USDT | 6.65 / 9.66 bps | 12.40 / 14.76 bps |
| TRX | 0.30 bps | 0.90 bps | 72,355 USDT | 5.15 / 5.15 bps | 5.51 / 6.88 bps |

All three instruments produced 8,640 valid 10-second samples, or 100% nominal
daily coverage. Every retained trade matched a preceding quote. The L2 stream
contained 2,713,950 XRP messages, 755,988 LDO messages, and 681,293 TRX
messages, with no timestamp-order violation.

The economic result is cross-sectional heterogeneity, not a universal cost
number. The current 7 bps one-way assumption is conservative at the median for
100 USDT orders in this three-asset day. It nevertheless understates LDO tail
cost even at 100 USDT and materially understates visible-book cost for 1,000
and 10,000 USDT LDO orders. A single fixed 2 bps slippage value is therefore
not defensible across both assets and position sizes.

## Limits

- This is one recent day and three assets, selected to test feasibility and
  economically relevant liquidity variation. It cannot estimate long-run
  execution distributions.
- Visible-book impact excludes latency, rejection, hidden liquidity, queue
  position, and operational outages.
- Current contract specifications were used for a recent historical date.
  Older sampling requires point-in-time instrument specifications.
- An unchanged book can create quote staleness without a data failure; the
  staleness fields are descriptive rather than an exclusion rule.
- These measurements are factory-wide economic inputs and must not be selected
  or calibrated to alter the frozen low-volatility factor, the microstructure
  candidate, or any other named factor after seeing performance.

## Next Decision-Changing Work

1. Read and freeze the exact microstructure factor definitions used by the
   selected primary study.
2. Before downloading more L2 data, predeclare a small date set spanning calm,
   stressed, high-volume, and low-volume market conditions.
3. Estimate an asset- and notional-conditioned cost surface on that frozen
   sample, including uncertainty and conservative tail choices.
4. Only if coverage and economics survive, freeze one canonical factor path
   and at most two mechanism-based variants.

The next deliverable is the exact-method reading note. A factor batch remains
blocked until both the method and multi-regime cost evidence are adequate.

## Verification

- Local full regression: `278 passed`, with nine unchanged constant-series
  warnings.
- Linux full regression: `278 passed`, with the same nine warnings.
- The deployed code, test, three research documents, and two canonical pilot
  outputs have matching local/Linux SHA-256 hashes.
- The prospective data, prospective snapshot, and factory scheduler timers
  remained active after deployment.
