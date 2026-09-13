"""Incremental technical indicators for the XAUUSD backtester.

Every indicator here is a small STATEFUL object with an update(value) method
that returns the current indicator value (or None while still warming up). This
keeps the work O(1) per bar over the stream instead of recomputing from a
sliding window each bar, which matters because the tick CSV is ~11.86M rows.

Indicators provided:
  * EMA    - exponential moving average, standard 2/(n+1) smoothing, SEEDED with
             the simple average (SMA) of the first n samples (this matches how
             MT5's iMA EMA warms up: it prints its first value only once n bars
             exist, using an SMA seed, then applies the recursive EMA formula).
  * ATR    - Wilder's Average True Range (default period 14) fed bar high/low/
             close. True range needs the PREVIOUS close, so the first TR uses
             high-low. The average is seeded with the SMA of the first period
             TRs, then Wilder-smoothed: atr = (atr*(n-1) + tr) / n.
  * RSI    - Wilder's Relative Strength Index (default period 14) fed closes.
             Gains/losses are seeded with the SMA of the first period deltas,
             then Wilder-smoothed. Returns a value in [0, 100].
  * H1Ema  - an EMA fed by HOURLY closes derived from the M5 stream. It watches
             the bar timestamp's hour; when the hour rolls over it feeds the
             previous hour's last M5 close into an inner EMA. This is the HTF
             EMA200 approximation (see happybot.py docstring for caveats).

APPROXIMATIONS vs MT5 (documented so parity work is honest):
  * MT5 EMA/ATR/RSI are computed on completed broker bars. Here the M5 bars are
    built from tick MIDs (see bars.py), so the close feeding these indicators is
    a mid, not the broker's bid/ask close. Small but real difference.
  * The H1 EMA200 is built by sampling the M5 stream at hour boundaries rather
    than from a genuine broker H1 series. An H1 close here is the last M5 mid
    close of that hour. Alignment and the exact seed therefore differ slightly
    from MT5's own H1 EMA200.
  * Seeding uses an SMA of the first n samples. MT5's precise seeding is not
    publicly byte-specified; this is the widely used and documented convention.

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

from typing import List, Optional


class EMA:
    """Exponential moving average, seeded with the SMA of the first `period`.

    update(value) returns the current EMA once at least `period` samples have
    been seen, otherwise None. alpha = 2 / (period + 1).
    """

    def __init__(self, period: int):
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = int(period)
        self.alpha = 2.0 / (self.period + 1.0)
        self._seed = []  # type: List[float]
        self.value = None  # type: Optional[float]

    def update(self, price: float) -> Optional[float]:
        price = float(price)
        if self.value is None:
            self._seed.append(price)
            if len(self._seed) >= self.period:
                self.value = sum(self._seed) / float(self.period)
            return self.value
        self.value = self.value + self.alpha * (price - self.value)
        return self.value

    @property
    def ready(self) -> bool:
        return self.value is not None


class ATR:
    """Wilder's Average True Range fed (high, low, close) per bar.

    update(high, low, close) returns the current ATR once `period` true ranges
    have accumulated, else None. The first true range (no previous close) uses
    high - low.
    """

    def __init__(self, period: int = 14):
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = int(period)
        self._prev_close = None  # type: Optional[float]
        self._seed = []  # type: List[float]
        self.value = None  # type: Optional[float]

    def _true_range(self, high: float, low: float) -> float:
        if self._prev_close is None:
            return high - low
        return max(
            high - low,
            abs(high - self._prev_close),
            abs(low - self._prev_close),
        )

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        high = float(high)
        low = float(low)
        close = float(close)
        tr = self._true_range(high, low)
        self._prev_close = close
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) >= self.period:
                self.value = sum(self._seed) / float(self.period)
            return self.value
        self.value = (self.value * (self.period - 1) + tr) / float(self.period)
        return self.value

    @property
    def ready(self) -> bool:
        return self.value is not None


class RSI:
    """Wilder's Relative Strength Index fed a price series (closes).

    update(price) returns the current RSI in [0, 100] once `period` deltas have
    accumulated, else None. Uses Wilder smoothing of average gain / average loss
    seeded with the SMA of the first `period` deltas.
    """

    def __init__(self, period: int = 14):
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = int(period)
        self._prev = None  # type: Optional[float]
        self._gains = []  # type: List[float]
        self._losses = []  # type: List[float]
        self.avg_gain = None  # type: Optional[float]
        self.avg_loss = None  # type: Optional[float]
        self.value = None  # type: Optional[float]

    def _rsi_from(self, avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0.0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def update(self, price: float) -> Optional[float]:
        price = float(price)
        if self._prev is None:
            self._prev = price
            return None
        delta = price - self._prev
        self._prev = price
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0

        if self.avg_gain is None:
            self._gains.append(gain)
            self._losses.append(loss)
            if len(self._gains) >= self.period:
                self.avg_gain = sum(self._gains) / float(self.period)
                self.avg_loss = sum(self._losses) / float(self.period)
                self.value = self._rsi_from(self.avg_gain, self.avg_loss)
            return self.value

        self.avg_gain = (self.avg_gain * (self.period - 1) + gain) / float(self.period)
        self.avg_loss = (self.avg_loss * (self.period - 1) + loss) / float(self.period)
        self.value = self._rsi_from(self.avg_gain, self.avg_loss)
        return self.value

    @property
    def ready(self) -> bool:
        return self.value is not None


class H1Ema:
    """HTF EMA200 approximation fed by the M5 bar stream.

    Feed update(bar_ts_hour, close) with each M5 bar's opening-hour (an int 0-23
    or, better, an (year, month, day, hour) key) and its close mid. When the
    hour key changes, the PREVIOUS hour's last close is pushed into an inner EMA
    (one hourly sample per hour). value is the current H1 EMA (None until the
    inner EMA has enough hourly closes).

    APPROXIMATION: an H1 close here is the last M5 mid close of the hour, not a
    broker H1 bar close; see module docstring.
    """

    def __init__(self, period: int = 200):
        self.period = int(period)
        self._ema = EMA(self.period)
        self._cur_key = None
        self._cur_last_close = None  # type: Optional[float]
        self.value = None  # type: Optional[float]

    def update(self, hour_key, close: float) -> Optional[float]:
        close = float(close)
        if self._cur_key is None:
            self._cur_key = hour_key
            self._cur_last_close = close
            return self.value
        if hour_key != self._cur_key:
            # The hour rolled over: commit the finished hour's last close.
            self.value = self._ema.update(self._cur_last_close)
            self._cur_key = hour_key
            self._cur_last_close = close
        else:
            self._cur_last_close = close
        return self.value

    @property
    def ready(self) -> bool:
        return self.value is not None
