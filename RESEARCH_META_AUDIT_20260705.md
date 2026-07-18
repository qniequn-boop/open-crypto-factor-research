# Research Meta-Audit - 2026-07-05 (updated 2026-07-10)

## Purpose

Step outside the implementation loop and audit whether the project is still
moving toward a genuinely usable crypto research system, rather than becoming a
more automated way to mine false positives.

## Current Evidence

- Old single-BTC research did not produce an exportable strict-audit strategy.
- The 16-asset / 730-day panel is a better research base than BTC-only, but it
  is still a small crypto cross-section.
- Batch0 AI candidate factory completed the intended process loop:
  - AI generated 5 literature-constrained panel candidates.
  - Candidates were frozen in `logs/panel_candidate_batch_20260704T155950Z.json`.
  - Trials were recorded in `logs/panel_trial_registry.jsonl`.
  - A quality-gated 730-day / 16-asset audit completed in
    `logs/panel_factor_report_20260710T105926Z.json`.
  - Failure analysis is in `logs/panel_failure_analysis_20260704T155950Z.json`.
- Full batch0 audit result:
  - 45 total factor variants.
  - 5 AI candidate variants.
  - PASS 0.
  - WATCHLIST 0.
  - AI candidate watchlist count 0.
  - All 5 AI candidate variants were `panel_factor_reject`.
  - `combo_allowed = false`.

## Literature-Consistent Interpretation

- The current system is valuable primarily because it reduces false discovery
  risk through preregistration, trial counting, holdout isolation, baseline
  comparison, rolling checks, and failure logging.
- Backtest-overfitting work such as Deflated Sharpe Ratio / PBO implies that
  more trials must make promotion harder, not easier.
- Crypto factor literature supports market, size, momentum, liquidity, and
  carry/funding as benchmark mechanisms, but these should be treated as
  baselines and hypotheses, not as discoveries.
- With 16 assets and roughly 730 days, the panel can produce research evidence,
  but it is not a large-sample institutional factor lab.
- Funding/carry watchlist rows are mechanism-plausible, but they remain
  fragile and competitive. They are research leads, not deployable strategies.

Reference anchors:

- Bailey and Lopez de Prado, Deflated Sharpe Ratio / selection bias under
  multiple testing: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2465675
- Bailey, Borwein, Lopez de Prado, and Zhu, Probability of Backtest
  Overfitting: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Liu, Tsyvinski, and Wu, Common Risk Factors in Cryptocurrency:
  https://www.nber.org/papers/w25882
- Angeris, Chitra, Evans, and Lorig, Fundamentals of Perpetual Futures:
  https://arxiv.org/abs/2212.06888

## Main Risk Right Now

The main risk is no longer missing code. The main risk is process drift:

```text
generate candidates -> reject -> generate more -> reject -> keep trying
```

That would turn the AI panel factory into a more disciplined-looking
overfitting machine.

The project has not entered that loop yet because batch0 was frozen, audited,
rejected, and analyzed. But the next decision matters.

## Stop Decisions

- Stop trying to revive batch0 AI candidates.
- Stop generating more AI candidates until the data/audit substrate is improved.
- Stop treating watchlist rows as strategy candidates.
- Stop interpreting 60-day smoke runs as research evidence.
- Stop letting SSH instability dominate research priorities; it is operational
  noise unless it blocks required server jobs.

## Continue Decisions

- Continue the panel-first research direction.
- Continue literature registry constraints.
- Continue trial registry counting, including rejected and syntax-failed trials.
- Continue holdout isolation.
- Continue no-pass/no-combo enforcement.
- Continue documenting rejected hypotheses.

## Change Decisions

Before batch1 AI generation, improve evidence quality rather than candidate
quantity:

1. Add a data coverage audit.
   - Per-symbol bars, spot coverage, funding event count, basis coverage.
   - Missingness by asset and split.
   - Minimum viable history per asset.

2. Add robustness views to the panel report.
   - Large/liquid-only subset.
   - Liquidity-bucket within-group performance.
   - Crash/stress windows.
   - Regime splits if labels are available.

3. Add data fields before widening formula search.
   - Open interest.
   - Listing age.
   - Asset family labels.
   - Better market-cap or liquidity proxies.

4. Strengthen multiple-testing accounting.
   - Use full trial registry as the research budget ledger.
   - Report family-level trial counts.
   - Keep batch-level and family-level budgets visible in reports.

5. Only then run batch1.
   - Max 5-10 candidates.
   - Must cite literature source IDs.
   - Must explain why it is not a near-duplicate of a rejected formula.
   - Must not see holdout details.

## Objective Next Step

Do not generate batch1 solely because batch0 is finished.

`Panel data and robustness audit v1` now exists:

- `panel_data_audit.py`
- `logs/panel_data_audit_20260705T061505Z.json`

The first data audit passed the data-substrate gate:

- 16 loaded assets.
- 17,700 common hourly bars.
- Close coverage 99.95%.
- Basis coverage 99.93%.
- Funding events 34,926, sparse by design at roughly the expected funding
  cadence.
- 5 crash/stress windows identified.
- `data_audit_pass_for_batch1 = true`.

Batch1 waited until the robustness views were integrated into the factor report
and connected to promotion decisions:

- large/liquid-only factor diagnostics,
- liquidity-bucket factor diagnostics,
- crash/stress window factor diagnostics.

This integration is implemented in `panel_factor_research.py` and verified by
the quality-gated full server report
`logs/panel_factor_report_20260710T105926Z.json`.

Current robustness result:

- PASS 0.
- WATCHLIST 0.
- All batch0 AI candidates remain rejected.
- The 4 former funding/carry watchlist rows were demoted for documented reasons:
  Val or Holdout liquidity-bucket concentration, rolling Sharpe fragility,
  multiple-testing failure, or excessive crash-window loss.
- No combo is allowed.

Quality gates v1 success criterion is satisfied:

The factor report itself should be able to explain whether a candidate survives
large/liquid-only, liquidity-bucket, and crash/stress diagnostics. These checks
now participate in both pass and watchlist promotion, and appear in
`failed_checks` when they fail.

Panel data substrate v2 is now complete:

- `logs/panel_data_audit_20260712T115651Z.json`
- 50/50 requested assets loaded, 48 eligible at least once.
- Analyzable-period median and p10 breadth are both 40; 12 assets per side are
  available for top/bottom 30% portfolios.
- Basis coverage is 99.994%, OI coverage is 100%, and all funding histories
  satisfy the preregistered span gate.
- The technical substrate passes.
- Retrospective exploration is allowed with a hard watchlist ceiling.
- Formal promotion remains blocked because the pre-freeze universe is
  survivor-conditioned.
- Immutable daily prospective snapshots and data updates are active. Only
  complete UTC-day snapshots count as formal prospective evidence.

## Current Research State

No factor is deployable.
No combo is allowed.
No live trading is justified.

The project is still useful, but its next value comes from better evidence
quality, not more AI-generated candidates.
