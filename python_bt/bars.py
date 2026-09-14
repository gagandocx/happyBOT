"""Ticks -> M5 (or any timeframe) bar aggregator.

iter_bars() consumes a tick stream (from python_bt.loader.iter_ticks) and yields
a completed Bar every time the timeframe boundary rolls over. OHLC is built from
the MID price ((bid + ask) / 2) of each tick in the bucket. Each Bar also
carries the LAST bid/ask seen in the bucket, so a strategy that runs on bar
closes can still fill at a realistic spread rather than at the mid.

Boundary alignment is deterministic: a tick's bucket is its timestamp floored to
a multiple of timeframe_minutes (seconds and microseconds zeroed). The final
partial bar at end of stream is emitted.

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Iterator


@dataclass
class Bar:
    """An OHLC bar built from tick mids, aligned to a timeframe boundary.

    ts_open is the bar's opening timestamp aligned to the boundary. open/high/
    low/close are mid prices. last_bid/last_ask are the final quote in the bar
    so fills stay spread-aware. tick_count is how many ticks formed the bar.
    """

    ts_open: datetime
    open: float
    high: float
    low: float
    close: float
    tick_count: int
    last_bid: float
    last_ask: float


def floor_ts(ts: datetime, timeframe_minutes: int) -> datetime:
    """Floor a timestamp to the start of its timeframe bucket.

    Minutes are floored to a multiple of timeframe_minutes; seconds and
    microseconds are zeroed. The flooring is anchored to the top of the hour,
    which matches how M5/M15/etc. bars align in MT5 for divisors of 60.
    """
    floored_minute = (ts.minute // timeframe_minutes) * timeframe_minutes
    return ts.replace(minute=floored_minute, second=0, microsecond=0)


def iter_bars(tick_iterable: Iterable, timeframe_minutes: int = 5) -> Iterator[Bar]:
    """Yield completed Bars from a tick iterable.

    A bar is emitted when a tick's bucket differs from the current bucket. The
    final (possibly partial) bar is emitted when the tick stream ends.
    """
    if timeframe_minutes <= 0:
        raise ValueError("timeframe_minutes must be positive")

    cur_open_ts = None  # type: datetime
    o = h = l = c = 0.0
    last_bid = last_ask = 0.0
    count = 0

    for tick in tick_iterable:
        mid = (tick.bid + tick.ask) / 2.0
        bucket = floor_ts(tick.ts, timeframe_minutes)

        if cur_open_ts is None:
            # First tick: open a new bar.
            cur_open_ts = bucket
            o = h = l = c = mid
            last_bid = tick.bid
            last_ask = tick.ask
            count = 1
            continue

        if bucket != cur_open_ts:
            # Boundary rolled over: emit the completed bar, then open a new one.
            yield Bar(
                ts_open=cur_open_ts,
                open=o,
                high=h,
                low=l,
                close=c,
                tick_count=count,
                last_bid=last_bid,
                last_ask=last_ask,
            )
            cur_open_ts = bucket
            o = h = l = c = mid
            last_bid = tick.bid
            last_ask = tick.ask
            count = 1
            continue

        # Same bucket: update OHLC and last quote.
        if mid > h:
            h = mid
        if mid < l:
            l = mid
        c = mid
        last_bid = tick.bid
        last_ask = tick.ask
        count += 1

    # Emit the final partial bar, if any ticks were seen.
    if cur_open_ts is not None:
        yield Bar(
            ts_open=cur_open_ts,
            open=o,
            high=h,
            low=l,
            close=c,
            tick_count=count,
            last_bid=last_bid,
            last_ask=last_ask,
        )
