"""Tests for the repair-vs-nudge delta classification in tuner.propose_next.

These lock the composed propose_next -> params.validate path, in particular the
three ORIGIN cases for a param that ends up changed:

  * collision   - a nudge/coordinate step moved a param AND validate then
                  overrode that move (e.g. the seeded-invalid v2.11 first run:
                  the pf<1 rule tightens StopLoss_Pips down, ordering-repair
                  then raises it to satisfy T3 <= StopLoss). Must be reported as
                  "repair overrode nudge", NOT "not a nudge".
  * repair_only - validate changed a param that NO nudge/step touched. Reported
                  as "ordering/bounds repair (not a nudge)".
  * nudge-only  - a nudge/step moved a param and validate left it alone. Must
                  NOT appear in repair_names.
"""

import unittest

from tests import _bootstrap  # noqa: F401  (sets up sys.path)
import params
import tuner


def _state(current):
    """A minimal state dict (no best -> base = current) at iteration 0."""
    return {
        "version": 1,
        "iteration": 0,
        "current": dict(current),
        "best": None,
        "history": [],
    }


def _seeded_invalid_v211():
    """The shipped v2.11 vector: T3_Pips=1800 > StopLoss_Pips=1000 (invalid
    ordering), all other params at their v2.11 defaults."""
    v = params.defaults()
    v["T3_Pips"] = 1800
    v["StopLoss_Pips"] = 1000
    return v


class TestDeltaSplit(unittest.TestCase):
    def test_collision_stoploss_nudged_then_repaired(self):
        # Metrics that trip pf<1 (mirrors the real v2.11 baseline: PF 0.58,
        # DD 28.36, 1012 trades). The pf<1 rule steps StopLoss_Pips DOWN
        # (1000->900), then ordering-repair raises it to 1800 (>= T3=1800).
        metrics = {
            "profit_factor": 0.58,
            "relative_drawdown_pct": 28.36,
            "total_trades": 1012,
            "total_net_profit": -500.0,
        }
        state = _state(_seeded_invalid_v211())
        valid, notes, repair_names, repair_only, collision = tuner.propose_next(
            state, metrics, {"metrics": metrics}
        )

        # Final written value is legal and the repair raised StopLoss to fit T3.
        self.assertTrue(params.is_valid(valid))
        self.assertEqual(valid["StopLoss_Pips"], 1800)

        # StopLoss_Pips is a COLLISION: validate raised it (it is in
        # repair_names) AND a nudge (pf<1) targeted it, so it must be classified
        # as a collision, NOT as pure repair.
        self.assertIn("StopLoss_Pips", repair_names)
        self.assertIn("StopLoss_Pips", collision)
        self.assertNotIn("StopLoss_Pips", repair_only)

        # The notes must NOT claim StopLoss_Pips is "not a nudge"; they must
        # carry the collision wording instead.
        joined = "; ".join(notes)
        self.assertIn("repair overrode nudge: StopLoss_Pips", joined)
        self.assertNotIn("not a nudge): StopLoss_Pips", joined)
        # The pf<1 diagnosis note is still present (the nudge DID target it).
        self.assertTrue(any("pf<1" in n for n in notes))

    def test_pure_repair_no_nudge_touched(self):
        # Benign metrics: no rule fires (PF >= 1, DD <= 15, trades <= 400), so
        # only the coordinate-descent step moves a param. At iteration 0 the
        # step targets Risk_Percent (index 0), NOT StopLoss_Pips. The seeded
        # ordering violation (T3=1800 > StopLoss=1000) is then repaired by
        # validate alone -> StopLoss_Pips is a PURE repair.
        metrics = {
            "profit_factor": 1.50,
            "relative_drawdown_pct": 5.0,
            "total_trades": 100,
            "total_net_profit": 200.0,
        }
        state = _state(_seeded_invalid_v211())
        valid, notes, repair_names, repair_only, collision = tuner.propose_next(
            state, metrics, {"metrics": metrics}
        )

        self.assertTrue(params.is_valid(valid))
        self.assertEqual(valid["StopLoss_Pips"], 1800)

        # StopLoss_Pips was changed only by validate, with no nudge touching it.
        self.assertIn("StopLoss_Pips", repair_names)
        self.assertIn("StopLoss_Pips", repair_only)
        self.assertNotIn("StopLoss_Pips", collision)

        joined = "; ".join(notes)
        self.assertIn("ordering/bounds repair (not a nudge): StopLoss_Pips", joined)
        self.assertNotIn("repair overrode nudge", joined)
        # No pf<1 note here since PF >= 1.
        self.assertFalse(any("pf<1" in n for n in notes))

    def test_pure_nudge_not_in_repair_names(self):
        # A legal starting vector (T3 <= StopLoss) so ordering-repair does not
        # fire. DD > 15 trips the risk-cut rule, which steps Risk_Percent DOWN
        # (1.0 -> 0.75), a value that stays legal, so validate leaves it alone.
        start = params.defaults()
        start["T3_Pips"] = 900          # <= StopLoss_Pips (1000): already legal
        metrics = {
            "profit_factor": 1.20,
            "relative_drawdown_pct": 30.0,  # trips dd>15 -> cut Risk_Percent
            "total_trades": 100,
            "total_net_profit": 100.0,
        }
        state = _state(start)
        # iteration 9 -> coordinate step targets Entry_Cooldown_Bars (index 9),
        # NOT Risk_Percent, so the dd>15 cut on Risk_Percent is not cancelled by
        # the coordinate step stepping it back up.
        state["iteration"] = 9
        valid, notes, repair_names, repair_only, collision = tuner.propose_next(
            state, metrics, {"metrics": metrics}
        )

        self.assertTrue(params.is_valid(valid))
        # Risk_Percent was nudged down and survived validation unchanged.
        self.assertEqual(valid["Risk_Percent"], 0.75)
        self.assertNotIn("Risk_Percent", repair_names)
        self.assertNotIn("Risk_Percent", repair_only)
        self.assertNotIn("Risk_Percent", collision)
        # The dd>15 diagnosis note is present.
        self.assertTrue(any("dd>" in n for n in notes))

    def test_repair_names_is_union_of_buckets(self):
        # The full repair set must equal repair_only + collision (no overlap,
        # no leakage) so the delta split in run() routes every repaired param.
        metrics = {
            "profit_factor": 0.58,
            "relative_drawdown_pct": 28.36,
            "total_trades": 1012,
        }
        state = _state(_seeded_invalid_v211())
        _, _, repair_names, repair_only, collision = tuner.propose_next(
            state, metrics, {"metrics": metrics}
        )
        self.assertEqual(set(repair_only) & set(collision), set())
        self.assertEqual(set(repair_names), set(repair_only) | set(collision))


if __name__ == "__main__":
    unittest.main()
