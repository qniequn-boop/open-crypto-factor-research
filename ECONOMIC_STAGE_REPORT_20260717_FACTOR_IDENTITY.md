# Economic Stage Report - Factor Identity Audit v1

Date: 2026-07-17

## Decision

The frozen 90-day monthly low-volatility relation remains worth observing, but
it is not promoted and cannot enter a combo. The most defensible label is:

> Defensive low-volatility relation with partial incremental alpha; independent
> factor identity remains unresolved.

No formula, lookback, sign, prospective contract, trial count, or promotion
state was changed.

## What Was Verified

- The new audit reconstructed IS and Validation return, gross return, cost, and
  drawdown exactly against frozen Batch 005 before attribution.
- Holdout was not loaded into any identity estimator.
- The audit used 50 registered assets, 40 valid monthly formations, and a median
  eligible cross-section of 40 assets.
- Joint time-series controls covered crypto market, size, 21-day momentum, and
  30-day liquidity.
- Conditional cross-sectional controls added market cap, momentum, liquidity,
  and 90-day market beta.
- Long and short legs, individual-asset contribution, neutralization, and market
  regimes were reported separately.

## Evidence For The Relation

- Pooled daily joint-control net alpha: 17.98% annualized, HAC t=2.01,
  two-sided p=0.044.
- Pooled monthly joint-control net alpha: 16.70% annualized, HAC t=1.75,
  two-sided p=0.081.
- The conditional low-volatility slope was positive in both IS and Validation.
- Joint-neutralized net returns stayed positive: +38.05% IS and +7.49%
  Validation.
- The long low-volatility leg was positive in both periods.
- The five largest absolute asset contributions represented 29.92% of total
  absolute contribution, so the result was not produced by one coin alone.

## Evidence Against A Strong Claim

- The pooled conditional Fama-MacBeth low-volatility slope had HAC t=1.47 and
  p=0.141. It did not establish a clean cross-sectional factor after controls.
- The neutralized Validation result had monthly HAC t=0.58.
- The short high-volatility leg changed from -39.11% in IS to +16.61% in
  Validation.
- Market-up months totaled -33.44%, while market-down months totaled +108.48%.
- Low-market-volatility months totaled -16.10%, while high-volatility months
  totaled +91.14%.
- The universe remains current-live and survivor conditioned. Historical L2
  spread, depth, impact, borrow, and short capacity are not yet measured.

The regime partitions above are descriptive. They are not a new timing rule and
must not be used to tune the frozen prospective factor.

## Stage Completion

Immediate economic program: 1 of 4 deliverables complete.

1. Factor Identity Audit v1: complete.
2. OKX historical L2 pilot and executable-cost report: current.
3. Exact microstructure method note: pending the data pilot.
4. One bounded microstructure batch: conditional on items 2 and 3.

The prospective low-volatility clock continues independently and still needs
365 complete future days before formal promotion can be considered.

## Next Work

The next decision-changing task is a small OKX historical L2 pilot. It will test
whether we can reliably measure quoted/effective spread, depth at fixed basis
point bands, and price impact at 100, 1,000, and 10,000 USDT notionals. It will
also determine whether the short high-volatility leg is economically
executable, or whether only a separately evaluated defensive long sleeve is
plausible.

Canonical machine report: `logs/factor_identity_audit_v1_20260717.json`.

Canonical readable report: `logs/factor_identity_audit_v1_20260717.md`.

Implementation verification: `274 passed` locally and on Linux, with the same
nine pre-existing constant-series warnings. The Linux full-data rerun reports
an exact frozen reconstruction and the same evidence flags as the local run.
