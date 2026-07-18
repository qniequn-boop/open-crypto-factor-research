# Perpetual Basis And Funding Applicability Audit - 2026-07-16

## Decision

The available data are suitable for a bounded **spot-perpetual two-leg
mechanism adaptation**. They do not justify treating high perpetual basis or
high funding as a standalone forecast that the perpetual's future price will
fall.

Batches 003 and 004 are complete. All 12 paths were historical rejects and no
path accessed Holdout. Legacy directional funding/basis formulas remain
visible as baselines, but they are deprecated for new AI candidates. This
family is frozen on the current historical sample.

## Why The Previous Abstraction Was Wrong

Chi et al. study dated cryptocurrency futures. Their strongest displayed
result is a positive high-minus-low dated-futures basis premium. A dated
contract has maturity and convergence. The OKX instruments in this factory are
perpetual swaps with no expiry and periodic funding cash flows. Transferring
the paper's signal name while changing both the contract and the sign is not a
replication.

Gornall, Rinaldi, and Xiao identify constrained arbitrage and speculative
demand as drivers of futures dislocations. Ackerer, Hugonnier, and Jermann
show that funding specifications anchor perpetuals to spot. Both mechanisms
involve the spot and perpetual legs together. Neither source supplies a
canonical cross-sectional rule saying that a rich perpetual must have a
negative outright return.

OKX's official rule is a cash-flow constraint: positive realized funding is
paid by perpetual longs to shorts, and settlement intervals may be 1, 2, 4,
or 8 hours. The evaluator must use actual sparse events and cannot forward-fill
funding into PnL or assume one universal schedule.

## Data Applicability

The latest frozen audit contains:

- 50 registered OKX USDT perpetual assets;
- a point-in-time top-40 median eligible panel;
- a 656-day common range, from 2024-09-24 through 2026-07-11;
- 99.9936% spot and basis coverage;
- 111,881 realized funding events;
- full daily open-interest coverage for eligible asset-days, although OI is
  not required by Batch 003.

The claim ceiling remains material: the registered history is conditioned on
the current-live pool and does not contain a complete delisting archive.
Historical evidence can authorize prospective shadow observation, not capital.

## Frozen Pilots

`LITERATURE_REPLICATION_BATCH_003.json` contains three hypotheses and two
predeclared breadths per hypothesis:

1. Positive basis: top 5 and top 10.
2. Positive trailing 24-hour realized funding: top 5 and top 10.
3. Positive basis-funding alignment: top 5 and top 10.

Every path is long spot and short the matching perpetual, with 0.5 gross on
each leg, one-hour execution lag, 24-hour holding period, and 5 bps fee plus 2
bps slippage charged independently to both legs. Current-interval funding is
excluded from the signal; only lagged realized events are used.

IS and Validation decide whether a path is a reject, a cheap prospective
shadow clue, or strong enough to unlock Holdout. Holdout remains unaccessed for
ordinary rejects and weak clues. No historical classification can create
`panel_factor_pass` or permit deployment.

Batch 003 showed positive gross convergence plus funding in every IS path, but
two-leg daily turnover costs were larger and all net IS/Validation results were
negative. Batch 004 then applied the source-prescribed 10/20 and 10/50 sS
buy/hold spreads. Turnover fell, but all six net paths remained negative.

## Red-Team Notes

- A positive funding receipt can still be overwhelmed by basis widening,
  execution costs, liquidation, or exchange risk.
- The backtest does not yet model coin-specific cash financing, borrow rates,
  margin liquidation paths, or order-book impact.
- The 12 paths in Batches 003 and 004 are the closed outcome-seen family
  budget. A failed path cannot be revived by changing N, holding period,
  hysteresis band, threshold, or candidate ID after results are visible.
- A shadow clue is deliberately cheaper than a historical pass. It earns only
  permission to collect future paper evidence.

## Sources

- Chi et al. (2023), DOI `10.1002/fut.22425`.
- Gornall, Rinaldi, and Xiao (2025), SSRN `5036933`.
- Ackerer, Hugonnier, and Jermann (2026), DOI `10.1111/mafi.70018`.
- OKX, `Perpetual funding fee mechanism`, updated 2026-06-03.
- Novy-Marx and Velikov (2016), DOI `10.1093/rfs/hhv063`.
- Garleanu and Pedersen (2013), DOI `10.1111/jofi.12080`.
