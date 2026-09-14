"""Backtest event loop driving a strategy against tick or M5-bar data.

The engine feeds quotes to a Broker (which fires SL/TP) and gives a Strategy a
chance to act. Two modes share the same underlying tick stream:

  * tick mode ("tick"): every tick is a quote. broker.on_quote fires SL/TP with
    tick-accuracy, then strategy.on_tick (if defined) runs. When a bar closes,
    strategy.on_bar runs. Fills the strategy requests use the current tick's
    bid/ask.
  * bar mode ("bar", fast): M5 bars are built from the same ticks. For each bar
    the engine issues a SINGLE quote using the bar's last_bid/last_ask before
    calling strategy.on_bar. APPROXIMATION: in bar mode SL/TP are only checked
    once per bar (at the bar's closing quote), so intrabar stop/target hits are
    not tick-accurate. Use tick mode for accurate fills; bar mode is for fast
    research sweeps.

Strategy protocol (the full interface lands in FEAT-003; the minimum the engine
relies on):
    strategy.on_bar(bar, ctx)            # required, called on each bar close
    strategy.on_tick(tick, ctx)          # optional, tick mode only
Both receive a Context giving broker-facing actions:
    ctx.buy(volume, sl, tp) / ctx.sell(volume, sl, tp)
    ctx.positions                        # list of open Position
    ctx.close_partial(pos, volume, reason) / ctx.close_full(pos, reason)
    ctx.modify_sl(pos, new_sl)
    ctx.bid / ctx.ask / ctx.ts           # latest quote
    ctx.bar                              # most recent closed bar (or None)

run() returns a JSON-serializable dict: {metrics, score, params, meta}.

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

from python_bt import config
from python_bt.bars import iter_bars
from python_bt.broker import Broker
from python_bt.metrics import compute_metrics
from python_bt.scoring_bridge import score


class Context:
    """Broker-facing API handed to the strategy on each callback.

    The engine keeps the latest quote (bid/ask/ts) and the latest closed bar on
    the context so strategy fill requests use realistic prices.
    """

    def __init__(self, broker: Broker):
        self._broker = broker
        self.bid = 0.0
        self.ask = 0.0
        self.ts = None
        self.bar = None

    @property
    def positions(self):
        return self._broker.positions

    def buy(self, volume, sl=None, tp=None):
        return self._broker.open("buy", volume, self.bid, self.ask, sl, tp, self.ts)

    def sell(self, volume, sl=None, tp=None):
        return self._broker.open("sell", volume, self.bid, self.ask, sl, tp, self.ts)

    def close_partial(self, pos, volume, reason="partial"):
        return self._broker.close_partial(pos, volume, self.bid, self.ask, self.ts, reason)

    def close_full(self, pos, reason="close"):
        return self._broker.close_full(pos, self.bid, self.ask, self.ts, reason)

    def modify_sl(self, pos, new_sl):
        return self._broker.modify_sl(pos, new_sl)


class Engine:
    """Drives a strategy over a tick stream in tick or bar mode."""

    def __init__(
        self,
        strategy,
        broker: Optional[Broker] = None,
        mode: str = "tick",
        timeframe_minutes: int = 5,
        params: Optional[Dict] = None,
    ):
        if mode not in ("tick", "bar"):
            raise ValueError("mode must be 'tick' or 'bar'")
        self.strategy = strategy
        self.broker = broker if broker is not None else Broker()
        self.mode = mode
        self.timeframe_minutes = timeframe_minutes
        self.params = params or {}
        self.ctx = Context(self.broker)
        self.equity_curve = []  # sampled equity values
        self.tick_count = 0
        self.bar_count = 0
        self.first_ts = None
        self.last_ts = None

    def _note_ts(self, ts):
        if self.first_ts is None:
            self.first_ts = ts
        self.last_ts = ts

    def _run_tick_mode(self, ticks: Iterable):
        on_tick = getattr(self.strategy, "on_tick", None)
        bar_open_ts = None
        # Build bars incrementally while replaying ticks so on_bar can fire at
        # the exact tick where a new bucket begins (bar just closed).
        from python_bt.bars import floor_ts

        pending_bar_ticks = []  # accumulate to synthesize the closed bar
        cur_bucket = None
        cur_o = cur_h = cur_l = cur_c = 0.0
        cur_lb = cur_la = 0.0
        cur_n = 0
        from python_bt.bars import Bar

        for tick in ticks:
            self.tick_count += 1
            self._note_ts(tick.ts)
            self.ctx.bid = tick.bid
            self.ctx.ask = tick.ask
            self.ctx.ts = tick.ts

            # Broker sees the quote first (fires SL/TP), then equity sampled.
            self.broker.on_quote(tick.bid, tick.ask, tick.ts)
            self.equity_curve.append(self.broker.equity)

            if callable(on_tick):
                on_tick(tick, self.ctx)

            # Incremental M5 bar assembly.
            mid = (tick.bid + tick.ask) / 2.0
            bucket = floor_ts(tick.ts, self.timeframe_minutes)
            if cur_bucket is None:
                cur_bucket = bucket
                cur_o = cur_h = cur_l = cur_c = mid
                cur_lb, cur_la = tick.bid, tick.ask
                cur_n = 1
            elif bucket != cur_bucket:
                closed = Bar(
                    ts_open=cur_bucket, open=cur_o, high=cur_h, low=cur_l,
                    close=cur_c, tick_count=cur_n, last_bid=cur_lb, last_ask=cur_la,
                )
                self.bar_count += 1
                self.ctx.bar = closed
                self.strategy.on_bar(closed, self.ctx)
                cur_bucket = bucket
                cur_o = cur_h = cur_l = cur_c = mid
                cur_lb, cur_la = tick.bid, tick.ask
                cur_n = 1
            else:
                if mid > cur_h:
                    cur_h = mid
                if mid < cur_l:
                    cur_l = mid
                cur_c = mid
                cur_lb, cur_la = tick.bid, tick.ask
                cur_n += 1

        # Emit the final partial bar so the strategy sees it close.
        if cur_bucket is not None:
            closed = Bar(
                ts_open=cur_bucket, open=cur_o, high=cur_h, low=cur_l,
                close=cur_c, tick_count=cur_n, last_bid=cur_lb, last_ask=cur_la,
            )
            self.bar_count += 1
            self.ctx.bar = closed
            self.strategy.on_bar(closed, self.ctx)

    def _run_bar_mode(self, ticks: Iterable):
        for bar in iter_bars(ticks, timeframe_minutes=self.timeframe_minutes):
            self.bar_count += 1
            self._note_ts(bar.ts_open)
            self.ctx.bid = bar.last_bid
            self.ctx.ask = bar.last_ask
            self.ctx.ts = bar.ts_open
            self.ctx.bar = bar
            # Single closing quote per bar (approximation, see module docstring).
            self.broker.on_quote(bar.last_bid, bar.last_ask, bar.ts_open)
            self.equity_curve.append(self.broker.equity)
            self.tick_count += bar.tick_count
            self.strategy.on_bar(bar, self.ctx)

    def run(self, ticks: Iterable) -> Dict[str, object]:
        """Replay the tick iterable, then return {metrics, score, params, meta}."""
        if self.mode == "tick":
            self._run_tick_mode(ticks)
        else:
            self._run_bar_mode(ticks)

        metrics = compute_metrics(
            self.broker.ledger,
            equity_curve=self.equity_curve,
            deposit=self.broker.deposit,
            broker=self.broker,
        )
        # Optional warm-up / eligibility diagnostic (see Strategy.warmup_info).
        warmup = None
        warmup_fn = getattr(self.strategy, "warmup_info", None)
        if callable(warmup_fn):
            warmup = warmup_fn()
        result = {
            "metrics": _jsonable(metrics),
            "score": score(metrics),
            "params": dict(self.params),
            "meta": {
                "mode": self.mode,
                "timeframe_minutes": self.timeframe_minutes,
                "tick_count": self.tick_count,
                "bar_count": self.bar_count,
                "data_from": self.first_ts.isoformat() if self.first_ts else None,
                "data_to": self.last_ts.isoformat() if self.last_ts else None,
                "deposit": self.broker.deposit,
                "warmup": warmup,
                "config": {
                    "POINT_SIZE": config.POINT_SIZE,
                    "TICK_SIZE": config.TICK_SIZE,
                    "TICK_VALUE": config.TICK_VALUE,
                    "CONTRACT_SIZE": config.CONTRACT_SIZE,
                    "COMMISSION_PER_LOT_PER_SIDE": config.COMMISSION_PER_LOT_PER_SIDE,
                    "INITIAL_DEPOSIT": config.INITIAL_DEPOSIT,
                    "LEVERAGE": config.LEVERAGE,
                },
            },
        }
        return result


def _jsonable(metrics: Dict[str, object]) -> Dict[str, object]:
    """Coerce non-finite floats (inf profit_factor) to a JSON-serializable form."""
    import math

    out = {}
    for k, v in metrics.items():
        if isinstance(v, float) and not math.isfinite(v):
            # Represent an infinite profit factor (zero losses) as None so the
            # result stays JSON-serializable; scoring.py reads the live float.
            out[k] = None
        else:
            out[k] = v
    return out
