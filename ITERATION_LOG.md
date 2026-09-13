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

## Round 1 — <baseline measurement>  (YYYY-MM-DD)

- **Hypothesis:** <e.g. establish the true v2.10 baseline metrics on XAUUSD M5>
- **Change made:** <none / EA inputs adjusted>
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
- **Report file:** reports/round01_YYYYMMDD.html
