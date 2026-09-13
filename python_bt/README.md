# python_bt - in-sandbox XAUUSD research backtester

## 1. What this is

`python_bt` is a fast, stdlib-only tick backtester for XAUUSD (gold) strategies
that runs entirely inside the sandbox, with NO MetaTrader 5, NO pip, and NO
external network. It exists so a strategy can be developed, measured, and ranked
in seconds without a Windows/MT5 round-trip.

It is a FAST SEARCH rig, not a verdict machine. MT5 is the SOURCE OF TRUTH. Any
config or strategy that looks good here MUST be validated on a real MT5 run of
the same period before it is trusted. See section 7.

The live trading artifact is `GaganEA.mq5` at the repo root; this Python code is
a faithful (not byte-exact) port of its core plus a research harness around it.

## 2. Layout

Every module and its role:

- `python_bt/config.py` - instrument and account constants (point size, tick
  size, tick value, contract size, commission, deposit, leverage). Every value
  is a PARITY ASSUMPTION flagged CONFIRM (see section 5).
- `python_bt/loader.py` - `iter_ticks(path, date_from, date_to, max_ticks)`;
  streams the tab-separated tick CSV line by line (never loads the 526 MB file
  into memory), with date-range slicing and a tick cap.
- `python_bt/bars.py` - `iter_bars(...)` and `floor_ts(...)`; aggregates ticks
  into M5 bars (OHLC from tick mids, plus the bar's last bid/ask for fills).
- `python_bt/broker.py` - `Broker` and `Position`; simulates fills (buy at ask,
  sell at bid), SL/TP firing on quote cross, partial/full closes, SL
  modification (breakeven/trailing), commission per lot per side, and running
  equity/drawdown.
- `python_bt/metrics.py` - `compute_metrics(...)`; turns the broker ledger and
  equity curve into the analyzer metrics schema (see section 8).
- `python_bt/scoring_bridge.py` - re-exports `score()` from
  `automation/tuner/scoring.py` (the single source of truth for ranking; the
  hard 15% relative-DD ceiling). Not reimplemented here.
- `python_bt/engine.py` - `Engine` and `Context`; the event loop that feeds
  quotes to the broker and callbacks to the strategy in tick or bar mode, then
  returns `{metrics, score, params, meta}`.
- `python_bt/indicators.py` - `EMA`, `ATR`, `RSI`, `H1Ema`; streaming indicator
  state used by the strategy.
- `python_bt/strategy/base.py` - `Strategy` base class, `STRATEGY_REGISTRY`,
  `@register`, `get_strategy(name)`.
- `python_bt/strategy/gagan.py` - `GaganStrategy` (NAME `gagan`); the faithful
  port of GaganEA v2.12's entry/exit core.
- `python_bt/runner.py` - the runner CLI: run one strategy/param set (or A/B
  `--compare` two), print metrics + score + diagnosis, optionally write JSON.
  Exposes `run_once(...)`, reused by the research harness.
- `python_bt/research.py` - the RESEARCH LOOP harness: run many configs, rank by
  score, print a leaderboard, and persist a results JSON (see sections 3-4).
- `python_bt/tests/` - the stdlib unittest suite for all of the above.
- `data/extract.py` - regenerates the tick CSV from the tracked split chunks.
- `data/README.md` - data provenance and the regenerate step.

## 3. How to run

### Regenerate the tick CSV (once per fresh checkout)

The 526 MB CSV is gitignored and rebuilt from the tracked chunks:

```
python3 data/extract.py
```

This writes `data/XAUUSD_202607011100_202609011203/XAUUSD_202607011100_202609011203.csv`.

### Run one strategy (runner CLI)

```
python3 -m python_bt.runner --strategy gagan --to 2026.07.20 --mode bar
python3 -m python_bt.runner --params '{"Risk_Percent":0.5}' --json out.json
python3 -m python_bt.runner --compare --params '{}' --params '{"Risk_Percent":2.0}' --to 2026.07.20
```

Flags: `--data` (CSV path), `--strategy` (registry name), `--params` (inline
JSON or `@file.json`), `--from` / `--to` (YYYY.MM.DD), `--mode` (`bar` fast or
`tick` accurate), `--max-ticks` (smoke cap), `--json` (write result), and
`--compare` for an A/B run.

`--from` and `--to` name whole days: `--from` starts at 00:00:00 of its day and
`--to` is INCLUSIVE of its entire day (through 23:59:59.999999), so
`--to 2026.09.01` keeps every tick on Sep 1 rather than only the first instant.

### Run the research loop (batch + leaderboard)

```
python3 -m python_bt.research --baseline --to 2026.07.20 --mode bar
python3 -m python_bt.research --configs @candidates.json --top 5
python3 -m python_bt.research --configs @candidates.json --max-ticks 200000
```

- `--configs @file.json` takes a JSON list of `{strategy, params, label}`
  objects. Fields may be omitted: `strategy` defaults to `gagan`, `params` to
  `{}`, and `label` is synthesized. With no `--configs`, a small built-in set
  (gagan defaults plus two risk variations) runs.
- `--baseline` always prepends the `GaganStrategy` defaults as a comparison
  anchor.
- `--top N` shows only the best N rows in the printed leaderboard (the full set
  is still persisted).
- `--from` / `--to` / `--mode` / `--max-ticks` mirror the runner CLI and apply
  to the shared data slice all configs run on.

Example `candidates.json`:

```json
[
  {"strategy": "gagan", "params": {}, "label": "baseline"},
  {"strategy": "gagan", "params": {"Risk_Percent": 0.5}, "label": "risk-half"},
  {"strategy": "gagan", "params": {"Min_EMA_Distance": 300}, "label": "wider-ema-gate"}
]
```

### Where results are written

The harness writes a small JSON to `reports/pybt/<timestamp>.results.json`
(the directory is created on demand). Results are tiny (a few KB), so committing
one is harmless. This path is deliberately a NEW subdirectory: the repo's
`.gitignore` ignores `reports/*.summary.json` (files directly under `reports/`),
so a `reports/pybt/*.results.json` file does not match that pattern and is not
accidentally swept up. Use `--no-write` to print only, or `--results-dir` to
pick another location.

The results JSON contains `{generated_at, run, leaderboard}`, where
`leaderboard` is the full ranked list of `{label, strategy, params, metrics,
score, meta, diagnosis}` rows the agent can read back.

### Add a new strategy

1. Create a module under `python_bt/strategy/`, subclass `Strategy`, set a
   unique `NAME`, implement `default_params()` and `on_bar(self, bar, ctx)`
   (and optionally `on_tick(self, tick, ctx)`), and decorate the class with
   `@register`.
2. Make sure it is imported (add it to `python_bt/strategy/__init__.py` so it
   self-registers).
3. Add a config entry referencing it by `NAME` to your `candidates.json` and
   re-run `python3 -m python_bt.research --configs @candidates.json`.

## 4. The DEVELOP -> MEASURE -> RANK -> ITERATE loop

This rig turns strategy research into a tight in-sandbox loop the agent drives
directly:

1. DEVELOP - edit a `candidates.json` (change params, add labels) or add a new
   `Strategy` subclass and register it.
2. MEASURE - run `python3 -m python_bt.research` on a data slice. Each config is
   replayed through the same `Engine` the runner CLI uses, so results are
   directly comparable.
3. RANK - configs are sorted by `score()` descending. Because `scoring.py`
   pushes any config over the 15% relative-DD ceiling below every compliant
   one, a reckless-but-profitable config always sinks to the bottom.
4. ITERATE - read the persisted results JSON (and the printed leaderboard +
   per-config diagnosis verdict), form a new hypothesis, edit the configs or add
   a strategy, and re-run.

The agent participates by reading the leaderboard/results JSON, proposing the
next config or strategy change, running the harness again, and repeating until
a promising candidate emerges - then handing that candidate to MT5 for the
authoritative check (section 7).

## 5. Parity assumptions (each flagged CONFIRM)

These live in `python_bt/config.py` and the strategy port. NONE are
broker-verified in the sandbox; each must be CONFIRMED against the user's
broker (Fusion Markets) and MT5 symbol spec before results are trusted.

- POINT_SIZE = 0.01 - CONFIRM. Detected from 2-decimal XAUUSD quotes
  (SYMBOL_POINT).
- TICK_SIZE = 0.01 - CONFIRM. Smallest tradable price change
  (SYMBOL_TRADE_TICK_SIZE).
- CONTRACT_SIZE = 100 oz per 1.0 lot - CONFIRM (SYMBOL_TRADE_CONTRACT_SIZE).
- TICK_VALUE = 1.00 USD per TICK_SIZE per 1.0 lot - CONFIRM
  (SYMBOL_TRADE_TICK_VALUE). Derived from 100 oz: a 0.01 move = 1.00 USD per
  lot. Drives P&L parity directly.
- COMMISSION_PER_LOT_PER_SIDE = 3.5 USD - CONFIRM vs the user's Fusion tier.
  Charged on both entry and exit.
- INITIAL_DEPOSIT = 1000 USD - CONFIRM vs the deposit used in MT5 tests.
- LEVERAGE = 1:500 - CONFIRM. Not enforced as a margin constraint here.
- SPREAD SOURCE = per-tick ask - bid, taken directly from each tick - CONFIRM
  the data spread matches live conditions.
- FILL TIMING - buy at the current ask, sell at the current bid. In tick mode
  fills use the current tick; in bar mode a single closing quote per bar is
  used, so intrabar fills are approximated at bar granularity (see section 6).
- REQUOTES = none modeled - CONFIRM acceptable.
- SLIPPAGE = none modeled (fills at the quoted side) - CONFIRM acceptable.
- PARTIAL CLOSES / BREAKEVEN / TRAILING - tiered partials T1/T2/T3 close
  `T1_ClosePercent`, then `T2_ClosePercent` of the remaining volume, then the
  rest, when profit in points crosses each tier threshold (ATR-scaled when
  enabled else fixed `Tx_Pips`); breakeven moves SL to entry after T1;
  individual trailing steps SL by `Trail_Step_Pips` after T2. This mirrors the
  EA's percent-of-current-volume logic but is CONFIRM vs exact MT5 fill
  sequencing.
- INDICATOR SEEDING - EMA/ATR/RSI are seeded with an SMA of the first n samples;
  MT5's exact seed is not byte-specified. CONFIRM tolerance.
- H1 HTF EMA - the HTF EMA200 is built from hourly closes sampled off the M5
  tick stream (the last M5 mid close of each hour), not a broker H1 series.
  CONFIRM tolerance.

## 6. Known differences vs MT5

- BAR-CLOSE vs INTRABAR TIMING - entries are decided on the just-closed M5 bar;
  in bar mode SL/TP and tier management run only at the bar's closing quote, so
  intrabar stop/target/tier hits are approximated. Use tick mode for
  tick-accurate fills.
- INDICATOR SEEDING - the SMA seed differs from MT5's internal warm-up, so early
  indicator values can diverge slightly.
- H1 EMA CONSTRUCTION - built from M5-sampled hourly closes rather than a real
  broker H1 series.
- SWAP / ROLLOVER FINANCING - not modeled. Overnight swap is ignored.
- MARGIN / LEVERAGE - leverage is a documented constant but margin is not
  enforced; positions are never rejected for insufficient margin.
- SPREAD REALISM - spread is exactly the data's ask-bid; live spread widening
  around news/rollover is only present to the extent the recorded ticks show it.
- NEWS GAPS - no synthetic gaps or halts are injected beyond what the ticks
  contain.
- MID-BASED BARS - OHLC bars are built from tick mids; trend/distance
  comparisons use the mid where the EA reads bid, though fills still use real
  bid/ask.
- WARM-UP vs FLAT - the HTF EMA200 needs ~`EMA_Period_HTF` hours of stream to
  warm up (about 200 hours by default), so a slice shorter than that produces
  zero trades because no entry can fire yet. This is NOT a flat/losing strategy.
  The engine records a warm-up diagnostic in `result['meta']['warmup']`
  (`warmed_up`, `entry_ever_eligible`, `bars_seen`, `htf_warmup_bars`, `note`);
  the runner prints a `NOTE:` line and the research leaderboard shows
  `insufficient warm-up` (with the per-row note beneath the table) whenever a
  config had zero trades AND never finished warming up. Use a slice of at least
  ~200 hours (the full ~1500-hour window warms fine) to get meaningful trades.

## 7. MT5 is the source of truth

Python results MUST be validated against a real MT5 run of the same period
before being trusted. The Python engine is for FAST SEARCH: it explores many
configs cheaply in the sandbox. It is NOT authoritative. Because parity is
unverifiable in the sandbox (no MT5, no broker symbol spec), treat every Python
number as a hypothesis to confirm, not a result to report. Promote a candidate
to MT5, run it on the same window on the user's PC, analyze the HTML report with
`tools/analyze_report.py`, and only then treat the outcome as real.

## 8. How metrics and score map across the MT5 and Python paths

The Python engine emits the SAME metrics schema that `tools/analyze_report.py`
produces from an MT5 HTML report (`summary['metrics']`): `total_net_profit`,
`gross_profit`, `gross_loss`, `profit_factor`, `expected_payoff`,
`recovery_factor`, `sharpe_ratio`, drawdown fields including
`relative_drawdown_pct` and `maximal_drawdown_money`, `total_trades`,
`total_deals`, `win_rate_pct`, and the largest/average/consecutive trade fields.
Because the key names match, the same `automation/tuner/scoring.py::score()`
consumes both the Python metrics and the MT5-analyzer metrics, so a config's
score is directly comparable across the two paths. The research harness also
attaches the analyzer's `build_diagnosis` / `diagnosis_verdict` output per
config, using the same vocabulary and thresholds as the MT5 report path.
