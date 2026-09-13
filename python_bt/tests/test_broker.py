"""Tests for python_bt.broker with hand-computed expected P&L.

All fixtures are tiny synthetic quotes. P&L uses the config constants:
  TICK_SIZE = 0.01, TICK_VALUE = 1.0, COMMISSION_PER_LOT_PER_SIDE = 3.5,
  INITIAL_DEPOSIT = 1000.0
So money = profit_price / 0.01 * 1.0 * lots = profit_price * 100 * lots.
Never touches the 526 MB CSV.
"""

import os
import sys
import unittest
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from python_bt.broker import Broker  # noqa: E402


def _ts(sec=0):
    return datetime(2026, 7, 1, 11, 0, sec)


class OpenCloseTests(unittest.TestCase):
    def test_buy_fills_at_ask_commission_on_open_and_close(self):
        b = Broker(deposit=1000.0)
        # Open 1.0 lot buy at ask=100.00; open commission 3.5.
        pos = b.open("buy", 1.0, price_bid=99.99, price_ask=100.00, ts=_ts())
        self.assertEqual(pos.entry_price, 100.00)
        self.assertAlmostEqual(b.balance, 1000.0 - 3.5)
        # Close full at bid=100.50 (buy closes at bid).
        # gross = (100.50 - 100.00)/0.01 * 1.0 * 1.0 = 0.50*100 = 50.0
        # close commission 3.5 -> net deal profit = 46.5
        deal = b.close_full(pos, price_bid=100.50, price_ask=100.51, ts=_ts(1))
        self.assertAlmostEqual(deal.profit, 50.0 - 3.5)
        # balance = 1000 - 3.5 (open) + 46.5 (net close) = 1043.0
        self.assertAlmostEqual(b.balance, 1000.0 - 3.5 + (50.0 - 3.5))
        self.assertEqual(len(b.positions), 0)
        self.assertEqual(len(b.ledger), 1)

    def test_sell_fills_at_bid(self):
        b = Broker(deposit=1000.0)
        # Sell 1.0 lot at bid=100.00.
        pos = b.open("sell", 1.0, price_bid=100.00, price_ask=100.01, ts=_ts())
        self.assertEqual(pos.entry_price, 100.00)
        # Close full at ask=99.50 (sell closes at ask).
        # gross = (100.00 - 99.50)/0.01 * 1.0 = 50.0 ; net = 46.5
        deal = b.close_full(pos, price_bid=99.49, price_ask=99.50, ts=_ts(1))
        self.assertAlmostEqual(deal.profit, 50.0 - 3.5)


class StopTargetTests(unittest.TestCase):
    def test_buy_hits_tp_closes_at_tp(self):
        b = Broker(deposit=1000.0)
        pos = b.open("buy", 1.0, price_bid=99.99, price_ask=100.00, sl=99.00, tp=101.00, ts=_ts())
        # Quote where bid >= tp -> TP fires at tp=101.00.
        fired = b.on_quote(bid=101.00, ask=101.01, ts=_ts(1))
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].reason, "tp")
        # gross = (101.00 - 100.00)*100 = 100.0 ; net = 96.5
        self.assertAlmostEqual(fired[0].profit, 100.0 - 3.5)
        self.assertEqual(len(b.positions), 0)

    def test_buy_hits_sl_closes_at_sl(self):
        b = Broker(deposit=1000.0)
        pos = b.open("buy", 1.0, price_bid=99.99, price_ask=100.00, sl=99.50, tp=101.00, ts=_ts())
        fired = b.on_quote(bid=99.50, ask=99.51, ts=_ts(1))
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].reason, "sl")
        # gross = (99.50 - 100.00)*100 = -50.0 ; net = -53.5
        self.assertAlmostEqual(fired[0].profit, -50.0 - 3.5)

    def test_sell_hits_sl_and_tp_mirror(self):
        # Sell SL: ask >= sl.
        b = Broker(deposit=1000.0)
        pos = b.open("sell", 1.0, price_bid=100.00, price_ask=100.01, sl=100.50, tp=99.00, ts=_ts())
        fired = b.on_quote(bid=100.49, ask=100.50, ts=_ts(1))
        self.assertEqual(fired[0].reason, "sl")
        # gross = (100.00 - 100.50)*100 = -50.0 ; net = -53.5
        self.assertAlmostEqual(fired[0].profit, -50.0 - 3.5)

        # Sell TP: ask <= tp.
        b2 = Broker(deposit=1000.0)
        pos2 = b2.open("sell", 1.0, price_bid=100.00, price_ask=100.01, sl=100.50, tp=99.00, ts=_ts())
        fired2 = b2.on_quote(bid=98.99, ask=99.00, ts=_ts(1))
        self.assertEqual(fired2[0].reason, "tp")
        # gross = (100.00 - 99.00)*100 = 100.0 ; net = 96.5
        self.assertAlmostEqual(fired2[0].profit, 100.0 - 3.5)


