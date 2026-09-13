# GaganEA Iteration Log

A per-round changelog for the XAUUSD M5 backtest-improvement loop.

**Goal:** maximize return while keeping drawdown **conservative** (risk-adjusted
and robust out-of-sample, *not* raw headline return).

## The loop

1. **Hypothesis** — state one change and why it should help.
2. **Change** — adjust EA inputs (or, in a code round, the EA logic).
3. **Backtest** — run MT5 Strategy Tester on your local PC (XAUUSD, M5,
   Fusion Markets) and export the HTML report to
   `reports/roundNN_YYYYMMDD.html` (see `reports/README.md`).
4. **Analyze** — run `python3 tools/analyze_report.py reports/roundNN_*.html`
   to get metrics + a conservative-drawdown DIAGNOSIS.
5. **Diagnose & decide** — record the verdict and the next step below.

> Note: XAUUSD is 2–3 digits; the EA's `*_Pips` inputs are actually **POINTS**
> (e.g. `StopLoss_Pips = 2500` = 2500 points).

---

## Per-round template (copy for each new round)

```
## Round NN — <short title>  (YYYY-MM-DD)

- **Hypothesis:** <what you believe and why>
- **Change made:** <EA inputs or logic changed; "none" for a baseline>
- **Backtest config:**
  - Symbol / timeframe: XAUUSD / M5
  - Date range: <YYYY.MM.DD – YYYY.MM.DD>
  - Deposit: <e.g. 10000 USD>
  - Leverage: <e.g. 1:500>
  - Broker: Fusion Markets
  - Modelling: <e.g. Every tick based on real ticks>
- **Key metrics:**
  - Net profit: <value>
  - Max drawdown %: <value>
  - Profit factor: <value>
  - Win rate: <value>
  - Total trades: <value>
- **Diagnosis:** <verdict + notable flags from analyze_report.py>
- **Next step:** <the single change to try next>
- **Report file:** reports/roundNN_YYYYMMDD.html
```

---

## Round 0 — Baseline scaffolding  (tooling only)

- **Hypothesis:** Before tuning anything, we need a repeatable way to measure a
  backtest against the conservative-DD goal. Establish the measurement half of
  the loop first.
- **Change made:** **No trading-logic change.** EA is **GaganEA v2.10**
  baseline (`GaganEA.mq5`, unmodified). Added the analysis tooling:
  - `tools/analyze_report.py` — stdlib-only MT5 HTML report parser +
    metrics summary + conservative-DD diagnosis + JSON output.
  - `reports/README.md` — how to export the MT5 HTML report, filename
    convention, and how to run the analyzer.
  - `reports/samples/` — synthetic sample reports (newer + older MT5 layouts)
    for verifying the analyzer.
  - This `ITERATION_LOG.md`.
- **Backtest config:** N/A (no backtest run this round; scaffolding only).
- **Key metrics:** N/A (baseline — to be filled from Round 1 onward).
- **Diagnosis:** Tooling verified against the synthetic samples: the analyzer
  parses both MT5 report layouts, extracts net profit / profit factor /
  drawdowns / trades / win rate, and prints a DIAGNOSIS with a verdict.
- **Next step:** Run the first real backtest of the v2.10 baseline on the local
  PC, export the HTML, and analyze it to capture true baseline metrics.
- **Report file:** none (no backtest this round).

---

## Round 1 — True v2.10 baseline  (2026-09-13)

- **Hypothesis:** Establish the real, reproducible v2.10 baseline on a clean
  real-tick run. (The original "$1000 -> $8970 / 797%" header was suspected to
  be curve-fit / non-reproducible.)
- **Change made:** **None** — stock GaganEA v2.10, default inputs
  (Risk_Percent=6.0, StopLoss_Pips=2500, T1/T2/T3 800/1200/2000, all patterns on).
- **Backtest config:**
  - Symbol / timeframe: XAUUSD / M5 (tester Period M1)
  - Date range: 2026.03.01 – 2026.09.11 (full ~6 months)
  - Deposit: 1000 USD
  - Leverage: 1:500
  - Broker: Fusion Markets (Demo, Hedge)
  - Modelling: Every tick based on real ticks (Model 4)
- **Key metrics:**
  - Net profit: **-387.57** (loses money)
  - Max / Relative drawdown %: **41.09%** (target is < 15%)
  - Profit factor: **0.62**
  - Win rate: 52.27%
  - Total trades: 2204
  - Avg win / avg loss: +0.55 / -0.89 (reward:risk upside-down)
  - Sharpe: -5.00 ; Recovery factor: -0.92
- **Diagnosis:** VERDICT **NOT SUITABLE**. Negative net profit; 41% DD (serious,
  way over the 15% goal); PF 0.62 (weak edge). The reported 797% does NOT
  reproduce. Story from the data: overtrades (~100/day on M5 gold -> cost bleed),
  winners smaller than losers, and 6% risk + position stacking drives the huge DD.
- **Next step (Round 2):** Attack survival first — cut overtrading (stricter,
  higher-quality entry filters), fix reward:risk (let winners run / tighten the
  wide 2500-pt SL relative to targets), and cut Risk_Percent to slash DD. Aim:
  profitable with DD < 15%, even if modest, before pushing return.
- **Report file:** reports/round01_20260913.html

> Iteration note: switching to direct-to-`main` commits (no per-round PRs) and
> Windows Task Scheduler so the loop runs hands-off. Backtest window temporarily
> shortened to the last ~1 month (2026.08.11–2026.09.11) for fast iteration;
> restore the full 6-month window for robustness checks once a version looks good.
