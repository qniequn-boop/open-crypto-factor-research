# Monthly Low-Volatility Batch 005 Result

Date: 2026-07-16

## Decision

Batch 005 produced the first frozen historical factor clue that is strong
enough to justify genuine future observation:
`monthly_low_vol_90d__equal_quintile_v1`.

This result is **not** a factor pass, strategy pass, paper-trading pass, or
permission to deploy capital. It is a survivor-conditioned OKX spot adaptation
whose only allowed next action is immutable prospective factor tracking.

The 60-day path is a terminal historical reject. It may not be inverted,
retuned, or renamed for another attempt on this sample.

## Preregistered Design

- Evidence base: Pyo and Jang (2026), who report a low-volatility effect in a
  broad Binance spot sample, challenged by Burggraf and Rudolf (2021), who
  report no low-volatility premium in an earlier and broader crypto sample.
- Universe: 50 current-live registered OKX assets; point-in-time eligibility
  requires at least 20 assets. Median formation breadth was 40.
- Signal: negative 60- or 90-day realized volatility from daily spot log
  returns, formed at completed calendar month ends.
- Portfolio: equal-weighted lowest-volatility quintile minus
  highest-volatility quintile, held for one month with a one-day execution lag.
- Friction: 5 bp fee plus 2 bp slippage per one-way turnover.
- Selection: IS and Validation through 2025-11-30. The period beginning
  2025-12-01 was inaccessible unless the frozen strong-evidence gate passed.
- Multiplicity: both frozen paths count in family BH and BY corrections; the
  random control used 500 seeded permutations.

Sources:

- [Pyo and Jang (2026)](https://doi.org/10.1016/j.frl.2026.109851)
- [Burggraf and Rudolf (2021)](https://doi.org/10.1016/j.frl.2020.101683)

## Frozen Results

| Path | IS net | IS daily Sharpe | Val net | Val daily Sharpe | Val RankIC | Val HAC p | Outcome |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 60d | -13.89% | -0.24 | 38.66% | 1.14 | 0.2550 | 0.0021 | reject |
| 90d | 24.33% | 0.44 | 50.71% | 1.50 | 0.2532 | 0.0007 | prospective shadow strong |

For the 90-day path:

- Family BH adjusted p = 0.00143; BY sensitivity adjusted p = 0.00214.
- Permutation-control p = 0.001996.
- Top-20 liquid-only net return was +3.84% in IS and +59.53% in Validation.
- 19 of 29 rolling 12-month windows were positive (65.52%).
- Validation crash-decile factor return was positive, consistent with the
  defensive mechanism rather than an ordinary market-beta explanation.
- The source-out-of-sample audit covered only 223 days and eight formations:
  net return +9.53%, daily Sharpe 0.64, RankIC 0.1389, max drawdown 15.71%, and
  no collapse under the preregistered floor.

Important adverse evidence remains:

- IS daily Sharpe was only 0.44 and IS max drawdown was 45.08%.
- The IS monthly net-return HAC p-value was 0.295; the economic sign is
  positive, but the IS portfolio mean is not statistically precise.
- Only 40 source-period formations were available, not the source paper's
  roughly 95 months.
- The universe contains current-live contracts and therefore has survivor
  conditioning. It cannot support claims about delisted or illiquid crypto.
- The source-out-of-sample period is only about seven months. Its monthly
  return and IC inference is too short for promotion.
- Spot-return evidence does not prove that a short high-volatility leg is
  executable after borrow, perpetual funding, liquidation, and venue costs.

## Independent Red-Team Checks

- Independent weight/PnL reconstruction exactly matched the stored 90-day IS
  and Validation gross return, cost, and net return.
- All 50 daily spot cache files predated the batch freeze.
- Locked input and implementation hashes matched the preregistration.
- The 60-day Holdout remained sealed; only the qualifying 90-day path accessed
  the post-source audit.
- Trial accounting contains two preregistration and two evaluation events for
  this batch. Re-running the historical evaluation is prohibited.
- The final local and Linux regression suites both passed 242 tests. The nine
  warnings are the pre-existing constant-series correlation warnings.
- The deployed readiness audit ignores one registered, deprecated OI shadow
  row without treating it as current evidence; completely unregistered tracks
  still fail integrity checks.

## Frozen Next Action

`monthly_low_vol_90d_prospective_v1` activates on 2026-07-17. The first valid
daily observation can be captured only after the 2026-07-17 daily bar is fully
closed, expected by the server snapshot job on 2026-07-18 UTC.

The track is bound to `PROSPECTIVE_FACTOR_PROMOTION_POLICY_V1.json`. Formal
factor-promotion review requires at least 365 complete future days at 99%
calendar coverage and every frozen economic, statistical, drawdown, rolling,
cost-stress, and integrity check. Promotion would permit combo research only.

Server deployment status at close: 50/50 daily spot caches are ready; both
`btclab-prospective-data.timer` and `btclab-prospective-snapshot.timer` are
enabled and active; readiness is `collect_only`, integrity is true, and the
new track has zero formal future days.

In parallel, a separate execution-translation audit must determine whether the
spot low-minus-high relation can be implemented with spot borrowing or
perpetuals. That audit may change execution assumptions, but may not alter the
frozen 90-day signal or feed results back into this track.

## Immutable Artifacts

- Batch SHA-256:
  `2cd4eab388bb6fea0baed2882943fdaf5a7317785b13356564a8d6d7dc1f4a4b`
- Historical report SHA-256:
  `a349a667e12e190d8640f566a607ec0b671509def4cab72d4116b672383606e3`
- Historical evaluator SHA-256:
  `897a2fb19e602db44bf64322de61a8d61edd3178e19b9deae5dcbcb5b232d85a`
- Prospective promotion policy SHA-256:
  `a0daade1b868ccd196fee34b4caa00841cd9061b6ffd13a617c7add525a1bd0c`
- Prospective evaluator bundle SHA-256:
  `3cf9861c62504744332964b3cdcba15e2bfbb5e98413d08d8dc94fd086c9238d`
- Track contract SHA-256:
  `e691001c6bb8e705cdcadc37d7cbbbb714648b227d7d07d24aa9014938428417`
