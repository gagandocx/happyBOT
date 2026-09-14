"""Performance metrics for a completed backtest run.

compute_metrics(ledger, equity_curve, deposit) returns a dict whose KEYS MATCH
reports/samples/sample_report.summary.json's metrics schema so that
automation/tuner/scoring.py score() (and tools/analyze_report.py's vocabulary)
consume it directly without translation.

TRADE vs DEAL definitions (this matters because scoring.py reads total_trades):
  * A DEAL is a single realized close: each partial close AND the final close of
    a position is one deal. total_deals counts every ClosedDeal in the ledger.
  * A TRADE is one round-trip position: opened, then eventually fully closed
    (possibly across several partial deals). total_trades counts positions that
    were fully closed, i.e. the number of ClosedDeal rows whose trade_closed
    flag is True. This mirrors MT5's report, where a position closed in tranches
    shows several deals but rolls up to one trade for win/loss statistics.

Win/loss statistics (win_rate, profit factor, streaks, largest/average) are
computed per TRADE by aggregating all deals of a position into a single realized
P&L, so a scaled-out position counts once and is a win/loss by its net result.

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

import statistics
from typing import Dict, List, Optional, Sequence


def _round_trip_pnls(ledger: Sequence) -> List[float]:
    """Aggregate ledger deals into per-position (per-trade) realized P&L.

    Returns one net-P&L number per fully closed position, in the order the
    positions finished closing (order of their final deal in the ledger).
    """
    by_pos = {}  # position_id -> accumulated profit
    order = []  # position_ids in the order they fully close
    for deal in ledger:
        pid = deal.position_id
        by_pos[pid] = by_pos.get(pid, 0.0) + deal.profit
        if deal.trade_closed:
            order.append(pid)
    return [by_pos[pid] for pid in order]


def compute_metrics(
    ledger: Sequence,
    equity_curve: Optional[Sequence] = None,
    deposit: float = 0.0,
    broker=None,
) -> Dict[str, object]:
    """Compute the metrics dict.

    ledger: sequence of ClosedDeal (see broker.ClosedDeal).
    equity_curve: optional sequence of equity values sampled over the run; used
      only as a fallback for drawdown if a broker is not supplied.
    deposit: starting deposit (denominator for percentage drawdowns).
    broker: optional Broker whose peak/trough trackers give MT5-comparable
      drawdown figures directly (preferred over equity_curve scanning).
    """
    deposit = float(deposit) if deposit else 0.0

    trade_pnls = _round_trip_pnls(ledger)
    total_trades = len(trade_pnls)
    total_deals = len(ledger)

    wins = [p for p in trade_pnls if p > 0.0]
    losses = [p for p in trade_pnls if p < 0.0]

    gross_profit = sum(wins)
    gross_loss = sum(losses)  # negative or zero
    total_net_profit = sum(trade_pnls)

    if gross_loss != 0.0:
        profit_factor = gross_profit / abs(gross_loss)
    elif gross_profit > 0.0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    expected_payoff = total_net_profit / total_trades if total_trades else 0.0

    # Drawdown: prefer the broker's per-quote trackers.
    if broker is not None:
        maximal_drawdown_money = float(broker.max_drawdown_money)
        relative_drawdown_money = float(broker.rel_drawdown_money)
        relative_drawdown_pct = float(broker.rel_drawdown_pct)
        absolute_drawdown = float(broker.absolute_drawdown)
        peak_equity = float(broker.peak_equity)
    else:
        maximal_drawdown_money, relative_drawdown_money, relative_drawdown_pct, \
            absolute_drawdown, peak_equity = _drawdown_from_curve(equity_curve, deposit)

    # maximal_drawdown_pct: the max money drop expressed vs the peak equity.
    if peak_equity > 0.0:
        maximal_drawdown_pct = maximal_drawdown_money / peak_equity * 100.0
    else:
        maximal_drawdown_pct = 0.0

    recovery_factor = (
        total_net_profit / maximal_drawdown_money if maximal_drawdown_money > 0.0 else 0.0
    )

    # Sharpe over per-trade returns (0 if fewer than 2 trades or zero stdev).
    if total_trades >= 2:
        mean_ret = statistics.fmean(trade_pnls)
        stdev_ret = statistics.pstdev(trade_pnls)
        sharpe_ratio = mean_ret / stdev_ret if stdev_ret > 0.0 else 0.0
    else:
        sharpe_ratio = 0.0

    win_rate_pct = (len(wins) / total_trades * 100.0) if total_trades else 0.0

    largest_profit_trade = max(wins) if wins else 0.0
    largest_loss_trade = min(losses) if losses else 0.0
    average_profit_trade = (gross_profit / len(wins)) if wins else 0.0
    average_loss_trade = (gross_loss / len(losses)) if losses else 0.0

    (
        max_consecutive_wins_count,
        max_consecutive_wins_money,
        max_consecutive_losses_count,
        max_consecutive_losses_money,
    ) = _consecutive_streaks(trade_pnls)

    return {
        "total_net_profit": total_net_profit,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "expected_payoff": expected_payoff,
        "recovery_factor": recovery_factor,
        "sharpe_ratio": sharpe_ratio,
        "absolute_drawdown": absolute_drawdown,
        "maximal_drawdown_money": maximal_drawdown_money,
        "maximal_drawdown_pct": maximal_drawdown_pct,
        "relative_drawdown_money": relative_drawdown_money,
        "relative_drawdown_pct": relative_drawdown_pct,
        "total_trades": total_trades,
        "total_deals": total_deals,
        "win_rate_pct": win_rate_pct,
        "largest_profit_trade": largest_profit_trade,
        "largest_loss_trade": largest_loss_trade,
        "average_profit_trade": average_profit_trade,
        "average_loss_trade": average_loss_trade,
        "max_consecutive_wins_count": max_consecutive_wins_count,
        "max_consecutive_wins_money": max_consecutive_wins_money,
        "max_consecutive_losses_count": max_consecutive_losses_count,
        "max_consecutive_losses_money": max_consecutive_losses_money,
    }


def _consecutive_streaks(trade_pnls: Sequence):
    """Longest run of wins and of losses, with the summed money over the run.

    Returns (win_count, win_money, loss_count, loss_money) where loss_money is
    negative (sum of the worst losing streak). A win is P&L > 0, a loss < 0;
    exactly-zero trades break both streaks and belong to neither.
    """
    best_win_count = 0
    best_win_money = 0.0
    best_loss_count = 0
    best_loss_money = 0.0

    cur_win_count = 0
    cur_win_money = 0.0
    cur_loss_count = 0
    cur_loss_money = 0.0

    for p in trade_pnls:
        if p > 0.0:
            cur_win_count += 1
            cur_win_money += p
            if cur_win_count > best_win_count or (
                cur_win_count == best_win_count and cur_win_money > best_win_money
            ):
                best_win_count = cur_win_count
                best_win_money = cur_win_money
            cur_loss_count = 0
            cur_loss_money = 0.0
        elif p < 0.0:
            cur_loss_count += 1
            cur_loss_money += p
            if cur_loss_count > best_loss_count or (
                cur_loss_count == best_loss_count and cur_loss_money < best_loss_money
            ):
                best_loss_count = cur_loss_count
                best_loss_money = cur_loss_money
            cur_win_count = 0
            cur_win_money = 0.0
        else:
            cur_win_count = 0
            cur_win_money = 0.0
            cur_loss_count = 0
            cur_loss_money = 0.0

    return best_win_count, best_win_money, best_loss_count, best_loss_money


def _drawdown_from_curve(equity_curve: Optional[Sequence], deposit: float):
    """Fallback drawdown computation by scanning an equity curve.

    Returns (maximal_dd_money, relative_dd_money, relative_dd_pct,
    absolute_dd, peak_equity). Used only when no Broker is supplied.
    """
    if not equity_curve:
        return 0.0, 0.0, 0.0, 0.0, deposit

    peak = equity_curve[0]
    max_dd_money = 0.0
    rel_dd_money = 0.0
    rel_dd_pct = 0.0
    min_equity = equity_curve[0]
    peak_at_max = peak

    for eq in equity_curve:
        if eq > peak:
            peak = eq
        drop = peak - eq
        if drop > max_dd_money:
            max_dd_money = drop
            peak_at_max = peak
        if peak > 0.0:
            rp = drop / peak * 100.0
            if rp > rel_dd_pct:
                rel_dd_pct = rp
                rel_dd_money = drop
        if eq < min_equity:
            min_equity = eq

    absolute_dd = 0.0 if min_equity >= deposit else deposit - min_equity
    return max_dd_money, rel_dd_money, rel_dd_pct, absolute_dd, peak_at_max
