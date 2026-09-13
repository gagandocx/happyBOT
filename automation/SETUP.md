# GaganEA Backtest Automation — Setup & Operation

This folder automates the GaganEA improvement loop on **your local Windows PC**:

> **compile → headless backtest → analyze → commit/push → repeat**

so you (or Windows Task Scheduler) can keep refining the strategy and
re-backtesting on XAUUSD until it hits the goal: **under 15% drawdown** on the
last few months of data.

Files in this folder:

| File | What it is |
| --- | --- |
| `run_backtest_loop.ps1` | The main harness (all the logic). |
| `run_backtest_loop.bat` | Double-click wrapper that launches the `.ps1`. |
| `backtest_template.ini` | MT5 Strategy Tester config template (your exact settings). |
| `SETUP.md` | This guide. |
| `logs/` | Per-run logs (git-ignored; created on first run). |

---

## 1. Overview: the loop, and the sandbox-vs-PC split

Each round the harness performs, in order:

- **(a)** `git pull` the repo
- **(b)** copy `GaganEA.mq5` into MT5's `MQL5\Experts` folder
- **(c)** compile it headlessly with `metaeditor64.exe` and **parse the compile
  log** — it aborts on any compile error (the compiler's *exit code* is
  unreliable across MT5 builds, so we read the log instead)
- **(d)** fill `backtest_template.ini` and run `terminal64.exe` headlessly,
  waiting for it to finish (`ShutdownTerminal=1` makes the terminal exit on its
  own)
- **(e)** copy the report MT5 wrote to `reports\roundNN_YYYYMMDD.html`
- **(f)** best-effort, non-fatal: `python tools\analyze_report.py <report>`
- **(g)** `git add` / `commit` / `push` the report (and any `.summary.json`),
  skipping cleanly if nothing changed

**Important split:** the analysis tooling (`tools/analyze_report.py`) can run
anywhere, but the *backtest itself* needs MetaTrader 5, the MQL5 compiler, and
market data — which only exist on your Windows PC. **This harness was authored
in a Linux sandbox and could NOT be executed there** (no MT5, no MQL5 compiler,
no PowerShell). Please treat your first run as a manual shakedown: run it once
by hand and watch the console + log before scheduling it hands-off.

---

## 2. Prerequisites

- **MetaTrader 5 installed and logged in** to your **FusionMarkets-Demo**
  account (Hedge, 1000 USD balance). Open MT5 once and log in before automating.
- **git installed** and **authenticated to push** to
  `github.com/gagandocx/happyBOT` (see the Git-auth note in section 9).
- **Python 3** — *optional*. Only needed for the automatic analysis in step (f).
  If it is missing the harness logs a friendly note and carries on.
- **Windows PowerShell 5.1** (built into Windows 10/11) or PowerShell 7.

---

## 3. Find your MT5 paths

### 3a. The two executables (in the MT5 **install** dir)

Right-click your MT5 desktop shortcut → **Open file location**. That folder
holds both:

- `terminal64.exe`
- `metaeditor64.exe`

Typical for Fusion Markets:
`C:\Program Files\FusionMarkets MetaTrader 5\`.

### 3b. The per-user **data** folder (the hashed folder)

This is **not** the install dir. In MT5, go to **File → Open Data Folder**. The
window that opens is your data folder — its path looks like:

```
C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\<HASH>
```

where `<HASH>` is a long hex string (e.g. `D0E8209F77C8CF37AD8BF550E51FF075`).
This is the folder you want because it contains the `MQL5\` subtree (including
`MQL5\Experts`) and your account. If you have several `Terminal\<HASH>` folders,
the correct one is **the one that contains `MQL5\Experts`** and matches the
terminal you log into. `File → Open Data Folder` always opens the right one.

> Note: portable installs put the data folder next to `terminal64.exe` instead.
> If so, use that path for `MT5DataDir`.

---

## 4. Fill the configuration block

Open `run_backtest_loop.ps1` and edit the `$Config` block near the top. Every
machine-specific path lives there and nowhere else:

| Key | Set to | From |
| --- | --- | --- |
| `MetaEditor64Exe` | full path to `metaeditor64.exe` | section 3a |
| `Terminal64Exe` | full path to `terminal64.exe` | section 3a |
| `MT5DataDir` | the hashed `...\Terminal\<HASH>` folder | section 3b |
| `ExpertsSubDir` | `MQL5\Experts` (rarely changes) | — |
| `RepoDir` | your local `happyBOT` checkout (contains `GaganEA.mq5`) | your clone |
| `ExpertName` | `GaganEA` (the compiled EA name, no extension) | — |
| `GitBranch` | the branch you work on (default `round0-backtest-tooling`) | — |
| `TesterTimeoutSec` | safety timeout for one backtest (default 3600) | — |

**Placeholders are filled automatically.** You do **not** edit
`backtest_template.ini`'s `__EXPERT_PATH__` / `__REPORT_PATH__` tokens by hand —
the script substitutes them at runtime (`__EXPERT_PATH__` → `ExpertName`,
`__REPORT_PATH__` → the report path derived from `RoundNumber` + `RunDate`) and
writes a runtime copy into `automation\logs\`.

---

## 5. Running it

**Double-click** `run_backtest_loop.bat` — it launches the `.ps1` with
`-ExecutionPolicy Bypass -NoProfile`, forwards any arguments, and pauses at the
end so the window stays open.

Or run the script directly in PowerShell:

```powershell
# Round 1, today's date:
.\run_backtest_loop.ps1

