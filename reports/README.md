# Backtest Reports

This folder holds MT5 Strategy Tester HTML backtest reports for **GaganEA**
(XAUUSD, M5, Fusion Markets) and the JSON summaries produced by the analyzer.

The loop is human-in-the-loop:

1. You run a backtest in MT5 on your local PC and export the HTML report.
2. You drop the HTML report in this folder using the naming convention below.
3. You run the analyzer (`tools/analyze_report.py`) to get a metrics summary
   and a conservative-drawdown **DIAGNOSIS**, plus a `.summary.json`.
4. Findings feed the next round in `../ITERATION_LOG.md`.

> A fully-automatic in-sandbox backtest loop is not possible (there is no MT5,
> no MQL5 compiler, and no market data in the build environment). This tooling
> is the measurement half of the loop; the backtest half runs on your PC.

---

## 1. How to export the HTML report from MT5

### Newer MetaTrader 5 Strategy Tester

1. Open MetaTrader 5 and press **Ctrl+R** (or **View → Strategy Tester**).
2. In the **Settings** tab choose:
   - **Expert:** `GaganEA`
   - **Symbol:** `XAUUSD`
   - **Period (timeframe):** `M5`
   - **Date range**, **Deposit**, and **Leverage** as desired.
   - Modelling: **Every tick based on real ticks** is recommended for gold.
3. Click **Start** and wait for the run to finish.
4. Open the **Backtest** (results) tab, **right-click anywhere in the report
   area**, and choose one of:
   - **Report → Open XML/HTML** (newer builds), or
   - **Save as Report…**
5. Save the file as **HTML** (`.html`). If MT5 offers `.xlsx`/`.xml` only, pick
   the HTML option; the analyzer parses the HTML layout.

### Older "ReportTester" layout

Older builds produce a single-page **ReportTester** HTML. The analyzer supports
this layout too (different whitespace, comma thousands separators, and combined
drawdown cells). Just save it as `.html` and analyze it the same way.

---

## 2. Filename convention

Save reports as:

```
reports/roundNN_YYYYMMDD.html
```

- `NN` = the iteration/round number (matches `../ITERATION_LOG.md`), e.g. `01`.
- `YYYYMMDD` = the date you ran the backtest.

Examples:

```
reports/round01_20240115.html
reports/round02_20240122.html
```

The analyzer writes a JSON summary next to each report:

```
reports/round01_20240115.summary.json
```

---

## 3. How to run the analyzer

From the repo root (`happyBOT/`):

```bash
# analyze a single report
python3 tools/analyze_report.py reports/round01_20240115.html

# analyze several at once (shell expands the glob)
python3 tools/analyze_report.py reports/round01_*.html

# print only, do not write JSON
python3 tools/analyze_report.py reports/round01_20240115.html --no-json

# collect all JSON summaries in one directory
python3 tools/analyze_report.py reports/round0*.html --json-dir reports/summaries
```

Requirements: **Python 3** standard library only (no `pip install` needed).

The analyzer prints a metrics block and a `DIAGNOSIS` section tuned for the
goal *"maximize return while keeping drawdown conservative"*. It flags:

- relative/maximal drawdown above conservative thresholds (warn ≥ 20%,
  serious ≥ 35%),
- profit factor below ~1.2 (weak edge),
- low trade count (< 100 = statistically weak / overfit risk),
- worst consecutive-loss streak as a fraction of net profit (risk-of-ruin),
- recovery factor when present.

Thresholds live as named constants at the top of `tools/analyze_report.py` and
are easy to tune.

---

## 4. Gold / XAUUSD note (important when reading configs)

Gold on MT5 is quoted with **2 or 3 digits**. GaganEA computes
`pip = point * 10` for 3/5-digit symbols, so the EA's `*_Pips` inputs are
effectively **POINTS**, not classic pips. For example `StopLoss_Pips = 2500`
means **2500 points**. Keep this in mind when interpreting metrics or adjusting
inputs between rounds.

---

## 5. `samples/`

`samples/` contains **synthetic** MT5-style reports (clearly labelled, not real
backtests) used to verify the analyzer:

- `samples/sample_report.html` — newer Strategy Tester layout.
- `samples/sample_report_old.html` — older ReportTester layout.

Verify the toolchain any time with:

```bash
python3 tools/analyze_report.py reports/samples/sample_report.html
```
