# Execution-Cost Heterogeneity and Evidence-Window Detection Power

Sanitized public research note, 2026-07-25.

This note is the public-facing summary of two frozen research results: a
visible-book execution-cost surface and a synthetic evidence-window
detection-power confirmation. It publishes only aggregate, public-safe
evidence. It contains no candidate formulas, no named strategy paths, no
per-seed rows, no Holdout metrics, no loading values, no optimization
history, and no operational identifiers. No factor, combo, paper-trading,
deployment, or capital authority is granted by this package; every such
authority field in the machine-readable package is false.

## Summary

- Execution costs measured on a visible limit-order-book surface are
  heterogeneous across assets and rise with order size. Median one-way
  all-in cost (5 bps taker fee included) spans 5.18 to 12.91 bps across 15
  aggregate asset/notional cells; the p95 stress span is 5.82 to 33.54 bps.
- An OHLC-based bid-ask composite spread proxy ranked liquidity in the
  correct direction on all five frozen dates but missed the frozen median
  cross-sectional Spearman gate (0.4 against a 0.5 minimum), so it is
  demoted to a ranking diagnostic and cannot calibrate execution-cost
  magnitude.
- In a nonbinding historical sensitivity, low-turnover liquidity/Amihud
  path groups were comparatively stable under the measured cost surface,
  while higher-turnover momentum, funding, basis, and reversal groups
  deteriorated. No profit recipe and no named-path outcomes are published.
- A synthetic detection-power confirmation over 124/365/730-day evidence
  windows shows the research gate is mechanically traversable yet has
  insufficient realistic power: zero formal passes in 1,800 realistic
  planted-effect outcomes, with watchlist rates below every frozen minimum
  through 730 days. The frozen seven-rule classification is
  `mechanically_open_realistic_power_insufficient`. No real factor was
  tested; the study evaluates the evaluation machinery itself.

## Frozen Evidence

Two frozen artifacts underlie this note:

1. A multi-regime visible-book cost study. Five USDT-margined perpetual
   swaps (LDO, LTC, SOL, TRX, XRP) were swept on five frozen regime dates
   against preregistered order-book archives. The 25 preregistered
   asset-date cells aggregate into 15 asset/notional surface cells at
   100, 1,000, and 10,000 USDT. Each cell records the median and p95
   one-way all-in cost of walking the visible book, including the 5 bps
   one-way taker fee, plus the minimum buy/sell fill fractions.
2. A synthetic evidence-window detection-power confirmation. Six frozen
   cells (two null controls, three realistic planted reference effects, and
   one mechanics-only anchor) were each replicated 200 times at three
   Validation windows (124, 365, and 730 days), producing 18 cells and
   3,600 outcomes on previously untouched confirmation seeds. The frozen
   decision bands and the seven ordered classification rules were fixed
   before any confirmation outcome was observed.

Both results are nonbinding. They change research priority and
methodology understanding; they change no formal status of anything.

## Cost Heterogeneity

Median one-way all-in cost in bps (5 bps taker fee included), by asset and
order notional:

| Asset | 100 USDT | 1,000 USDT | 10,000 USDT |
| --- | ---: | ---: | ---: |
| LDO-USDT-SWAP | 6.31 | 7.94 | 12.91 |
| LTC-USDT-SWAP | 5.89 | 5.89 | 6.23 |
| SOL-USDT-SWAP | 5.39 | 5.39 | 5.56 |
| TRX-USDT-SWAP | 5.18 | 5.18 | 5.94 |
| XRP-USDT-SWAP | 5.37 | 5.37 | 5.49 |

Aggregate heterogeneity:

- Median one-way cost ranges from 5.18 bps (TRX, 100 USDT) to 12.91 bps
  (LDO, 10,000 USDT), a max/min ratio of about 2.49.
- p95 one-way cost ranges from 5.82 bps (SOL, 100 USDT) to 33.54 bps
  (LDO, 10,000 USDT), a max/min ratio of about 5.76.
- Median cost increases with notional for every one of the five assets;
  the increase is modest for the most liquid assets and material for the
  thinnest one.
- Minimum buy and sell fill fractions are 100% in all 15 cells at the
  sampled grid; this says nothing about sizes above the grid.

Scope of the surface: it covers five assets and five frozen dates, the
5 bps taker fee is included, and it excludes latency, queue position,
hidden liquidity, rejects, outages, and any production capacity inference.