# Specific round:
.\run_backtest_loop.ps1 -RoundNumber 3

# Specific round AND date (YYYYMMDD) — reproduce an older run:
.\run_backtest_loop.ps1 -RoundNumber 3 -RunDate 20260911
```

`-RoundNumber` and `-RunDate` drive the report filename
`reports\roundNN_YYYYMMDD.html` (`NN` is zero-padded, e.g. `round03`). `RunDate`
defaults to today.

**What you'll see:** each step is announced in the console (colour-coded
`STEP` / `WARN` / `ERROR`) and mirrored to a timestamped log at
`automation\logs\roundNN_YYYYMMDD_HHMMSS.log`. On success it ends with
`=== DONE ... ===` and exit code 0; a failed step prints a red `ERROR`, points
you at the log, and exits non-zero.

---

## 6. Scheduling it hands-off (Windows Task Scheduler)

### Command-line (schtasks) — daily at 02:00

Run in an **Administrator** Command Prompt (adjust the path):

```bat
schtasks /Create /TN "GaganEA Backtest Loop" /SC DAILY /ST 02:00 ^
  /TR "powershell.exe -ExecutionPolicy Bypass -NoProfile -File \"C:\Users\YOU\happyBOT\automation\run_backtest_loop.ps1\" -RoundNumber 1" ^
  /RL LIMITED /F
