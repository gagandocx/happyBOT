"""Tests for python_bt.strategy.happybot.HappyBotStrategy.

These use a lightweight fake Context + Broker-backed positions so the entry
gates and exit management can be exercised without warming a real EMA200 over
thousands of bars: the strategy's internal indicators are pre-seeded to known
values, then on_bar / _manage_open are driven directly.

Covered:
  * registry: 'happybot' resolves to HappyBotStrategy.
  * tuner-param validation snaps supplied params to the shared MT5 space.
  * BUY fires when every gate aligns.
  * BUY is rejected when a single gate fails (RSI overbought, wrong session
    hour, ATR below Min, no pullback-resume).
  * lot sizing math for a known balance/SL.
  * a scripted winning path banks T1 then moves SL to breakeven.
"""

import os
import sys
import unittest
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from python_bt import config  # noqa: E402
from python_bt.bars import Bar  # noqa: E402
from python_bt.broker import Broker  # noqa: E402
from python_bt.strategy import get_strategy  # noqa: E402
from python_bt.strategy.happybot import HappyBotStrategy  # noqa: E402


class FakeCtx:
    """Minimal Context standing in for python_bt.engine.Context."""

    def __init__(self, broker, bid, ask, ts):
        self._broker = broker
        self.bid = bid
        self.ask = ask
        self.ts = ts

    @property
    def positions(self):
        return self._broker.positions

    def buy(self, volume, sl=None, tp=None):
        return self._broker.open("buy", volume, self.bid, self.ask, sl, tp, self.ts)

    def sell(self, volume, sl=None, tp=None):
        return self._broker.open("sell", volume, self.bid, self.ask, sl, tp, self.ts)

    def close_partial(self, pos, volume, reason="partial"):
        return self._broker.close_partial(pos, volume, self.bid, self.ask, self.ts, reason)

    def close_full(self, pos, reason="close"):
        return self._broker.close_full(pos, self.bid, self.ask, self.ts, reason)

    def modify_sl(self, pos, new_sl):
        return self._broker.modify_sl(pos, new_sl)


def _mk_bar(hour, close, low=None, high=None):
    ts = datetime(2026, 7, 1, hour, 0, 0)
    low = low if low is not None else close - 1.0
    high = high if high is not None else close + 1.0
    return Bar(ts_open=ts, open=close, high=high, low=low, close=close,
               tick_count=1, last_bid=close, last_ask=close + 0.02)


def _prime_bull(strat, ema_ctf, ema_htf, atr, rsi, pullback=True):
    """Force the strategy indicators + recent-bar window into a BUY-ready state.

    Sets CTF/HTF EMA below price, ATR in-regime, RSI not overbought, and a
    recent window where an earlier bar dipped its low to/below the CTF EMA and
    the last closed bar closed back above it.
    """
    strat._ema_ctf.value = ema_ctf
    strat._ema_htf.value = ema_htf
    strat._atr.value = atr
    strat._rsi.value = rsi
    # recent window: pullback bar (low <= ema) then resume bar (close > ema).
    strat._recent = []
    if pullback:
        strat._recent.append({"low": ema_ctf - 0.5, "high": ema_ctf + 0.5,
                              "close": ema_ctf + 0.1, "ema_ctf": ema_ctf})
    else:
        # no bar dips to the ema
        strat._recent.append({"low": ema_ctf + 2.0, "high": ema_ctf + 3.0,
                              "close": ema_ctf + 2.5, "ema_ctf": ema_ctf})
    # resume bar (the just-closed bar): close clearly above ema
    strat._recent.append({"low": ema_ctf + 1.0, "high": ema_ctf + 3.0,
                          "close": ema_ctf + 2.0, "ema_ctf": ema_ctf})


class RegistryAndValidationTests(unittest.TestCase):
    def test_registered(self):
        self.assertIs(get_strategy("happybot"), HappyBotStrategy)

    def test_tuner_params_validated(self):
        # Risk_Percent out of bounds gets clamped to the tuner space [0.25, 2.0].
        s = HappyBotStrategy({"Risk_Percent": 99.0})
        self.assertLessEqual(s.params["Risk_Percent"], 2.0)
        # T1<T2<T3 ordering repaired even if supplied out of order.
        s2 = HappyBotStrategy({"T1_Pips": 900, "T2_Pips": 200, "T3_Pips": 300})
        self.assertLess(s2.params["T1_Pips"], s2.params["T2_Pips"])
        self.assertLess(s2.params["T2_Pips"], s2.params["T3_Pips"])


class LotSizingTests(unittest.TestCase):
    def test_calc_lot_size_known(self):
        # balance 1000, Risk 1% -> riskAmt 10. SL dist = StopLoss_Pips*POINT.
        # StopLoss_Pips default 1000 -> slDist = 1000*0.01 = 10.0 price.
        # denom = (10.0 / 0.01) * 1.0 = 1000. lots = 10/1000 = 0.01.
        s = HappyBotStrategy({"Risk_Percent": 1.0, "StopLoss_Pips": 1000})
        lots = s._calc_lot_size(1000.0, 10.0)
        self.assertAlmostEqual(lots, 0.01)

    def test_calc_lot_size_scales_with_balance(self):
        # balance 100000, Risk 1% -> riskAmt 1000; denom 1000 -> lots 1.0.
        s = HappyBotStrategy({"Risk_Percent": 1.0, "StopLoss_Pips": 1000})
        lots = s._calc_lot_size(100000.0, 10.0)
        self.assertAlmostEqual(lots, 1.0)