### Cost Sensitivity by Turnover Group

A nonbinding 3 x 3 historical sensitivity (100/1,000/10,000 USDT total
capital against median/p95/double-p95 cost scenarios) replayed frozen
baseline path groups against the surface. From the fixed 7 bps one-way
baseline to the most stressed cell (10,000 USDT, double-p95), the change
in Validation total return by group was:

| Path group | Total-return change | Interpretation |
| --- | ---: | --- |
| Low-turnover liquidity/Amihud, rank-linear | -0.0066 to -0.0074 | Comparatively stable |
| Low-turnover liquidity/Amihud, top-bottom | about -0.0120 | Comparatively stable |
| Momentum | -0.24 to -0.37 | Deteriorated |
| Funding carry | -0.51 to -0.65 | Deteriorated |
| Basis carry | -0.55 to -0.65 | Deteriorated |
| Short reversal | -0.67 to -0.79 | Deteriorated |

Low-turnover groups were comparatively stable and higher-turnover groups
deteriorated. This is group-level evidence only: no profit recipe, no
named-path outcomes, and no promotion-relevant status is published or
implied.

## Proxy Rejection

A preregistered bid-ask spread composite proxy, built from daily OHLC
prices, was evaluated as a candidate cheap calibration source for
execution cost. The composite is the average, over 29 overlapping pairs,
of two estimators: the 30-day Corwin-Schultz high-low estimator and the
30-day two-day-corrected Abdi-Ranaldo close-high-low estimator. The
frozen admission rule required, among coverage conditions, a median
cross-sectional Spearman rank correlation of at least 0.5 against
directly measured order-book spreads.

The proxy ranked liquidity in the correct direction on all five frozen
dates, but its median cross-sectional Spearman was 0.4, below the frozen
0.5 gate. Admission therefore failed. The proxy remains a ranking
diagnostic only and cannot calibrate execution-cost magnitude; no proxy
magnitude enters the cost surface. The preregistered gate was applied as
frozen and was not relaxed after the result was observed.

## Detection-Power Interpretation

The confirmation study asked a methodological question: if a realistic,
plausible effect were present, would the current gate detect it within a
feasible evidence window? Six synthetic cells were evaluated at 124, 365,
and 730 Validation days with 200 replications per cell: two null controls,
three realistic planted reference effects (full-panel net Sharpe 0.30,
full-panel net Sharpe 0.60, and large/liquid-only net Sharpe 0.50), and
one mechanics-only anchor. That is 18 cells and 3,600 outcomes, of which
1,800 are realistic outcomes.

Aggregate results:

- Null controls: zero formal passes at every window; screened
  watchlist-or-pass rates of at most 1% at every window, inside all frozen
  null bands (pass successes at most 1 of 200, Wilson-95 upper bound at
  most 0.028, watchlist-or-pass rate at most 0.10).
- Realistic reference effects: zero formal passes in all 1,800 realistic
  outcomes. Screened watchlist-or-pass rates against the frozen minima:

| Reference effect | Frozen watchlist minimum | 124d | 365d | 730d |
| --- | ---: | ---: | ---: | ---: |
| Full panel net Sharpe 0.30 | 0.65 | 0.29 | 0.32 | 0.395 |
| Full panel net Sharpe 0.60 | 0.95 | 0.43 | 0.51 | 0.615 |
| Large/liquid net Sharpe 0.50 | 0.80 | 0.15 | 0.28 | 0.385 |

- Mechanics-only anchor: 100% formal-pass rate (200 of 200) at every
  window. The anchor is a deliberately extreme synthetic effect used only
  to demonstrate that the evaluation machinery can open. It is
  diagnostic-only, is excluded from every realistic-power claim, and is
  not economic evidence. No real factor was tested in this study.

The frozen seven ordered classification rules evaluate, in order:
(1) null-band breach, (2) realistic power at a feasible window,
(3) realistic power only at 730 days, (4) watchlist-only power at a
feasible window, (5) watchlist-only power at 730 days, (6) mechanics
demonstrated but realistic power insufficient, and (7) mechanics not
demonstrated. Rules 1 through 5 did not match; rule 6 matched. The
classification is therefore:

```
mechanically_open_realistic_power_insufficient
```

