"""Broker + position model for the XAUUSD tick backtester.

This module simulates a HEDGING account (MT5 ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
analog): multiple positions can be open at the same time, including both a buy
and a sell simultaneously. It models spread-based fills, per-lot commission on
every side, partial closes with proportional P&L realization, SL/TP that fire
when the quoted side crosses the level, SL modification (breakeven/trailing),
and per-quote equity / drawdown tracking.

Fill model (matches GaganEA / MT5 semantics documented in context.json):
  * A BUY is opened at the ASK and later closed at the BID.
  * A SELL is opened at the BID and later closed at the ASK.
  * Commission is charged per lot per side, on OPEN and on each CLOSE (a partial
    close is charged on the closed volume only).
  * SL/TP crossing checks use the side that would close the position:
      - buy  SL fires when bid <= sl   (close at sl)
      - buy  TP fires when bid >= tp   (close at tp)
      - sell SL fires when ask >= sl   (close at sl)
      - sell TP fires when ask <= tp   (close at tp)
  * Realized P&L money for a closed volume v (lots):
      profit_price = (exit - entry) for buy, (entry - exit) for sell
      money = profit_price / TICK_SIZE * TICK_VALUE * v
    net of the close-side commission.

Performance: on_quote does work proportional to the number of OPEN positions,
never proportional to the total number of ticks seen so far.

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from python_bt import config


@dataclass
class Position:
    """A single open position on the HEDGING account.

    side is 'buy' or 'sell'. volume_lots is the CURRENT (possibly reduced by
    partial closes) open volume; initial_volume is what it opened with. tags
    carry strategy bookkeeping such as tiered-partial and breakeven state.
    """

    side: str
    volume_lots: float
    entry_price: float
    sl: Optional[float]
    tp: Optional[float]
    open_ts: Optional[datetime]
    initial_volume: float = 0.0
    t1_done: bool = False
    t2_done: bool = False
    t3_done: bool = False
    breakeven_done: bool = False
    id: int = 0

    def __post_init__(self):
        if not self.initial_volume:
            self.initial_volume = self.volume_lots


@dataclass
class ClosedDeal:
    """One realized close (a 'deal'): a full or partial close of a position.

    A round-trip position (open -> fully closed, possibly via several partials)
    is a 'trade'. Each partial (and the final) close is a 'deal'. profit is the
    money realized on THIS close, net of the commission charged on it.
    """

    position_id: int
    side: str
    volume_lots: float
    entry_price: float
    exit_price: float
    profit: float
    commission: float
    open_ts: Optional[datetime]
    close_ts: Optional[datetime]
    reason: str
    trade_closed: bool


def _pnl_money(side: str, entry: float, exit_price: float, volume_lots: float) -> float:
    """Gross P&L money (before commission) for closing volume_lots at exit_price."""
    if side == "buy":
        profit_price = exit_price - entry
    else:
        profit_price = entry - exit_price
    return profit_price / config.TICK_SIZE * config.TICK_VALUE * volume_lots


def _commission(volume_lots: float) -> float:
    """Commission (money) for one side on the given volume."""
    return config.COMMISSION_PER_LOT_PER_SIDE * volume_lots


class Broker:
    """Simulated hedging broker with per-quote equity/drawdown tracking.

    balance is realized cash; equity is balance + floating (unrealized) P&L of
    all open positions, recomputed on every quote. deposit is the starting
    balance and the denominator base for drawdown percentages.

    Drawdown semantics (MT5-comparable):
      * maximal_drawdown_money = the largest peak-to-trough equity DROP in money.
      * relative_drawdown_money / _pct = the drop that produced the largest
        PERCENT decline relative to the equity peak it started from. _pct is the
        value scoring.py reads for its hard 15% ceiling.
      * absolute_drawdown = deposit minus the lowest equity ever reached below
        the initial deposit (0 if equity never dipped below deposit).
    """

    def __init__(self, deposit: Optional[float] = None):
        self.deposit = float(deposit) if deposit is not None else float(config.INITIAL_DEPOSIT)
        self.balance = self.deposit
        self.equity = self.deposit
        self.positions = []  # type: List[Position]
        self.ledger = []  # type: List[ClosedDeal]
        self._next_id = 1

        # Drawdown trackers (O(1) per quote).
        self.peak_equity = self.deposit
        self.max_drawdown_money = 0.0
        self.rel_drawdown_money = 0.0
        self.rel_drawdown_pct = 0.0
        self.min_equity = self.deposit

    # -- opening -----------------------------------------------------------

    def open(
        self,
        side: str,
        volume: float,
        price_bid: float,
        price_ask: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        ts: Optional[datetime] = None,
    ) -> Position:
        """Open a position: buy fills at ask, sell at bid. Charges open commission."""
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if volume <= 0:
            raise ValueError("volume must be positive")
        entry = price_ask if side == "buy" else price_bid
        pos = Position(
            side=side,
            volume_lots=float(volume),
            entry_price=float(entry),
            sl=sl,
            tp=tp,
            open_ts=ts,
            initial_volume=float(volume),
            id=self._next_id,
        )
        self._next_id += 1
        self.positions.append(pos)
        # Open commission reduces realized balance immediately.
        self.balance -= _commission(volume)
        return pos

    # -- closing -----------------------------------------------------------

    def _record_close(
        self,
        pos: Position,
        volume: float,
        exit_price: float,
        ts: Optional[datetime],
        reason: str,
        trade_closed: bool,
    ) -> ClosedDeal:
        gross = _pnl_money(pos.side, pos.entry_price, exit_price, volume)
        comm = _commission(volume)
        net = gross - comm
        self.balance += net
        deal = ClosedDeal(
            position_id=pos.id,
            side=pos.side,
            volume_lots=float(volume),
            entry_price=pos.entry_price,
            exit_price=float(exit_price),
            profit=net,
            commission=comm,
            open_ts=pos.open_ts,
            close_ts=ts,
            reason=reason,
            trade_closed=trade_closed,
        )
        self.ledger.append(deal)
        return deal

    def close_partial(
        self,
        pos: Position,
        volume: float,
        price_bid: float,
        price_ask: float,
        ts: Optional[datetime] = None,
        reason: str = "partial",
    ) -> ClosedDeal:
        """Close part of a position, realizing proportional P&L and commission.

        The closed volume is clamped to the currently open volume; if it closes
        the whole remaining volume this becomes a full close.
        """
        if volume <= 0:
            raise ValueError("volume must be positive")
        vol = min(float(volume), pos.volume_lots)
        exit_price = price_bid if pos.side == "buy" else price_ask
        closes_all = vol >= pos.volume_lots - 1e-12
        deal = self._record_close(pos, vol, exit_price, ts, reason, closes_all)
        if closes_all:
            pos.volume_lots = 0.0
            self._remove(pos)
        else:
            pos.volume_lots -= vol
        return deal

    def close_full(
        self,
        pos: Position,
        price_bid: float,
        price_ask: float,
        ts: Optional[datetime] = None,
        reason: str = "close",
    ) -> ClosedDeal:
        """Fully close a position at the current quote (buy->bid, sell->ask)."""
        exit_price = price_bid if pos.side == "buy" else price_ask
        deal = self._record_close(pos, pos.volume_lots, exit_price, ts, reason, True)
        pos.volume_lots = 0.0
        self._remove(pos)
        return deal

    def _close_at_price(
        self,
        pos: Position,
        exit_price: float,
        ts: Optional[datetime],
        reason: str,
    ) -> ClosedDeal:
        """Fully close a position at an explicit price (used for SL/TP fills)."""
        deal = self._record_close(pos, pos.volume_lots, exit_price, ts, reason, True)
        pos.volume_lots = 0.0
        self._remove(pos)
        return deal

    def _remove(self, pos: Position) -> None:
        for i, p in enumerate(self.positions):
            if p is pos:
                del self.positions[i]
                return

    # -- modification ------------------------------------------------------

    def modify_sl(self, pos: Position, new_sl: Optional[float]) -> None:
        """Set a new stop-loss (breakeven / trailing). No fill occurs here."""
        pos.sl = new_sl

    # -- per-quote engine hook --------------------------------------------

    def on_quote(self, bid: float, ask: float, ts: Optional[datetime] = None):
        """Process a new quote: fire any SL/TP, then recompute equity/drawdown.

        Returns the list of ClosedDeal fired by this quote (may be empty). Work
        is O(number of open positions).
        """
        fired = []  # type: List[ClosedDeal]
        # Iterate over a snapshot because _close_at_price mutates self.positions.
        for pos in list(self.positions):
            if pos.volume_lots <= 0:
                continue
            if pos.side == "buy":
                # SL first (conservative: a gap through both hits the stop).
                if pos.sl is not None and bid <= pos.sl:
                    fired.append(self._close_at_price(pos, pos.sl, ts, "sl"))
                    continue
                if pos.tp is not None and bid >= pos.tp:
                    fired.append(self._close_at_price(pos, pos.tp, ts, "tp"))
                    continue
            else:  # sell
                if pos.sl is not None and ask >= pos.sl:
                    fired.append(self._close_at_price(pos, pos.sl, ts, "sl"))
                    continue
                if pos.tp is not None and ask <= pos.tp:
                    fired.append(self._close_at_price(pos, pos.tp, ts, "tp"))
                    continue
        self._update_equity(bid, ask)
        return fired

    def floating_pnl(self, bid: float, ask: float) -> float:
        """Sum of unrealized P&L (gross of exit commission) across open positions.

        A buy is marked at the bid it could close into; a sell at the ask.
        """
        total = 0.0
        for pos in self.positions:
            if pos.volume_lots <= 0:
                continue
            mark = bid if pos.side == "buy" else ask
            total += _pnl_money(pos.side, pos.entry_price, mark, pos.volume_lots)
        return total

    def _update_equity(self, bid: float, ask: float) -> None:
        self.equity = self.balance + self.floating_pnl(bid, ask)
        # Peak / trough tracking for drawdown, O(1).
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
        drop = self.peak_equity - self.equity
        if drop > self.max_drawdown_money:
            self.max_drawdown_money = drop
        if self.peak_equity > 0:
            rel_pct = drop / self.peak_equity * 100.0
            if rel_pct > self.rel_drawdown_pct:
                self.rel_drawdown_pct = rel_pct
                self.rel_drawdown_money = drop
        if self.equity < self.min_equity:
            self.min_equity = self.equity

    @property
    def absolute_drawdown(self) -> float:
        """Deposit minus the lowest equity below deposit (0 if never below)."""
        if self.min_equity >= self.deposit:
            return 0.0
        return self.deposit - self.min_equity
