"""Tests for python_bt.runner CLI on a tiny generated tick CSV.

Writes a small tab-separated CSV in the exact loader format to a temp path,
then invokes the runner's main() with --max-ticks and asserts it runs, prints
metrics + a score, and that --json writes valid JSON. Never uses the 526 MB CSV.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from python_bt import runner  # noqa: E402


def _write_tiny_csv(path):
    """Write a small tab-separated, CRLF CSV in the verified tick format."""
    lines = ["<DATE>\t<TIME>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>\t<FLAGS>"]
    # A short walk across a few M5 buckets during a valid session hour (10:00).
    price = 3975.00
    minute = 0
    sec = 0
    for i in range(400):
        bid = price + i * 0.05
        ask = bid + 0.05
        t = "10:{:02d}:{:02d}.000".format(minute, sec)
        lines.append("2026.07.01\t{}\t{:.2f}\t{:.2f}\t\t\t6".format(t, bid, ask))
        sec += 30
        if sec >= 60:
            sec = 0
            minute += 1
    with open(path, "w", newline="") as fh:
        fh.write("\r\n".join(lines) + "\r\n")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.csv = os.path.join(self.tmp, "tiny.csv")
        _write_tiny_csv(self.csv)

    def test_run_prints_metrics_and_score(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = runner.main([
                "--data", self.csv, "--strategy", "happybot",
                "--mode", "bar", "--max-ticks", "500",
            ])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("metrics", out)
        self.assertIn("tuner SCORE", out)
        self.assertIn("VERDICT", out)

    def test_json_output_is_valid(self):
        out_json = os.path.join(self.tmp, "out.json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = runner.main([
                "--data", self.csv, "--strategy", "happybot",
                "--mode", "bar", "--json", out_json,
            ])
        self.assertEqual(rc, 0)
        with open(out_json) as fh:
            result = json.load(fh)
        self.assertIn("metrics", result)
        self.assertIn("score", result)
        self.assertIn("diagnosis", result)
        self.assertEqual(result["strategy"], "happybot")

    def test_compare_two_param_sets(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = runner.main([
                "--data", self.csv, "--compare",
                "--params", "{}", "--params", '{"Risk_Percent": 2.0}',
                "--mode", "bar", "--max-ticks", "500",
            ])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("COMPARISON", out)
        self.assertIn("WINNER", out)

    def test_warmup_note_helper(self):
        # Zero trades + not warmed up -> note returned.
        note = runner._warmup_note(
            {"total_trades": 0},
            {"warmup": {"warmed_up": False, "note": "insufficient warm-up: HTF EMA not ready"}},
        )
        self.assertIn("warm-up", note)
        # Warmed up (flat strategy) -> no note even with zero trades.
        self.assertIsNone(runner._warmup_note(
            {"total_trades": 0}, {"warmup": {"warmed_up": True, "note": ""}}))
        # Trades occurred -> no note.
        self.assertIsNone(runner._warmup_note(
            {"total_trades": 3}, {"warmup": {"warmed_up": False, "note": "x"}}))
        # No warmup info at all -> no note.
        self.assertIsNone(runner._warmup_note({"total_trades": 0}, {}))

    def test_run_prints_warmup_note_on_short_slice(self):
        # The tiny CSV never warms the HTF EMA200, so the runner must print the
        # warm-up NOTE instead of leaving a bare zero-trade result.
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = runner.main([
                "--data", self.csv, "--strategy", "happybot", "--mode", "bar",
            ])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("insufficient warm-up", out)

    def test_params_at_file(self):
        pfile = os.path.join(self.tmp, "p.json")
        with open(pfile, "w") as fh:
            json.dump({"Risk_Percent": 0.5}, fh)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = runner.main([
                "--data", self.csv, "--params", "@" + pfile,
                "--mode", "bar", "--max-ticks", "500",
            ])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
