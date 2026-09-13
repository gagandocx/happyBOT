#!/usr/bin/env python3
"""Analyze MetaTrader 5 Strategy Tester HTML backtest reports for HappyBot.

This tool is part of the HappyBot (XAUUSD M5) backtest-improvement loop. It parses
an MT5 Strategy Tester HTML report (both the older "ReportTester" layout and the
newer Strategy Tester export), extracts the key performance metrics, produces a
human-readable summary plus a DIAGNOSIS tuned for the user's stated goal --
maximize return while keeping drawdown conservative -- and writes a machine
readable <basename>.summary.json next to each report.

Design constraints:
  * Standard library ONLY (html.parser, re, json, argparse, os, sys). No pip
    installs, no third-party packages. The sandbox network may be restricted.
  * Never crash on a malformed or partial report. One bad file must not abort a
    batch run.

Usage:
    python3 tools/analyze_report.py reports/round01_20240115.html
    python3 tools/analyze_report.py reports/round01_*.html
    python3 tools/analyze_report.py report.html --json-dir /tmp/out
    python3 tools/analyze_report.py report.html --no-json
"""

import argparse
import json
import os
import re
import sys
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# Diagnosis thresholds (tuned for "maximize return, conservative DD"). These
# are named constants so they are easy to tune as the strategy evolves.
# ---------------------------------------------------------------------------
REL_DD_WARN_PCT = 20.0        # relative drawdown % above this -> warn
REL_DD_SERIOUS_PCT = 35.0     # relative drawdown % above this -> serious
PROFIT_FACTOR_MIN = 1.2       # profit factor below this -> weak edge
PROFIT_FACTOR_GOOD = 1.5      # profit factor at/above this -> healthy
LOW_TRADE_COUNT = 100         # fewer trades than this -> statistically weak
RECOVERY_FACTOR_MIN = 2.0     # recovery factor below this -> fragile
# Fraction of net profit that a single max-consecutive-loss streak may wipe out
# before we flag risk-of-ruin.
CONSEC_LOSS_RISK_FRACTION = 0.5

# Cap on how many raw trade rows we keep in the JSON / print. Keeps output
# readable for reports with thousands of deals.
MAX_TRADE_ROWS_IN_JSON = 200


# ---------------------------------------------------------------------------
# Canonical metric labels and their known synonyms across MT5 report layouts.
# Keys are canonical names; values are lists of normalized label variants.
# Labels are normalized (lowercased, punctuation stripped) before lookup.
# ---------------------------------------------------------------------------
LABEL_SYNONYMS = {
    "total_net_profit": ["total net profit", "net profit"],
    "gross_profit": ["gross profit"],
    "gross_loss": ["gross loss"],
    "profit_factor": ["profit factor"],
    "expected_payoff": ["expected payoff"],
    "recovery_factor": ["recovery factor"],
    "sharpe_ratio": ["sharpe ratio"],
    "absolute_drawdown": [
        "balance drawdown absolute",
        "absolute drawdown",
        "equity drawdown absolute",
    ],
    "maximal_drawdown": [
        "balance drawdown maximal",
        "maximal drawdown",
        "equity drawdown maximal",
        "maximum drawdown",
    ],
    "relative_drawdown": [
        "balance drawdown relative",
        "relative drawdown",
        "equity drawdown relative",
    ],
    "total_trades": ["total trades"],
    "total_deals": ["total deals"],
    "profit_trades": [
        "profit trades of total",
        "profit trades",
        "profit trades of total in ",
    ],
    "loss_trades": ["loss trades of total", "loss trades"],
    "largest_profit_trade": ["largest profit trade"],
    "largest_loss_trade": ["largest loss trade"],
    "average_profit_trade": ["average profit trade"],
    "average_loss_trade": ["average loss trade"],
    "max_consecutive_wins": [
        "maximum consecutive wins profit in money",
        "maximum consecutive wins",
        "maximal consecutive wins",
    ],
    "max_consecutive_losses": [
        "maximum consecutive losses loss in money",
        "maximum consecutive losses",
        "maximal consecutive losses",
    ],
}

# Metrics whose cell often contains a combined "PERCENT% (MONEY)" or
# "MONEY (PERCENT%)" value from which we split two numbers.
DRAWDOWN_METRICS = {"maximal_drawdown", "relative_drawdown", "absolute_drawdown"}

