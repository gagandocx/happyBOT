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

---

## Round 2 - Conservative rework (v2.11)  (pending next backtest)

- **Hypothesis:** Attack survival first. The Round 1 baseline lost money mainly
  because of three things: overtrading (~100 trades/day bleeds cost and enters
  low-quality signals), an upside-down reward:risk (avg win +0.55 vs avg loss
  -0.89 because winners are closed early and losers run to a wide 2500-pt stop),
  and 6% risk plus unbounded position stacking that pushes drawdown to 41%.
  Cutting risk, capping concurrent exposure, throttling entry frequency, keeping
  only the more reliable patterns, and fixing the SL/target ratio should shrink
  the drawdown well below the 15% goal and give winners a chance to exceed
  losers. Wiring up the previously-dead real-SL protection functions means
  open winners are actually protected (breakeven after T1, trailing after T2,
  and real trailing stops during a master-EP event) instead of relying solely
  on basket close-outs.
- **Change made:** EA logic + defaults, `GaganEA.mq5` only. Version bumped
  v2.10 -> v2.11 (header, #property copyright/version, OnInit/OnDeinit prints,
  dashboard title). Specific changes:
  - **Cut risk:** `Risk_Percent` 6.0 -> **1.0** (Manual_LotSize and Max_LotSize
    unchanged; Max_LotSize still caps). Intended effect: per-trade risk and the
    lot size fall roughly 6x, directly shrinking drawdown.
  - **Concurrent-exposure cap:** new input `Max_Concurrent_Positions = 2`.
    `OpenTrade()` now returns early when `open_buy_count + open_sell_count`
    (already maintained by `CountOpenPositions()`) is at or above the cap.
    Intended effect: bounds stacked exposure so risk cannot compound into a
    40% drawdown.
  - **Entry cooldown:** new input `Entry_Cooldown_Bars = 3` plus a global
    `last_entry_bar_time` (declared and initialized to 0 in OnInit). After a
    successful Buy/Sell, `last_entry_bar_time` is set to the current bar time;
    `OpenTrade()` skips new entries until
    `Entry_Cooldown_Bars * PeriodSeconds(Trade_Timeframe)` has elapsed.
    Intended effect: throttles the ~100 trades/day overtrading.
  - **Wider entry distance / stacking gap:** `Min_EMA_Distance` 150 -> **400**
    (points, ~$4 on gold) so entries only fire when price is meaningfully
    extended from the CTF EMA; `Min_Trade_Distance` 20 -> **500** (points, ~$5)
    so a second same-side entry needs real separation, not ~$0.20. Conservative
    defaults; can be tuned looser later.
  - **Fewer, more reliable patterns:** default-ON kept to the stronger
    multi-candle / engulfing signals only: Use_BullEngulf, Use_MorningStar,
    Use_ThreeWhite, Use_BearEngulf, Use_EveningStar, Use_ThreeBlack. All other
    candlestick patterns (Hammer, InvHammer, PiercingLine, BullHarami, Doji,
    ShootingStar, DarkCloud, BearHarami, HangingMan) and ALL chart patterns
    default to false. No inputs or detection code were removed, so any can be
    re-enabled. Intended effect: fewer, higher-quality entries.
  - **Fixed reward:risk:** `StopLoss_Pips` 2500 -> **1000** (tighter stop);
    targets `T1/T2/T3` 800/1200/2000 -> **500/1000/1800**; close percents
    `T1/T2` 65/80 -> **33/50**, T3 stays 100. Intended effect: a smaller first
    partial banks some profit while leaving most of the position to reach
    T2/T3, with a stop now ~2x the first target instead of ~3x, so the average
    winner can match or exceed the average loser. Use_StopLoss stays true.
  - **Real-SL protection wired up (previously dead code):**
    `ManageIndividualTrailing()` now (1) calls a new `ApplyBreakevenToTickets(t1_tickets)`
    that moves the real SL to breakeven once T1 has been banked and price is
    beyond entry, and (2) calls the previously-dead
    `ApplyTrailingToTickets(t2_tickets, Trail_Step_Pips)` to trail the real SL
    after T2. `CheckMasterEquityProtection()` now calls the previously-dead
    `ApplyMasterTrailing(POSITION_TYPE_BUY/SELL, Master_Trail_Step)` while a
    master trail is active, moving real stop losses in addition to the existing
    CloseAllByType safety net. All PositionModify guards (newSL relative to
    open/current price) are preserved.
  - **Trailing distances widened for gold (follow-up fix):** the newly-live
    real-SL trails multiply their `*_Pips` inputs by `_Point` (the same raw-point
    unit as `StopLoss_Pips` and `T1_Pips`, per the EA convention that `*_Pips`
    inputs are POINTS on gold). Their old defaults were far too small in that
    unit: `Trail_Step_Pips`=30 gave a $0.30 trail, `Master_Trail_Step`/
    `Basket_Trail_Step`=15 gave a $0.15 trail, and `Master_Lock_Pips`/
    `Basket_Lock_Pips`=30 armed the trail at $0.30 profit -- all far inside
    normal XAUUSD tick noise and likely to stop winners out prematurely. Kept
    the unit math consistent (still `* _Point`) and raised the DEFAULT values to
    sane gold distances comparable to the ~500-pt T1: `Trail_Step_Pips`
    30 -> **400** (~$4 individual after-T2 trail); `Basket_Lock_Pips`
    30.0 -> **500.0** and `Basket_Trail_Step` 15.0 -> **250.0**; `Master_Lock_Pips`
    30.0 -> **500.0** and `Master_Trail_Step` 15.0 -> **250.0**. Lock stays >=
    trail step in both basket and master paths so the trail still arms sensibly
    (lock ~$5 profit, then give back at most ~$2.5). Intended effect: the real
    trailing stops lock in meaningful profit instead of being knocked out by
    noise. Values are conservative and can be tuned on the next backtest.
  - **Master trail trigger metric (reviewed, left as-is):** `ApplyMasterTrailing`
    is triggered from `CheckMasterEquityProtection`, whose `buyProfitPips`/
    `sellProfitPips` are summed across same-side positions rather than
    per-position. Left unchanged: the per-ticket `PositionModify` inside
    `ApplyMasterTrailing` uses each position's own open/current price, so the
    stop MOVE is per-position correct; only the trigger to run it is aggregate,
    and the `Max_Concurrent_Positions = 2` cap bounds the sum to at most two
    tickets. A backtest is the cheapest way to confirm this behaves sensibly on
    a stacked pair before adding per-position trigger complexity.
  - **Full stop exposed until T1 (by design, left as-is):** breakeven only
    engages after T1 (500 pts), so between entry and T1 the full 1000-pt stop
    is live. This is intentional for the reward:risk goal -- protecting before
    T1 would tighten stops inside noise and re-create the premature-stop-out
    problem the wider trails above are meant to avoid. Noted here so drawdown
    results are read with this in mind.
- **Backtest config:**
  - Symbol / timeframe: XAUUSD / M5 (tester Period M1)
  - Date range: pending next run (Round 1 used 2026.03.01 - 2026.09.11 full,
    with a shortened 2026.08.11 - 2026.09.11 window for fast iteration)
  - Deposit: 1000 USD
  - Leverage: 1:500
  - Broker: Fusion Markets
  - Modelling: Every tick based on real ticks
- **Key metrics:** pending next backtest (no sandbox compiler/MT5; the user's
  next MT5 Strategy Tester run on Windows is the authoritative check). No
  performance numbers are claimed here.
- **Diagnosis:** pending next backtest.
- **Next step:** Compile v2.11 in MetaEditor, run the MT5 Strategy Tester on
  XAUUSD, export the HTML to `reports/round02_YYYYMMDD.html`, and run
  `python3 tools/analyze_report.py` to confirm whether drawdown is now under
  15% and the reward:risk has inverted in our favor. Then decide whether to
  loosen the (deliberately strict) entry filters to lift trade count/return.
- **Report file:** pending next backtest.
