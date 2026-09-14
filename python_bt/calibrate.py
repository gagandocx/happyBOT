"""Calibration harness: compare the Python backtester against the MT5 truth.

This is the MEASUREMENT tool for the MT5 calibration effort. It:

  1. Parses the real MT5 Strategy Tester report (UTF-16 HTML) into both its
     SUMMARY metrics and its per-DEAL table, reusing tools/analyze_report.py's
     battle-tested parser (read_html / parse_rows / extract_metrics /
     parse_trade_table). It does NOT reimplement HTML parsing.
  2. Pairs the MT5 'in'/'out' deals into round-trip trades and derives a
     like-for-like summary (trade count, win rate, avg win/loss, largest
     win/loss, streaks, gross profit/loss, profit factor) straight from the
     deal table, so the comparison does not rely solely on the report's own
     summary block.
  3. RECONCILES the money multiplier from real deals: for a sample of MT5 'out'
     deals it computes expected money = price_move / TICK_SIZE * TICK_VALUE *
     volume and compares to the reported Profit column, deriving the observed
     USD-per-point-per-lot and confirming config.TICK_VALUE / CONTRACT_SIZE.
  4. Runs the Python engine (python_bt.runner.run_once) with strategy 'happybot'
     and v2.13 defaults over the SAME window in BOTH bar and tick mode.
  5. Prints a fixed-width MT5 | Py(bar) | Py(tick) | delta(tick vs MT5)
     comparison table and, with --json, dumps the whole comparison as
     machine-readable JSON.

Design constraints (shared with the rest of python_bt/ and tools/):
  * Standard library ONLY. No pip, no pandas/numpy.
  * Pure ASCII. No em dashes.
  * Never crash on a partially parsed report: a missing metric prints 'n/a' in
    that cell and the rest of the table still renders.
  * Stream ticks (run_once already does via loader.iter_ticks); never buffer all
    11.86M ticks in memory.

Examples:
    python3 -m python_bt.calibrate --report data/ReportTester-470903.html
    python3 -m python_bt.calibrate --report data/ReportTester-470903.html --json /tmp/calib.json
    python3 -m python_bt.calibrate --mode-both false --data <csv> --from 2026.07.01 --to 2026.08.01

Target Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

from python_bt import config
from python_bt.runner import DEFAULT_DATA, run_once

# Reuse the MT5 report parser from tools/ the same way runner.py bootstraps it.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_TOOLS_DIR = os.path.join(_REPO_ROOT, "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from analyze_report import (  # noqa: E402
    read_html,
    parse_rows,
    extract_kv_pairs,
    extract_metrics,
    parse_trade_table,
    normalize_number,
)

# Default MT5 truth report (HappyBot v2.13, XAUUSD, 2026.07.01-2026.09.01).
DEFAULT_REPORT = os.path.join("data", "ReportTester-470903.html")

# Tolerance (USD per point per 0.01 lot) for the deal-money reconciliation.
RECON_TOL = 0.02
# Number of 'out' deals to print in the reconciliation sample.
RECON_SAMPLE = 6

_DATE_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}")


# ---------------------------------------------------------------------------
# MT5 report -> normalized dict {summary_metrics, deals, deal_summary}
# ---------------------------------------------------------------------------
# The MT5 deals table has 13 columns:
#   0 Time, 1 Deal, 2 Symbol, 3 Type(buy/sell/balance), 4 Direction(in/out),
#   5 Volume, 6 Price, 7 Order, 8 Commission, 9 Swap, 10 Profit, 11 Balance,
#   12 Comment. Data rows start with a YYYY.MM.DD timestamp. The very first
#   date-first 13-col row is the initial 'balance' deposit (Type == 'balance').
_DEAL_COLS = 13
_C_TIME, _C_DEAL, _C_SYMBOL, _C_TYPE, _C_DIR = 0, 1, 2, 3, 4
_C_VOLUME, _C_PRICE, _C_ORDER, _C_COMMISSION = 5, 6, 7, 8
_C_SWAP, _C_PROFIT, _C_BALANCE, _C_COMMENT = 9, 10, 11, 12


def _clean(cell: str) -> str:
    if cell is None:
        return ""
    return cell.replace("\xa0", " ").strip()


def _parse_deal_rows(rows) -> List[Dict[str, object]]:
    """Extract the 13-column MT5 deal rows into normalized per-deal records.

    Skips the initial 'balance' deposit row. Never raises on a short/odd row:
    missing numeric cells become None.
    """
    deals: List[Dict[str, object]] = []
    for row in rows:
        if not row or len(row) != _DEAL_COLS:
            continue
        if not _DATE_RE.match(_clean(row[_C_TIME])):
            continue
        deal_type = _clean(row[_C_TYPE]).lower()
        if deal_type not in ("buy", "sell"):
            # 'balance' (initial deposit) and anything else is not a trade deal.
            continue
        deals.append({
            "time": _clean(row[_C_TIME]),
            "deal": _clean(row[_C_DEAL]),
            "symbol": _clean(row[_C_SYMBOL]),
            "type": deal_type,
            "direction": _clean(row[_C_DIR]).lower(),
            "volume": normalize_number(row[_C_VOLUME]),
            "price": normalize_number(row[_C_PRICE]),
            "order": _clean(row[_C_ORDER]),
            "commission": normalize_number(row[_C_COMMISSION]),
            "swap": normalize_number(row[_C_SWAP]),
            "profit": normalize_number(row[_C_PROFIT]),
        })
    return deals


def _pair_trades(deals: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """Pair 'in'/'out' deals into round-trip trades.

    MT5 opens a position with an 'in' deal (buy=long, sell=short) and closes it
    with an 'out' deal on the opposite side (a long closes with a sell-out, a
    short with a buy-out). Every deal here is 0.01 lot with no partial closes.
    Positions can OVERLAP (Max_Concurrent_Positions > 1), so a naive "next out
    closes the last in" scan mispairs entries. Instead, for each 'out' deal we
    match it to the OPEN entry (of the side it closes) whose price move best
    explains the deal's reported Profit column:

        long:  profit ~= (exit - entry) / TICK_SIZE * TICK_VALUE * volume
        short: profit ~= (entry - exit) / TICK_SIZE * TICK_VALUE * volume

    This profit-guided matching is robust to overlapping positions and to the
    fact that the report's Order column is just a sequential deal counter here.
    Net trade P&L = reported Profit + commission (both sides) + swap, matching
    the Python engine's per-trade realized P&L which is net of commission.
    """
    trades: List[Dict[str, object]] = []
    # Open entries keyed by the side they will be closed FROM:
    #   a buy-in (long) is closed by a sell-out -> store under 'sell'
    #   a sell-in (short) is closed by a buy-out -> store under 'buy'
    open_by_close_side: Dict[str, List[Dict[str, object]]] = {"buy": [], "sell": []}

    def _num(v):
        return v if isinstance(v, (int, float)) else 0.0

    for d in deals:
        direction = d.get("direction")
        dtype = d.get("type")
        if direction == "in":
            close_side = "sell" if dtype == "buy" else "buy"
            open_by_close_side[close_side].append(d)
        elif direction == "out":
            candidates = open_by_close_side.get(dtype, [])
            if not candidates:
                continue
            exit_price = d.get("price")
            vol = _num(d.get("volume"))
            reported = _num(d.get("profit"))
            entry = _best_entry_match(candidates, dtype, exit_price, reported, vol)
            candidates.remove(entry)
            entry_price = entry.get("price")
            # entry 'type' is opposite of the out 'type': long entry is a buy.
            entry_type = "buy" if dtype == "sell" else "sell"
            costs = (_num(entry.get("commission")) + _num(entry.get("swap"))
                     + _num(d.get("commission")) + _num(d.get("swap")))
            net = reported + costs
            # 'reported_gross' is the MT5 Profit column for the closing deal,
            # i.e. the TRUE per-trade gross before commission/swap (used by the
            # money reconciliation). 'net' adds the costs back in. We do NOT key
            # a 'gross_profit' here so the deal-derived summary is never confused
            # with the report's own gross_profit/gross_loss aggregate.
            trades.append({
                "entry_time": entry.get("time"),
                "exit_time": d.get("time"),
                "type": entry_type,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "volume": entry.get("volume"),
                "reported_gross": reported,
                "costs": costs,
                "net": net,
            })
    return trades


def _best_entry_match(candidates: List[Dict[str, object]], out_type: str,
                      exit_price, reported, vol) -> Dict[str, object]:
    """Pick the open entry whose implied price move best explains reported P&L.

    out_type 'sell' closes a long (entry was a buy): move = exit - entry.
    out_type 'buy' closes a short (entry was a sell): move = entry - exit.
    Falls back to the oldest open entry (FIFO) when prices are missing.
    """
    best = None
    best_err = None
    for c in candidates:
        entry_price = c.get("price")
        if entry_price is None or exit_price is None or not vol:
            continue
        if out_type == "sell":  # closing a long
            move = exit_price - entry_price
        else:  # closing a short
            move = entry_price - exit_price
        expected = move / config.TICK_SIZE * config.TICK_VALUE * vol
        err = abs(expected - reported)
        if best_err is None or err < best_err:
            best_err = err
            best = c
    return best if best is not None else candidates[0]


def _summarize_trades(trades: List[Dict[str, object]]) -> Dict[str, object]:
    """Derive MT5-comparable summary metrics from paired round-trip trades.

    Uses NET P&L (profit column net of commission/swap) so the numbers line up
    with the Python engine's per-trade realized P&L, which is net of
    commission. Returns metric keys the Python engine emits so the comparison
    table can pull from a single schema.

    IMPORTANT (net-partitioned, NOT true gross): 'net_partitioned_win_sum' and
    'net_partitioned_loss_sum' are the sums of NET per-trade P&L partitioned
    into wins and losses. They are NOT the report's true gross_profit/gross_loss
    (which sum the deals' Profit column BEFORE commission). On the real report
    the net-partitioned figures are 407.39 / -355.89 while the report's true
    gross is 410.08 / -358.58. They are deliberately NOT keyed 'gross_profit'/
    'gross_loss' so nothing mislabels them as gross: _mt5_value pulls those two
    rows from the report summary_metrics, which carry the true gross. The
    'profit_factor' here is likewise computed from the net-partitioned sums (a
    net PF), matching the Python engine's per-trade net PF definition.
    """
    nets = [float(t["net"]) for t in trades if t.get("net") is not None]
    total_trades = len(nets)
    wins = [p for p in nets if p > 0.0]
    losses = [p for p in nets if p < 0.0]
    net_win_sum = sum(wins)     # net-partitioned, NOT true gross profit
    net_loss_sum = sum(losses)  # net-partitioned, NOT true gross loss
    net_profit = sum(nets)

    if net_loss_sum != 0.0:
        profit_factor = net_win_sum / abs(net_loss_sum)
    elif net_win_sum > 0.0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    win_rate = (len(wins) / total_trades * 100.0) if total_trades else 0.0
    avg_win = (net_win_sum / len(wins)) if wins else 0.0
    avg_loss = (net_loss_sum / len(losses)) if losses else 0.0
    largest_win = max(wins) if wins else 0.0
    largest_loss = min(losses) if losses else 0.0
    win_streak, loss_streak = _streaks(nets)

    return {
        "total_trades": total_trades,
        "total_deals": total_trades * 2,
        "win_rate_pct": win_rate,
        "total_net_profit": net_profit,
        # Net-partitioned win/loss sums (see docstring): NOT true gross. Kept
        # under explicit names so the JSON/deal_summary never mislabels them.
        "net_partitioned_win_sum": net_win_sum,
        "net_partitioned_loss_sum": net_loss_sum,
        "profit_factor": profit_factor,
        "average_profit_trade": avg_win,
        "average_loss_trade": avg_loss,
        "largest_profit_trade": largest_win,
        "largest_loss_trade": largest_loss,
        "max_consecutive_wins_count": win_streak,
        "max_consecutive_losses_count": loss_streak,
    }


def _streaks(nets: List[float]) -> Tuple[int, int]:
    """Longest run of wins and of losses over per-trade net P&L."""
    best_w = best_l = cur_w = cur_l = 0
    for p in nets:
        if p > 0.0:
            cur_w += 1
            cur_l = 0
            best_w = max(best_w, cur_w)
        elif p < 0.0:
            cur_l += 1
            cur_w = 0
            best_l = max(best_l, cur_l)
        else:
            cur_w = cur_l = 0
    return best_w, best_l


def parse_mt5_report(path: str) -> Dict[str, object]:
    """Parse the MT5 report into {summary_metrics, deals, deal_summary, trades}.

    Defensive: if the file cannot be read or has no recognizable tables, returns
    empty structures rather than raising, so the harness still prints a table
    with 'n/a' cells for the MT5 column.
    """
    try:
        html = read_html(path)
    except Exception:
        return {
            "summary_metrics": {},
            "deals": [],
            "trades": [],
            "deal_summary": {},
            "trade_table": {"count": 0},
            "error": "could not read report: {}".format(path),
        }

    rows = parse_rows(html)
    summary_metrics = extract_metrics(extract_kv_pairs(rows))
    trade_table = parse_trade_table(rows)
    deals = _parse_deal_rows(rows)
    trades = _pair_trades(deals)
    deal_summary = _summarize_trades(trades)
    return {
        "summary_metrics": summary_metrics,
        "deals": deals,
        "trades": trades,
        "deal_summary": deal_summary,
        "trade_table": {"count": trade_table.get("count")},
    }


# ---------------------------------------------------------------------------
# Deal-money reconciliation: derive USD-per-point-per-lot from real deals
# ---------------------------------------------------------------------------
def reconcile_deals(trades: List[Dict[str, object]],
                    sample: int = RECON_SAMPLE) -> Dict[str, object]:
    """Derive the money multiplier from real round-trip trades.

    For each trade, price_move = (exit - entry) for buy, (entry - exit) for
    sell. Expected money under the engine's formula is
        price_move / config.TICK_SIZE * config.TICK_VALUE * volume
    which should equal the trade's reported_gross (the closing deal's MT5 Profit
    column, before commission). We also derive the observed USD per 1.00 price
    move per 0.01 lot:
        reported_gross / price_move   (for a 0.01-lot trade -> ~1.00).

    Returns a dict with the sample rows, the mean observed USD/point/lot, the
    config-implied value, and an 'agrees' flag within RECON_TOL.
    """
    rows_out: List[Dict[str, object]] = []
    observed_per_move: List[float] = []
    max_abs_err = 0.0

    for t in trades:
        entry = t.get("entry_price")
        exit_ = t.get("exit_price")
        vol = t.get("volume")
        gross = t.get("reported_gross")
        if entry is None or exit_ is None or vol in (None, 0) or gross is None:
            continue
        if t.get("type") == "buy":
            move = exit_ - entry
        else:
            move = entry - exit_
        expected = move / config.TICK_SIZE * config.TICK_VALUE * vol
        err = abs(expected - gross)
        if err > max_abs_err:
            max_abs_err = err
        # USD per 1.00 price move per 0.01 lot (normalize volume to 0.01 units).
        if move != 0.0:
            per_move_per_001 = (gross / move) / (vol / 0.01)
            observed_per_move.append(per_move_per_001)
        rows_out.append({
            "entry_time": t.get("entry_time"),
            "exit_time": t.get("exit_time"),
            "type": t.get("type"),
            "entry_price": entry,
            "exit_price": exit_,
            "volume": vol,
            "price_move": round(move, 5),
            "reported_gross": round(gross, 5),
            "expected_money": round(expected, 5),
            "abs_err": round(err, 5),
        })

    mean_obs = (sum(observed_per_move) / len(observed_per_move)
                if observed_per_move else None)
    # config-implied USD per 1.00 move per 0.01 lot:
    #   (1.00 / TICK_SIZE) * TICK_VALUE * 0.01
    config_per_move_per_001 = (1.0 / config.TICK_SIZE) * config.TICK_VALUE * 0.01
    agrees = (mean_obs is not None
              and abs(mean_obs - config_per_move_per_001) <= RECON_TOL
              and max_abs_err <= RECON_TOL)

    return {
        "sample_rows": rows_out[:sample],
        "trades_checked": len(rows_out),
        "observed_usd_per_move_per_001lot": mean_obs,
        "config_usd_per_move_per_001lot": config_per_move_per_001,
        "config_tick_value": config.TICK_VALUE,
        "config_tick_size": config.TICK_SIZE,
        "config_contract_size": config.CONTRACT_SIZE,
        "max_abs_error": round(max_abs_err, 5),
        "tolerance": RECON_TOL,
        "agrees": agrees,
    }


# ---------------------------------------------------------------------------
# Comparison table
# ---------------------------------------------------------------------------
# (metric_key, label, is_percent, decimals). Percent rows compute a percentage
# delta only where the MT5 value is non-zero; the rest show an absolute delta.
_COMPARE_ROWS = [
    ("total_trades", "Total trades", False, 0),
    ("total_deals", "Total deals", False, 0),
    ("win_rate_pct", "Win rate %", True, 2),
    ("total_net_profit", "Net profit", False, 2),
    ("gross_profit", "Gross profit", False, 2),
    ("gross_loss", "Gross loss", False, 2),
    ("profit_factor", "Profit factor", False, 2),
    ("average_profit_trade", "Avg win", False, 2),
    ("average_loss_trade", "Avg loss", False, 2),
    ("relative_drawdown_pct", "Max relative DD %", True, 2),
    ("largest_profit_trade", "Largest win", False, 2),
    ("largest_loss_trade", "Largest loss", False, 2),
    ("max_consecutive_wins_count", "Max consec wins", False, 0),
    ("max_consecutive_losses_count", "Max consec losses", False, 0),
]


def _mt5_value(key: str, mt5: Dict[str, object]) -> Optional[float]:
    """Pull an MT5 value, preferring the report summary and falling back to the
    deal-derived summary so every comparable row is populated when possible."""
    summary = mt5.get("summary_metrics", {}) or {}
    derived = mt5.get("deal_summary", {}) or {}
    val = summary.get(key)
    if val is None:
        val = derived.get(key)
    return val


def _fmt_num(val, decimals) -> str:
    if val is None:
        return "n/a"
    if isinstance(val, float):
        if val == float("inf"):
            return "inf"
        if val == float("-inf"):
            return "-inf"
        return "{:,.{d}f}".format(val, d=decimals)
    return str(val)


def _fmt_delta(mt5_val, py_val, is_percent, decimals) -> str:
    """Delta of Py(tick) vs MT5. Absolute for counts/money; also a percent-of-
    MT5 for money/factor rows where MT5 is a non-zero magnitude."""
    if mt5_val is None or py_val is None:
        return "n/a"
    try:
        diff = float(py_val) - float(mt5_val)
    except (TypeError, ValueError):
        return "n/a"
    if diff == float("inf") or diff == float("-inf"):
        return "inf"
    base = _fmt_num(diff, decimals)
    if is_percent:
        # Percentage-point delta; label with 'pp' to avoid confusion.
        return "{} pp".format(base)
    if mt5_val not in (0, 0.0):
        pct = diff / abs(float(mt5_val)) * 100.0
        return "{} ({:+.1f}%)".format(base, pct)
    return base


def build_comparison(mt5: Dict[str, object],
                     py_bar: Optional[Dict[str, object]],
                     py_tick: Optional[Dict[str, object]]) -> Dict[str, object]:
    """Build the comparison structure (rows + reconciliation) for print/JSON."""
    bar_metrics = (py_bar or {}).get("metrics", {}) or {}
    tick_metrics = (py_tick or {}).get("metrics", {}) or {}

    rows = []
    for key, label, is_percent, decimals in _COMPARE_ROWS:
        mt5_val = _mt5_value(key, mt5)
        bar_val = bar_metrics.get(key)
        tick_val = tick_metrics.get(key)
        rows.append({
            "key": key,
            "label": label,
            "is_percent": is_percent,
            "decimals": decimals,
            "mt5": mt5_val,
            "py_bar": bar_val,
            "py_tick": tick_val,
            "delta_tick_vs_mt5": (
                (float(tick_val) - float(mt5_val))
                if (mt5_val is not None and tick_val is not None)
                else None
            ),
        })
    return {"rows": rows, "reconciliation": reconcile_deals(mt5.get("trades", []))}


def _print_reconciliation(recon: Dict[str, object]) -> None:
    print("=" * 78)
    print("DEAL-MONEY RECONCILIATION (derive USD-per-point-per-lot from real MT5 deals)")
    print("=" * 78)
    print("  formula: expected = price_move / TICK_SIZE * TICK_VALUE * volume")
    print("  {:<20} {:<9} {:<9} {:>9} {:>9} {:>9}".format(
        "exit_time", "type", "vol", "move", "reported", "expected"))
    print("  " + "-" * 74)
    for r in recon.get("sample_rows", []):
        print("  {:<20} {:<9} {:<9} {:>9} {:>9} {:>9}".format(
            str(r.get("exit_time"))[:20],
            str(r.get("type")),
            _fmt_num(r.get("volume"), 2),
            _fmt_num(r.get("price_move"), 2),
            _fmt_num(r.get("reported_gross"), 2),
            _fmt_num(r.get("expected_money"), 2),
        ))
    print("  " + "-" * 74)
    obs = recon.get("observed_usd_per_move_per_001lot")
    cfg = recon.get("config_usd_per_move_per_001lot")
    print("  trades checked:            {}".format(recon.get("trades_checked")))
    print("  observed USD /1.00 move /0.01 lot: {}".format(
        _fmt_num(obs, 4) if obs is not None else "n/a"))
    print("  config-implied  (same units):      {}".format(_fmt_num(cfg, 4)))
    print("  config TICK_VALUE={} TICK_SIZE={} CONTRACT_SIZE={}".format(
        recon.get("config_tick_value"),
        recon.get("config_tick_size"),
        recon.get("config_contract_size")))
    print("  max abs error: {}  tolerance: {}".format(
        _fmt_num(recon.get("max_abs_error"), 4), recon.get("tolerance")))
    verdict = "AGREES" if recon.get("agrees") else "MISMATCH"
    print("  RECONCILIATION: {} (constants confirmed by real deals)".format(verdict)
          if recon.get("agrees")
          else "  RECONCILIATION: {} (review config constants)".format(verdict))


def _print_comparison(comparison: Dict[str, object], meta: Dict[str, object]) -> None:
    print("=" * 78)
    print("MT5 vs PYTHON ENGINE CALIBRATION")
    print("=" * 78)
    print("  report: {}".format(meta.get("report")))
    print("  data:   {}".format(meta.get("data")))
    print("  window: {} -> {}   params: {}".format(
        meta.get("date_from") or "(full)",
        meta.get("date_to") or "(full)",
        meta.get("params")))
    print("-" * 78)
    header = "  {:<20} {:>12} {:>12} {:>12} {:>16}".format(
        "metric", "MT5", "Py(bar)", "Py(tick)", "delta(tick-MT5)")
    print(header)
    print("  " + "-" * 74)
    for row in comparison["rows"]:
        dec = row["decimals"]
        print("  {:<20} {:>12} {:>12} {:>12} {:>16}".format(
            row["label"],
            _fmt_num(row["mt5"], dec),
            _fmt_num(row["py_bar"], dec),
            _fmt_num(row["py_tick"], dec),
            _fmt_delta(row["mt5"], row["py_tick"], row["is_percent"], dec),
        ))
    print("-" * 78)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _load_params(raw: Optional[str]) -> Dict[str, object]:
    """Parse --params: inline JSON, or @file.json for a file path (mirrors runner)."""
    if not raw:
        return {}
    if raw.startswith("@"):
        with open(raw[1:], "r") as fh:
            return json.load(fh)
    return json.loads(raw)


def _truthy(val: str) -> bool:
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m python_bt.calibrate",
        description="Calibrate the Python backtester against the MT5 truth "
                    "report: parse MT5 summary + deals, reconcile the money "
                    "multiplier, run the engine in bar and tick mode, and print "
                    "a side-by-side comparison table.",
    )
    p.add_argument("--report", default=DEFAULT_REPORT, help="MT5 HTML report path")
    p.add_argument("--data", default=DEFAULT_DATA, help="tick CSV path")
    p.add_argument("--from", dest="date_from", default=None, help="YYYY.MM.DD")
    p.add_argument("--to", dest="date_to", default=None, help="YYYY.MM.DD")
    p.add_argument("--params", default=None,
                   help="JSON string or @file.json of engine params (default v2.13)")
    p.add_argument("--strategy", default="happybot", help="strategy name (registry)")
    p.add_argument("--mode-both", dest="mode_both", default="true",
                   help="run BOTH bar and tick mode (default true); "
                        "false runs tick mode only")
    p.add_argument("--max-ticks", type=int, default=None,
                   help="cap ticks for a quick smoke run")
    p.add_argument("--json", dest="json_out", default=None,
                   help="write the full comparison as JSON here")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    params = _load_params(args.params)
    run_both = _truthy(args.mode_both)

    if not os.path.exists(args.report):
        print("WARNING: report not found: {} (MT5 column will be n/a)".format(args.report))
    mt5 = parse_mt5_report(args.report)
    if mt5.get("error"):
        print("WARNING: {}".format(mt5["error"]))

    py_bar = None
    if run_both:
        print("running Python engine (bar mode) ...")
        py_bar = run_once(args.data, args.strategy, params,
                          args.date_from, args.date_to, "bar", args.max_ticks)

    print("running Python engine (tick mode) ...")
    py_tick = run_once(args.data, args.strategy, params,
                       args.date_from, args.date_to, "tick", args.max_ticks)

    comparison = build_comparison(mt5, py_bar, py_tick)
    meta = {
        "report": args.report,
        "data": args.data,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "params": params or "(v2.13 defaults)",
        "strategy": args.strategy,
        "mode_both": run_both,
    }

    print("")
    _print_reconciliation(comparison["reconciliation"])
    print("")
    _print_comparison(comparison, meta)

    if args.json_out:
        payload = {
            "meta": meta,
            "mt5_summary_metrics": mt5.get("summary_metrics", {}),
            "mt5_deal_summary": mt5.get("deal_summary", {}),
            "mt5_deal_count": mt5.get("trade_table", {}).get("count"),
            "py_bar_metrics": (py_bar or {}).get("metrics") if py_bar else None,
            "py_tick_metrics": (py_tick or {}).get("metrics"),
            "comparison_rows": comparison["rows"],
            "reconciliation": comparison["reconciliation"],
        }
        with open(args.json_out, "w") as fh:
            json.dump(payload, fh, indent=2, default=_json_default)
        print("")
        print("wrote {}".format(args.json_out))

    return 0


def _json_default(obj):
    """Make inf/-inf and other odd floats JSON-safe."""
    if isinstance(obj, float):
        if obj == float("inf"):
            return "inf"
        if obj == float("-inf"):
            return "-inf"
    return str(obj)


if __name__ == "__main__":
    sys.exit(main())