# Metrics whose cell is often "COUNT (MONEY)" e.g. "5 (1234.56)".
COUNT_MONEY_METRICS = {"max_consecutive_wins", "max_consecutive_losses"}

# Metrics whose cell is often "COUNT (PERCENT%)" e.g. "123 (61.50%)".
COUNT_PERCENT_METRICS = {"profit_trades", "loss_trades"}


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------
class _TableParser(HTMLParser):
    """Collect table cell text row-by-row from an HTML document.

    We do not rely on a specific table structure; we gather every <tr> as a
    list of cell strings, flattening <td>/<th>. This lets us treat MT5 reports
    (which lay metrics out as label/value cell pairs) generically.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []            # list[list[str]] : all rows across all tables
        self._current_row = None  # list[str] for the row being built
        self._cell_parts = None   # list[str] for the cell being built
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            if self._current_row is not None and self._cell_parts is not None:
                text = "".join(self._cell_parts)
                self._current_row.append(_clean_ws(text))
            self._in_cell = False
            self._cell_parts = None
        elif tag == "tr":
            if self._current_row is not None:
                self.rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data):
        if self._in_cell and self._cell_parts is not None:
            self._cell_parts.append(data)


def read_html(path):
    """Read an HTML file trying a few common MT5 encodings."""
    for enc in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                return fh.read()
        except (UnicodeError, UnicodeDecodeError):
            continue
    # Last resort: binary read with replacement so we never crash.
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def _clean_ws(text):
    """Collapse whitespace and normalize non-breaking spaces."""
    if text is None:
        return ""
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_rows(html):
    """Return all table rows (list of cell-string lists) from the HTML."""
    parser = _TableParser()
    try:
        parser.feed(html)
    except Exception:
        # HTMLParser can raise on badly broken markup; salvage what we have.
        pass
    return parser.rows


# ---------------------------------------------------------------------------
# Number normalization
# ---------------------------------------------------------------------------
def normalize_number(raw):
    """Convert an MT5 cell string to a float, or None if not numeric.

    Handles currency symbols, spaces / non-breaking spaces as thousands
    separators, comma thousands separators, and trailing percent signs.
    """
    if raw is None:
        return None
    s = _clean_ws(str(raw))
    if not s:
        return None
    # Strip common currency symbols and the percent sign.
    s = re.sub(r"[$€£¥%]", "", s)
    s = s.replace("\xa0", " ").strip()

    # Determine the decimal separator. MT5 reports usually use '.' as decimal.
    # Remove spaces (thousands sep). Handle both '1,234.56' and '1 234,56'.
    has_dot = "." in s
    has_comma = "," in s
    s_nospace = s.replace(" ", "")
    if has_dot and has_comma:
        # Assume comma is thousands, dot is decimal: 1,234.56
        s_norm = s_nospace.replace(",", "")
    elif has_comma and not has_dot:
        # Could be european decimal (1234,56) or thousands (1,234).
        # If exactly one comma with 1-2 trailing digits -> decimal comma.
        if re.search(r",\d{1,2}$", s_nospace):
            s_norm = s_nospace.replace(",", ".")
        else:
            s_norm = s_nospace.replace(",", "")
    else:
        s_norm = s_nospace
    m = re.search(r"[-+]?\d*\.?\d+", s_norm)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def split_percent_money(raw):
    """Split a combined cell into (percent, money).

    Handles 'PERCENT% (MONEY)' and 'MONEY (PERCENT%)'. Returns (percent, money)
    where either may be None. Numbers are normalized.
    """
    if raw is None:
        return (None, None)
    s = _clean_ws(str(raw))
    if not s:
        return (None, None)

    # Find a parenthesized part and an outside part.
    m = re.search(r"\(([^)]*)\)", s)
    inside = m.group(1) if m else None
    outside = re.sub(r"\([^)]*\)", "", s).strip() if m else s

    def _is_pct(chunk):
        return chunk is not None and "%" in chunk

    percent = None
    money = None
    if _is_pct(outside) and inside is not None:
        percent = normalize_number(outside)
        money = normalize_number(inside)
    elif _is_pct(inside):
        percent = normalize_number(inside)
        money = normalize_number(outside)
    else:
        # No explicit percent marker. If two numbers, treat first as money.
        if inside is not None:
            money = normalize_number(outside)
            # inside might still be a percent-less value; keep as percent slot.
            percent = normalize_number(inside)
        else:
            money = normalize_number(outside)
    return (percent, money)


def split_count_money(raw):
    """Split 'COUNT (MONEY)' -> (count:int|None, money:float|None)."""
    if raw is None:
        return (None, None)
    s = _clean_ws(str(raw))
    m = re.search(r"\(([^)]*)\)", s)
    inside = m.group(1) if m else None
    outside = re.sub(r"\([^)]*\)", "", s).strip() if m else s
    count = normalize_number(outside)
    money = normalize_number(inside) if inside is not None else None
    count_int = int(count) if count is not None else None
    return (count_int, money)


def split_count_percent(raw):
    """Split 'COUNT (PERCENT%)' -> (count:int|None, percent:float|None)."""
    if raw is None:
        return (None, None)
    s = _clean_ws(str(raw))
    m = re.search(r"\(([^)]*)\)", s)
    inside = m.group(1) if m else None
    outside = re.sub(r"\([^)]*\)", "", s).strip() if m else s
    count = normalize_number(outside)
    percent = normalize_number(inside) if inside is not None else None
    count_int = int(count) if count is not None else None
    return (count_int, percent)


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------
def _normalize_label(label):
    """Lowercase, strip punctuation/colons, collapse whitespace for matching."""
    s = _clean_ws(label).lower()
    s = s.replace(":", " ")
    # Drop trailing parenthetical qualifiers like "(%)".
    s = re.sub(r"[^a-z0-9%() ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_kv_pairs(rows):
    """Turn table rows into a flat {normalized_label: value_string} dict.

    MT5 metric tables usually place a label cell immediately followed by its
    value cell (often several label/value pairs per row). We scan each row and
    pair every label-like cell with the next non-empty cell.
    """
    pairs = {}
    for row in rows:
        cells = [c for c in row]
        i = 0
        while i < len(cells):
            label = cells[i]
            norm = _normalize_label(label)
            # A label is something with letters; value is the next cell.
            if norm and re.search(r"[a-z]", norm) and i + 1 < len(cells):
                value = cells[i + 1]
                if norm not in pairs:
                    pairs[norm] = value
                i += 2
                continue
            i += 1
    return pairs


def _match_metric(norm_label):
    """Return the canonical metric name for a normalized label, or None."""
    for canonical, variants in LABEL_SYNONYMS.items():
        for v in variants:
            v = v.strip()
            if not v:
                continue
            if norm_label == v or norm_label.startswith(v):
                return canonical
    return None


def extract_metrics(pairs):
    """Map raw label/value pairs to canonical, numeric metrics."""
    metrics = {name: None for name in LABEL_SYNONYMS}
    # Extra split fields.
    metrics["maximal_drawdown_pct"] = None
    metrics["maximal_drawdown_money"] = None
    metrics["relative_drawdown_pct"] = None
    metrics["relative_drawdown_money"] = None
    metrics["absolute_drawdown_money"] = None
    metrics["win_rate_pct"] = None
    metrics["profit_trades_count"] = None
    metrics["loss_trades_count"] = None
    metrics["max_consecutive_wins_count"] = None
    metrics["max_consecutive_wins_money"] = None
    metrics["max_consecutive_losses_count"] = None
    metrics["max_consecutive_losses_money"] = None

    for norm_label, value in pairs.items():
        canonical = _match_metric(norm_label)
        if canonical is None:
            continue

        if canonical in DRAWDOWN_METRICS:
            percent, money = split_percent_money(value)
            if canonical == "absolute_drawdown":
                metrics["absolute_drawdown"] = money if money is not None else normalize_number(value)
                metrics["absolute_drawdown_money"] = metrics["absolute_drawdown"]
            elif canonical == "maximal_drawdown":
                metrics["maximal_drawdown_money"] = money
                metrics["maximal_drawdown_pct"] = percent
                metrics["maximal_drawdown"] = money
            elif canonical == "relative_drawdown":
                metrics["relative_drawdown_money"] = money
                metrics["relative_drawdown_pct"] = percent
                metrics["relative_drawdown"] = money
        elif canonical in COUNT_MONEY_METRICS:
            count, money = split_count_money(value)
            metrics[canonical] = count
            metrics[canonical + "_count"] = count
            metrics[canonical + "_money"] = money
        elif canonical in COUNT_PERCENT_METRICS:
            count, percent = split_count_percent(value)
            metrics[canonical] = count
            metrics[canonical + "_count"] = count
            if canonical == "profit_trades" and percent is not None:
                metrics["win_rate_pct"] = percent
        elif canonical in ("total_trades", "total_deals"):
            num = normalize_number(value)
            metrics[canonical] = int(num) if num is not None else None
        else:
            metrics[canonical] = normalize_number(value)

    # Derive win rate if not present but counts are.
    if metrics["win_rate_pct"] is None:
        pt = metrics.get("profit_trades_count")
        tot = metrics.get("total_trades")
        if pt is not None and tot:
            try:
                metrics["win_rate_pct"] = round(100.0 * pt / tot, 2)
            except ZeroDivisionError:
                pass
    return metrics


# ---------------------------------------------------------------------------
# Trade / deal table parsing
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}")  # MT5 dates: 2024.01.15 ...

# Header labels (normalized) that identify the per-deal "Profit" column and
# the "Balance" column. Balance is tracked so we can explicitly avoid summing
# it as if it were profit.
_PROFIT_HEADER_TOKENS = ("profit",)
_BALANCE_HEADER_TOKENS = ("balance",)


def _find_profit_column_index(rows):
    """Locate the 0-based index of the deal table's 'Profit' column.

    Scans for a header row (a row containing a cell whose normalized text is
    exactly 'profit'). Returns None if no explicit Profit header is found, so
    callers can fall back gracefully instead of guessing (and summing the
    Balance column by mistake, which was the previous bug).
    """
    for row in rows:
        # A header row is one that carries a 'profit' label but is not itself a
        # data row (data rows start with an MT5 timestamp).
        if row and _DATE_RE.match(_clean_ws(row[0])):
            continue
        for idx, cell in enumerate(row):
            if _clean_ws(cell).lower() == "profit":
                return idx
    return None


def parse_trade_table(rows):
    """Extract per-deal rows and aggregate the true Profit column.

    MT5 deal tables start each data row with a timestamp like
    '2024.01.15 10:30:00'. We collect those rows, capping the number retained.

    The aggregate is computed from the explicit 'Profit' column identified by
    the table header (NOT the last numeric cell, which is typically the running
    Balance). If no Profit header can be located we omit the money aggregate
    and report an honest row count only, rather than summing the wrong column.
    """
    deal_rows = []
    for row in rows:
        if not row:
            continue
        first = _clean_ws(row[0])
        if _DATE_RE.match(first) and len(row) >= 4:
            deal_rows.append(row)

    count = len(deal_rows)
    profit_idx = _find_profit_column_index(rows)

    profits = []
    if profit_idx is not None:
        for row in deal_rows:
            if profit_idx < len(row):
                val = normalize_number(row[profit_idx])
                if val is not None:
                    profits.append(val)

    aggregate = None
    if profit_idx is not None and profits:
        # Zero-profit rows (e.g. position-open deals) are neither wins nor
        # losses; count only strictly positive / negative closed results.
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p < 0]
        aggregate = {
            "profit_column_index": profit_idx,
            "rows_with_profit_value": len(profits),
            "sum_profit_column": round(sum(profits), 2),
            "positive_count": len(wins),
            "negative_count": len(losses),
            "zero_count": len(profits) - len(wins) - len(losses),
        }

    return {
        "count": count,
        "profit_column_found": profit_idx is not None,
        "aggregate": aggregate,
        "rows": deal_rows[:MAX_TRADE_ROWS_IN_JSON],
        "rows_truncated": count > MAX_TRADE_ROWS_IN_JSON,
    }


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------
def build_diagnosis(metrics):
    """Build a list of diagnosis flags for conservative-DD / return goal.

    Each flag is a dict: {level, code, message}. level in
    {"ok", "info", "warn", "serious"}.
    """
    flags = []

    def add(level, code, message):
        flags.append({"level": level, "code": code, "message": message})

    net = metrics.get("total_net_profit")
    rel_dd = metrics.get("relative_drawdown_pct")
    max_dd = metrics.get("maximal_drawdown_pct")
    pf = metrics.get("profit_factor")
    trades = metrics.get("total_trades")
    rf = metrics.get("recovery_factor")
    consec_loss_money = metrics.get("max_consecutive_losses_money")

    # Net profit direction.
    if net is not None:
        if net > 0:
            add("ok", "net_profit_positive", "Net profit is positive ({:.2f}).".format(net))
        else:
            add("serious", "net_profit_negative",
                "Net profit is NEGATIVE ({:.2f}); the strategy loses money.".format(net))
    else:
        add("info", "net_profit_missing", "Net profit not found in report.")

    # Relative drawdown (primary conservative-DD gate).
    dd_for_check = rel_dd if rel_dd is not None else max_dd
    dd_name = "relative" if rel_dd is not None else "maximal"
    if dd_for_check is not None:
        if dd_for_check >= REL_DD_SERIOUS_PCT:
            add("serious", "drawdown_serious",
                "{} drawdown {:.2f}% >= {:.0f}% (serious). Too aggressive for a conservative-DD goal.".format(
                    dd_name.capitalize(), dd_for_check, REL_DD_SERIOUS_PCT))
        elif dd_for_check >= REL_DD_WARN_PCT:
            add("warn", "drawdown_high",
                "{} drawdown {:.2f}% >= {:.0f}% (elevated). Consider tighter risk / smaller lots.".format(
                    dd_name.capitalize(), dd_for_check, REL_DD_WARN_PCT))
        else:
            add("ok", "drawdown_ok",
                "{} drawdown {:.2f}% is within the conservative {:.0f}% threshold.".format(
                    dd_name.capitalize(), dd_for_check, REL_DD_WARN_PCT))
    else:
        add("info", "drawdown_missing", "Drawdown % not found in report; cannot assess DD.")

    # Profit factor.
    if pf is not None:
        if pf < PROFIT_FACTOR_MIN:
            add("warn", "profit_factor_low",
                "Profit factor {:.2f} < {:.2f}: weak edge.".format(pf, PROFIT_FACTOR_MIN))
        elif pf >= PROFIT_FACTOR_GOOD:
            add("ok", "profit_factor_good",
                "Profit factor {:.2f} >= {:.2f}: healthy edge.".format(pf, PROFIT_FACTOR_GOOD))
        else:
            add("info", "profit_factor_ok",
                "Profit factor {:.2f} is acceptable but not strong.".format(pf))
    else:
        add("info", "profit_factor_missing", "Profit factor not found in report.")

    # Trade count (sample size).
    if trades is not None:
        if trades < LOW_TRADE_COUNT:
            add("warn", "low_trade_count",
                "Only {} trades (< {}): statistically weak, high overfit risk.".format(
                    int(trades), LOW_TRADE_COUNT))
        else:
            add("ok", "trade_count_ok",
                "{} trades: adequate sample size.".format(int(trades)))
    else:
        add("info", "trade_count_missing", "Total trades not found in report.")

    # Recovery factor.
    if rf is not None:
        if rf < RECOVERY_FACTOR_MIN:
            add("warn", "recovery_factor_low",
                "Recovery factor {:.2f} < {:.1f}: profit is small relative to drawdown.".format(
                    rf, RECOVERY_FACTOR_MIN))
        else:
            add("ok", "recovery_factor_ok",
                "Recovery factor {:.2f}: profit comfortably exceeds drawdown.".format(rf))

    # Risk of ruin: consecutive-loss streak vs net profit.
    if consec_loss_money is not None and net not in (None, 0):
        streak = abs(consec_loss_money)
        frac = streak / abs(net) if net else None
        if frac is not None and frac >= CONSEC_LOSS_RISK_FRACTION:
            add("warn", "consecutive_loss_risk",
                "Worst losing streak ({:.2f}) is {:.0f}% of net profit: a single bad run can erase most gains.".format(
                    streak, frac * 100))
        else:
            add("ok", "consecutive_loss_ok",
                "Worst losing streak ({:.2f}) is a modest fraction of net profit.".format(streak))

    return flags


# Flag codes that indicate a required metric could not be found in the report.
# When the report is empty or unparseable, the diagnosis is made up entirely of
# these "missing" flags and we must NOT report "LOOKS REASONABLE".
_MISSING_FLAG_CODES = {
    "drawdown_missing",
    "profit_factor_missing",
    "trade_count_missing",
    "net_profit_missing",
}

# Minimum number of the core gating metrics (net profit, drawdown, profit
# factor, trade count) that must be present for a "reasonable" verdict to be
# meaningful. Below this we return INCONCLUSIVE instead.
MIN_CORE_METRICS_FOR_VERDICT = 2


def _core_metrics_present(metrics):
    """Count how many of the core gating metrics were actually parsed."""
    core = 0
    if metrics.get("total_net_profit") is not None:
        core += 1
    if (metrics.get("relative_drawdown_pct") is not None
            or metrics.get("maximal_drawdown_pct") is not None):
        core += 1
    if metrics.get("profit_factor") is not None:
        core += 1
    if metrics.get("total_trades") is not None:
        core += 1
    return core


def diagnosis_verdict(flags, metrics=None):
    """Summarize the worst level present into a one-line verdict.

    A report with too few core metrics (empty / garbage / unparseable input)
    yields INCONCLUSIVE, even though the "missing metric" notices are recorded
    as info-level flags. This closes the earlier dead-code path where an empty
    report incorrectly read as "LOOKS REASONABLE".
    """
    levels = {f["level"] for f in flags}
    if "serious" in levels:
        return "NOT SUITABLE (serious issues for a conservative-DD goal)"
    if "warn" in levels:
        return "NEEDS IMPROVEMENT (warnings present)"

    # Decide whether we parsed enough to say anything meaningful.
    if metrics is not None:
        core_present = _core_metrics_present(metrics)
    else:
        # Fall back to flag inspection: if every flag is a "missing" notice we
        # clearly parsed nothing useful.
        non_missing = [f for f in flags if f["code"] not in _MISSING_FLAG_CODES]
        core_present = len(non_missing)

    if core_present < MIN_CORE_METRICS_FOR_VERDICT:
        return "INCONCLUSIVE (insufficient metrics parsed)"

    if levels and levels <= {"ok", "info"}:
        return "LOOKS REASONABLE (no warnings)"
    return "INCONCLUSIVE (insufficient metrics parsed)"


# ---------------------------------------------------------------------------
# Summary assembly + printing
# ---------------------------------------------------------------------------
def summarize(path, metrics, trade_table, flags):
    """Build the JSON-serializable summary dict for one report."""
    return {
        "report": os.path.basename(path),
        "report_path": path,
        "metrics": metrics,
        "trade_table": {
            "count": trade_table["count"],
            "profit_column_found": trade_table.get("profit_column_found", False),
            "aggregate": trade_table["aggregate"],
            "rows_truncated": trade_table["rows_truncated"],
            "rows_kept": len(trade_table["rows"]),
        },
        "diagnosis": {
            "verdict": diagnosis_verdict(flags, metrics),
            "flags": flags,
        },
    }


_PRINT_ORDER = [
    ("total_net_profit", "Total net profit", ""),
    ("gross_profit", "Gross profit", ""),
    ("gross_loss", "Gross loss", ""),
    ("profit_factor", "Profit factor", ""),
    ("expected_payoff", "Expected payoff", ""),
    ("recovery_factor", "Recovery factor", ""),
    ("sharpe_ratio", "Sharpe ratio", ""),
    ("absolute_drawdown", "Absolute drawdown", ""),
    ("maximal_drawdown_money", "Maximal drawdown (money)", ""),
    ("maximal_drawdown_pct", "Maximal drawdown (%)", "%"),
    ("relative_drawdown_pct", "Relative drawdown (%)", "%"),
    ("relative_drawdown_money", "Relative drawdown (money)", ""),
    ("total_trades", "Total trades", ""),
    ("total_deals", "Total deals", ""),
    ("win_rate_pct", "Win rate", "%"),
    ("largest_profit_trade", "Largest profit trade", ""),
    ("largest_loss_trade", "Largest loss trade", ""),
    ("average_profit_trade", "Average profit trade", ""),
    ("average_loss_trade", "Average loss trade", ""),
    ("max_consecutive_wins_count", "Max consecutive wins (count)", ""),
    ("max_consecutive_wins_money", "Max consecutive wins (money)", ""),
    ("max_consecutive_losses_count", "Max consecutive losses (count)", ""),
    ("max_consecutive_losses_money", "Max consecutive losses (money)", ""),
]

_LEVEL_TAG = {"ok": "[ OK ]", "info": "[INFO]", "warn": "[WARN]", "serious": "[!!!!]"}


def print_summary(summary):
    """Print a human-readable metrics block + DIAGNOSIS to stdout."""
    metrics = summary["metrics"]
    print("=" * 68)
    print("MT5 BACKTEST REPORT: {}".format(summary["report"]))
    print("=" * 68)
    print("METRICS")
    print("-" * 68)
    for key, label, suffix in _PRINT_ORDER:
        val = metrics.get(key)
        if val is None:
            shown = "n/a"
        elif isinstance(val, float):
            shown = "{:,.2f}{}".format(val, suffix)
        else:
            shown = "{}{}".format(val, suffix)
        print("  {:<32} {}".format(label + ":", shown))

    tt = summary["trade_table"]
    print("-" * 68)
    print("  {:<32} {}".format("Per-deal rows parsed:", tt["count"]))
    if tt.get("aggregate"):
        agg = tt["aggregate"]
        print("  {:<32} {}".format("  profit column sum:",
                                    "{:,.2f}".format(agg["sum_profit_column"])))
        print("  {:<32} {}".format("  win/loss/flat rows:",
                                    "{} / {} / {}".format(
                                        agg["positive_count"],
                                        agg["negative_count"],
                                        agg.get("zero_count", 0))))
    elif tt["count"]:
        # Rows exist but no explicit Profit column header was found; report the
        # honest row count only rather than a misleading money figure.
        print("  {:<32} {}".format("  profit aggregate:",
                                    "n/a (no Profit column header found)"))

    print()
    print("DIAGNOSIS  (goal: maximize return with conservative drawdown)")
    print("-" * 68)
    print("  VERDICT: {}".format(summary["diagnosis"]["verdict"]))
    for flag in summary["diagnosis"]["flags"]:
        tag = _LEVEL_TAG.get(flag["level"], "[????]")
        print("  {} {}".format(tag, flag["message"]))
    print()


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------
def analyze_file(path, json_dir=None, write_json=True):
    """Parse one report and return its summary dict. Raises on I/O errors."""
    html = read_html(path)
    rows = parse_rows(html)
    pairs = extract_kv_pairs(rows)
    metrics = extract_metrics(pairs)
    trade_table = parse_trade_table(rows)
    flags = build_diagnosis(metrics)
    summary = summarize(path, metrics, trade_table, flags)

    if write_json:
        base = os.path.splitext(os.path.basename(path))[0]
        out_dir = json_dir if json_dir else os.path.dirname(os.path.abspath(path))
        out_path = os.path.join(out_dir, base + ".summary.json")
        # Include capped raw rows in the JSON for reference.
        json_payload = dict(summary)
        json_payload["trade_table"] = dict(summary["trade_table"])
        json_payload["trade_table"]["rows"] = trade_table["rows"]
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(json_payload, fh, indent=2)
        summary["_json_written_to"] = out_path

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Parse MT5 Strategy Tester HTML backtest reports and diagnose "
                    "them for a maximize-return / conservative-drawdown goal.",
    )
    parser.add_argument(
        "reports", nargs="+",
        help="One or more MT5 HTML report paths (globs may be pre-expanded by the shell).",
    )
    parser.add_argument(
        "--json-dir", default=None,
        help="Directory to write <basename>.summary.json files "
             "(default: alongside each input report).",
    )
    parser.add_argument(
        "--no-json", action="store_true",
        help="Do not write JSON summary files; print to stdout only.",
    )
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Usage error: any missing file -> non-zero exit.
    missing = [p for p in args.reports if not os.path.isfile(p)]
    if missing:
        for p in missing:
            print("ERROR: file not found: {}".format(p), file=sys.stderr)
        return 2

    if args.json_dir and not os.path.isdir(args.json_dir):
        try:
            os.makedirs(args.json_dir, exist_ok=True)
        except OSError as exc:
            print("ERROR: cannot create --json-dir {}: {}".format(args.json_dir, exc),
                  file=sys.stderr)
            return 2

    any_ok = False
    for path in args.reports:
        try:
            summary = analyze_file(path, json_dir=args.json_dir,
                                   write_json=not args.no_json)
            print_summary(summary)
            if summary.get("_json_written_to"):
                print("JSON summary written: {}".format(summary["_json_written_to"]))
                print()
            any_ok = True
        except Exception as exc:  # never abort the batch on one bad file
            print("ERROR analyzing {}: {}".format(path, exc), file=sys.stderr)
            continue

    # Exit 0 if at least one report was processed (even partially).
    return 0 if any_ok else 1


if __name__ == "__main__":
    sys.exit(main())
