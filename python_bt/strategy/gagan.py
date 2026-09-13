"""GaganStrategy: a faithful (NOT byte-exact) Python port of GaganEA.mq5 v2.12.

This ports the CURRENT entry/exit core of GaganEA.mq5 (Round 4 confluence +
ATR dynamic SL/TP + tiered partials). It deliberately does NOT port the many
legacy/optional sub-systems that Round 4 layers on top and that are off or
secondary for the tuned strategy (candlestick/chart pattern detectors, AMA exit,
reversal exit, basket trailing, master/global equity protection, news filter,
dashboard). Those are documented here as intentionally omitted so parity work
knows what is and is not modeled.

WHAT IS MODELED (referencing GaganEA.mq5 line regions):
  ENTRY (OpenTrade ~572-712, on each CLOSED M5 bar):
    * trend: htfBull/htfBear = mid vs HTF EMA200 (H1); ctfBull/ctfBear = mid vs
      CTF EMA200 (M5).
    * Min_EMA_Distance gate: |mid - emaCTF| / POINT >= Min_EMA_Distance.
    * Max_Concurrent_Positions cap on total open positions.
    * Entry_Cooldown_Bars since the last entry bar.
    * SessionOK (SessionOK ~490): hour in [Session_Start_Hour, Session_End_Hour)
      and (optionally) skip Rollover_Hour.
    * ATR regime (Use_ATR_Regime_Filter): atr>0 and atr/POINT in
      [ATR_Min_Points, ATR_Max_Points].
    * confluence (Use_Confluence_Entry): BUY = BullPullbackResume (~505) AND
      entry RSI <= RSI_Buy_Max; SELL = BearPullbackResume (~535) AND entry RSI
      >= RSI_Sell_Min.
    * Min_Trade_Distance de-clustering vs existing same-side positions
      (DistanceCheckOK ~790).
    * lot sizing (CalcLotSize ~700): riskAmt = balance*Risk_Percent/100;
      lots = riskAmt / ((slDist/TICK_SIZE)*TICK_VALUE); floor to lot step; clamp
      [min_lot, Max_LotSize].
  EXIT (ManageTargets ~808 + ManageIndividualTrailing ~892):
    * ATR dynamic SL/TP (Use_ATR_Dynamic_SLTP): slDist = ATR_SL_Mult*atr clamped
      up to a min-stop constant, tpDist = slDist*(ATR_TP_Mult/ATR_SL_Mult); SL/TP
      set on the position and fired by the broker on a quote cross. Legacy fixed
      StopLoss_Pips SL used when ATR SL/TP is off.
    * tiers T1/T2/T3 in POINTS = ATR_Tx_Mult*atr/POINT when Use_ATR_Scaled_Tiers
      (and ATR ready) else fixed Tx_Pips. On reaching a tier: close
      T1_ClosePercent, then T2_ClosePercent of the remaining, then full close at
      T3 (matches the EA's percent-of-current-volume closes, min-lot floored).
    * breakeven-after-T1: move SL to entry once T1 banks and price is onside.
    * trailing-after-T2: trail SL by Trail_Step_Pips once T2 banks.

APPROXIMATIONS vs MQL5 (be honest, this is UNVERIFIABLE in-sandbox):
  * BAR-CLOSE TIMING. The EA acts inside OnTick but gates entries on a NEW M5
    bar and reads indicator buffer index 0 (the current, still-forming bar's
    value in a running tester). Here entries are decided in on_bar using the
    just-CLOSED bar. Tier/SL management runs per bar in bar mode and per tick in
    tick mode; in bar mode SL/TP fire only at the bar's closing quote (see
    engine.py), so intrabar tier hits are approximated at bar granularity.
  * INDICATOR SEEDING. EMA/ATR/RSI are seeded with an SMA of the first n samples
    (see indicators.py); MT5's exact seed is not byte-specified.
  * H1 EMA CONSTRUCTION. The HTF EMA200 is built from hourly closes sampled off
    the M5 stream (last M5 mid close of each hour), not a broker H1 series.
  * PRICE BASIS. Bars are built from tick MIDs, so the mid is used for the
    trend/distance comparisons where the EA reads SYMBOL_BID; fills still use the
    real bid/ask via the broker.
  * MIN-STOP. MT5 uses SYMBOL_TRADE_STOPS_LEVEL; here MIN_STOP_POINTS is a
    documented constant (CONFIRM vs broker).
  * The 11 tuner-managed params are snapped/clamped/order-repaired through
    automation/tuner/params.validate so the Python and MT5 param spaces agree.

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

from python_bt import config
from python_bt.indicators import ATR, EMA, RSI, H1Ema
from python_bt.strategy.base import Strategy, register

# Make automation/tuner importable (same bootstrap style as scoring_bridge).
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_TUNER_DIR = os.path.join(_REPO_ROOT, "automation", "tuner")
if _TUNER_DIR not in sys.path:
    sys.path.insert(0, _TUNER_DIR)

import params as tuner_params  # noqa: E402

# The 11 tuner-managed params (exact GaganEA input names). These are validated
# via tuner_params.validate so Python and MT5 search the SAME space.
TUNER_PARAM_NAMES = list(tuner_params.PARAM_NAMES)

# Broker min-stop distance in POINTS (SYMBOL_TRADE_STOPS_LEVEL analog).
# CONFIRM vs broker; 0 means "no minimum" in the sandbox model.
MIN_STOP_POINTS = 0.0

# Minimum tradable lot and lot step (SYMBOL_VOLUME_MIN / _STEP analogs).
# CONFIRM vs broker symbol spec.
MIN_LOT = 0.01
LOT_STEP = 0.01


@register
class GaganStrategy(Strategy):
    """Faithful port of GaganEA v2.12's current entry/exit core."""

    NAME = "gagan"

    @classmethod
    def default_params(cls) -> Dict[str, object]:
        p = {}  # type: Dict[str, object]
        # -- 11 tuner-managed params (defaults from automation/tuner/params). --
        p.update(tuner_params.defaults())
        # -- Round 4 structural params (GaganEA inputs). --
        p["EMA_Period_HTF"] = 200
        p["EMA_Period_CTF"] = 200
        p["Max_LotSize"] = 10.0
        p["Manual_LotSize"] = 0.0
        p["Use_StopLoss"] = True
        p["T3_ClosePercent"] = 100.0
        p["Trail_Step_Pips"] = 400
        p["ATR_Period"] = 14
        p["Use_ATR_Regime_Filter"] = True
        p["ATR_Min_Points"] = 150.0
        p["ATR_Max_Points"] = 4000.0
        p["Use_ATR_Dynamic_SLTP"] = True
        p["ATR_SL_Mult"] = 1.5
        p["ATR_TP_Mult"] = 2.5
        p["Use_ATR_Scaled_Tiers"] = True
        p["ATR_T1_Mult"] = 0.8
        p["ATR_T2_Mult"] = 1.5
        p["ATR_T3_Mult"] = 2.2
        p["Use_Confluence_Entry"] = True
        p["RSI_Entry_Period"] = 14
        p["RSI_Buy_Max"] = 68.0
        p["RSI_Sell_Min"] = 32.0
        p["Pullback_Lookback"] = 6
        p["Use_Session_Filter"] = True
        p["Session_Start_Hour"] = 7
        p["Session_End_Hour"] = 20
        p["Skip_Rollover_Hour"] = True
        p["Rollover_Hour"] = 0
        return p

    def __init__(self, params: Optional[Dict] = None):
        super().__init__(params)
        # Snap/clamp/order-repair ONLY the 11 tuner-managed params so the Python
        # param space equals the MT5 one; leave structural params/switches as-is.
        supplied_tuner = dict((k, self.params[k]) for k in TUNER_PARAM_NAMES if k in self.params)
        validated = tuner_params.validate(supplied_tuner)
        self.params.update(validated)

        pr = self.params
        # -- indicators (incremental over the M5 bar stream) --
        self._ema_htf = H1Ema(int(pr["EMA_Period_HTF"]))
        self._ema_ctf = EMA(int(pr["EMA_Period_CTF"]))
        self._atr = ATR(int(pr["ATR_Period"]))
        self._rsi = RSI(int(pr["RSI_Entry_Period"]))

        # Rolling window of recent closed bars for pullback-and-resume + the
        # CTF EMA value AT each of those bars (needed to test low<=ema / high>=ema
        # historically the way the EA reads ema[i] per historical bar).
        self._recent = []  # type: List[dict]
        self._max_recent = max(int(pr["Pullback_Lookback"]) + 3, 5)

        self._last_entry_bar_index = None  # type: Optional[int]
        self._bar_index = 0

        # Warm-up / eligibility tracking so a zero-trade run can be told apart
        # from a "not enough data to warm up" run (see warmup_info()). The HTF
        # EMA200 built from hourly closes is the slowest to warm up, so it is
        # the practical gate on whether ANY entry can fire.
        self._warmed_up = False  # both HTF+CTF EMA200 ready at least once
        self._entry_ever_eligible = False  # an entry order was ever placed
        # Warm-up threshold in M5 bars: EMA_Period_HTF hourly closes ~= that many
        # hours; 12 M5 bars per hour. Used only for the diagnostic note.
        self._htf_warmup_bars = int(pr["EMA_Period_HTF"]) * 12

    # -- helpers -----------------------------------------------------------

    def _session_ok(self, ts) -> bool:
        pr = self.params
        if not pr["Use_Session_Filter"]:
            return True
        hour = ts.hour
        if hour < int(pr["Session_Start_Hour"]) or hour >= int(pr["Session_End_Hour"]):
            return False
        if pr["Skip_Rollover_Hour"] and hour == int(pr["Rollover_Hour"]):
            return False
        return True

    def _bull_pullback_resume(self, ema_ctf_now: float) -> bool:
        """Last closed bar close>ema, and within lookback an earlier bar low<=ema.

        Mirrors BullPullbackResume: the resume bar is the most recent closed bar
        (index 1 in the EA); the pullback is any of the preceding lookback bars.
        Here _recent[-1] is the just-closed (resume) bar and we scan the bars
        before it, using the CTF EMA value recorded AT each historical bar.
        """
        pr = self.params
        if not self._recent:
            return False
        resume = self._recent[-1]
        if resume["ema_ctf"] is None or resume["close"] <= resume["ema_ctf"]:
            return False
        lookback = int(pr["Pullback_Lookback"])
        # Bars before the resume bar, up to `lookback` of them.
        prior = self._recent[:-1][-lookback:]
        for b in prior:
            if b["ema_ctf"] is not None and b["low"] <= b["ema_ctf"]:
                return True
        return False

    def _bear_pullback_resume(self, ema_ctf_now: float) -> bool:
        pr = self.params
        if not self._recent:
            return False
        resume = self._recent[-1]
        if resume["ema_ctf"] is None or resume["close"] >= resume["ema_ctf"]:
            return False
        lookback = int(pr["Pullback_Lookback"])
        prior = self._recent[:-1][-lookback:]
        for b in prior:
            if b["ema_ctf"] is not None and b["high"] >= b["ema_ctf"]:
                return True
        return False

    def _calc_lot_size(self, balance: float, sl_dist_price: float) -> float:
        """CalcLotSize port: risk-based lots, floored to step, clamped."""
        pr = self.params
        if float(pr["Manual_LotSize"]) > 0:
            return self._normalize_lot(float(pr["Manual_LotSize"]))
        risk_amt = balance * float(pr["Risk_Percent"]) / 100.0
        denom = (sl_dist_price / config.TICK_SIZE) * config.TICK_VALUE
        if denom <= 0:
            return MIN_LOT
        lots = risk_amt / denom
        return self._normalize_lot(lots)

    def _normalize_lot(self, lots: float) -> float:
        pr = self.params
        import math

        lots = math.floor(lots / LOT_STEP) * LOT_STEP
        lots = max(lots, MIN_LOT)
        lots = min(lots, float(pr["Max_LotSize"]))
        return round(lots, 2)

    def _distance_ok(self, side: str, mid: float, ctx) -> bool:
        """DistanceCheckOK port: reject a same-side entry too close to an open one."""
        pr = self.params
        min_dist = int(pr["Min_Trade_Distance"])
        for pos in ctx.positions:
            if pos.side != side:
                continue
            if abs(mid - pos.entry_price) / config.POINT_SIZE < min_dist:
                return False
        return True

    # -- exit management (ManageTargets + trailing) ------------------------

    def _manage_open(self, ctx) -> None:
        pr = self.params
        atr = self._atr.value
        # Effective tier thresholds in POINTS.
        t1_thr = float(pr["T1_Pips"])
        t2_thr = float(pr["T2_Pips"])
        t3_thr = float(pr["T3_Pips"])
        if pr["Use_ATR_Dynamic_SLTP"] and pr["Use_ATR_Scaled_Tiers"] and atr and atr > 0:
            t1_thr = float(pr["ATR_T1_Mult"]) * atr / config.POINT_SIZE
            t2_thr = float(pr["ATR_T2_Mult"]) * atr / config.POINT_SIZE
            t3_thr = float(pr["ATR_T3_Mult"]) * atr / config.POINT_SIZE

        bid = ctx.bid
        ask = ctx.ask
        for pos in list(ctx.positions):
            op = pos.entry_price
            if pos.side == "buy":
                profit_pts = (bid - op) / config.POINT_SIZE
            else:
                profit_pts = (op - ask) / config.POINT_SIZE

            # T1: close T1_ClosePercent of current volume.
            if profit_pts >= t1_thr and not pos.t1_done:
                close_lots = self._tier_close_volume(pos.volume_lots, float(pr["T1_ClosePercent"]))
                if close_lots > 0:
                    ctx.close_partial(pos, close_lots, reason="t1")
                pos.t1_done = True

            # T2: close T2_ClosePercent of remaining volume.
            if profit_pts >= t2_thr and not pos.t2_done and pos.volume_lots > 0:
                close_lots = self._tier_close_volume(pos.volume_lots, float(pr["T2_ClosePercent"]))
                if close_lots > 0:
                    ctx.close_partial(pos, close_lots, reason="t2")
                pos.t2_done = True

            # T3: full close.
            if profit_pts >= t3_thr and pos.volume_lots > 0:
                ctx.close_full(pos, reason="t3")
                continue

            # Breakeven after T1 (move SL to entry when onside).
            if pos.t1_done and pos.volume_lots > 0:
                if pos.side == "buy":
                    if bid > op and (pos.sl is None or pos.sl < op):
                        ctx.modify_sl(pos, op)
                else:
                    if ask < op and (pos.sl is None or pos.sl > op):
                        ctx.modify_sl(pos, op)

            # Trailing after T2 by Trail_Step_Pips.
            if pos.t2_done and pos.volume_lots > 0:
                trail = float(pr["Trail_Step_Pips"]) * config.POINT_SIZE
                if pos.side == "buy":
                    new_sl = bid - trail
                    if (pos.sl is None or new_sl > pos.sl) and new_sl > op:
                        ctx.modify_sl(pos, new_sl)
                else:
                    new_sl = ask + trail
                    if (pos.sl is None or new_sl < pos.sl) and new_sl < op:
                        ctx.modify_sl(pos, new_sl)

    def _tier_close_volume(self, cur_volume: float, close_pct: float) -> float:
        """Percent-of-current-volume close, min-lot floored (ManageTargets port)."""
        close_lots = round(cur_volume * close_pct / 100.0, 2)
        if close_lots < MIN_LOT:
            close_lots = MIN_LOT
        if close_lots >= cur_volume:
            close_lots = round(cur_volume - MIN_LOT, 2)
        return close_lots if close_lots > 0 else 0.0

    # -- entry (OpenTrade) -------------------------------------------------

    def _open_trade(self, bar, ctx, mid: float) -> None:
        pr = self.params
        ema_htf = self._ema_htf.value
        ema_ctf = self._ema_ctf.value
        if ema_htf is None or ema_ctf is None:
            return  # indicators not warmed up
        # Both trend EMAs are ready: the strategy is out of warm-up.
        self._warmed_up = True

        htf_bull = mid > ema_htf
        htf_bear = mid < ema_htf
        ctf_bull = mid > ema_ctf
        ctf_bear = mid < ema_ctf
        dist = abs(mid - ema_ctf) / config.POINT_SIZE
        far_enough = dist >= int(pr["Min_EMA_Distance"])

        # Concurrent-exposure cap.
        max_conc = int(pr["Max_Concurrent_Positions"])
        if max_conc > 0 and len(ctx.positions) >= max_conc:
            return

        # Entry cooldown (in bars).
        cooldown = int(pr["Entry_Cooldown_Bars"])
        if cooldown > 0 and self._last_entry_bar_index is not None:
            if (self._bar_index - self._last_entry_bar_index) < cooldown:
                return

        # Session filter.
        if not self._session_ok(bar.ts_open):
            return

        # ATR regime filter.
        atr = self._atr.value
        if pr["Use_ATR_Regime_Filter"]:
            if not atr or atr <= 0:
                return
            atr_pts = atr / config.POINT_SIZE
            if atr_pts < float(pr["ATR_Min_Points"]) or atr_pts > float(pr["ATR_Max_Points"]):
                return

        rsi_entry = self._rsi.value if pr["Use_Confluence_Entry"] else -1.0

        min_stop = MIN_STOP_POINTS * config.POINT_SIZE

        # BUY
        if htf_bull and ctf_bull and far_enough:
            if pr["Use_Confluence_Entry"]:
                buy_ok = self._bull_pullback_resume(ema_ctf) and (
                    rsi_entry is not None and rsi_entry >= 0 and rsi_entry <= float(pr["RSI_Buy_Max"])
                )
            else:
                buy_ok = False  # legacy pattern gate not ported
            if buy_ok and self._distance_ok("buy", mid, ctx):
                self._enter("buy", ctx, atr, min_stop)

        # SELL
        if htf_bear and ctf_bear and far_enough:
            if pr["Use_Confluence_Entry"]:
                sell_ok = self._bear_pullback_resume(ema_ctf) and (
                    rsi_entry is not None and rsi_entry >= 0 and rsi_entry >= float(pr["RSI_Sell_Min"])
                )
            else:
                sell_ok = False
            if sell_ok and self._distance_ok("sell", mid, ctx):
                self._enter("sell", ctx, atr, min_stop)

    def _enter(self, side: str, ctx, atr: Optional[float], min_stop: float) -> None:
        pr = self.params
        ask = ctx.ask
        bid = ctx.bid
        sl = None
        tp = None
        if pr["Use_ATR_Dynamic_SLTP"] and atr and atr > 0:
            sl_dist = float(pr["ATR_SL_Mult"]) * atr
            if min_stop > 0 and sl_dist < min_stop:
                sl_dist = min_stop
            tp_dist = sl_dist * (float(pr["ATR_TP_Mult"]) / float(pr["ATR_SL_Mult"]))
            if min_stop > 0 and tp_dist < min_stop:
                tp_dist = min_stop
            if side == "buy":
                sl = ask - sl_dist
                tp = ask + tp_dist
            else:
                sl = bid + sl_dist
                tp = bid - tp_dist
            sl_dist_for_lots = sl_dist
        else:
            sl_dist_for_lots = float(pr["StopLoss_Pips"]) * config.POINT_SIZE
            if pr["Use_StopLoss"]:
                if side == "buy":
                    sl = ask - sl_dist_for_lots
                else:
                    sl = bid + sl_dist_for_lots

        # Lot sizing uses the fixed StopLoss_Pips distance, mirroring CalcLotSize
        # in the EA (which always sizes off StopLoss_Pips, not the ATR SL).
        lots = self._calc_lot_size(ctx._broker.balance, float(pr["StopLoss_Pips"]) * config.POINT_SIZE)
        if lots <= 0:
            return
        if side == "buy":
            ctx.buy(lots, sl=sl, tp=tp)
        else:
            ctx.sell(lots, sl=sl, tp=tp)
        self._entry_ever_eligible = True
        self._last_entry_bar_index = self._bar_index

    # -- engine callback ---------------------------------------------------

    def on_bar(self, bar, ctx) -> None:
        self._bar_index += 1
        mid = bar.close  # bars.py builds OHLC from tick mids

        # Update indicators with this just-closed bar.
        self._ema_ctf.update(mid)
        self._atr.update(bar.high, bar.low, bar.close)
        self._rsi.update(mid)
        hour_key = (bar.ts_open.year, bar.ts_open.month, bar.ts_open.day, bar.ts_open.hour)
        self._ema_htf.update(hour_key, mid)

        # Record this bar (with the CTF EMA value AT this bar) for pullback scan.
        self._recent.append(
            {"low": bar.low, "high": bar.high, "close": bar.close, "ema_ctf": self._ema_ctf.value}
        )
        if len(self._recent) > self._max_recent:
            self._recent.pop(0)

        # Manage existing positions first (mirrors OnTick order: manage, then
        # look for a new-bar entry).
        self._manage_open(ctx)

        # Then evaluate a fresh entry on this bar close.
        self._open_trade(bar, ctx, mid)

    def on_tick(self, tick, ctx) -> None:
        # In tick mode, run tier/SL management on every tick so partials and
        # trailing react intrabar (closer to the EA's per-OnTick management).
        self._manage_open(ctx)

    def warmup_info(self) -> Dict[str, object]:
        """Report warm-up / entry-eligibility so flat != under-warmed-up.

        The slice may end before the HTF EMA200 (~EMA_Period_HTF hours) is ready,
        in which case no entry can ever fire and a zero-trade run should read as
        "insufficient warm-up", not "strategy is flat". warmed_up flips True the
        first time both trend EMAs have a value; entry_ever_eligible flips True
        the first time an entry order is actually placed.
        """
        info = {
            "warmed_up": bool(self._warmed_up),
            "entry_ever_eligible": bool(self._entry_ever_eligible),
            "bars_seen": int(self._bar_index),
            "htf_warmup_bars": int(self._htf_warmup_bars),
            "note": "",
        }
        if not self._warmed_up:
            info["note"] = (
                "insufficient warm-up: HTF EMA not ready "
                "(saw {} M5 bars, need ~{} for the {}-hour HTF EMA)".format(
                    self._bar_index,
                    self._htf_warmup_bars,
                    int(self.params["EMA_Period_HTF"]),
                )
            )
        return info
