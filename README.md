# GaganEA v2.10

An MQL5 Expert Advisor for MetaTrader 5.

GaganEA is a multi-pattern, trend-following EA that trades in the direction of a
higher-timeframe trend, confirmed by candlestick and chart patterns on the
execution timeframe.

## Features

- **Multi-pattern entries** — candlestick and chart pattern detection aligned
  with the higher-timeframe (HTF) and current-timeframe (CTF) EMA trend.
- **Risk-based lot sizing** — automatic position sizing from account balance and
  a configurable risk percentage, with a manual lot override and lot caps.
- **Tiered take-profit targets (T1/T2/T3)** — staged partial closes at each
  target level.
- **Individual and basket trailing stops** — per-position trailing after T2 plus
  same-side basket trailing that locks in and protects aggregate profit.
- **AMA trend-flip exit** — closes positions when the M1 Adaptive Moving Average
  confirms a trend flip against the open direction.
- **Reversal-detection exit** — multi-signal confirmation (RSI divergence, MACD
  histogram, volume spike, EMA cross-back, ADX exhaustion) to exit on reversals.
- **Equity protection** — global drawdown protection by percent or money, plus a
  master equity-protection trailing layer.
- **On-chart dashboard** — live display of trend, signal, spread, open trades,
  floating and period P&L, and exit-system status.

## Usage

1. Copy `GaganEA.mq5` into the MetaTrader 5 `MQL5/Experts` folder.
2. Compile it in MetaEditor to produce `GaganEA.ex5`.
3. Attach the EA to a chart and configure the input parameters as needed.

> Trading involves substantial risk. Test thoroughly in the Strategy Tester and
> on a demo account before using with real funds.