class EntryGateTests(unittest.TestCase):
    def _run_bar(self, strat, hour=10, price=110.0):
        broker = Broker(deposit=100000.0)
        ctx = FakeCtx(broker, bid=price, ask=price + 0.02, ts=datetime(2026, 7, 1, hour, 0, 0))
        bar = _mk_bar(hour, price)
        strat._open_trade(bar, ctx, price)
        return broker

    def test_buy_fires_when_all_gates_align(self):
        s = HappyBotStrategy({"Min_EMA_Distance": 100})
        # price 110, emaCTF 100 -> dist = (110-100)/0.01 = 1000 pts >= 100.
        _prime_bull(s, ema_ctf=100.0, ema_htf=100.0, atr=3.0, rsi=50.0, pullback=True)
        broker = self._run_bar(s, hour=10, price=110.0)
        self.assertEqual(len(broker.positions), 1)
        self.assertEqual(broker.positions[0].side, "buy")

    def test_buy_rejected_rsi_overbought(self):
        s = HappyBotStrategy({"Min_EMA_Distance": 100, "RSI_Buy_Max": 68.0})
        _prime_bull(s, ema_ctf=100.0, ema_htf=100.0, atr=3.0, rsi=80.0, pullback=True)
        broker = self._run_bar(s, hour=10, price=110.0)
        self.assertEqual(len(broker.positions), 0)

    def test_buy_rejected_wrong_session_hour(self):
        s = HappyBotStrategy({"Min_EMA_Distance": 100, "Session_Start_Hour": 7,
                           "Session_End_Hour": 20})
        _prime_bull(s, ema_ctf=100.0, ema_htf=100.0, atr=3.0, rsi=50.0, pullback=True)
        broker = self._run_bar(s, hour=3, price=110.0)  # 3 < 7 -> out of session
        self.assertEqual(len(broker.positions), 0)

    def test_buy_rejected_atr_below_min(self):
        s = HappyBotStrategy({"Min_EMA_Distance": 100, "ATR_Min_Points": 150.0})
        # atr 0.5 -> atr_pts = 0.5/0.01 = 50 < 150 -> rejected.
        _prime_bull(s, ema_ctf=100.0, ema_htf=100.0, atr=0.5, rsi=50.0, pullback=True)
        broker = self._run_bar(s, hour=10, price=110.0)
        self.assertEqual(len(broker.positions), 0)

    def test_buy_rejected_no_pullback(self):
        s = HappyBotStrategy({"Min_EMA_Distance": 100})
        _prime_bull(s, ema_ctf=100.0, ema_htf=100.0, atr=3.0, rsi=50.0, pullback=False)
        broker = self._run_bar(s, hour=10, price=110.0)
        self.assertEqual(len(broker.positions), 0)

    def test_buy_rejected_distance_too_small(self):
        s = HappyBotStrategy({"Min_EMA_Distance": 1200})
        # dist 1000 < 1200 -> rejected.
        _prime_bull(s, ema_ctf=100.0, ema_htf=100.0, atr=3.0, rsi=50.0, pullback=True)
        broker = self._run_bar(s, hour=10, price=110.0)
        self.assertEqual(len(broker.positions), 0)


class ExitManagementTests(unittest.TestCase):
    def test_t1_partial_then_breakeven(self):
        # Open a buy manually, then drive _manage_open on a winning quote so T1
        # banks a partial and SL moves to breakeven (entry).
        s = HappyBotStrategy({
            "Use_ATR_Scaled_Tiers": False,   # use fixed Tx_Pips for a clean threshold
            "T1_Pips": 100, "T2_Pips": 500, "T3_Pips": 1000,
            "T1_ClosePercent": 50.0,
        })
        broker = Broker(deposit=100000.0)
        # Open at ask 100.02, SL below entry.
        entry_ctx = FakeCtx(broker, bid=100.00, ask=100.02, ts=datetime(2026, 7, 1, 10))
        pos = entry_ctx.buy(1.0, sl=99.00, tp=None)
        self.assertEqual(pos.volume_lots, 1.0)
        # Winning quote: bid 101.04 -> profit = (101.04-100.02)/0.01 = 102 pts >= T1 100.
        win_ctx = FakeCtx(broker, bid=101.04, ask=101.06, ts=datetime(2026, 7, 1, 10, 5))
        s._manage_open(win_ctx)
        # T1 closed 50% -> 0.5 lot remains.
        self.assertTrue(pos.t1_done)
        self.assertAlmostEqual(pos.volume_lots, 0.5)
        # Breakeven: SL moved to entry (100.02).
        self.assertAlmostEqual(pos.sl, pos.entry_price)
        # One partial deal recorded, trade not fully closed yet.
        self.assertEqual(len(broker.ledger), 1)
        self.assertFalse(broker.ledger[0].trade_closed)

    def test_t3_full_close(self):
        s = HappyBotStrategy({
            "Use_ATR_Scaled_Tiers": False,
            "T1_Pips": 100, "T2_Pips": 200, "T3_Pips": 300,
            "T1_ClosePercent": 33.0, "T2_ClosePercent": 50.0,
        })
        broker = Broker(deposit=100000.0)
        entry_ctx = FakeCtx(broker, bid=100.00, ask=100.02, ts=datetime(2026, 7, 1, 10))
        pos = entry_ctx.buy(1.0, sl=99.00, tp=None)
        # Big winner: profit way past T3 (300 pts = 3.0 price).
        win_ctx = FakeCtx(broker, bid=104.02, ask=104.04, ts=datetime(2026, 7, 1, 10, 5))
        s._manage_open(win_ctx)
        self.assertEqual(len(broker.positions), 0)  # fully closed at T3


if __name__ == "__main__":
    unittest.main()