```

- `/SC DAILY /ST 02:00` — daily at 2 AM (see `schtasks /Create /?` for others).
- Point `-File` at *your* `.ps1` path; add `-RoundNumber` / `-RunDate` as needed.
- Prefer running the `.ps1` directly (not the `.bat`) for scheduled tasks — the
  `.bat`'s `pause` waits for a keypress that a background task never gets.

### GUI steps

1. **Start → Task Scheduler → Create Task…**
2. **General:** name it; select **Run whether user is logged on or not**.
3. **Triggers → New…:** e.g. **Daily**, set the time.
4. **Actions → New…:**
   - **Program/script:** `powershell.exe`
   - **Add arguments:**
     `-ExecutionPolicy Bypass -NoProfile -File "C:\Users\YOU\happyBOT\automation\run_backtest_loop.ps1" -RoundNumber 1`
5. **Conditions/Settings:** e.g. **Wake the computer to run this task** if you
   want overnight runs.
6. **OK** and enter your Windows password if prompted.

> The script must be able to `git push` unattended — set up a credential helper
> or PAT first (section 9).

---

## 7. Tester timeframe **M1** vs EA `Trade_Timeframe` **M5** (they differ on purpose)

These are two **independent** settings, and the combination is intended:

- **Tester `Period=M1`** (in `backtest_template.ini`) is the *Strategy Tester
  chart timeframe* — the modelling/tick granularity of the simulation. Using
  **M1** lets "Every tick based on real ticks" be reconstructed at the finest
  readily-available bar granularity, giving the most faithful fills for gold.
- **EA `Trade_Timeframe=M5`** is a **GaganEA input**. It is the timeframe the
  EA's own logic reads/trades on. **We do NOT change it**, and this harness does
  **not** set EA inputs at all.

So the tester steps through M1 fidelity while the EA still makes its decisions on
its M5 logic. `GaganEA.mq5` is left byte-for-byte unchanged.

---

## 8. Exact backtest settings baked into `backtest_template.ini`

These mirror your confirmed Fusion Markets Strategy Tester config:

| Setting | Value | `.ini` key |
| --- | --- | --- |
| Symbol | **XAUUSD** | `Symbol` |
| Tester timeframe (Period) | **M1** (tick granularity; see section 7) | `Period` |
| Modelling | **Every tick based on real ticks** (Model **4**) | `Model` |
| Date range (custom) | **2026.03.01 → 2026.09.11** | `FromDate` / `ToDate` |
| Forward test | **Off** | `ForwardMode=0` |
| Delays / execution | **Zero latency, ideal execution** | `ExecutionMode=0` *(build-dependent)* |
| Deposit | **1000 USD** | `Deposit` / `Currency` |
| Leverage | **1:500** | `Leverage=500` |
| Optimization | **Off** | `Optimization=0` |
| Visual mode | **Off** (headless) | `Visual=0` |
| Overwrite report | yes | `ReplaceReport=1` |
| Terminal exits after run | yes | `ShutdownTerminal=1` |

**Build-dependent keys.** MT5 has changed `[Tester]` key names across builds. If
a run misbehaves, double-check the spelling for *your* build:

- **`ExecutionMode` / `Delays`** — the zero-latency model. Some builds use a
  numeric `Delays` key instead of `ExecutionMode`. If neither takes effect, set
  "Zero latency, ideal execution" once in the Tester GUI (MT5 remembers it per
  terminal).
- **`ShutdownTerminal`** — most builds honour this; if your terminal does not
  self-close, the harness will hit its `TesterTimeoutSec` safety timeout.
- **`Model` codes:** `0`=every tick, `1`=1-minute OHLC, `2`=open prices,
  `4`=every tick based on real ticks (what we use).

`Expert` is a path relative to `MQL5\Experts` **without** the `.ex5` extension
(MT5 convention); `FromDate`/`ToDate` use `YYYY.MM.DD`. The script fills
`Expert` and `Report` from the placeholders — you never edit those by hand.

---

## 9. Troubleshooting

- **Compile errors** — the harness aborts step (c) and points at the compile log
  in `automation\logs\compile_*.log`. Open it, fix `GaganEA.mq5`, re-run. (Exit
  codes are unreliable, so the harness trusts the *log*, not the code.)
- **Report not found (step e)** — check `MT5DataDir` is the correct hashed
  folder (section 3b) and that MT5 actually finished the run. MT5 writes the
  report relative to its data root; if your build writes it elsewhere, note the
  path MT5 used and adjust. The log lists exactly which paths were checked.
- **Git auth failures (step g)** — set up a credential helper so pushes work
  unattended: `git config --global credential.helper manager` (Windows), or use
  a **Personal Access Token** as the password on first push and let Windows
  Credential Manager remember it. Never hard-code a token in these files.
- **"Nothing changed" commit** — expected if a re-run produced an identical
  report; the harness logs it and skips commit/push (not an error).
- **`git add ... failed` in step (g)** — the harness now checks each `git add`
  exit code and aborts if one fails (a silent failure previously let artifacts
  never reach the repo). The usual cause is a `.gitignore` rule shadowing the
  file. `reports/*.summary.json` is ignored by default, so the repo keeps a
  `!reports/round*.summary.json` negation (right after that rule) that lets the
  per-round summaries (`reports/roundNN_YYYYMMDD.summary.json`) stage cleanly.
  If you see this error, confirm that negation is still present in `.gitignore`
  (verify with `git check-ignore -v reports/round01_20260101.summary.json` —
  it should report the negation line, not the ignore line).
- **PowerShell execution policy** — the `.bat` already passes
  `-ExecutionPolicy Bypass` for that one launch, so you should not need to change
  the machine policy. If you run the `.ps1` directly and it's blocked, use the
  `.bat`, or run `powershell -ExecutionPolicy Bypass -File .\run_backtest_loop.ps1`.
- **Terminal never exits** — likely `ShutdownTerminal` isn't honoured on your
  build (section 8); the run stops at `TesterTimeoutSec`. Set it in the GUI once.

---

## 10. Human sanity-check each round (avoid overfitting)

A ~6-month sample (2026.03.01 → 2026.09.11) is short. It is easy to tune the EA
until it looks great on *this* window but fails out-of-sample. **Recommended:
eyeball each round yourself** before trusting it:

- Read the analyzer's **`DIAGNOSIS`** block (`tools/analyze_report.py`) — it
  flags drawdown above conservative thresholds, weak profit factor, low trade
  counts (overfit risk), and consecutive-loss streaks.
- Record the round in **`../ITERATION_LOG.md`** (hypothesis → change → result →
  next step) so the improvement trail is auditable.
- The target is **under 15% drawdown on XAUUSD** with a genuine, robust edge —
  not the biggest headline return. Prefer changes that hold up across the window
  over ones that only spike the total profit.
