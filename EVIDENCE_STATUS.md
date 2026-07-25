# Evidence Status

Status date: 2026-07-25

This ledger separates implemented research infrastructure from empirical
evidence. A completed data loader or passing test suite is not evidence that a
factor earns a positive return.

## Status Vocabulary

| Status | Meaning |
| --- | --- |
| Registered | The hypothesis and failure conditions exist before evaluation |
| Historical reject | The frozen path failed its declared historical gate and cannot be retuned on the same sample |
| Historical clue | The path justifies further observation but is not a factor pass |
| Prospective eligible | A frozen rule may collect future shadow observations under a policy frozen before activation |
| Factor promotion | Prospective factor evidence has passed every frozen requirement and may enter combination research |
| Paper-trading eligible | A portfolio has passed separate historical, prospective, cost, and strategy audits |
| Deployment eligible | Paper evidence plus operational and risk review permits a separately governed capital decision |

## Current Ledger

| Object | Evidence | Status | Allowed next action |
| --- | --- | --- | --- |
| Point-in-time panel substrate | 50 registered assets; median and p10 analyzable breadth of 40; audited sparse funding, basis, and open-interest coverage | Engineering pass with a survivor-conditioned historical claim ceiling | Extend history and delisting coverage; continue prospective snapshots |
| Liu-Tsyvinski-Wu weekly momentum adaptation | Two frozen paths evaluated | Historical reject, 2 of 2 | Preserve negative result; no sign flip or sample retuning |
| Large/liquid daily momentum adaptation | Four frozen paths evaluated | Historical reject, 4 of 4 | Preserve negative result; no renamed retry |
| Perpetual basis and funding convergence | Twelve frozen spot-perpetual paths; gross convergence and funding did not overcome two-leg costs | Historical reject, 12 of 12; family frozen on this sample | Revisit only with genuinely new data or a new registered mechanism |
| Monthly low volatility, 60-day formation | Positive validation but negative in-sample net evidence under the frozen design | Terminal historical reject | None on the current sample |
| Monthly low volatility, 90-day formation | Positive historical clue with material uncertainty, survivor conditioning, weak in-sample precision, and limited source-out-of-sample length | Prospective eligible, not promoted | Collect unchanged future observations under the frozen policy |
| Low-volatility execution translation | Sparse realized funding and declared cost stresses were evaluated for the frozen signal | Passed for paper-design research only | Continue execution research; no factor or portfolio promotion |
| OKX visible-book cost surface | Five assets, five frozen dates, three notionals, and 15 complete aggregate cells; median one-way cost 5.18-12.91 bps and p95 5.82-33.54 bps with a 5 bps taker fee | Sanitized aggregate execution evidence; production cost calibration and capacity inference not passed | Expand direct measurement across assets, regimes, and operational frictions |
| Evidence-window detection power | Eighteen synthetic cells, 200 replications per cell, and 3,600 outcomes; zero formal passes in 1,800 realistic-reference outcomes | `mechanically_open_realistic_power_insufficient`; diagnostic only, no real factor tested | Improve data breadth and research design before interpreting continued rejection as evidence of no effect |
| Factor promotion | No factor has completed the required future evidence horizon | None | Wait for valid prospective evidence |
| Combination research | No promoted factor is available for admission | Blocked by design | Do not create a promoted combo |
| Strategy paper trading | No combination has passed the required strategy audit | None | No strategy paper-trading claim |
| Live capital | No factor or strategy is authorized | None | No deployment |

## Sanitized Execution-Economics Package

The public package
[`execution_economics_power_v1`](./evidence/execution_economics_power_v1.json)
contains aggregate cost-surface, proxy-admission, cost-sensitivity, and
synthetic detection-power evidence. Its schema is `1.0`; `real_factor_tested`
and `mechanics_anchor_is_economic_evidence` are false, as are factor admission,
combination, paper-trading, deployment, and capital authorities.

The package is accompanied by a
[research note](./docs/EXECUTION_ECONOMICS_AND_DETECTION_POWER_20260725.md)
and a [data-free validator](./examples/run_execution_economics_power_demo.py).
Passing that validator confirms package integrity and the declared arithmetic.
It does not promote a factor or support production execution capacity.

## The Low-Volatility Claim, Precisely

The frozen 90-day monthly low-volatility path is the strongest current clue,
but it remains below factor promotion. Its favorable historical evidence
includes positive Validation performance, multiplicity-adjusted inference, a
permutation control, and a positive liquid-only result. Its adverse evidence
includes weak in-sample precision, a large in-sample drawdown, limited
formation count, current-survivor conditioning, a short source-out-of-sample
period, and unresolved real-world short-leg implementation.

The original prospective v1 track was invalidated after producing zero formal
factor days because its integrity contract was coupled to unrelated evaluator
changes. The v2 track began unchanged on 2026-07-18 with the same frozen factor
and promotion policy. No v1 observation can be backfilled.

Relevant records:

- [MONTHLY_LOW_VOL_BATCH005_RESULT_20260716.md](./MONTHLY_LOW_VOL_BATCH005_RESULT_20260716.md)
- [LOW_VOL_EXECUTION_TRANSLATION_RESULT_20260716.md](./LOW_VOL_EXECUTION_TRANSLATION_RESULT_20260716.md)
- [PROSPECTIVE_FACTOR_TRACKING_REGISTRY.json](./PROSPECTIVE_FACTOR_TRACKING_REGISTRY.json)
- [PROSPECTIVE_FACTOR_PROMOTION_POLICY_V1.json](./PROSPECTIVE_FACTOR_PROMOTION_POLICY_V1.json)

## Negative Evidence Is a Result

Rejected paths are not erased or quietly inverted. The momentum and
basis/funding replications narrow the set of claims supported by this sample.
They also prevent repeated attempts from being presented as independent new
discoveries. New work in a closed family requires a genuinely new registered
source, new mechanism, or new evidence period, not a cosmetic formula change.

## What Would Change the Claim

The public claim may advance only when an immutable record supplies new
decision-relevant evidence. Examples include:

- enough valid prospective days to evaluate the frozen promotion policy;
- a complete delisted-instrument archive that changes the survivorship claim;
- a broader preregistered L2 sample that extends the asset- and
  notional-dependent cost surface across more regimes and operational frictions;
- a new literature mechanism admitted before its candidate formulas and
  results are known.

Changing a threshold, sign, lookback, sample, or status label after viewing an
outcome does not strengthen evidence and must create a new counted trial where
it is allowed at all.
