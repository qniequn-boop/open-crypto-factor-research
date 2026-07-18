# Perpetual Basis/Funding Batch 003 Result - 2026-07-16

## Outcome

Batch 003 completed on the frozen 50-asset substrate. All six paths are
`historical_mechanism_reject`. No path accessed Holdout and no path entered
prospective tracking.

This is not a zero-signal result. Every path had positive IS gross pair payoff
after combining spot-perpetual price convergence and funding receipts. The
daily two-leg rebalance cost was larger than that gross payoff, producing
negative net IS and Validation returns.

## Attribution

| Path | IS gross + funding | IS cost | IS net | Val gross + funding | Val cost | Val net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| basis top 5 | 0.0987 | 0.2660 | -0.1673 | 0.0088 | 0.0160 | -0.0071 |
| basis top 10 | 0.0706 | 0.1975 | -0.1270 | 0.0051 | 0.0094 | -0.0043 |
| funding top 5 | 0.0465 | 0.3073 | -0.2608 | 0.0119 | 0.1037 | -0.0918 |
| funding top 10 | 0.0425 | 0.2512 | -0.2087 | 0.0080 | 0.0851 | -0.0771 |
| aligned top 5 | 0.0786 | 0.2206 | -0.1421 | 0.0086 | 0.0162 | -0.0077 |
| aligned top 10 | 0.0520 | 0.1287 | -0.0766 | 0.0050 | 0.0092 | -0.0042 |

The result routes the mechanism to execution-cost mitigation, not to formula
generation or sign flipping. Batch 004 is the single allowed rescue batch. It
uses the source-prescribed 10/20 and 10/50 sS buy/hold spreads without tuning
the bands on our outcomes. If Batch 004 has no net IS/Validation clue, the
perpetual basis/funding family is frozen.

The exact evaluated code and report are archived on the server at
`logs/source_archives/20260716_batch003_evaluated/`. The CLI summary error that
occurred after the report was written did not alter the report and was fixed
after archiving the evaluated source.
