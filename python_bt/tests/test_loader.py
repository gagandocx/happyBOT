"""Tests for python_bt.loader using tiny inline fixtures.

Never touches the 526 MB CSV; every fixture is a few-line temp file written in
the exact verified tab format (with the '<DATE>' header, CRLF endings, empty
LAST/VOLUME, millisecond timestamps, and a malformed line).
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime

# Make the repo root importable so 'python_bt' resolves when tests run from any
# cwd (mirrors the tuner tests' bootstrap approach).
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from python_bt.loader import Tick, iter_ticks, parse_ts  # noqa: E402

# Exact verified format: TAB-separated, CRLF line endings.
HEADER = "<DATE>\t<TIME>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>\t<FLAGS>"


def _row(date, time, bid, ask, last="", vol="", flags="6"):
    return "\t".join([date, time, bid, ask, last, vol, flags])


def _write_csv(lines):
    """Write lines joined with CRLF to a temp file, return its path."""
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as fh:
        fh.write("\r\n".join(lines) + "\r\n")
    return path


class ParseTsTests(unittest.TestCase):
    def test_milliseconds(self):
        ts = parse_ts("2026.07.01", "11:00:00.051")
        self.assertEqual(ts, datetime(2026, 7, 1, 11, 0, 0, 51000))

    def test_no_milliseconds(self):
        ts = parse_ts("2026.07.01", "11:00:00")
        self.assertEqual(ts, datetime(2026, 7, 1, 11, 0, 0, 0))

    def test_full_ms_precision(self):
        ts = parse_ts("2026.12.31", "23:59:59.999")
        self.assertEqual(ts, datetime(2026, 12, 31, 23, 59, 59, 999000))


class IterTicksTests(unittest.TestCase):
    def setUp(self):
        self._paths = []

    def tearDown(self):
        for p in self._paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def _csv(self, lines):
        path = _write_csv(lines)
        self._paths.append(path)
        return path

    def test_header_skipped_and_parsing(self):
        path = self._csv([
            HEADER,
            _row("2026.07.01", "11:00:00.051", "3975.95", "3976.00"),
            _row("2026.07.01", "11:00:00.178", "3975.86", "3975.92"),
        ])
        ticks = list(iter_ticks(path))
        self.assertEqual(len(ticks), 2)
        self.assertIsInstance(ticks[0], Tick)
        self.assertEqual(ticks[0].ts, datetime(2026, 7, 1, 11, 0, 0, 51000))
        self.assertAlmostEqual(ticks[0].bid, 3975.95)
        self.assertAlmostEqual(ticks[0].ask, 3976.00)

    def test_empty_last_volume_tolerated(self):
        path = self._csv([
            HEADER,
            _row("2026.07.01", "11:00:00.051", "3975.95", "3976.00", last="", vol=""),
        ])
        ticks = list(iter_ticks(path))
        self.assertEqual(len(ticks), 1)
        self.assertAlmostEqual(ticks[0].bid, 3975.95)

    def test_malformed_lines_skipped(self):
        path = self._csv([
            HEADER,
            _row("2026.07.01", "11:00:00.051", "3975.95", "3976.00"),
            "this\tis\tbroken",  # too few numeric cols / non-float
            "",  # blank line
            "2026.07.01\tbadtime\t3975.00\t3975.10\t\t\t6",  # bad time
            _row("2026.07.01", "11:00:01.000", "3976.10", "3976.20"),
        ])
        ticks = list(iter_ticks(path))
        # Only the two well-formed rows survive.
        self.assertEqual(len(ticks), 2)
        self.assertAlmostEqual(ticks[1].bid, 3976.10)

    def test_missing_bid_or_ask_skipped(self):
        path = self._csv([
            HEADER,
            "2026.07.01\t11:00:00.051\t\t3976.00\t\t\t6",  # missing bid
            "2026.07.01\t11:00:00.100\t3975.95\t\t\t\t6",  # missing ask
            _row("2026.07.01", "11:00:01.000", "3976.10", "3976.20"),
        ])
        ticks = list(iter_ticks(path))
        self.assertEqual(len(ticks), 1)

    def test_date_from_inclusive(self):
        path = self._csv([
            HEADER,
            _row("2026.07.01", "11:00:00.000", "1", "2"),
            _row("2026.07.02", "09:00:00.000", "3", "4"),
            _row("2026.07.03", "09:00:00.000", "5", "6"),
        ])
        ticks = list(iter_ticks(path, date_from="2026.07.02"))
        self.assertEqual(len(ticks), 2)
        self.assertEqual(ticks[0].ts, datetime(2026, 7, 2, 9, 0, 0))

    def test_date_to_stops_early_inclusive(self):
        path = self._csv([
            HEADER,
            _row("2026.07.01", "11:00:00.000", "1", "2"),
            _row("2026.07.02", "09:00:00.000", "3", "4"),
            _row("2026.07.03", "09:00:00.000", "5", "6"),
        ])
        # date_to as end-of-day datetime keeps 07.02 rows, drops 07.03.
        ticks = list(iter_ticks(path, date_to=datetime(2026, 7, 2, 23, 59, 59)))
        self.assertEqual(len(ticks), 2)
        self.assertEqual(ticks[-1].ts, datetime(2026, 7, 2, 9, 0, 0))

    def test_date_to_bare_string_includes_whole_end_day(self):
        # A bare 'YYYY.MM.DD' date_to (the CLI --to path) must include ticks
        # late in that day, not just its first instant. Regression guard for the
        # end-of-day truncation bug.
        path = self._csv([
            HEADER,
            _row("2026.07.01", "11:00:00.000", "1", "2"),
            _row("2026.07.02", "00:00:00.000", "3", "4"),  # first instant
            _row("2026.07.02", "23:59:59.999", "5", "6"),  # last instant
            _row("2026.07.03", "00:00:00.001", "7", "8"),  # next day, excluded
        ])
        ticks = list(iter_ticks(path, date_to="2026.07.02"))
        self.assertEqual(len(ticks), 3)
        # The late-in-day 07.02 tick is INCLUDED.
        self.assertEqual(ticks[-1].ts, datetime(2026, 7, 2, 23, 59, 59, 999000))

    def test_date_to_datetime_stays_exact(self):
        # A datetime date_to is honored exactly (no whole-day widening).
        path = self._csv([
            HEADER,
            _row("2026.07.02", "09:00:00.000", "1", "2"),
            _row("2026.07.02", "12:00:00.001", "3", "4"),  # just past the bound
        ])
        ticks = list(iter_ticks(path, date_to=datetime(2026, 7, 2, 12, 0, 0)))
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0].ts, datetime(2026, 7, 2, 9, 0, 0))

    def test_date_range_slice(self):
        path = self._csv([
            HEADER,
            _row("2026.07.01", "11:00:00.000", "1", "2"),
            _row("2026.07.02", "09:00:00.000", "3", "4"),
            _row("2026.07.03", "09:00:00.000", "5", "6"),
            _row("2026.07.04", "09:00:00.000", "7", "8"),
        ])
        ticks = list(iter_ticks(
            path,
            date_from="2026.07.02",
            date_to=datetime(2026, 7, 3, 23, 59, 59),
        ))
        self.assertEqual(len(ticks), 2)

    def test_max_ticks_honored(self):
        path = self._csv([
            HEADER,
            _row("2026.07.01", "11:00:00.000", "1", "2"),
            _row("2026.07.01", "11:00:01.000", "3", "4"),
            _row("2026.07.01", "11:00:02.000", "5", "6"),
        ])
        ticks = list(iter_ticks(path, max_ticks=2))
        self.assertEqual(len(ticks), 2)


if __name__ == "__main__":
    unittest.main()
