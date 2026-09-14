"""Fast tests for the calibrate.py MT5 parser + deal reconciliation.

Parses the REAL MT5 report data/ReportTester-470903.html (tracked, ~471 KB,
UTF-16 HTML) and asserts:
  * the summary parse: net +51.50, 209 trades, win 43.54%, PF 1.14;
  * the deal table pairs into 209 round-trip trades whose net sums to +51.50;
  * the deal-money reconciliation derives ~1.00 USD per 1.00 price move per
    0.01 lot, agreeing with config.TICK_VALUE=1.0 / CONTRACT_SIZE=100.

This ONLY parses the small HTML report; it never runs the engine on the 526 MB
CSV. If the report is not present (it is tracked, so it should be) the tests
skip rather than fail, keeping the suite green in a stripped checkout.

Pure ASCII. stdlib unittest only.
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from python_bt import config  # noqa: E402
from python_bt import calibrate  # noqa: E402

_REPORT = os.path.join(_REPO_ROOT, "data", "ReportTester-470903.html")


@unittest.skipUnless(os.path.exists(_REPORT), "MT5 report fixture not present")
class Mt5ReportParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Parse once; parsing the 471 KB report is fast.
        cls.parsed = calibrate.parse_mt5_report(_REPORT)

    def test_no_parse_error(self):
        self.assertNotIn("error", self.parsed)

    def test_summary_metrics_match_mt5_truth(self):
        summary = self.parsed["summary_metrics"]
        self.assertAlmostEqual(summary["total_net_profit"], 51.50, places=2)
        self.assertEqual(summary["total_trades"], 209)
        self.assertAlmostEqual(summary["win_rate_pct"], 43.54, places=2)
        self.assertAlmostEqual(summary["profit_factor"], 1.14, places=2)

    def test_deal_table_pairs_into_209_trades_summing_to_net(self):
        trades = self.parsed["trades"]
        self.assertEqual(len(trades), 209)
        net = sum(float(t["net"]) for t in trades)
        # Net-of-commission trade P&L reconciles to the reported +51.50 net.
        self.assertAlmostEqual(net, 51.50, places=2)

    def test_deal_summary_derived_from_table(self):
        # The deal-derived summary exposes 209 trades / 418 deals as a
        # cross-check of the report summary.
        ds = self.parsed["deal_summary"]
        self.assertEqual(ds["total_trades"], 209)
        self.assertEqual(ds["total_deals"], 418)


@unittest.skipUnless(os.path.exists(_REPORT), "MT5 report fixture not present")
class ReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = calibrate.parse_mt5_report(_REPORT)
        cls.recon = calibrate.reconcile_deals(cls.parsed["trades"])

    def test_derived_usd_per_move_per_001_lot_is_about_one(self):
        obs = self.recon["observed_usd_per_move_per_001lot"]
        self.assertIsNotNone(obs)
        # ~1.00 USD per 1.00 price move per 0.01 lot.
        self.assertAlmostEqual(obs, 1.0, places=2)

    def test_reconciliation_agrees_with_config(self):
        self.assertTrue(self.recon["agrees"])
        self.assertLessEqual(self.recon["max_abs_error"], self.recon["tolerance"])
        # config-implied multiplier equals the reconciled 1.00.
        self.assertAlmostEqual(
            self.recon["config_usd_per_move_per_001lot"], 1.0, places=6)

    def test_config_constants_are_the_reconciled_values(self):
        # The reconciliation confirms (does not change) these constants.
        self.assertEqual(config.TICK_VALUE, 1.0)
        self.assertEqual(config.TICK_SIZE, 0.01)
        self.assertEqual(config.CONTRACT_SIZE, 100)


if __name__ == "__main__":
    unittest.main()
