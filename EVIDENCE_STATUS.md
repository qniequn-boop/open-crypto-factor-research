# Evidence Status

Status date: 2026-07-19

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
| OKX historical L2 pilot | One UTC day, three assets, reproducible 400-level book reconstruction | Data-pipeline feasibility pass; production cost calibration not passed | Run the preregistered unseen date and asset sample |
| Factor promotion | No factor has completed the required future evidence horizon | None | Wait for valid prospective evidence |
| Combination research | No promoted factor is available for admission | Blocked by design | Do not create a promoted combo |
| Strategy paper trading | No combination has passed the required strategy audit | None | No strategy paper-trading claim |
| Live capital | No factor or strategy is authorized | None | No deployment |

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
- a preregistered multi-regime L2 sample that supports an asset- and
  notional-dependent cost surface;
- a new literature mechanism admitted before its candidate formulas and
  results are known.

Changing a threshold, sign, lookback, sample, or status label after viewing an
outcome does not strengthen evidence and must create a new counted trial where
it is allowed at all.
