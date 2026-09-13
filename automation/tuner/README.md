# GaganEA auto-tuner

A small, stdlib-only Python auto-tuner that grinds GaganEA's numeric inputs
toward the best risk-adjusted backtest score, one backtest at a time, and keeps
the best version it has seen. It runs on YOUR Windows PC as part of a continuous
loop that compiles the EA, runs the MT5 Strategy Tester, analyzes the report,
proposes the next parameters, and commits the result.

> READ THE CAVEATS at the bottom before you trust anything this produces. In
> short: it optimizes NUMBERS, not strategy logic; it CANNOT create a positive
> edge that is not already there; and continuous tuning on the short window
> WILL overfit unless you validate on the full window.

Cross-reference: `automation/SETUP.md` (how to configure the machine paths,
find your MT5 data folder, and the exact tester settings) and
`ITERATION_LOG.md` (the per-round history and the Round 3 entry that introduces
this tuner).

--------------------------------------------------------------------------------

## What the tuner does

One invocation of `automation/tuner/tuner.py` is ONE idempotent step:

1. Ingest the latest backtest result (a `.summary.json`, a raw `.html` parsed
   via `tools/analyze_report.py`, or the newest `reports/tuner/*.summary.json`).
2. Score the CURRENT parameter set's metrics and update the persistent state:
   if this result is the best seen so far, record it as the new best; append a
   history record with the accept/reject decision.
3. Propose the NEXT parameter vector using a simple, explainable local search
   (coordinate descent, one parameter per step) plus a rule-based nudge layer
   keyed off the diagnosis (see below).
4. Validate the proposal (clamp to bounds, snap to step, repair ordering) so an
   invalid EA is NEVER written.
5. Write the proposal into `GaganEA.mq5` (the `input` default literals), update
   `automation/tuner/current_params.json`, write a log line, and persist state.

The continuous loop (`automation/run_tuner_loop.ps1`) wires this into:

```
score -> local search + rule nudges -> rewrite mq5 inputs -> recompile
      -> backtest -> analyze -> ingest -> repeat
```

back to back, with no gap between iterations.

--------------------------------------------------------------------------------

## Scoring rule (authoritative)

Defined in `automation/tuner/scoring.py` as a single, editable `score(metrics)`
function. The rule:

- MAXIMIZE net profit, SUBJECT TO a HARD relative-drawdown ceiling of 15%.
- Any candidate with relative drawdown > 15% ALWAYS ranks below ANY candidate
  with drawdown <= 15%. This is a strict two-tier rule, not a soft penalty:
  the over-ceiling tier is always below the compliant tier.
- Among compliant (drawdown <= 15%) candidates: higher net profit wins, with
  profit factor as a small tiebreaker.
- Fewer than 30 trades is treated as statistically meaningless and is penalized
  (a per-missing-trade penalty), so the tuner does not chase a lucky handful of
  trades.
- Missing or unparseable metrics are treated as worst-case, so a broken report
  can never look like a winner.

The ceiling is the named constant `MAX_RELATIVE_DD_PCT = 15.0`. Edit that one
constant to change the drawdown ceiling.

--------------------------------------------------------------------------------

## Tunable parameter space

Defined in `automation/tuner/params.py`. Each parameter maps to the EXACT
`GaganEA.mq5` input name. Bounds and steps are grounded in the v2.11 defaults.
On gold, the `*_Pips` inputs are POINTS.

| Parameter                | Type   | Min   | Max   | Step | v2.11 default |
|--------------------------|--------|-------|-------|------|---------------|
| Risk_Percent             | double | 0.25  | 2.0   | 0.25 | 1.0           |
| Min_EMA_Distance         | int    | 100   | 1200  | 50   | 400           |
| Min_Trade_Distance       | int    | 100   | 1500  | 50   | 500           |
| StopLoss_Pips            | int    | 400   | 3000  | 50   | 1000          |
| T1_Pips                  | int    | 100   | 2000  | 50   | 500           |
| T2_Pips                  | int    | 200   | 2500  | 50   | 1000          |
| T3_Pips                  | int    | 300   | 3000  | 50   | 1800          |
| T1_ClosePercent          | double | 10.0  | 90.0  | 1.0  | 33.0          |
| T2_ClosePercent          | double | 10.0  | 90.0  | 1.0  | 50.0          |
| Entry_Cooldown_Bars      | int    | 0     | 20    | 1    | 3             |
| Max_Concurrent_Positions | int    | 1     | 5     | 1    | 2             |

