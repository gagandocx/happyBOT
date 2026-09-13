"""Tests for python_bt.research: config parsing, ranking, and end-to-end run.

The ranking tests use canned result rows (no engine run) to assert the core
guarantee: a higher-score config ranks first and an over-15%-relative-DD config
ranks LAST, because scoring.py banishes over-ceiling candidates below every
compliant one. A separate end-to-end test drives the full harness on a tiny
generated tick CSV (never the 526 MB real CSV) and checks a results JSON is
written and valid.
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

from python_bt import research  # noqa: E402
from python_bt.scoring_bridge import score  # noqa: E402


def _row(label, net_profit, dd_pct, pf=1.5, trades=50):
    """Build a canned leaderboard row with a real score from scoring.py."""
    metrics = {
        "total_net_profit": net_profit,
        "relative_drawdown_pct": dd_pct,
        "profit_factor": pf,
        "total_trades": trades,
    }
    return {
        "label": label,
        "strategy": "gagan",
        "params": {},
        "metrics": metrics,
        "score": score(metrics),
        "meta": {},
        "diagnosis": {"verdict": "test", "flags": []},
    }


class RankResultsTests(unittest.TestCase):
    def test_higher_score_ranks_first(self):
        low = _row("low-profit", net_profit=100.0, dd_pct=5.0)
        high = _row("high-profit", net_profit=500.0, dd_pct=5.0)
        ranked = research.rank_results([low, high])
        self.assertEqual(ranked[0]["label"], "high-profit")
        self.assertEqual(ranked[-1]["label"], "low-profit")

    def test_over_ceiling_config_ranks_last(self):
        # A compliant but LOSING config must still outrank a hugely profitable
        # but over-15%-DD config, per the hard ceiling in scoring.py.
        compliant_losing = _row("compliant-losing", net_profit=-50.0, dd_pct=10.0)
        over_ceiling_rich = _row("over-ceiling-rich", net_profit=100000.0, dd_pct=40.0)
        ranked = research.rank_results([over_ceiling_rich, compliant_losing])
        self.assertEqual(ranked[0]["label"], "compliant-losing")
        self.assertEqual(ranked[-1]["label"], "over-ceiling-rich")

    def test_full_ordering(self):
        rows = [
            _row("over-ceiling", net_profit=9999.0, dd_pct=25.0),
            _row("best", net_profit=800.0, dd_pct=8.0),
            _row("mid", net_profit=300.0, dd_pct=8.0),
        ]
        ranked = research.rank_results(rows)
        self.assertEqual([r["label"] for r in ranked], ["best", "mid", "over-ceiling"])

    def test_none_score_sorts_last(self):
        good = _row("good", net_profit=100.0, dd_pct=5.0)
        broken = {"label": "broken", "score": None, "metrics": {}, "diagnosis": {}}
        ranked = research.rank_results([broken, good])
        self.assertEqual(ranked[0]["label"], "good")
        self.assertEqual(ranked[-1]["label"], "broken")


class LoadConfigsTests(unittest.TestCase):
    def test_inline_json_normalizes_defaults(self):
        cfgs = research._load_configs('[{"strategy": "gagan"}, {"label": "x"}]')
        self.assertEqual(cfgs[0]["strategy"], "gagan")
        self.assertEqual(cfgs[0]["params"], {})
        self.assertTrue(cfgs[0]["label"])  # synthesized
        self.assertEqual(cfgs[1]["strategy"], "gagan")  # default strategy
        self.assertEqual(cfgs[1]["label"], "x")

    def test_at_file(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "c.json")
        with open(path, "w") as fh:
            json.dump([{"strategy": "gagan", "params": {"Risk_Percent": 0.5}, "label": "r05"}], fh)
        cfgs = research._load_configs("@" + path)
        self.assertEqual(cfgs[0]["label"], "r05")
        self.assertEqual(cfgs[0]["params"]["Risk_Percent"], 0.5)

    def test_non_list_rejected(self):
        with self.assertRaises(ValueError):
            research._load_configs('{"strategy": "gagan"}')

    def test_empty_returns_empty(self):
        self.assertEqual(research._load_configs(None), [])


def _write_tiny_csv(path):
    """Write a small tab-separated, CRLF CSV in the verified tick format."""
    lines = ["<DATE>\t<TIME>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>\t<FLAGS>"]
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


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.csv = os.path.join(self.tmp, "tiny.csv")
        _write_tiny_csv(self.csv)
        self.results_dir = os.path.join(self.tmp, "pybt")

    def test_main_writes_valid_small_results_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = research.main([
                "--data", self.csv, "--baseline", "--mode", "bar",
                "--max-ticks", "500", "--results-dir", self.results_dir,
            ])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("LEADERBOARD", out)
        self.assertIn("wrote results:", out)
        files = os.listdir(self.results_dir)
        self.assertEqual(len(files), 1)
        path = os.path.join(self.results_dir, files[0])
        self.assertLess(os.path.getsize(path), 1024 * 1024)  # small
        with open(path) as fh:
            payload = json.load(fh)
        self.assertIn("leaderboard", payload)
        self.assertIn("run", payload)
        self.assertTrue(payload["leaderboard"])  # at least the baseline row

    def test_no_write_skips_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = research.main([
                "--data", self.csv, "--mode", "bar", "--max-ticks", "500",
                "--no-write", "--results-dir", self.results_dir,
            ])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.isdir(self.results_dir))

    def test_run_research_returns_ranked_rows(self):
        configs = [
            {"strategy": "gagan", "params": {}, "label": "a"},
            {"strategy": "gagan", "params": {"Risk_Percent": 0.5}, "label": "b"},
        ]
        rows = research.run_research(configs, self.csv, mode="bar", max_ticks=500)
        self.assertEqual(len(rows), 2)
        # Scores are monotonically non-increasing (ranked desc).
        scores = [r["score"] for r in rows if isinstance(r["score"], (int, float))]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
