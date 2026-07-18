# Frozen Low-Volatility Execution Translation Result

## Decision

The preregistered audit classified the frozen 90-day monthly low-volatility
signal as `execution_translation_pass_for_paper_design`.

This is execution evidence for one factory product. It does not change the
factor's `prospective_shadow_strong` status, create a factor pass, authorize a
combo, start strategy paper trading, or authorize capital. No factor trial
events were written.

## Frozen Design

- Signal: unchanged `monthly_low_vol_90d__equal_quintile_v1` spot signal.
- Translation: the same monthly long-low-volatility/short-high-volatility
  weights applied to matching OKX USDT perpetual returns.
- Window: 2024-07-11 00:00 UTC through 2026-07-11 00:00 UTC.
- Standard one-way cost: 7 bps; stress cost: 14 bps.
- Funding: realized sparse settlement events, never forward-filled.
- Gross exposure: 1.0; no leverage.
- Spot-margin borrowing: not backtested because historical asset-specific
  borrow rates, availability, and recalls were unavailable.

OKX states that positive funding is paid by longs to shorts, while negative
funding reverses the payer, and that settlement intervals may be 1, 2, 4, or 8
hours ([funding mechanism](https://www.okx.com/en-gb/help/perps-funding-fee-mechanism)).
Current `minSz`, `lotSz`, and contract value came from the public instruments
endpoint ([OKX API documentation](https://www.okx.com/docs-v5/en/#public-data-rest-api-get-instruments)).
Borrow rates and limits are authenticated, account-specific fields, so they are
not a public point-in-time historical borrow panel
([OKX account API](https://www.okx.com/docs-v5/en/)).

## Results

| Evidence | Result |
| --- | ---: |
| Gross perpetual price return | +55.61% |
| Net realized funding cost | -4.93% |
| Standard execution cost | -1.02% |
| Arithmetic net return | +49.67% |
| Compounded net return | +52.40% |
| Daily Sharpe | 0.90 |
| Maximum drawdown | 22.85% |
| Double-cost arithmetic net return | +48.65% |
| Post-source arithmetic net return | +4.28% |
| Spot/perpetual daily gross correlation | 0.9975 |
| Held assets with complete funding evidence | 44 / 44 |
| Current 100 USDT legs within 25% sizing error | 11 / 12 |

Most of the historical gain came from the source-overlap period: +45.33%
versus +4.28% after 2025-11-30. The post-source segment remained positive but
had only a 0.29 daily Sharpe. Funding consumed about half of its gross return.
This is useful adverse context, not a reason to tune the signal.

At 100 USDT current contract granularity, BNB was the only active leg outside
the frozen 25% notional-error tolerance: the minimum contract represented
5.744 USDT versus an 8.333 USDT target, a 31.1% under-allocation. The 91.7%
aggregate feasibility check passed, but current specifications are not proof of
historical order-size feasibility.

## Independent Checks

- An independent reconstruction, outside the audit's portfolio function,
  exactly reproduced gross return, funding, turnover, costs, full net return,
  double-cost net return, and zero missing held returns.
- The independent continuous-hold post-source return was +4.336%; the report's
  +4.284% is lower because each reported subperiod conservatively pays a fresh
  initial-entry charge at its boundary.
- The factor trial registry remained 140 rows with unchanged SHA-256
  `c6428bc9900ebe7d6dddf8fce16bc0a96438afcaca1389ae47537ebbc1c59658`.
- The prospective tracking registry remained unchanged, and both server timers
  remained active.
- Local regression passed 248 tests. The six new focused tests passed on Linux.

## Data Drift Incident

The first server attempt stopped before calculating returns because its current
daily spot caches did not match the Batch 005 input fingerprint. The canonical
local caches did match. They were restored to the server, the frozen fingerprint
was verified, and only then was the audit allowed to run.

The exact 50-file cache version is preserved as
`logs/immutable_inputs/monthly_low_vol_daily_spot_cache_snapshot_20260716.tar.gz`
with SHA-256
`f89cbbdab181fe6b410ec5dc702baf0fa46b8b67623c2dc6608f4241e5e3a7c0`.
This confirms that fingerprints must fail closed and that input bodies, not
only hashes, must be recoverable.

## Factory Decision

Factor-specific development stops here. The result is retained as proof that
the factory can produce a historically plausible and execution-translatable
sample. Sustainable factory work takes priority: process-group termination,
stale-lock recovery, concurrent-batch isolation, bounded automatic source and
candidate scheduling, alerts, and quotas.

The source mechanism remains Pyo and Jang's contemporary crypto low-volatility
finding ([paper metadata and abstract](https://ideas.repec.org/a/eee/finlet/v97y2026ics1544612326003818.html)).

## Immutable Artifacts

- Contract SHA-256:
  `d119754442e7c25cf619ded7235feb24fd6e02b21b3d2600e97f85aa173e15ee`
- Auditor SHA-256:
  `77963b583104c161c393c33cb1032bed7c5a41599602690febcc64c9bcafc095`
- Machine report SHA-256:
  `17b9c3d76d5f0263f42341669d37b650f7d555dd7e3a5e2aad86fa968c0d8981`
