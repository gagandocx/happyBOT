import unittest

from tests import _bootstrap  # noqa: F401
import params


class TestParams(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertTrue(params.is_valid(params.validate(params.defaults())))

    def test_clamp_to_bounds(self):
        v = params.validate({"Risk_Percent": 999.0, "Max_Concurrent_Positions": -5})
        self.assertLessEqual(v["Risk_Percent"], params.PARAMS["Risk_Percent"].maximum)
        self.assertGreaterEqual(
            v["Max_Concurrent_Positions"], params.PARAMS["Max_Concurrent_Positions"].minimum
        )

    def test_step_snapping(self):
        # Risk_Percent step is 0.25; 1.1 should snap to a multiple of 0.25.
        v = params.validate({"Risk_Percent": 1.1})
        remainder = round((v["Risk_Percent"] - params.PARAMS["Risk_Percent"].minimum) / 0.25, 6)
        self.assertEqual(remainder, round(remainder))

    def test_ordering_repaired_when_inverted(self):
        # Deliberately inverted / colliding order.
        bad = {"T1_Pips": 2000, "T2_Pips": 500, "T3_Pips": 300, "StopLoss_Pips": 400}
        v = params.validate(bad)
        self.assertLess(v["T1_Pips"], v["T2_Pips"])
        self.assertLess(v["T2_Pips"], v["T3_Pips"])
        self.assertLessEqual(v["T3_Pips"], v["StopLoss_Pips"])
        self.assertTrue(params.is_valid(v))

    def test_ordering_repaired_when_equal(self):
        bad = {"T1_Pips": 800, "T2_Pips": 800, "T3_Pips": 800, "StopLoss_Pips": 800}
        v = params.validate(bad)
        self.assertLess(v["T1_Pips"], v["T2_Pips"])
        self.assertLess(v["T2_Pips"], v["T3_Pips"])
        self.assertLessEqual(v["T3_Pips"], v["StopLoss_Pips"])

    def test_t3_exceeds_stoploss_repaired(self):
        bad = {"T1_Pips": 500, "T2_Pips": 1000, "T3_Pips": 3000, "StopLoss_Pips": 400}
        v = params.validate(bad)
        self.assertLessEqual(v["T3_Pips"], v["StopLoss_Pips"])
        self.assertTrue(params.is_valid(v))

    def test_type_preservation(self):
        v = params.validate(params.defaults())
        self.assertIsInstance(v["Risk_Percent"], float)
        self.assertIsInstance(v["T1_ClosePercent"], float)
        self.assertIsInstance(v["T2_ClosePercent"], float)
        self.assertIsInstance(v["StopLoss_Pips"], int)
        self.assertIsInstance(v["T1_Pips"], int)
        self.assertIsInstance(v["Entry_Cooldown_Bars"], int)
        self.assertIsInstance(v["Max_Concurrent_Positions"], int)

    def test_missing_keys_filled_with_defaults(self):
        v = params.validate({})
        for name in params.PARAM_NAMES:
            self.assertIn(name, v)

    def test_unknown_keys_ignored(self):
        v = params.validate({"NotAParam": 5, "Risk_Percent": 0.5})
        self.assertNotIn("NotAParam", v)

    def test_fuzz_always_valid(self):
        # A spread of adversarial inputs must always repair to a valid vector.
        cases = [
            {"T1_Pips": 0, "T2_Pips": 0, "T3_Pips": 0, "StopLoss_Pips": 0},
            {"T1_Pips": 5000, "T2_Pips": 100, "T3_Pips": 100, "StopLoss_Pips": 100},
            {"T1_Pips": 100, "T2_Pips": 150, "T3_Pips": 200, "StopLoss_Pips": 100},
            {"T3_Pips": 3000, "StopLoss_Pips": 400},
        ]
        for c in cases:
            self.assertTrue(params.is_valid(params.validate(c)), c)


if __name__ == "__main__":
    unittest.main()
