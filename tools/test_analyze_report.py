#!/usr/bin/env python3
"""Standard-library unittest suite for tools/analyze_report.py.

Locks in the analyzer's behavior against the two synthetic sample reports and
verifies the fixes from the v1 semantic review:

  * The per-deal aggregate is computed from the true "Profit" column (not the
    running "Balance" column), so the money sum and win/loss counts are honest.
  * An empty or unparseable report yields an INCONCLUSIVE verdict rather than
    "LOOKS REASONABLE".

stdlib ONLY (unittest, os, tempfile). No third-party packages, no pip.

Run:
    python3 -m unittest discover -s tools -p 'test_*.py'
    python3 tools/test_analyze_report.py
"""

import os
import tempfile
import unittest

import analyze_report as ar


_HERE = os.path.dirname(os.path.abspath(__file__))
_SAMPLES = os.path.normpath(os.path.join(_HERE, "..", "reports", "samples"))
_SAMPLE_NEW = os.path.join(_SAMPLES, "sample_report.html")
_SAMPLE_OLD = os.path.join(_SAMPLES, "sample_report_old.html")


def _analyze(path):
    """Run the analyzer end-to-end without writing JSON side effects."""
    return ar.analyze_file(path, write_json=False)


class NewSampleMetricsTest(unittest.TestCase):
    """Metric extraction on the newer Strategy Tester layout."""

    @classmethod
    def setUpClass(cls):
        cls.summary = _analyze(_SAMPLE_NEW)
        cls.metrics = cls.summary["metrics"]

    def test_headline_metrics(self):
        m = self.metrics
        self.assertAlmostEqual(m["total_net_profit"], 4812.55, places=2)
        self.assertAlmostEqual(m["profit_factor"], 1.43, places=2)
        self.assertEqual(m["total_trades"], 280)
        self.assertAlmostEqual(m["win_rate_pct"], 61.43, places=2)

    def test_drawdown_split(self):
        m = self.metrics
        self.assertAlmostEqual(m["relative_drawdown_pct"], 16.75, places=2)
        self.assertAlmostEqual(m["relative_drawdown_money"], 1720.10, places=2)
        self.assertAlmostEqual(m["maximal_drawdown_pct"], 18.42, places=2)
        self.assertAlmostEqual(m["maximal_drawdown_money"], 1889.30, places=2)

    def test_consecutive_losses_money(self):
        self.assertAlmostEqual(
            self.metrics["max_consecutive_losses_money"], -1502.10, places=2)

    def test_verdict_reasonable(self):
        self.assertEqual(
            self.summary["diagnosis"]["verdict"],
            "LOOKS REASONABLE (no warnings)")


class TradeTableProfitColumnTest(unittest.TestCase):
    """The aggregate must reflect the Profit column, not the Balance column."""

    @classmethod
    def setUpClass(cls):
        cls.summary = _analyze(_SAMPLE_NEW)
        cls.tt = cls.summary["trade_table"]

    def test_profit_column_detected(self):
        self.assertTrue(self.tt["profit_column_found"])
        # Time, Deal, Type, Volume, Price, Profit(=5), Balance(=6)
        self.assertEqual(self.tt["aggregate"]["profit_column_index"], 5)

    def test_row_count(self):
        self.assertEqual(self.tt["count"], 6)

    def test_profit_sum_is_profit_not_balance(self):
        # Profit column: 0 + 138 + 0 - 157.50 + 0 + 364 = 344.50
        # (NOT the Balance column which would sum to ~60,581.50)
        self.assertAlmostEqual(
            self.tt["aggregate"]["sum_profit_column"], 344.50, places=2)

    def test_win_loss_flat_counts(self):
        agg = self.tt["aggregate"]
        self.assertEqual(agg["positive_count"], 2)
        self.assertEqual(agg["negative_count"], 1)
        self.assertEqual(agg["zero_count"], 3)


class OldSampleTest(unittest.TestCase):
    """Older ReportTester layout: metrics parse, no trade table present."""

    @classmethod
    def setUpClass(cls):
        cls.summary = _analyze(_SAMPLE_OLD)

    def test_metrics(self):
        m = self.summary["metrics"]
        self.assertAlmostEqual(m["total_net_profit"], 2145.90, places=2)
        self.assertAlmostEqual(m["profit_factor"], 1.28, places=2)
        self.assertAlmostEqual(m["relative_drawdown_pct"], 24.30, places=2)
        self.assertEqual(m["total_trades"], 202)

    def test_no_trade_table(self):
        self.assertEqual(self.summary["trade_table"]["count"], 0)
        self.assertFalse(self.summary["trade_table"]["profit_column_found"])
        self.assertIsNone(self.summary["trade_table"]["aggregate"])

    def test_verdict_needs_improvement(self):
        # 24.30% relative DD (>20%) and a large consecutive-loss streak -> warn.
        self.assertEqual(
            self.summary["diagnosis"]["verdict"],
            "NEEDS IMPROVEMENT (warnings present)")


class InconclusiveVerdictTest(unittest.TestCase):
    """Empty / garbage reports must NOT read as reasonable."""

    def _verdict_for_html(self, html):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False, encoding="utf-8") as fh:
            fh.write(html)
            path = fh.name
        try:
            return _analyze(path)["diagnosis"]["verdict"]
        finally:
            os.unlink(path)

    def test_empty_report_is_inconclusive(self):
        self.assertEqual(
            self._verdict_for_html(""),
            "INCONCLUSIVE (insufficient metrics parsed)")

    def test_garbage_report_is_inconclusive(self):
        html = "<html><body>random junk not a report<p>hi</p></body></html>"
        self.assertEqual(
            self._verdict_for_html(html),
            "INCONCLUSIVE (insufficient metrics parsed)")

    def test_partial_report_below_threshold_is_inconclusive(self):
        # Only one core metric (net profit) present -> below the 2-metric floor.
        html = ("<html><body><table>"
                "<tr><td>Total Net Profit:</td><td>1234.56</td></tr>"
                "</table></body></html>")
        self.assertEqual(
            self._verdict_for_html(html),
            "INCONCLUSIVE (insufficient metrics parsed)")


class NumberNormalizationTest(unittest.TestCase):
    """A few direct checks on the number/percent-money helpers."""

    def test_normalize_thousands_and_currency(self):
        self.assertAlmostEqual(ar.normalize_number("15 940.20"), 15940.20, places=2)
        self.assertAlmostEqual(ar.normalize_number("$1,234.56"), 1234.56, places=2)
        self.assertAlmostEqual(ar.normalize_number("-7,734.50"), -7734.50, places=2)

    def test_split_percent_money(self):
        pct, money = ar.split_percent_money("16.75% (1 720.10)")
        self.assertAlmostEqual(pct, 16.75, places=2)
        self.assertAlmostEqual(money, 1720.10, places=2)
        pct2, money2 = ar.split_percent_money("1 889.30 (18.42%)")
        self.assertAlmostEqual(pct2, 18.42, places=2)
        self.assertAlmostEqual(money2, 1889.30, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
