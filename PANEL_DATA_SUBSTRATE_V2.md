# Panel Data Substrate v2

## Objective

Construct a wider panel without pretending that a frozen list of today's live
contracts is a historical market universe. Eligibility must be computed at each
timestamp from information available before that timestamp.

## Registered Rules

- Candidate pool: 50 currently live, spot-backed OKX USDT perpetuals frozen in
  `PANEL_UNIVERSE_REGISTRY.json`.
- Historical target: at most 40 eligible assets per timestamp.
- Minimum listing age: 180 days using OKX `listTime`.
- Minimum observed history: 90 days with at least 90% hourly coverage.
- Liquidity: previous 30-day average quote volume, at least 21 days observed,
  lagged one hour, minimum USD 1 million per day.
- Ranking: point-in-time liquidity rank only. The freeze-date rank is never
  applied to historical timestamps.
- Open interest: raw OKX daily observations are retained as sparse events. A
  bounded 24-hour as-of view may be used by later candidates, but the raw audit
  never treats forward-filled values as new observations.
- Funding history: at least 90% of the requested span is mandatory. A recent
  REST fallback is rejected and is never cached as a 730-day dataset.
- Prefetch: funding downloads are always single-threaded. Limited concurrency
  is allowed only when funding is explicitly skipped.
- Asset families: manually preregistered broad labels. Labels are audit and
  neutralization metadata, not return predictors by themselves.

## Bias Boundary

The v2 pool is still survivor-conditioned because OKX's current instruments
endpoint does not return every contract delisted before the freeze date.
Consequently the engineering substrate can pass while `batch1_allowed` remains
false. Batch1 requires either a delisted-instrument archive or a prospective-only
protocol that begins at the registry freeze date.

The OKX live instruments endpoint was checked with `live`, `suspend`, `preopen`,
and `test` state parameters on 2026-07-11. Every query returned the same live
set, with no expired instruments. Historical-candle requests for ten contracts
named in official OKX delisting notices returned error `51001` (instrument does
not exist). An exchange-complete delisted archive therefore cannot be recreated
from the current public market API without pretending announcement search is
exhaustive.

The registered solution is a two-tier evidence protocol:

- Pre-freeze history is `survivor_conditioned_exploration`; its promotion
  ceiling is `panel_factor_watchlist`.
- Samples beginning on or after `2026-07-10T00:00:00Z` are prospective-only and
  may become eligible for formal promotion once all other gates pass.
- A retrospective pass can only be restored by a demonstrably complete
  delisted-instrument archive.

## Evidence

- OKX documents `listTime` on its public instruments endpoint and describes it
  as the listing timestamp: https://www.okx.com/docs-v5/en/#public-data-rest-api-get-instruments
- OKX added contract-level open-interest history in June 2024. The live endpoint
  accepts `instId`, `period`, `begin`, `end`, and `limit` and returns contract,
  coin, and USD open interest:
  https://www.okx.com/docs-v5/en/#trading-data-rest-api-get-contract-open-interest-history
- Liu, Tsyvinski, and Wu identify market, size, and momentum as core crypto
  cross-sectional factors, which makes breadth and benchmark construction a
  first-order data question: https://www.nber.org/papers/w25882
- Ammann, Burdorf, Liebi, and Stockl quantify material survivorship and delisting
  bias in crypto panels, especially for equal-weighted portfolios:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4287573

## Promotion Policy

`data_substrate_v2_pass` means the registered fields, point-in-time masks, and
power proxy are technically usable. It does not clear survivorship bias.
`batch1_allowed` additionally requires `survivorship_complete = true` or an
explicit prospective-only research mode.

The final strict 50-asset audit completed at `20260712T115651Z`: 50 assets
loaded without failures, 48 were eligible at least once, analyzable-period
median and p10 breadth were both 40, basis coverage was 0.99994,
open-interest coverage was 1.000, and 111,881 sparse funding events were
retained. The engineering substrate passed; formal promotion remained blocked
only by the historical survivorship boundary. After separating data audit from
factor construction, the cached full audit completed in about 131 seconds.

Daily prospective data updates and immutable universe snapshots are enabled on
the server. The first 2026-07-11 snapshot was created during an intraday smoke
test and is therefore bootstrap-only. New snapshots explicitly record
`day_complete` and `formal_evidence_eligible`; only a snapshot whose final bar
is 23:00 UTC counts as a complete-day formal observation.
