"""Tests for python_bt.metrics with a hand-computed ledger, plus score() tiers.

Builds small ClosedDeal ledgers directly (no broker needed) and checks the
metrics dict keys and values. Also proves the imported tuner score() separates
a compliant (relative_drawdown_pct 10) result strictly above an over-ceiling
(20) one. Never touches the 526 MB CSV.
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from python_bt.broker import ClosedDeal  # noqa: E402
from python_bt.metrics import compute_metrics  # noqa: E402
from python_bt.scoring_bridge import score  # noqa: E402


def _deal(pid, profit, trade_closed=True, side="buy"):
    return ClosedDeal(
        position_id=pid,
        side=side,
        volume_lots=1.0,
        entry_price=100.0,
        exit_price=101.0,
        profit=profit,
        commission=3.5,
        open_ts=None,
        close_ts=None,
        reason="test",
        trade_closed=trade_closed,
    )


class MetricsTests(unittest.TestCase):
    def test_three_wins_two_losses(self):
        # Per-trade P&L in order: +100, -50, +200, +30, -80
        # wins = [100, 200, 30] gross_profit = 330
        # losses = [-50, -80] gross_loss = -130
        # net = 200 ; profit_factor = 330/130 ; win_rate = 3/5 = 60
        ledger = [
            _deal(1, 100.0),
            _deal(2, -50.0),
            _deal(3, 200.0),
            _deal(4, 30.0),
            _deal(5, -80.0),
        ]
        m = compute_metrics(ledger, equity_curve=[1000.0], deposit=1000.0)
        self.assertEqual(m["total_trades"], 5)
        self.assertEqual(m["total_deals"], 5)
        self.assertAlmostEqual(m["gross_profit"], 330.0)
        self.assertAlmostEqual(m["gross_loss"], -130.0)
        self.assertAlmostEqual(m["total_net_profit"], 200.0)
        self.assertAlmostEqual(m["profit_factor"], 330.0 / 130.0)
        self.assertAlmostEqual(m["win_rate_pct"], 60.0)
        self.assertAlmostEqual(m["expected_payoff"], 200.0 / 5.0)
        self.assertAlmostEqual(m["largest_profit_trade"], 200.0)
        self.assertAlmostEqual(m["largest_loss_trade"], -80.0)
        self.assertAlmostEqual(m["average_profit_trade"], 330.0 / 3.0)
        self.assertAlmostEqual(m["average_loss_trade"], -130.0 / 2.0)

    def test_consecutive_streaks(self):
        # +10, +20, +5, -3, -7, +50  -> longest win streak count 3 money 35;
        # longest loss streak count 2 money -10.
        ledger = [
            _deal(1, 10.0),
            _deal(2, 20.0),
            _deal(3, 5.0),
            _deal(4, -3.0),
            _deal(5, -7.0),
            _deal(6, 50.0),
        ]
        m = compute_metrics(ledger, deposit=1000.0)
        self.assertEqual(m["max_consecutive_wins_count"], 3)
        self.assertAlmostEqual(m["max_consecutive_wins_money"], 35.0)
        self.assertEqual(m["max_consecutive_losses_count"], 2)
        self.assertAlmostEqual(m["max_consecutive_losses_money"], -10.0)

    def test_partials_roll_into_one_trade(self):
        # Two partial deals of position 1 (only last trade_closed), plus one
        # separate position 2. total_deals=3, total_trades=2.
        ledger = [
            _deal(1, 20.0, trade_closed=False),
            _deal(1, -5.0, trade_closed=True),  # position 1 net = 15 -> a win
            _deal(2, -40.0, trade_closed=True),
        ]
        m = compute_metrics(ledger, deposit=1000.0)
        self.assertEqual(m["total_deals"], 3)
        self.assertEqual(m["total_trades"], 2)
        # Position 1 net +15 (win), position 2 -40 (loss).
        self.assertAlmostEqual(m["gross_profit"], 15.0)
        self.assertAlmostEqual(m["gross_loss"], -40.0)
        self.assertAlmostEqual(m["total_net_profit"], -25.0)
        self.assertEqual(m["max_consecutive_wins_count"], 1)
        self.assertEqual(m["max_consecutive_losses_count"], 1)

    def test_zero_loss_profit_factor_is_inf(self):
        ledger = [_deal(1, 10.0), _deal(2, 20.0)]
        m = compute_metrics(ledger, deposit=1000.0)
        self.assertEqual(m["profit_factor"], float("inf"))

    def test_drawdown_from_broker_trackers(self):
        class FakeBroker:
            max_drawdown_money = 300.0
            rel_drawdown_money = 300.0
            rel_drawdown_pct = 27.35
            absolute_drawdown = 203.5
            peak_equity = 1096.5

        ledger = [_deal(1, 200.0)]
        m = compute_metrics(ledger, deposit=1000.0, broker=FakeBroker())
        self.assertAlmostEqual(m["maximal_drawdown_money"], 300.0)
        self.assertAlmostEqual(m["relative_drawdown_pct"], 27.35)
        self.assertAlmostEqual(m["relative_drawdown_money"], 300.0)
        self.assertAlmostEqual(m["absolute_drawdown"], 203.5)
        # recovery = net / max_dd = 200 / 300
        self.assertAlmostEqual(m["recovery_factor"], 200.0 / 300.0)
        # maximal_drawdown_pct = 300 / 1096.5 * 100
        self.assertAlmostEqual(m["maximal_drawdown_pct"], 300.0 / 1096.5 * 100.0)

    def test_empty_ledger_is_safe(self):
        m = compute_metrics([], deposit=1000.0)
        self.assertEqual(m["total_trades"], 0)
        self.assertEqual(m["total_deals"], 0)
        self.assertAlmostEqual(m["total_net_profit"], 0.0)
        self.assertAlmostEqual(m["profit_factor"], 0.0)
        self.assertAlmostEqual(m["win_rate_pct"], 0.0)


class ScoreTierTests(unittest.TestCase):
    def test_relative_dd_10_beats_20(self):
        good = {
            "total_net_profit": 100.0,
            "relative_drawdown_pct": 10.0,
            "profit_factor": 1.5,
            "total_trades": 40,
        }
        bad = {
            "total_net_profit": 100.0,
            "relative_drawdown_pct": 20.0,
            "profit_factor": 1.5,
            "total_trades": 40,
        }
        self.assertGreater(score(good), score(bad))

    def test_metrics_dict_is_consumable_by_score(self):
        ledger = [_deal(1, 100.0), _deal(2, -50.0), _deal(3, 200.0)]
        m = compute_metrics(ledger, deposit=1000.0)
        # score() reads the keys the metrics dict populates without KeyError.
        value = score(m)
        self.assertIsInstance(value, float)


if __name__ == "__main__":
    unittest.main()