Interpretation: the gate does not pass noise (nulls are controlled) and is
mechanically traversable (the anchor passes), yet it lacks power to admit
planted realistic effects even at 730 Validation days. A long run of zero
candidate admissions under this gate is therefore weak evidence about the
candidate pool: it is consistent both with genuinely weak candidates and
with a gate that could not detect a realistic effect if one were present.
This result motivates a multiplicity-governance audit; it does not by
itself authorize any threshold, gate, or status change.

## Limitations

- The cost surface covers five assets and five frozen dates, not the broad
  crypto population; extending direct measurement to more assets is open
  work.
- The surface is visible-book only. It excludes latency, queue position,
  hidden liquidity, rejects, outages, and any production capacity
  inference. No production capital ceiling can be inferred from it.
- The p95 and double-p95 scenarios are declared stress multipliers, not
  observed tail estimates.
- The turnover-group sensitivity is historical, nonbinding, and
  group-level; it is not a profit recipe and names no tradable path.
- The detection-power study is synthetic. Planted reference effects are
  methodological devices, not candidate factors, and the mechanics anchor
  is diagnostic-only. The study measures gate power; it says nothing
  directly about any real strategy.
- Watchlist rates below frozen minima indicate insufficient power at the
  tested effects; they do not prove that no detectable effect exists at
  other effect sizes or designs.

## Reproducibility

The package is self-contained and data-free. The demo script lives at
`examples/run_execution_economics_power_demo.py`, the machine-readable
package at `evidence/execution_economics_power_v1.json`, and the focused
test module at `tests/test_execution_economics_power_demo.py`. With
Python 3.11 (standard library only) and no network access, run the
following commands from the public repository root; the demo is always
invoked with an explicit `--package` path:

```bash
# Validate the package and print a human-readable report.
python examples/run_execution_economics_power_demo.py --package evidence/execution_economics_power_v1.json

# Emit the machine-readable validation report.
python examples/run_execution_economics_power_demo.py --package evidence/execution_economics_power_v1.json --json

# Run the focused test suite.
python -m pytest tests/test_execution_economics_power_demo.py
```

The validator re-derives every published conclusion from the shipped
aggregate data: cost-cell completeness and uniqueness, heterogeneity
ranges and ratios, the proxy admission decision against the frozen 0.5
gate, the per-window band evaluation, and the seven-rule classification.
It fails closed on malformed schema, unknown keys at any documented
object level, incomplete or duplicated cost cells, changed power
identities, tampered published rates or band values (even when the
classification would remain unchanged), any true authority field, or any
true false-flag claim.

## Primary References

- Corwin, S. A., and P. Schultz (2012). "A Simple Way to Estimate Bid-Ask
  Spreads from Daily High and Low Prices." Journal of Finance, 67(2),
  719-760. https://doi.org/10.1111/j.1540-6261.2012.01729.x
- Abdi, F., and A. Ranaldo (2017). "A Simple Estimation of Bid-Ask Spreads
  from Daily Close, High, and Low Prices." Review of Financial Studies,
  30(12), 4437-4480. https://doi.org/10.1093/rfs/hhx084
- Bailey, D. H., and M. Lopez de Prado (2014). "The Deflated Sharpe Ratio:
  Correcting for Selection Bias, Backtest Overfitting and Non-Normality."
  Journal of Portfolio Management, 40(5), 94-107.
  https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- Harvey, C. R., Y. Liu, and H. Zhu (2016). "... and the Cross-Section of
  Expected Returns." Review of Financial Studies, 29(1), 5-68.
  https://www.nber.org/papers/w20592
- Arnott, R., C. R. Harvey, and H. Markowitz (2019). "A Backtesting
  Protocol in the Era of Machine Learning." Journal of Financial Data
  Science, 1(1), 64-74.
  https://people.duke.edu/~charvey/Research/Published_Papers/SSRN-id3275654.pdf
- Bailey, D. H., J. Borwein, M. Lopez de Prado, and Q. J. Zhu (2014).
  "Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest
  Overfitting on Out-of-Sample Performance." Notices of the American
  Mathematical Society, 61(5), 458-471.
- OKX official documentation: Historical Market Data,
  https://www.okx.com/historical-data ; Trading fee schedule,
  https://www.okx.com/fees . The 5 bps one-way taker fee used here is a
  declared scenario input, not a fitted value.