Ordering constraint (always repaired before a write):
`T1_Pips < T2_Pips < T3_Pips <= StopLoss_Pips`.

Rule-based nudges (in addition to plain coordinate descent):

- Drawdown > 15%: cut `Risk_Percent`, widen `Min_EMA_Distance` and
  `Min_Trade_Distance`.
- Overtrading (very high trade count): widen the `Min_*` distances and raise
  `Entry_Cooldown_Bars`.
- Profit factor < 1: tighten `StopLoss_Pips` toward the targets and lower
  `T1_Pips` to shift the reward:risk ratio.

--------------------------------------------------------------------------------

## Run ONE manual iteration FIRST (strongly recommended)

Before you start the infinite loop, do a single manual pass and eyeball it:

1. Compile and run ONE backtest of the current `GaganEA.mq5` in MetaEditor /
   the MT5 Strategy Tester (or one pass of `run_backtest_loop.ps1`).
2. Analyze it: `python3 tools/analyze_report.py <the report>.html`
3. Run the tuner once, dry, to see what it WOULD do without touching anything:

   ```
   python3 automation/tuner/tuner.py --summary-json reports/tuner/iter0001.summary.json --dry-run
   ```

   Then, if it looks sensible, run it for real (drop `--dry-run`) so it writes
   the next params into `GaganEA.mq5` and updates the state.

Only after that dry run looks reasonable should you start the continuous loop.

--------------------------------------------------------------------------------

## First run note: the opening move widens the stop

Heads up about the VERY FIRST tuner write. The shipped v2.11 EA has
`T3_Pips = 1800` but `StopLoss_Pips = 1000`, which VIOLATES the tuner's ordering
rule `T1 < T2 < T3 <= StopLoss`. The tuner deliberately seeds its state with the
RAW live v2.11 vector (so the state file truthfully mirrors the compiled EA) and
only repairs the ordering at propose/write time. The consequence: `StopLoss_Pips`
is written as 1800 on the FIRST run (an 80% wider stop, a materially different
risk profile), and how it gets there depends on the ingested backtest.

On the real v2.11 baseline (`profit_factor` about 0.58, below 1) the `pf < 1`
rule FIRES on this first run, and its net effect on `StopLoss_Pips` is a two-step
story, NOT a pure legality repair:

1. The `pf < 1` nudge first tightens `StopLoss_Pips` DOWN (1000 -> 900) to shift
   the reward:risk ratio.
2. Ordering-repair then RAISES `StopLoss_Pips` up to 1800 so that
   `T3_Pips (1800) <= StopLoss_Pips` holds.

So the repair OVERRODE the nudge, and the net written value is 1000 -> 1800. A
diagnosis rule DID target `StopLoss_Pips`; the repair just won. The log is
honest about this:

- The tuner log line splits its delta into `delta=...` (nudge / coordinate-step
  moves whose proposed value survived validation) and `repair_delta=...` (values
  validate changed to satisfy bounds / step / ordering). On the first run
  `StopLoss_Pips` shows up in `repair_delta` (final written value 1800), and the
  `notes=` field carries a `repair overrode nudge: StopLoss_Pips` note, NOT a
  "not a nudge" note, precisely because the `pf < 1` rule did nudge it.
- The `ordering/bounds repair (not a nudge): ...` note is reserved for
  PURE-repair params: ones validate changed while NO nudge or coordinate step
  touched them. If the `pf < 1` rule does not fire (a report with PF >= 1),
  `StopLoss_Pips` is a pure repair on the first write and would appear under
  that note instead.

Scoring and validation behavior are unchanged; this is transparency only. If you
would rather keep the live 1000 stop, edit `GaganEA.mq5` so the seeded ordering
is already legal (for example lower `T3_Pips` to `<= 1000`) BEFORE the first run,
or accept the wider stop as the tuner's legal starting point.

--------------------------------------------------------------------------------

## Start / stop the continuous loop

START (Windows):

- Double-click `automation/run_tuner_loop.bat`, or
- Run `automation\run_tuner_loop.ps1` in PowerShell.

Optional switches:

- `-MaxIterations 50` stops cleanly after 50 cycles (0 = run forever, default).
- `-TunerHtmlKeep 30` keeps the newest 30 full HTML reports (default 20).

The loop runs back to back with NO sleep gap. Each cycle: `git pull`, copy the
EA into MT5, compile (with compile-log parsing), run the tester headless, copy
the report to `reports/tuner/iterNNNN.html`, analyze it, invoke the tuner, prune
old HTMLs, and `git add / commit / push` the report + summary +
`tuner_state.json` + `current_params.json` + `GaganEA.mq5`.

