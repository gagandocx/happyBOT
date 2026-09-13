"""Runner CLI for the XAUUSD backtester.

Run a strategy over the tick data and print metrics + the tuner score + a short
diagnosis, optionally emit a machine-readable JSON, and A/B compare two param
sets or two strategies.

Examples:
    python3 -m python_bt.runner --strategy happybot --to 2026.07.02 --mode bar
    python3 -m python_bt.runner --params '{"Risk_Percent":0.5}' --json out.json
    python3 -m python_bt.runner --compare --params '{}' --params '{"Risk_Percent":2.0}'
    python3 -m python_bt.runner --compare --strategy happybot --strategy happybot --to 2026.07.02

Diagnosis reuses tools/analyze_report.py's build_diagnosis / diagnosis_verdict
(imported by adding tools/ to sys.path) so the Python-side output speaks the
same language and thresholds as the MT5 report analyzer.

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

from python_bt.broker import Broker
from python_bt.engine import Engine
from python_bt.loader import iter_ticks

# Ensure the strategy package imports so strategies self-register.
import python_bt.strategy  # noqa: F401
from python_bt.strategy import get_strategy

# Default extracted CSV path (see data/extract.py / context.json).
DEFAULT_DATA = os.path.join(
    "data",
    "XAUUSD_202607011100_202609011203",
    "XAUUSD_202607011100_202609011203.csv",
)

# Bring in the MT5 report analyzer's diagnosis vocabulary/thresholds.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_TOOLS_DIR = os.path.join(_REPO_ROOT, "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

try:
    from analyze_report import build_diagnosis, diagnosis_verdict  # noqa: E402
    _HAVE_DIAGNOSIS = True
except Exception:  # pragma: no cover - defensive; tools should always import
    _HAVE_DIAGNOSIS = False


def _load_params(raw: Optional[str]) -> Dict[str, object]:
    """Parse a --params argument: inline JSON, or @file.json for a file path."""
    if not raw:
        return {}
    if raw.startswith("@"):
        with open(raw[1:], "r") as fh:
            return json.load(fh)
    return json.loads(raw)


def run_once(
    data: str,
    strategy_name: str,
    params: Dict[str, object],
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    mode: str = "bar",
    max_ticks: Optional[int] = None,
) -> Dict[str, object]:
    """Build the strategy, replay the ticks, and return the engine result dict."""
    strat_cls = get_strategy(strategy_name)
    strategy = strat_cls(params)
    engine = Engine(strategy, broker=Broker(), mode=mode, params=strategy.params)
    ticks = iter_ticks(data, date_from=date_from, date_to=date_to, max_ticks=max_ticks)
    result = engine.run(ticks)
    result["strategy"] = strategy_name
    result["diagnosis"] = _diagnose(result["metrics"])
    return result


def _diagnose(metrics: Dict[str, object]) -> Dict[str, object]:
    """Return {verdict, flags} using the shared analyzer vocabulary."""
    if not _HAVE_DIAGNOSIS:
        return {"verdict": "(diagnosis unavailable)", "flags": []}
    flags = build_diagnosis(metrics)
    return {"verdict": diagnosis_verdict(flags, metrics), "flags": flags}


# -- printing --------------------------------------------------------------

_METRIC_ORDER = [
    ("total_net_profit", "Total net profit"),
    ("gross_profit", "Gross profit"),
    ("gross_loss", "Gross loss"),
    ("profit_factor", "Profit factor"),
    ("expected_payoff", "Expected payoff"),
    ("recovery_factor", "Recovery factor"),
    ("sharpe_ratio", "Sharpe ratio"),
    ("relative_drawdown_pct", "Relative drawdown %"),
    ("maximal_drawdown_money", "Maximal drawdown money"),
    ("total_trades", "Total trades"),
    ("total_deals", "Total deals"),
    ("win_rate_pct", "Win rate %"),
]


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return "{:.4f}".format(v)
    return str(v)


def _warmup_note(metrics: Dict[str, object], meta: Dict[str, object]) -> Optional[str]:
    """Return a warm-up note when zero trades occurred AND warm-up was not reached.

    This disambiguates "the strategy is flat / not suitable" (zero trades but
    indicators warmed up and entries were possible) from "not enough data to
    warm up" (the slice ended before the HTF EMA became ready, so no entry could
    ever fire). Returns None when there is nothing to flag.
    """
    warmup = (meta or {}).get("warmup") or {}
    if not warmup:
        return None
    total_trades = (metrics or {}).get("total_trades") or 0
    if total_trades == 0 and not warmup.get("warmed_up", True):
        return warmup.get("note") or "insufficient warm-up: HTF EMA not ready"
    return None


def _print_result(result: Dict[str, object], header: Optional[str] = None) -> None:
    if header:
        print("=" * 60)
        print(header)
        print("=" * 60)
    meta = result.get("meta", {})
    print("strategy: {}  mode: {}  bars: {}  ticks: {}".format(
        result.get("strategy", "?"),
        meta.get("mode"),
        meta.get("bar_count"),
        meta.get("tick_count"),
    ))
    print("data: {} -> {}".format(meta.get("data_from"), meta.get("data_to")))
    print("-- metrics --")
    metrics = result["metrics"]
    for key, label in _METRIC_ORDER:
        print("  {:<24} {}".format(label + ":", _fmt(metrics.get(key))))
    _note = _warmup_note(metrics, meta)
    if _note:
        print("  NOTE: {}".format(_note))
    print("-- score --")
    print("  tuner SCORE: {}".format(_fmt(result.get("score"))))
    diag = result.get("diagnosis", {})
    print("-- diagnosis --")
    print("  VERDICT: {}".format(diag.get("verdict")))
    for flag in diag.get("flags", []):
        print("  [{}] {}".format(flag["level"].upper(), flag["message"]))


def _print_compare(a: Dict[str, object], b: Dict[str, object]) -> None:
    _print_result(a, header="A")
    print("")
    _print_result(b, header="B")
    print("")
    print("=" * 60)
    print("COMPARISON")
    print("=" * 60)
    sa = a.get("score")
    sb = b.get("score")
    print("  A score: {}".format(_fmt(sa)))
    print("  B score: {}".format(_fmt(sb)))
    if sa is None or sb is None:
        winner = "indeterminate"
    elif sa > sb:
        winner = "A"
    elif sb > sa:
        winner = "B"
    else:
        winner = "tie"
    print("  WINNER: {}".format(winner))


# -- CLI --------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m python_bt.runner",
        description="Backtest a strategy on the XAUUSD tick data with metrics, "
                    "tuner score and diagnosis.",
    )
    p.add_argument("--data", default=DEFAULT_DATA, help="tick CSV path")
    p.add_argument("--strategy", action="append", default=None,
                   help="strategy name (registry). Repeat for --compare A/B.")
    p.add_argument("--params", action="append", default=None,
                   help="JSON string or @file.json. Repeat for --compare A/B.")
    p.add_argument("--from", dest="date_from", default=None, help="YYYY.MM.DD")
    p.add_argument("--to", dest="date_to", default=None, help="YYYY.MM.DD")
    p.add_argument("--mode", choices=("bar", "tick"), default="bar")
    p.add_argument("--max-ticks", type=int, default=None, help="cap ticks (smoke)")
    p.add_argument("--json", dest="json_out", default=None, help="write result JSON here")
    p.add_argument("--compare", action="store_true",
                   help="A/B two --params or two --strategy sets")
    return p


def _resolve_ab(strategies: Optional[List[str]], param_strs: Optional[List[str]]):
    """Resolve the two (strategy, params) legs for --compare.

    Accepts two --strategy, or two --params, or a mix; a single value is reused
    for both legs where only the other varies.
    """
    strategies = strategies or ["happybot"]
    param_strs = param_strs or [None]

    def leg(i):
        s = strategies[i] if i < len(strategies) else strategies[-1]
        pr = param_strs[i] if i < len(param_strs) else param_strs[-1]
        return s, _load_params(pr)

    return leg(0), leg(1)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.compare:
        (sa, pa), (sb, pb) = _resolve_ab(args.strategy, args.params)
        a = run_once(args.data, sa, pa, args.date_from, args.date_to, args.mode, args.max_ticks)
        b = run_once(args.data, sb, pb, args.date_from, args.date_to, args.mode, args.max_ticks)
        _print_compare(a, b)
        if args.json_out:
            with open(args.json_out, "w") as fh:
                json.dump({"A": a, "B": b}, fh, indent=2)
            print("wrote {}".format(args.json_out))
        return 0

    strategy = (args.strategy or ["happybot"])[0]
    params = _load_params((args.params or [None])[0])
    result = run_once(args.data, strategy, params, args.date_from, args.date_to,
                      args.mode, args.max_ticks)
    _print_result(result)
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(result, fh, indent=2)
        print("wrote {}".format(args.json_out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
