"""Streaming tick loader for the XAUUSD tick CSV.

The tick CSV is ~11.86M rows / 526 MB, so this loader NEVER reads the whole
file into memory: iter_ticks() is a generator that reads the file line by line
and yields one Tick at a time. Callers that need bars should feed this stream
into python_bt.bars.iter_bars().

Verified CSV format (tab-separated, CRLF line endings):
  header:  <DATE>\t<TIME>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>\t<FLAGS>
  row:     2026.07.01\t11:00:00.051\t3975.95\t3976.00\t\t\t6
DATE is YYYY.MM.DD, TIME is HH:MM:SS.mmm (milliseconds optional), LAST/VOLUME
are usually empty. Both BID and ASK are present on every row, so spread is real
per tick.

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterator, Optional, Union


@dataclass
class Tick:
    """A single quote: timestamp (ms precision), bid, ask."""

    ts: datetime
    bid: float
    ask: float


def parse_ts(date_str: str, time_str: str) -> datetime:
    """Parse a DATE ('YYYY.MM.DD') + TIME ('HH:MM:SS.mmm') into a datetime.

    Milliseconds are optional; if present they are converted to microseconds.
    Raises ValueError on malformed input (caller may catch to skip a row).
    """
    y, mo, d = date_str.split(".")
    if "." in time_str:
        hms, ms = time_str.split(".", 1)
    else:
        hms, ms = time_str, ""
    h, mi, s = hms.split(":")
    # Milliseconds -> microseconds. Pad/truncate to 3 digits then *1000.
    micros = 0
    if ms:
        ms = (ms + "000")[:3]
        micros = int(ms) * 1000
    return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), micros)


def _coerce_bound(
    bound: Optional[Union[datetime, str]], end_of_day: bool = False
) -> Optional[datetime]:
    """Turn a date_from/date_to argument into a datetime (or None).

    A datetime is accepted as-is (exact, no rounding), so a caller passing an
    explicit programmatic bound keeps full precision. A bare 'YYYY.MM.DD' string
    is a whole named day:
      * date_from (end_of_day=False) -> midnight 00:00:00.000000 of that day.
      * date_to   (end_of_day=True)  -> the LAST instant of that day
        (23:59:59.999999), so '--to 2026.09.01' includes ALL of Sep 1 rather
        than only its first instant. This makes the CLI slice inclusive of the
        entire end day and avoids silently dropping the rest of it.
    """
    if bound is None or isinstance(bound, datetime):
        return bound
    # String form: 'YYYY.MM.DD' (a whole named day).
    y, mo, d = bound.split(".")
    day = datetime(int(y), int(mo), int(d))
    if end_of_day:
        # Last representable microsecond of the named day.
        return day + timedelta(days=1) - timedelta(microseconds=1)
    return day


def iter_ticks(
    csv_path: str,
    date_from: Optional[Union[datetime, str]] = None,
    date_to: Optional[Union[datetime, str]] = None,
    max_ticks: Optional[int] = None,
) -> Iterator[Tick]:
    """Yield Tick objects from the CSV, streaming line by line.

    date_from / date_to slice the stream (inclusive of date_from, inclusive up
    to and including date_to). A bare 'YYYY.MM.DD' string date_to covers the
    WHOLE named day (up to 23:59:59.999999), so date_to='2026.09.01' keeps every
    tick on Sep 1; a datetime date_to is used exactly as given. Because the file
    is time-ordered, iteration stops early (returns) once a tick's timestamp
    passes date_to. max_ticks, if given, caps how many ticks are yielded (useful
    for smoke runs).

    Malformed or blank lines are skipped rather than raising. The header row
    (starting with '<DATE>') is skipped.
    """
    lo = _coerce_bound(date_from)
    hi = _coerce_bound(date_to, end_of_day=True)
    yielded = 0

    with open(csv_path, "r", newline="") as fh:
        for line in fh:
            # Strip CRLF / stray whitespace at the ends only.
            line = line.rstrip("\r\n")
            if not line:
                continue
            # Skip the header row.
            if line.startswith("<DATE>"):
                continue
            cols = line.split("\t")
            if len(cols) < 4:
                # Not enough columns to be a valid tick row.
                continue
            date_str = cols[0]
            time_str = cols[1]
            bid_str = cols[2]
            ask_str = cols[3]
            if not bid_str or not ask_str:
                continue
            try:
                ts = parse_ts(date_str, time_str)
                bid = float(bid_str)
                ask = float(ask_str)
            except (ValueError, IndexError):
                # Malformed line: skip, do not crash.
                continue

            if lo is not None and ts < lo:
                continue
            if hi is not None and ts > hi:
                # File is time-ordered; nothing further can match. Stop early.
                return

            yield Tick(ts=ts, bid=bid, ask=ask)
            yielded += 1
            if max_ticks is not None and yielded >= max_ticks:
                return