STOP the loop by any of:

- Closing the console window.
- Pressing Ctrl+C in the window.
- Ending the scheduled task (if you started it via Windows Task Scheduler).

A single bad cycle (compile error, missing report, analyzer failure) logs a
warning and moves on to the next cycle; it does NOT kill the loop. Only a fatal
CONFIGURATION error (bad paths, missing Python) stops it.

--------------------------------------------------------------------------------

## Iteration indexing and report history

`automation/tuner/tuner_state.json` holds `"iteration"` = the number of results
ingested so far. The loop reads that counter at the top of each cycle and names
the cycle's report `iterNNNN` where NNNN = counter + 1 (the index the tuner
stamps on the history record when it ingests this result). So
`reports/tuner/iterNNNN.html` maps 1:1 to the tuner history record with
`iteration = NNNN` and to the parameters that produced it. Because the counter
lives in the tracked state file, the naming is RESTART-SAFE: stop and restart
the loop and it picks up where it left off.

Tuner-failed cycles get a DISTINCT name (no overwrite). The state counter is
bumped only when the tuner INGESTS a result successfully. If a cycle produces
and commits a report but the tuner call then exits non-zero, the counter stays
at N, so the next cycle would recompute the SAME `iter(N+1)` index. To stop that
next cycle from silently overwriting the just-committed artifact, the loop
renames a tuner-failed cycle's report (and its `.summary.json`) to
`iterNNNN_notuned_<timestamp>` before committing, and commits under that name.
So a `_notuned_` report in `reports/tuner/` marks a cycle whose backtest was
captured but whose tuner step failed (no history record, no new params); the
plain `iterNNNN` name is then free for the next cycle to use cleanly.

Report retention:

- Every `reports/tuner/iterNNNN.summary.json` is kept FOREVER (they are tiny and
  are the permanent, complete history of every iteration).
- Only the newest N full `iterNNNN.html` reports are kept (N = `TunerHtmlKeep`,
  default 20). The loop `git rm`s the older HTMLs each cycle so the repository
  does not accumulate unbounded large HTML files. If you want the full HTML for
  a pruned iteration, re-run that parameter set (its params are in the history).

--------------------------------------------------------------------------------

## Reading the state and logs

- `automation/tuner/tuner_state.json` (TRACKED): the source of truth. Contains
  `iteration`, `current` (the vector now in the EA), `best` (best params +
  metrics + score, or null), and `history` (one record per iteration with the
  param delta, a metrics summary, the score, the accept/reject flag, and the
  best-so-far score).
- `automation/tuner/current_params.json` (TRACKED): a human-readable marker of
  the parameter set currently written into the EA, with a timestamp.
- `automation/tuner/logs/tuner.log` (IGNORED): a human-readable, appended
  per-iteration line (score, accepted?, best, param delta, and the nudge notes).
  The logs directory is git-ignored on purpose; the state file is the durable
  record.

--------------------------------------------------------------------------------

## Reset

To discard the tuning history and re-seed the state from whatever is currently
compiled into `GaganEA.mq5`:

```
python3 automation/tuner/tuner.py --reset
```

Add `--dry-run` to preview without writing. Reset re-initializes
`tuner_state.json` from the live EA input values (no best yet) and exits.

--------------------------------------------------------------------------------

## HONEST CAVEATS (read these)

1. It optimizes NUMBERS, not strategy LOGIC. The tuner only changes input
   defaults; it cannot change how the EA decides to enter or exit. If the
   underlying edge is negative it CANNOT manufacture a positive one. As of
   v2.11 the profit factor is about 0.58 (below 1), meaning the strategy loses
   money on average. Tuning can minimize the bleed and hold drawdown down, but
   turning PF above 1 requires STRUCTURAL changes to the entry/exit logic, not
   parameter grinding.

2. Continuous tuning on the shortened ~1-month window WILL overfit. The tester
   window in `automation/backtest_template.ini` is currently a fast ~1-month
   window (`FromDate=2026.08.11`). Grinding thousands of iterations against one
   short window fits the noise of that window. Before you TRUST any reported
   "best", VALIDATE it on the FULL 6-month window (`FromDate=2026.03.01`): edit
   the template's `FromDate`, run the best params once, and confirm the result
   holds up. Treat any best that does not survive the 6-month window as
   overfit, not real.

3. It is a LOCAL optimizer. Coordinate descent plus rule nudges is a hill-climb.
   It can get stuck in a local optimum and will not explore the whole parameter
   space. It keeps the best it happens to find, not a proven global best.
