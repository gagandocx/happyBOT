import unittest

from tests import _bootstrap  # noqa: F401
import mq5_rewriter


# Small fixture with varied whitespace, a trailing comment, a double, an int,
# and a NAME that is a substring of another identifier (StopLoss_Pips vs
# StopLoss_Pips_Extra).
FIXTURE = (
    "//+---+\n"
    "input group \"=== LOT SIZE ===\"\n"
    "input double          Risk_Percent        = 1.0;\n"
    "input int             StopLoss_Pips       = 1000;   // in points\n"
    "input int             StopLoss_Pips_Extra = 42;\n"
    "input int             T1_Pips             = 500;\n"
    "int notAnInput = StopLoss_Pips + 3;\n"
)


class TestRewriter(unittest.TestCase):
    def test_same_value_roundtrip_byte_identical(self):
        out = mq5_rewriter.rewrite_text(
            FIXTURE,
            {"Risk_Percent": 1.0, "StopLoss_Pips": 1000, "T1_Pips": 500},
        )
        self.assertEqual(out, FIXTURE)

    def test_only_targeted_literal_changes(self):
        out = mq5_rewriter.rewrite_text(FIXTURE, {"T1_Pips": 600})
        lines_before = FIXTURE.split("\n")
        lines_after = out.split("\n")
        self.assertEqual(len(lines_before), len(lines_after))
        for a, b in zip(lines_before, lines_after):
            if "T1_Pips " in a and a.strip().startswith("input"):
                self.assertNotEqual(a, b)
                self.assertIn("600", b)
            else:
                self.assertEqual(a, b)

    def test_double_keeps_decimal(self):
        out = mq5_rewriter.rewrite_text(FIXTURE, {"Risk_Percent": 2})
        self.assertIn("Risk_Percent        = 2.0;", out)

    def test_int_stays_int(self):
        out = mq5_rewriter.rewrite_text(FIXTURE, {"StopLoss_Pips": 1500})
        self.assertIn("StopLoss_Pips       = 1500;   // in points", out)

    def test_trailing_comment_preserved(self):
        out = mq5_rewriter.rewrite_text(FIXTURE, {"StopLoss_Pips": 900})
        self.assertIn("// in points", out)

    def test_substring_name_not_clobbered(self):
        out = mq5_rewriter.rewrite_text(FIXTURE, {"StopLoss_Pips": 1234})
        # The _Extra line and the plain assignment line must be untouched.
        self.assertIn("StopLoss_Pips_Extra = 42;", out)
        self.assertIn("int notAnInput = StopLoss_Pips + 3;", out)

    def test_missing_name_raises_and_no_corruption(self):
        with self.assertRaises(mq5_rewriter.MissingInputError):
            mq5_rewriter.rewrite_text(FIXTURE, {"Does_Not_Exist": 5})

    def test_read_values(self):
        vals = mq5_rewriter.read_values(
            FIXTURE, ["Risk_Percent", "StopLoss_Pips", "T1_Pips"]
        )
        self.assertEqual(vals["Risk_Percent"], 1.0)
        self.assertEqual(vals["StopLoss_Pips"], 1000)
        self.assertEqual(vals["T1_Pips"], 500)
        self.assertIsInstance(vals["Risk_Percent"], float)
        self.assertIsInstance(vals["StopLoss_Pips"], int)

    def test_read_substring_gets_right_value(self):
        vals = mq5_rewriter.read_values(FIXTURE, ["StopLoss_Pips"])
        self.assertEqual(vals["StopLoss_Pips"], 1000)


if __name__ == "__main__":
    unittest.main()
