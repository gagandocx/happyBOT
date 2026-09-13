"""Tests for python_bt.indicators against hand-computed short series.

EMA: seed with SMA of first n, then recursive 2/(n+1).
ATR: Wilder period, SMA-seeded, then (atr*(n-1)+tr)/n.
RSI: Wilder period, SMA-seeded avg gain/loss.
H1Ema: hourly-close-sampled EMA rolls over on hour-key change.
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from python_bt.indicators import ATR, EMA, RSI, H1Ema  # noqa: E402


class EMATests(unittest.TestCase):
    def test_seed_and_step(self):
        ema = EMA(3)  # alpha = 2/4 = 0.5
        self.assertIsNone(ema.update(2.0))   # warming
        self.assertIsNone(ema.update(4.0))   # warming
        # Third sample completes seed: SMA(2,4,6) = 4.0
        self.assertAlmostEqual(ema.update(6.0), 4.0)
        # Next: 4.0 + 0.5*(8.0 - 4.0) = 6.0
        self.assertAlmostEqual(ema.update(8.0), 6.0)
        # Next: 6.0 + 0.5*(10.0 - 6.0) = 8.0
        self.assertAlmostEqual(ema.update(10.0), 8.0)

    def test_period_one_tracks_input(self):
        ema = EMA(1)  # alpha = 1.0 -> follows input; seed is first value
        self.assertAlmostEqual(ema.update(5.0), 5.0)
        self.assertAlmostEqual(ema.update(9.0), 9.0)


class ATRTests(unittest.TestCase):
    def test_wilder_atr_period_3(self):
        atr = ATR(3)
        # Bars (high, low, close). First TR = high-low (no prev close).
        # b1: h=10,l=8  -> tr=2 ; prev_close=9
        # b2: h=11,l=9  -> tr=max(2, |11-9|, |9-9|)=2 ; prev_close=10
        # b3: h=12,l=10 -> tr=max(2, |12-10|, |10-10|)=2 ; seed=SMA(2,2,2)=2
        self.assertIsNone(atr.update(10, 8, 9))
        self.assertIsNone(atr.update(11, 9, 10))
        self.assertAlmostEqual(atr.update(12, 10, 11), 2.0)
        # b4: h=16,l=11 -> tr=max(5, |16-11|, |11-11|)=5
        #     atr = (2*2 + 5)/3 = 3.0
        self.assertAlmostEqual(atr.update(16, 11, 11), 3.0)

    def test_true_range_uses_prev_close_gap(self):
        atr = ATR(1)
        # period 1: seed is first tr, then each tr replaces.
        self.assertAlmostEqual(atr.update(10, 8, 9), 2.0)  # tr = 2
        # next bar low far below prev close 9: h=9.5 l=5 -> tr=max(4.5,|9.5-9|,|5-9|)=4.5
        self.assertAlmostEqual(atr.update(9.5, 5, 6), 4.5)


class RSITests(unittest.TestCase):
    def test_all_gains_is_100(self):
        rsi = RSI(3)
        # strictly increasing -> avg_loss 0 -> RSI 100 once seeded
        rsi.update(1.0)
        rsi.update(2.0)
        rsi.update(3.0)
        val = rsi.update(4.0)  # after 3 deltas (1,1,1)
        self.assertAlmostEqual(val, 100.0)

    def test_known_series(self):
        rsi = RSI(2)
        # closes: 10, 11, 10, 11 -> deltas: +1, -1, +1
        rsi.update(10.0)
        v1 = rsi.update(11.0)  # 1 delta, still warming (need 2)
        self.assertIsNone(v1)
        v2 = rsi.update(10.0)  # deltas (+1,-1): avg_gain=0.5, avg_loss=0.5, RS=1 -> RSI 50
        self.assertAlmostEqual(v2, 50.0)
        # next close 11 -> delta +1: gain=1,loss=0
        # avg_gain = (0.5*1 + 1)/2 = 0.75 ; avg_loss = (0.5*1 + 0)/2 = 0.25
        # RS = 3 -> RSI = 100 - 100/4 = 75
        v3 = rsi.update(11.0)
        self.assertAlmostEqual(v3, 75.0)


class H1EmaTests(unittest.TestCase):
    def test_hourly_rollover_feeds_inner_ema(self):
        h = H1Ema(2)  # inner EMA alpha 2/3
        # Hour 10: several closes; last is 4.0
        self.assertIsNone(h.update((2026, 7, 1, 10), 2.0))
        self.assertIsNone(h.update((2026, 7, 1, 10), 4.0))
        # Roll to hour 11: commit hour 10 last close 4.0 (inner seed, needs 2)
        self.assertIsNone(h.update((2026, 7, 1, 11), 5.0))
        self.assertIsNone(h.update((2026, 7, 1, 11), 6.0))
        # Roll to hour 12: commit hour 11 last close 6.0 -> seed SMA(4,6)=5.0
        self.assertAlmostEqual(h.update((2026, 7, 1, 12), 9.0), 5.0)
        # Roll to hour 13: commit hour 12 last close 9.0 -> 5 + (2/3)*(9-5)=7.6667
        self.assertAlmostEqual(h.update((2026, 7, 1, 13), 1.0), 5.0 + (2.0 / 3.0) * 4.0, places=6)


if __name__ == "__main__":
    unittest.main()
