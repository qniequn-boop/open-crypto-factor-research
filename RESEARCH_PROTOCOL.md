# BTC Factor Mining Research Protocol

## 1. Objective

This project is a BTC single-asset factor research machine, not a one-off
strategy optimizer. The expected output is a low-redundancy factor pool and a
combo signal whose incremental value survives a fixed validation protocol.

The LLM proposes falsifiable hypotheses and DSL expressions. Deterministic code
is the judge: fixed data splits, fixed costs, fixed metrics, fixed logs.

## 2. Data Discipline

- IS is used for candidate admission and fitting combo weights.
- Validation is used for combo selection.
- Holdout is audit only. Do not tune thresholds, prompts, families, or combo
  weights against Holdout.
- Every run must log the data split, cost assumptions, candidate expression,
  family, status, and all reported metrics.

## 3. BTC Single-Asset Metrics

BTC is not a cross-sectional equity universe, so RankIC-style objectives should
not be the primary target.

Primary metrics:

- Directional accuracy (`dir_acc`)
- Net Sharpe after costs and slippage
- Max drawdown
- Turnover / exposure
- Regime-split performance

Secondary diagnostics:

- Pearson IC
- Spearman IC
- Bucket returns
- Win rate and expectancy

## 4. Candidate Admission

A candidate can enter the factor pool only if:

- DSL parses and executes without unsafe behavior.
- No lookahead is introduced by the expression or backtest.
- IS evidence is positive in at least one regime.
- Behavior correlation with existing pool factors is below the configured pool
  threshold.
- The expression is not a trivial blacklist/template clone.

Entering the pool is not promotion. It means the factor is worth considering as
one component of a larger combo.

The candidate `direction` is executable semantics, not a comment. `short`
signals are multiplied by `-1` before evaluation, while `long` and `neutral`
are left unchanged.

Single-factor status is recorded separately:

- `pooled_is_only`: admitted by IS/regime evidence, but not validated as a
  standalone factor.
- `single_factor_val_sharpe_pass`: Validation Sharpe is positive, but direction
  hit rate is not yet clearly above 50%.
- `single_factor_val_pass`: Validation Sharpe is positive and directional
  accuracy is above 50%.

## 5. Combo Selection

Combo weights are fit on IS only. A combo is selected/promoted only by
Validation performance. Holdout can be printed and saved, but it must remain an
audit field.

The combo pool is stricter than the research pool. A factor can be remembered as
research evidence while being excluded from ridge combination if its full
IS/Validation evidence is too weak. This prevents one-regime IS artifacts from
poisoning the multi-factor signal.

Combo status has two layers:

- `combo_audit_pass`: beats the best Validation baseline, has acceptable
  Validation subperiod stability, and does not collapse in Holdout audit.
- `combo_audit_failed`: passes Validation selection but clearly fails Holdout
  audit. This is recorded as failure evidence, not as a deployable result.

The saved combo record must include:

- Factor ids and expressions
- Combo weights
- Validation metrics
- Holdout audit metrics
- The explicit note that Holdout was not used as a selection gate

## 6. Memory And Diversity

Experiment memory should accumulate structural lessons:

- Successful mechanisms
- Failed mechanisms
- Repeated templates to avoid
- Family coverage
- Behavior correlation against the pool
- Regime tags

The search objective is not "best single candidate". It is incremental
complementarity: a new factor is useful when it adds a distinct mechanism to the
current pool and improves the combo under the fixed protocol.

Admitted factors are persisted in `logs/factor_pool.json` as DSL expressions and
metadata. Signals are recomputed from the expressions on each run so the pool
stays auditable and compact.

## 7. Baseline Discipline

Before treating any result as meaningful, compare it against:

- Buy and hold
- Naive momentum
- Naive mean reversion
- RSI / Bollinger baseline
- Random sign or shuffled-signal control

These baselines are not optional decoration. They are the guardrail against
overfitting a noisy market.
