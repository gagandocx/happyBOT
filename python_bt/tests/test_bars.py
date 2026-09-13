"""Tests for python_bt.bars using hand-built tick lists.

Feeds ticks spanning more than two M5 buckets and asserts bar count, OHLC from
mids, boundary alignment, last bid/ask exposure, and that the final partial bar
is emitted. Never touches the 526 MB CSV.
"""

import os
import sys
import unittest
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from python_bt.bars import Bar, floor_ts, iter_bars  # noqa: E402
from python_bt.loader import Tick  # noqa: E402


def _tick(minute, second, bid, ask):
    return Tick(ts=datetime(2026, 7, 1, 11, minute, second), bid=bid, ask=ask)


class FloorTsTests(unittest.TestCase):
    def test_floor_to_m5_boundary(self):
        self.assertEqual(
            floor_ts(datetime(2026, 7, 1, 11, 3, 27, 500000), 5),
            datetime(2026, 7, 1, 11, 0, 0, 0),
        )
        self.assertEqual(
            floor_ts(datetime(2026, 7, 1, 11, 7, 59), 5),
            datetime(2026, 7, 1, 11, 5, 0, 0),
        )
        self.assertEqual(
            floor_ts(datetime(2026, 7, 1, 11, 10, 0), 5),
            datetime(2026, 7, 1, 11, 10, 0, 0),
        )


class IterBarsTests(unittest.TestCase):
    def test_three_buckets_ohlc_and_alignment(self):
        # Bucket 11:00-11:05 : mids 1.0, 3.0, 2.0  (open 1, high 3, low 1, close 2)
        # Bucket 11:05-11:10 : mids 5.0, 4.0       (open 5, high 5, low 4, close 4)
        # Bucket 11:10-11:15 : mid  6.0            (partial, open=high=low=close 6)
        ticks = [
            _tick(0, 1, 0.5, 1.5),   # mid 1.0
            _tick(2, 0, 2.5, 3.5),   # mid 3.0
            _tick(4, 30, 1.5, 2.5),  # mid 2.0
            _tick(5, 1, 4.5, 5.5),   # mid 5.0
            _tick(9, 0, 3.5, 4.5),   # mid 4.0
            _tick(10, 0, 5.5, 6.5),  # mid 6.0
        ]
        bars = list(iter_bars(ticks, timeframe_minutes=5))
        self.assertEqual(len(bars), 3)

        b0, b1, b2 = bars
        self.assertIsInstance(b0, Bar)

        # Bucket 0 alignment + OHLC
        self.assertEqual(b0.ts_open, datetime(2026, 7, 1, 11, 0, 0))
        self.assertAlmostEqual(b0.open, 1.0)
        self.assertAlmostEqual(b0.high, 3.0)
        self.assertAlmostEqual(b0.low, 1.0)
        self.assertAlmostEqual(b0.close, 2.0)
        self.assertEqual(b0.tick_count, 3)
        # last quote of bucket 0 is the third tick (bid 1.5, ask 2.5)
        self.assertAlmostEqual(b0.last_bid, 1.5)
        self.assertAlmostEqual(b0.last_ask, 2.5)

        # Bucket 1 alignment + OHLC
        self.assertEqual(b1.ts_open, datetime(2026, 7, 1, 11, 5, 0))
        self.assertAlmostEqual(b1.open, 5.0)
        self.assertAlmostEqual(b1.high, 5.0)
        self.assertAlmostEqual(b1.low, 4.0)
        self.assertAlmostEqual(b1.close, 4.0)
        self.assertEqual(b1.tick_count, 2)

        # Bucket 2 is the final partial bar (single tick), still emitted.
        self.assertEqual(b2.ts_open, datetime(2026, 7, 1, 11, 10, 0))
        self.assertAlmostEqual(b2.open, 6.0)
        self.assertAlmostEqual(b2.close, 6.0)
        self.assertEqual(b2.tick_count, 1)
        self.assertAlmostEqual(b2.last_bid, 5.5)
        self.assertAlmostEqual(b2.last_ask, 6.5)

    def test_empty_stream_yields_nothing(self):
        self.assertEqual(list(iter_bars([], timeframe_minutes=5)), [])

    def test_single_tick_emits_one_partial_bar(self):
        bars = list(iter_bars([_tick(3, 0, 10.0, 11.0)], timeframe_minutes=5))
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].ts_open, datetime(2026, 7, 1, 11, 0, 0))
        self.assertAlmostEqual(bars[0].open, 10.5)
        self.assertEqual(bars[0].tick_count, 1)

    def test_invalid_timeframe_raises(self):
        with self.assertRaises(ValueError):
            list(iter_bars([_tick(0, 0, 1.0, 2.0)], timeframe_minutes=0))


if __name__ == "__main__":
    unittest.main()
