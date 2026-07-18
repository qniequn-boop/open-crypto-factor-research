# Differential Point-In-Time Formula Audit v1

## Purpose

`panel_formula_audit.py` is a mandatory compilation gate for frozen candidate
batches. It tests observable behavior rather than trusting source inspection.
The method follows Freqtrade's sliced lookahead analysis and Qlib's
point-in-time rule: changing or removing future input must not alter any
feature value that was already observable.

## Method

The audit builds a complete baseline and then reruns the matrix builder at
multiple frozen cutoffs in two ways:

- physically truncate every panel input after the cutoff;
- retain the full index but strongly perturb every numeric future input.

For each cutoff it compares the complete historical prefix of eligibility,
core matrices, formula-library outputs, and factor outputs. Comparisons are
NaN-aware and use declared numeric tolerances. `fwd_returns` is deliberately
excluded because it is a supervised label, not a tradable feature.

## Fail-Closed Contract

- Any historical mismatch is `leakage_detected`.
- A required candidate formula with no observable values is
  `inconclusive_no_observations`, not a pass.
- Every required candidate must be exactly `causal_pass`.
- The formula-audit report contains no Holdout performance payload.
- The report is bound to the candidate batch id and immutable substrate.
- The independent critic and evaluator recheck the report's file hash.

## Verified Evidence

Tests cover a causal formula, a planted `shift(-1)` leak, an unobservable
required factor, and the production momentum matrix builder. The planted leak
is detected in both the formula and candidate factor frames.

The real eight-asset, 730-day audit on 2026-07-15 inspected 63 frames across
378 differential comparisons:

- 53 frames were `causal_pass`;
- 10 were `inconclusive_no_observations`;
- zero leakage frames were found;
- both OI candidate formulas were unobservable under the current 20-asset
  breadth requirement, so the batch failed closed.

Report: `logs/panel_formula_audit_20260715T144253Z.json`.

## Non-Claims

- Causal equivalence does not prove economic value.
- Passing does not authorize historical evaluation without critic approval.
- Passing does not authorize prospective tracking, a combo, or capital.
- The audit cannot prove correctness for an input field that has no
  observations; that case remains inconclusive.

