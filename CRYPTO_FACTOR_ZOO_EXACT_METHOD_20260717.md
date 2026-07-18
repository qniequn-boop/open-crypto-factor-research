# Crypto Factor Zoo Exact-Method Reading Note

Date: 2026-07-17

## Research Question

Can the liquidity dimensions selected by Mercik, Zaremba, and Demir (2026) be
translated into a causal, executable OKX panel study without confusing a
low-frequency liquidity proxy with actual trading cost?

The answer is **method yes, factor not yet**. The source construction is now
precise and coded, but the first L2 comparison reveals large magnitude bias in
the OHLC spread proxy. A predeclared multi-regime validation must finish before
either characteristic enters a frozen factor batch.

## Source Population And Design

The paper studies 565 active and inactive spot cryptocurrencies from January
2018 to July 2024. CryptoCompare supplies volume-weighted OHLC and volume from
more than 250 centralized exchanges, CoinMarketCap supplies market value and
classification tags, and IntoTheBlock supplies on-chain fields.

The source removes stablecoins, metal-pegged assets, derivative-platform
collateral coins, and wrapped assets. It removes nonpositive price, volume, and
market-value observations, daily volume/market-cap ratios above one, and market
values below USD 1 million. It forms weekly zero-investment quartile portfolios
and reports equal- and value-weighted results.

This matters because our registered OKX pool is a narrower, current-live,
survivor-conditioned perpetual universe. Our work is an adaptation, not an
exact population replication.

## Exact Characteristics

### Turnover Volatility

For asset `i` and day `t`:

```text
turnover(i,t) = daily dollar trading volume(i,t) / market value(i,t)
std_dto(i,t) = sample standard deviation of turnover over the trailing 30 days
```

The paper describes the second expression equivalently as the residual
standard deviation from a 30-day intercept-only regression. Values with
turnover above one are excluded by the source cleaning rule.

### Bid-Ask Spread Proxy

The paper's `bidask` is not a direct quote. It is the simple average of two
30-day OHLC estimators.

For Corwin-Schultz, each overlapping two-day pair defines:

```text
beta  = ln(H[t-1]/L[t-1])^2 + ln(H[t]/L[t])^2
gamma = ln(max(H[t-1],H[t]) / min(L[t-1],L[t]))^2
d     = 3 - 2*sqrt(2)
alpha = (sqrt(2*beta) - sqrt(beta))/d - sqrt(gamma/d)
S_CS  = max(2*(exp(alpha)-1)/(1+exp(alpha)), 0)
```

The 30-day estimate is the average of the 29 overlapping pair estimates.
Crypto trades continuously, so the stock-market overnight closure correction
is not applied.

For two-day-corrected Abdi-Ranaldo, using log prices:

```text
eta[t] = (ln(H[t]) + ln(L[t])) / 2
S_AR_pair[t] = sqrt(max(4*(ln(C[t-1])-eta[t-1])
                           *(ln(C[t-1])-eta[t]), 0))
```

Again, the 30-day estimate averages 29 overlapping pairs. A value reported at
the end of day `t` uses the prior close and current high/low, so it does not use
day `t+1` information.

The frozen source proxy is:

```text
bidask = (S_CS_30d + S_AR_30d) / 2
```

Both characteristics have source direction `-1`: weekly long the lowest
quartile and short the highest quartile.

## Source Evidence

- Equal-weighted turnover volatility earned 0.98% per week with Newey-West
  t=3.14 in the source univariate table and entered first in the equal-weighted
  iterative factor model.
- Bid-ask spread earned 0.66% per week with t=2.19 equal weighted and 2.09% with
  t=3.65 value weighted. It entered first in the value-weighted factor model.
- Bid-ask spread was the only selected value-weighted factor that survived both
  source subperiods. The paper nevertheless reports limited temporal stability
  for the broader selected set and material sensitivity to trading costs.

These results motivate replication. They are not evidence that an OKX
perpetual implementation will earn the same premium.

## First Direct L2 Check

The exact formulas were applied to refreshed OKX perpetual OHLC for the same
three assets and date as the 2026-07-10 L2 pilot.

| Asset | Source OHLC composite | Direct L2 quoted median | Composite / quoted |
|---|---:|---:|---:|
| XRP | 72.35 bps | 0.91 bps | 79.9x |
| LDO | 187.43 bps | 3.28 bps | 57.1x |
| TRX | 40.79 bps | 0.30 bps | 134.9x |

The descending order matches exactly (`LDO > XRP > TRX`), but three assets on
one day are not validation. The absolute proxy is tens to more than one hundred
times the quoted spread. This is direct evidence that the OHLC estimator mixes
volatility with trading friction in this market. It may still be useful as a
cross-sectional characteristic, but it cannot calibrate execution cost.

Canonical audit outputs:

- `logs/crypto_factor_zoo_method_audit_20260717.json`
- `logs/crypto_factor_zoo_method_audit_20260717.md`

## Frozen Next Test

`OKX_L2_REGIME_SAMPLE_V1.json` freezes five unseen BTC-defined market dates,
five assets, a 2 GB compressed-download budget, and admission checks before any
new L2 result is inspected. The already observed 2026-07-10 pilot is excluded
from unseen validation counts.

The dates were selected from a hash-locked BTC hourly file using only market
return, intraday range, and quote volume. No candidate return, Validation, or
Holdout result entered selection.

Passing this next test only permits a frozen batch containing the canonical
bid-ask path and canonical turnover-volatility path. It does not make either
factor a historical pass.

## Decision

- Exact source method: frozen and executable.
- Literature hypothesis and replication contracts: registered.
- OHLC spread as transaction cost: rejected.
- OHLC spread as cross-sectional rank proxy: unresolved.
- Turnover-volatility adaptation: unresolved.
- Candidate/trial registry: unchanged.
- Promotion, combo, and prospective low-volatility track: unchanged.

## Primary Sources

- [Mercik, Zaremba, and Demir, Crypto Factor Zoo](https://www.sciencedirect.com/science/article/pii/S1057521926000645)
- [Open accepted manuscript](https://open.icm.edu.pl/handle/123456789/26644)
- [Official factor-return dataset](https://repod.icm.edu.pl/dataset.xhtml?persistentId=doi%3A10.18150%2FIIVQQE)
- [Corwin and Schultz high-low estimator](https://doi.org/10.1111/j.1540-6261.2012.01729.x)
- [Abdi and Ranaldo close-high-low estimator](https://doi.org/10.1093/rfs/hhx084)
