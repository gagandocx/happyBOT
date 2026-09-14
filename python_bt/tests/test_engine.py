"""Tests for python_bt.engine using a trivial stub strategy and a scripted feed.

Feeds a few synthetic ticks/bars through the engine with an always-buy stub
strategy that opens one position with a TP, then asserts a trade opens and
closes and that the result dict {metrics, score, params, meta} comes back and
is JSON-serializable. Never touches the 526 MB CSV.
"""

import json
import os
import sys
import unittest
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from python_bt.engine import Engine  # noqa: E402
from python_bt.loader import Tick  # noqa: E402


class AlwaysBuyOnce:
    """Opens exactly one 1.0-lot buy on the first bar close, with a TP/SL."""

    def __init__(self):
        self.opened = False

    def on_bar(self, bar, ctx):
        if not self.opened and not ctx.positions:
            # Enter at current ask, TP a little above, SL well below.
            ctx.buy(1.0, sl=bar.last_bid - 5.0, tp=ctx.ask + 0.50)
            self.opened = True


def _tick(minute, sec, bid, ask):
    return Tick(ts=datetime(2026, 7, 1, 11, minute, sec), bid=bid, ask=ask)


class EngineTickModeTests(unittest.TestCase):
    def test_trade_opens_and_hits_tp(self):
        # Bucket 11:00 first tick opens at ask 100.01 after the bar closes at
        # the next bucket boundary. TP = 100.01 + 0.50 = 100.51 (buy TP fires
        # when bid >= 100.51). Later ticks cross it.
        ticks = [
            _tick(0, 0, 100.00, 100.01),
            _tick(4, 59, 100.05, 100.06),   # still bucket 0
            _tick(5, 0, 100.10, 100.11),    # bucket 1 boundary -> on_bar fires, buy opens
            _tick(5, 30, 100.60, 100.61),   # bid 100.60 >= tp 100.61? no; opens then TP later
            _tick(6, 0, 100.80, 100.81),    # bid 100.80 >= tp -> TP fires
        ]
        strat = AlwaysBuyOnce()
        eng = Engine(strat, mode="tick", params={"demo": 1})
        result = eng.run(ticks)

        m = result["metrics"]
        self.assertEqual(m["total_trades"], 1)
        self.assertEqual(m["total_deals"], 1)
        self.assertGreater(m["total_net_profit"], 0.0)
        self.assertEqual(len(eng.broker.positions), 0)
        self.assertIn("score", result)
        self.assertIsInstance(result["score"], float)
        self.assertEqual(result["params"], {"demo": 1})
        self.assertEqual(result["meta"]["mode"], "tick")
        self.assertGreater(result["meta"]["tick_count"], 0)
        # Result must be JSON-serializable.
        json.dumps(result)

    def test_bar_mode_runs_and_returns_result(self):
        ticks = [
            _tick(0, 0, 100.00, 100.01),
            _tick(5, 0, 100.10, 100.11),
            _tick(6, 0, 100.80, 100.81),
            _tick(10, 0, 101.00, 101.01),
        ]
        strat = AlwaysBuyOnce()
        eng = Engine(strat, mode="bar", params={})
        result = eng.run(ticks)
        self.assertEqual(result["meta"]["mode"], "bar")
        self.assertGreaterEqual(result["meta"]["bar_count"], 1)
        self.assertIn("metrics", result)
        self.assertIn("score", result)
        json.dumps(result)

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            Engine(AlwaysBuyOnce(), mode="weird")

    def test_warmup_absent_when_strategy_has_no_hook(self):
        # AlwaysBuyOnce has no warmup_info(), so meta.warmup stays None.
        ticks = [_tick(0, 0, 100.00, 100.01), _tick(5, 0, 100.10, 100.11)]
        result = Engine(AlwaysBuyOnce(), mode="bar").run(ticks)
        self.assertIsNone(result["meta"]["warmup"])

    def test_warmup_surfaced_when_strategy_reports(self):
        # A strategy exposing warmup_info() gets it copied into meta.warmup.
        class UnwarmedStub:
            def on_bar(self, bar, ctx):
                pass

            def warmup_info(self):
                return {"warmed_up": False, "entry_ever_eligible": False,
                        "note": "insufficient warm-up: HTF EMA not ready"}

        ticks = [_tick(0, 0, 100.00, 100.01), _tick(5, 0, 100.10, 100.11)]
        result = Engine(UnwarmedStub(), mode="bar").run(ticks)
        self.assertIsNotNone(result["meta"]["warmup"])
        self.assertFalse(result["meta"]["warmup"]["warmed_up"])
        self.assertIn("warm-up", result["meta"]["warmup"]["note"])


if __name__ == "__main__":
    unittest.main()