class PartialCloseTests(unittest.TestCase):
    def test_partial_then_second_partial_then_full(self):
        b = Broker(deposit=1000.0)
        # Open 1.0 lot buy at ask=100.00. open comm 3.5.
        pos = b.open("buy", 1.0, price_bid=99.99, price_ask=100.00, ts=_ts())
        # Partial close 0.4 lot at bid=100.50.
        # gross = (100.50-100.00)*100*0.4 = 50*0.4 = 20.0 ; comm 3.5*0.4 = 1.4 ; net = 18.6
        d1 = b.close_partial(pos, 0.4, price_bid=100.50, price_ask=100.51, ts=_ts(1))
        self.assertAlmostEqual(d1.profit, 20.0 - 1.4)
        self.assertAlmostEqual(pos.volume_lots, 0.6)
        self.assertFalse(d1.trade_closed)

        # Second partial 0.3 lot at bid=101.00.
        # gross = (101.00-100.00)*100*0.3 = 100*0.3 = 30.0 ; comm 3.5*0.3=1.05 ; net = 28.95
        d2 = b.close_partial(pos, 0.3, price_bid=101.00, price_ask=101.01, ts=_ts(2))
        self.assertAlmostEqual(d2.profit, 30.0 - 1.05)
        self.assertAlmostEqual(pos.volume_lots, 0.3)
        self.assertFalse(d2.trade_closed)

        # Full close remaining 0.3 lot at bid=99.00 (loss).
        # gross = (99.00-100.00)*100*0.3 = -100*0.3 = -30.0 ; comm 1.05 ; net = -31.05
        d3 = b.close_full(pos, price_bid=99.00, price_ask=99.01, ts=_ts(3))
        self.assertAlmostEqual(d3.profit, -30.0 - 1.05)
        self.assertTrue(d3.trade_closed)
        self.assertEqual(len(b.positions), 0)
        self.assertEqual(len(b.ledger), 3)

    def test_partial_exceeding_volume_becomes_full_close(self):
        b = Broker(deposit=1000.0)
        pos = b.open("buy", 0.5, price_bid=99.99, price_ask=100.00, ts=_ts())
        d = b.close_partial(pos, 2.0, price_bid=100.10, price_ask=100.11, ts=_ts(1))
        self.assertTrue(d.trade_closed)
        self.assertAlmostEqual(d.volume_lots, 0.5)
        self.assertEqual(len(b.positions), 0)


class HedgingTests(unittest.TestCase):
    def test_buy_and_sell_open_simultaneously(self):
        b = Broker(deposit=1000.0)
        buy = b.open("buy", 1.0, price_bid=99.99, price_ask=100.00, sl=90.0, tp=110.0, ts=_ts())
        sell = b.open("sell", 1.0, price_bid=100.00, price_ask=100.01, sl=110.0, tp=90.0, ts=_ts())
        self.assertEqual(len(b.positions), 2)
        # A quote in the middle fires neither.
        fired = b.on_quote(bid=100.20, ask=100.21, ts=_ts(1))
        self.assertEqual(len(fired), 0)
        self.assertEqual(len(b.positions), 2)
        # Floating pnl at bid=100.20/ask=100.21:
        # buy: (100.20-100.00)*100 = 20.0 ; sell: (100.00-100.21)*100 = -21.0
        self.assertAlmostEqual(b.floating_pnl(100.20, 100.21), 20.0 - 21.0)


class ModifySlTests(unittest.TestCase):
    def test_modify_sl_to_breakeven_then_fires(self):
        b = Broker(deposit=1000.0)
        pos = b.open("buy", 1.0, price_bid=99.99, price_ask=100.00, sl=99.00, tp=105.00, ts=_ts())
        # Move SL up to breakeven 100.00.
        b.modify_sl(pos, 100.00)
        self.assertEqual(pos.sl, 100.00)
        # Now bid touches 100.00 -> SL fires at breakeven, gross 0, net = -3.5 (close comm).
        fired = b.on_quote(bid=100.00, ask=100.01, ts=_ts(1))
        self.assertEqual(len(fired), 1)
        self.assertAlmostEqual(fired[0].profit, 0.0 - 3.5)


class DrawdownTests(unittest.TestCase):
    def test_scripted_peak_to_trough_drawdown(self):
        # Deposit 1000. Open 1.0 lot buy at ask=100.00 (balance 996.5 after comm).
        b = Broker(deposit=1000.0)
        b.open("buy", 1.0, price_bid=99.99, price_ask=100.00, sl=None, tp=None, ts=_ts())
        # Quote sequence drives floating equity. equity = balance(996.5) + floating.
        # floating(buy) marks at bid: (bid-100.00)*100.
        # q1 bid=101.00 -> floating +100 -> equity 1096.5 (new peak)
        b.on_quote(bid=101.00, ask=101.01, ts=_ts(1))
        self.assertAlmostEqual(b.equity, 996.5 + 100.0)
        self.assertAlmostEqual(b.peak_equity, 1096.5)
        # q2 bid=98.00 -> floating -200 -> equity 796.5. drop from peak = 300.
        b.on_quote(bid=98.00, ask=98.01, ts=_ts(2))
        self.assertAlmostEqual(b.equity, 996.5 - 200.0)
        self.assertAlmostEqual(b.max_drawdown_money, 1096.5 - 796.5)
        # relative pct = 300 / 1096.5 * 100
        self.assertAlmostEqual(b.rel_drawdown_pct, 300.0 / 1096.5 * 100.0)
        self.assertAlmostEqual(b.rel_drawdown_money, 300.0)
        # absolute drawdown = deposit - lowest equity = 1000 - 796.5 = 203.5
        self.assertAlmostEqual(b.absolute_drawdown, 1000.0 - 796.5)


if __name__ == "__main__":
    unittest.main()
