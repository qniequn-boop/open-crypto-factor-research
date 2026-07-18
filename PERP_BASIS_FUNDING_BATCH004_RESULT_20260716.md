# Perpetual Basis/Funding Batch 004 Result - 2026-07-16

## Outcome

The literature-prescribed sS turnover rescue also produced six
`historical_mechanism_reject` results. Holdout remained sealed for all paths.
The perpetual basis/funding family is now frozen on this historical sample.

| Path | IS gross + funding | IS cost | IS net | Val gross + funding | Val cost | Val net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| basis 10/20 | 0.1235 | 0.2830 | -0.1595 | 0.0111 | 0.0184 | -0.0073 |
| basis 10/50 | 0.1172 | 0.2521 | -0.1349 | 0.0113 | 0.0177 | -0.0064 |
| funding 10/20 | 0.0479 | 0.2925 | -0.2447 | 0.0107 | 0.1010 | -0.0902 |
| funding 10/50 | 0.0452 | 0.2173 | -0.1722 | 0.0092 | 0.0734 | -0.0642 |
| aligned 10/20 | 0.0955 | 0.2343 | -0.1388 | 0.0098 | 0.0182 | -0.0084 |
| aligned 10/50 | 0.0930 | 0.2133 | -0.1203 | 0.0100 | 0.0175 | -0.0075 |

The wider hold band reduced turnover and cost, especially for the funding
signal, but the cost remained several times larger than the gross payoff. No
holding-period, rank-band, cost-threshold, or direction variants may now be
added from the same mechanism and sample.

The append-only registry now contains 44 candidate IDs and 62 portfolio
variants. The 12 spot-perpetual paths from Batches 003 and 004 are included in
the global trial count.

## Next Route

Do not resume AI generation inside this family. The next research batch must
come from an independent mechanism and source, or from materially new data
that changes the estimand, such as executable premium-index/order-book data,
cross-exchange spreads, or a longer point-in-time delisting-complete history.
