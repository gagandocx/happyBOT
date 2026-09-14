"""Calibration tests locking in the Round 7 MT5 alignment.

These pin the behaviors that the MT5 calibration confirmed or fixed:

  1. INTRABAR SL/TP fill timing (tick mode). A buy whose stop is crossed by an
     intrabar bid tick closes at the SL WITHIN the bar, not at bar close. This
     is the tick-vs-bar difference that made bar mode ~6x too optimistic.
  2. PARTIAL-CLOSE COMMISSION. A partial close charges commission on the closed
     volume only, on both sides (open charged on full volume, each close on its
     own closed volume).
  3. MONEY CONVERSION. broker._pnl_money reproduces the MT5 deal reconciliation:
     0.01 lot with a 1.36 price move yields 1.36 USD gross, i.e. 1.00 USD per
     1.00 move per 0.01 lot (confirming TICK_VALUE=1.0 / CONTRACT_SIZE=100).
  4. v2.13 DEFAULTS. default_params() carries the EA v2.13 compiled-in inputs
     that FEAT-002 aligned (the defaults mismatch was the trade-count root
     cause).

Tiny synthetic fixtures only. Never touches the 526 MB CSV. Pure ASCII.

The money-conversion tests pin config.TICK_VALUE=1.0, TICK_SIZE=0.01,
CONTRACT_SIZE=100 and COMMISSION_PER_LOT_PER_SIDE=3.0 (the reconciled Fusion
values) for the duration of each test and restore them, so the suite stays
deterministic regardless of any future config recalibration.
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
from python_bt.broker import Broker, _pnl_money  # noqa: E402
from python_bt.engine import Engine  # noqa: E402
from python_bt.loader import Tick  # noqa: E402
from python_bt.strategy.happybot import HappyBotStrategy  # noqa: E402


# Reconciled constants confirmed from the MT5 deal table (FEAT-001/FEAT-002).
_RECON_TICK_SIZE = 0.01
_RECON_TICK_VALUE = 1.0
_RECON_CONTRACT_SIZE = 100
_RECON_COMMISSION_PER_SIDE = 3.0


def _ts(minute=0, sec=0):
    return datetime(2026, 7, 1, 11, minute, sec)


class _PinnedReconConstants(unittest.TestCase):
    """Pin the reconciled MT5 constants, then restore, for determinism."""

    def setUp(self):
        self._saved = (
            config.TICK_SIZE,
            config.TICK_VALUE,
            config.CONTRACT_SIZE,
            config.COMMISSION_PER_LOT_PER_SIDE,
        )
        config.TICK_SIZE = _RECON_TICK_SIZE
        config.TICK_VALUE = _RECON_TICK_VALUE
        config.CONTRACT_SIZE = _RECON_CONTRACT_SIZE
        config.COMMISSION_PER_LOT_PER_SIDE = _RECON_COMMISSION_PER_SIDE

    def tearDown(self):
        (config.TICK_SIZE, config.TICK_VALUE, config.CONTRACT_SIZE,
         config.COMMISSION_PER_LOT_PER_SIDE) = self._saved


def _tick(minute, sec, bid, ask):
    return Tick(ts=_ts(minute, sec), bid=bid, ask=ask)


class _OpenBuyOnceWithStop:
    """Opens exactly one buy on the first bar close with an explicit SL/TP.

    Records whether the position was still open when each subsequent bar closed,
    so a test can prove the SL fired INTRABAR (tick mode) rather than at a bar
    boundary.
    """

    def __init__(self, volume, sl, tp):
        self.volume = volume
        self.sl = sl
        self.tp = tp
        self.opened = False
        self.open_positions_at_bar_close = []

    def on_bar(self, bar, ctx):
        # Record open-position count seen at every bar close after entry.
        if self.opened:
            self.open_positions_at_bar_close.append(len(ctx.positions))
        if not self.opened and not ctx.positions:
            ctx.buy(self.volume, sl=self.sl, tp=self.tp)
            self.opened = True


class IntrabarFillTimingTests(_PinnedReconConstants):
    """The key tick-vs-bar fill-timing behavior."""

    def test_buy_sl_hit_by_intrabar_bid_tick_closes_within_bar(self):
        # Bar 0 (11:00-11:04) accumulates; the entry fires on the FIRST tick of
        # bar 1 (11:05:00) at ask 100.01, with SL 99.50 and a far TP.
        # DURING bar 1 (before it closes at 11:10) a bid tick dips to 99.40,
        # crossing the SL. In tick mode the broker must close the buy at 99.50
        # right then, so by the time bar 1 closes there are zero open positions.
        ticks = [
            _tick(0, 0, 100.00, 100.01),   # bar 0 opens
            _tick(4, 59, 100.02, 100.03),  # still bar 0
            _tick(5, 0, 100.00, 100.01),   # bar 1 boundary -> on_bar (bar 0 close), buy opens
            _tick(6, 0, 99.80, 99.81),     # intrabar, above SL
            _tick(7, 0, 99.40, 99.41),     # intrabar bid 99.40 <= SL 99.50 -> SL fires HERE
            _tick(8, 0, 99.90, 99.91),     # recovers within the same bar
            _tick(10, 0, 100.20, 100.21),  # bar 2 boundary -> on_bar (bar 1 close)
        ]
        strat = _OpenBuyOnceWithStop(volume=0.10, sl=99.50, tp=200.00)
        eng = Engine(strat, mode="tick", params={})
        result = eng.run(ticks)

        # The SL fired intrabar, so at the first bar-close AFTER entry the
        # position was already gone.
        self.assertTrue(strat.open_positions_at_bar_close)
        self.assertEqual(strat.open_positions_at_bar_close[0], 0)
        self.assertEqual(len(eng.broker.positions), 0)

        # Exactly one closed deal, closed at the SL price for an "sl" reason.
        self.assertEqual(len(eng.broker.ledger), 1)
        deal = eng.broker.ledger[0]
        self.assertEqual(deal.reason, "sl")
        self.assertAlmostEqual(deal.exit_price, 99.50)
        # gross = (99.50 - 100.01)/0.01 * 1.0 * 0.10 = -5.1 ; comm 3.0*0.10=0.30
        gross = (99.50 - 100.01) / config.TICK_SIZE * config.TICK_VALUE * 0.10
        self.assertAlmostEqual(deal.profit, gross - _RECON_COMMISSION_PER_SIDE * 0.10)
        self.assertEqual(result["metrics"]["total_trades"], 1)

    def test_bar_mode_misses_the_intrabar_dip_and_survives_to_bar_close(self):
        # SAME price path, but bar mode only checks SL/TP at each bar's closing
        # quote. Bar 1's close is 99.90/99.91 (the last tick before 11:10), which
        # is ABOVE the SL of 99.50, so the intrabar dip to 99.40 is NOT seen and
        # the position survives. This is exactly why bar mode is over-optimistic.
        ticks = [
            _tick(0, 0, 100.00, 100.01),
            _tick(4, 59, 100.02, 100.03),
            _tick(5, 0, 100.00, 100.01),
            _tick(6, 0, 99.80, 99.81),
            _tick(7, 0, 99.40, 99.41),     # the dip bar mode never checks
            _tick(8, 0, 99.90, 99.91),     # bar 1 closing quote (above SL)
            _tick(10, 0, 100.20, 100.21),
        ]
        strat = _OpenBuyOnceWithStop(volume=0.10, sl=99.50, tp=200.00)
        eng = Engine(strat, mode="bar", params={})
        eng.run(ticks)
        # Bar mode never fired the stop: no SL deal, position still open.
        self.assertEqual(len([d for d in eng.broker.ledger if d.reason == "sl"]), 0)
        self.assertEqual(len(eng.broker.positions), 1)


class PartialCloseCommissionTests(_PinnedReconConstants):
    """Commission is charged on the closed volume only, both sides."""

    def test_partial_close_commission_on_closed_volume_both_sides(self):
        b = Broker(deposit=1000.0)
        # Open 1.0 lot buy at ask 100.00. Open commission charged on FULL 1.0:
        #   3.0 * 1.0 = 3.00
        pos = b.open("buy", 1.0, price_bid=99.99, price_ask=100.00, ts=_ts())
        self.assertAlmostEqual(b.balance, 1000.0 - 3.0)

        # Partial close 0.30 lot at bid 101.00. Close commission on 0.30 ONLY:
        #   comm = 3.0 * 0.30 = 0.90
        #   gross = (101.00 - 100.00)/0.01 * 1.0 * 0.30 = 100 * 0.30 = 30.0
        #   net = 30.0 - 0.90 = 29.10
        d1 = b.close_partial(pos, 0.30, price_bid=101.00, price_ask=101.01, ts=_ts(1))
        self.assertAlmostEqual(d1.commission, 3.0 * 0.30)
        self.assertAlmostEqual(d1.profit, 30.0 - 0.90)
        self.assertFalse(d1.trade_closed)
        self.assertAlmostEqual(pos.volume_lots, 0.70)

        # Close the remaining 0.70 at bid 100.50. Close commission on 0.70 ONLY:
        #   comm = 3.0 * 0.70 = 2.10
        #   gross = (100.50 - 100.00)*100 * 0.70 = 50 * 0.70 = 35.0
        #   net = 35.0 - 2.10 = 32.90
        d2 = b.close_full(pos, price_bid=100.50, price_ask=100.51, ts=_ts(2))
        self.assertAlmostEqual(d2.commission, 3.0 * 0.70)
        self.assertAlmostEqual(d2.profit, 35.0 - 2.10)
        self.assertTrue(d2.trade_closed)

        # Total commission across both closes = closed-volume-proportional:
        #   open 3.0*1.0 + close 3.0*0.30 + close 3.0*0.70 = 3.0 + 0.90 + 2.10 = 6.0
        total_close_comm = d1.commission + d2.commission
        self.assertAlmostEqual(total_close_comm, 3.0)  # 3.0 on the round-turn close side
        self.assertEqual(len(b.ledger), 2)


class MoneyConversionTests(_PinnedReconConstants):
    """_pnl_money reproduces the MT5 deal reconciliation exactly."""

    def test_reconciliation_136_move_001_lot_is_136_usd(self):
        # MT5 deal 2/3: buy 0.01 @ 4166.33 -> sell out 0.01 @ 4164.97.
        # price move = -1.36 -> reported profit -1.36 USD (gross).
        gross = _pnl_money("buy", entry=4166.33, exit_price=4164.97, volume_lots=0.01)
        self.assertAlmostEqual(gross, -1.36, places=6)

    def test_one_dollar_move_per_lot_is_100_usd(self):
        # A 1.00 price move on 1.0 lot = 100 USD (100 oz contract).
        gross = _pnl_money("buy", entry=4000.00, exit_price=4001.00, volume_lots=1.0)
        self.assertAlmostEqual(gross, 100.0, places=6)

    def test_derived_usd_per_move_per_001_lot_is_one(self):
        # USD per 1.00 price move per 0.01 lot, derived from the formula.
        gross = _pnl_money("sell", entry=4200.00, exit_price=4199.00, volume_lots=0.01)
        per_move_per_001 = (gross / 1.00) / (0.01 / 0.01)
        self.assertAlmostEqual(per_move_per_001, 1.0, places=6)

    def test_config_implied_multiplier_matches_reconciliation(self):
        # (1.00 / TICK_SIZE) * TICK_VALUE * 0.01 == 1.00 USD per 1.00 move / 0.01 lot.
        config_per_move_per_001 = (1.0 / config.TICK_SIZE) * config.TICK_VALUE * 0.01
        self.assertAlmostEqual(config_per_move_per_001, 1.0, places=6)


class V213DefaultsTests(unittest.TestCase):
    """default_params() carries the EA v2.13 inputs FEAT-002 aligned."""

    def test_v213_calibrated_defaults_present(self):
        p = HappyBotStrategy.default_params()
        self.assertEqual(p["Pullback_Lookback"], 10)
        self.assertEqual(p["RSI_Buy_Max"], 75.0)
        self.assertEqual(p["RSI_Sell_Min"], 25.0)
        self.assertEqual(p["ATR_TP_Mult"], 3.5)
        self.assertEqual(p["Entry_Cooldown_Bars"], 1)


def _bar_rec(low, high, close, ema_ctf):
    """A single _recent record in the exact shape on_bar appends."""
    return {"low": low, "high": high, "close": close, "ema_ctf": ema_ctf}


class PullbackResumeOffByOneTests(unittest.TestCase):
    """Direct regression guard for the FEAT-002 pullback-resume off-by-one fix.

    The EA scans series indices i=2..Pullback_Lookback (that is lookback-1 bars
    immediately before the resume bar). The port's resume bar is _recent[-1];
    the correct window is the last (lookback-1) bars of _recent[:-1], i.e.
    _recent[-2] .. _recent[-lookback].

      NEW (fixed) code:  prior = _recent[:-1][-(lookback-1):]
      OLD (buggy) code:  prior = _recent[:-1][-lookback:]   (one bar too old)

    With Pullback_Lookback=3 the NEW window is {_recent[-3], _recent[-2]} while
    the OLD window also reaches _recent[-4]. We place the ONLY pullback bar (the
    one whose low crosses the CTF EMA) at exactly _recent[-4] so the boundary is
    unambiguous: the NEW code returns False, the OLD code would return True.
    These tests would FAIL if either helper were reverted to scan lookback bars.
    """

    _EMA = 100.0

    def _strat(self):
        s = HappyBotStrategy({"Pullback_Lookback": 3})
        # validate() may repair params; assert the value we rely on survived.
        self.assertEqual(int(s.params["Pullback_Lookback"]), 3)
        return s

    def test_bull_pullback_only_boundary_bar_excluded_by_fix(self):
        s = self._strat()
        ema = self._EMA
        # _recent[-5] .. _recent[-1]. Resume bar (-1): close above EMA.
        # ONLY _recent[-4] dips to/below the EMA (low <= ema); every other
        # candidate bar stays strictly above it. lookback=3 -> NEW window is
        # {-3, -2} (both above EMA -> False); OLD window adds -4 (a dip -> True).
        s._recent = [
            _bar_rec(low=105.0, high=110.0, close=107.0, ema_ctf=ema),  # -5 (outside both)
            _bar_rec(low=99.0, high=104.0, close=103.0, ema_ctf=ema),   # -4 boundary DIP (low<=ema)
            _bar_rec(low=101.0, high=106.0, close=105.0, ema_ctf=ema),  # -3 above ema
            _bar_rec(low=102.0, high=107.0, close=106.0, ema_ctf=ema),  # -2 above ema
            _bar_rec(low=103.0, high=112.0, close=108.0, ema_ctf=ema),  # -1 resume (close>ema)
        ]
        # With the fix the boundary dip at -4 is OUTSIDE the scan window.
        self.assertFalse(s._bull_pullback_resume(ema))

        # Sanity: move the dip INTO the fixed window (-3) and it resumes True,
        # proving the helper still detects a genuine in-window pullback.
        s._recent[2] = _bar_rec(low=99.0, high=106.0, close=105.0, ema_ctf=ema)
        s._recent[1] = _bar_rec(low=101.0, high=104.0, close=103.0, ema_ctf=ema)
        self.assertTrue(s._bull_pullback_resume(ema))

    def test_bear_pullback_only_boundary_bar_excluded_by_fix(self):
        s = self._strat()
        ema = self._EMA
        # Mirror image for the short side: resume bar close BELOW ema, and the
        # ONLY bar whose high pierces the EMA (high >= ema) sits at -4.
        s._recent = [
            _bar_rec(low=90.0, high=95.0, close=93.0, ema_ctf=ema),     # -5 (outside both)
            _bar_rec(low=96.0, high=101.0, close=97.0, ema_ctf=ema),    # -4 boundary SPIKE (high>=ema)
            _bar_rec(low=94.0, high=99.0, close=95.0, ema_ctf=ema),     # -3 below ema
            _bar_rec(low=93.0, high=98.0, close=94.0, ema_ctf=ema),     # -2 below ema
            _bar_rec(low=88.0, high=97.0, close=92.0, ema_ctf=ema),     # -1 resume (close<ema)
        ]
        self.assertFalse(s._bear_pullback_resume(ema))

        # Move the spike into the fixed window (-3): now it resumes True.
        s._recent[2] = _bar_rec(low=94.0, high=101.0, close=95.0, ema_ctf=ema)
        s._recent[1] = _bar_rec(low=96.0, high=99.0, close=97.0, ema_ctf=ema)
        self.assertTrue(s._bear_pullback_resume(ema))


class _StubPos:
    """Minimal open-position stand-in for _distance_ok (only side + entry)."""

    def __init__(self, side, entry_price):
        self.side = side
        self.entry_price = entry_price


class _StubCtx:
    """Minimal ctx carrying just the open positions _distance_ok reads."""

    def __init__(self, positions):
        self.positions = positions


class DistanceOkReferencePriceTests(unittest.TestCase):
    """Pin the _distance_ok reference-price semantics (it takes ref_price now).

    The mid->bid switch (FEAT-002) changed the de-clustering gate to compare the
    live reference price (ctx.bid in tick mode) against each same-side open
    position, replacing the closed-bar mid. This is hard to exercise end-to-end
    at the unit level (it needs a full engine run with htf/ctf trend flipping on
    the reference price). Rather than assert nothing, we pin the direct
    contract: _distance_ok(side, ref_price, ctx) measures distance FROM the
    passed ref_price, in POINTS, only against SAME-side positions.

    A different ref_price flips the same fixture from blocked to allowed, which
    is exactly the behavior that makes bid-vs-mid matter: had the switch been
    reverted to pass the mid, the gate would evaluate a different distance.
    """

    def test_distance_measured_from_ref_price_same_side_only(self):
        s = HappyBotStrategy({})
        # One open long at 100.00. Min_Trade_Distance is in POINTS (POINT_SIZE
        # = 0.01), so 50 points == 0.50 in price.
        s.params["Min_Trade_Distance"] = 50
        ctx = _StubCtx([_StubPos("buy", 100.00)])

        # ref_price 100.10 is 10 points from the open long -> too close -> blocked.
        self.assertFalse(s._distance_ok("buy", 100.10, ctx))
        # ref_price 100.80 is 80 points away -> far enough -> allowed. Same
        # fixture, different reference price flips the outcome (bid vs mid).
        self.assertTrue(s._distance_ok("buy", 100.80, ctx))
        # Opposite side is never gated by a long position.
        self.assertTrue(s._distance_ok("sell", 100.10, ctx))


if __name__ == "__main__":
    unittest.main()
