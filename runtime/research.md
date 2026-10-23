# Quantitative research — 2,000 USD

Results are specific to the supplied dataset; no forecast.
Data origin: alpaca_iex_download

| Sample | Strategy | Return % | Max drawdown % | Round trips |
|---|---|---:|---:|---:|
| train | trend_6_24 | -3.96 | -9.37 | 461 |
| train | breakout_12 | -7.64 | -9.56 | 310 |
| train | reversion_20 | 2.53 | -7.15 | 267 |
| validation | trend_6_24 | 1.72 | -4.01 | 177 |
| validation | breakout_12 | 2.08 | -1.78 | 105 |
| validation | reversion_20 | 1.59 | -2.08 | 78 |
| holdout | breakout_12 | -2.85 | -3.60 | 98 |
| holdout | SPY 100% | 12.58 | -9.04 | 1 |
| holdout | SPY 60% + cash | 7.55 | -5.47 | 1 |

Research gate: False
Blockers: holdout_not_profitable, does_not_beat_60pct_spy, fails_cost_stress

Data hash: b2e9205cb2f607d99d03607c724744bdecb9c8018c9a3c8c58b60b9f32ff036c

Feed: iex
Declared price basis: dividend_adjusted_research_proxy. Paper fills and dividends differ. No automatic promotion.
