"""Research loop harness for the XAUUSD backtester.

This is the crux of the in-sandbox research loop: run a batch of candidate
strategy/param configs on a shared data slice, RANK them by the tuner score
(automation/tuner/scoring.py, which enforces the hard 15% relative-drawdown
ceiling), print a leaderboard with the analyzer diagnosis verdict per config,
and persist all results to a small JSON file the agent can read back.

The loop the agent runs:

    1. DEVELOP  - edit a --configs JSON (list of {strategy, params, label}) or
                  add a new Strategy subclass under python_bt/strategy/ and
                  register it with @register.
    2. MEASURE  - run this harness on a data slice; each config is replayed via
                  python_bt.runner.run_once (the SAME engine wiring the runner
                  CLI uses, so results are directly comparable).
    3. RANK     - configs are sorted by score() descending. Because scoring.py
                  banishes any over-ceiling config below every compliant one, a
                  config that breaks the 15% relative-DD ceiling always sinks to
                  the bottom of the leaderboard.
    4. ITERATE  - read the persisted results JSON, form a new hypothesis, edit
                  the configs (or add a strategy), and re-run. Tight loop, no
                  MT5 round-trip needed for the SEARCH phase.

IMPORTANT: this is a FAST SEARCH rig. MT5 remains the SOURCE OF TRUTH. Any
config that looks good here must be validated on a real MT5 run of the same
period before it is trusted. See python_bt/README.md for the parity caveats.

Examples:
    python3 -m python_bt.research --baseline --to 2026.07.02 --mode bar
    python3 -m python_bt.research --configs @candidates.json --top 5
    python3 -m python_bt.research --configs @candidates.json --max-ticks 200000

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from typing import Dict, List, Optional

# Ensure strategies self-register.
import python_bt.strategy  # noqa: F401
from python_bt.runner import DEFAULT_DATA, run_once, _warmup_note
from python_bt.strategy import get_strategy
from python_bt.strategy.gagan import GaganStrategy


# Where results JSON are written. A dedicated subdir under reports/ that does
# NOT match the gitignored `reports/*.summary.json` pattern (that rule only
# ignores files directly under reports/, and these are named *.results.json).
# Results are tiny (a few KB) so committing them is harmless; the subdir keeps
# them out of the way. Stated in python_bt/README.md.
DEFAULT_RESULTS_DIR = os.path.join("reports", "pybt")


def _load_configs(raw: Optional[str]) -> List[Dict[str, object]]:
    """Parse a --configs argument: inline JSON or @file.json.

    Returns a list of {strategy, params, label} dicts. Each entry may omit
    fields: strategy defaults to 'gagan', params to {}, label is synthesized.
    """
    if not raw:
        return []
    if raw.startswith("@"):
        with open(raw[1:], "r") as fh:
            data = json.load(fh)
    else:
        data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("--configs must be a JSON list of {strategy, params, label}")
    return [_normalize_config(i, entry) for i, entry in enumerate(data)]


def _normalize_config(index: int, entry: Dict[str, object]) -> Dict[str, object]:
    """Fill defaults and validate one config entry."""
    if not isinstance(entry, dict):
        raise ValueError("config entry #{} must be an object".format(index))
    strategy = entry.get("strategy", "gagan")
    params = entry.get("params", {}) or {}
    if not isinstance(params, dict):
        raise ValueError("config entry #{} 'params' must be an object".format(index))
    label = entry.get("label") or "{}#{}".format(strategy, index)
    return {"strategy": str(strategy), "params": dict(params), "label": str(label)}


def _default_configs() -> List[Dict[str, object]]:
    """A tiny built-in candidate set used when no --configs is supplied.

    Kept intentionally small and centred on the GaganStrategy defaults with a
    couple of single-knob variations so a bare `python3 -m python_bt.research`
    run produces a meaningful multi-row leaderboard out of the box.
    """
    return [
        {"strategy": "gagan", "params": {}, "label": "gagan-default"},
        {"strategy": "gagan", "params": {"Risk_Percent": 0.5}, "label": "gagan-risk0.5"},
        {"strategy": "gagan", "params": {"Risk_Percent": 2.0}, "label": "gagan-risk2.0"},
    ]


def _baseline_config() -> Dict[str, object]:
    """The GaganStrategy defaults, always available as a comparison anchor."""
    return {"strategy": GaganStrategy.NAME, "params": {}, "label": "baseline-gagan-default"}


def run_research(
    configs: List[Dict[str, object]],
    data: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    mode: str = "bar",
    max_ticks: Optional[int] = None,
) -> List[Dict[str, object]]:
    """Run each config via run_once and return results RANKED by score desc.

    Each returned row is {label, strategy, params, metrics, score, meta,
    diagnosis}. Ranking is a stable sort by score descending, so over-ceiling
    configs (pushed below the tier separator by scoring.py) land last.
    """
    rows = []  # type: List[Dict[str, object]]
    for cfg in configs:
        result = run_once(
            data, cfg["strategy"], cfg["params"],
            date_from=date_from, date_to=date_to, mode=mode, max_ticks=max_ticks,
        )
        rows.append({
            "label": cfg["label"],
            "strategy": cfg["strategy"],
            "params": cfg["params"],
            "metrics": result["metrics"],
            "score": result["score"],
            "meta": result["meta"],
            "diagnosis": result["diagnosis"],
        })
    return rank_results(rows)


def rank_results(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """Return rows sorted by score descending (None scores sort last)."""
    def _key(row):
        s = row.get("score")
        # None -> treat as -inf so unscored/errored configs sink to the bottom.
        return s if isinstance(s, (int, float)) else float("-inf")

    return sorted(rows, key=_key, reverse=True)


# -- printing ---------------------------------------------------------------

def _fmt(v, spec="{:.2f}") -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return spec.format(v)
    return str(v)


def _print_leaderboard(rows: List[Dict[str, object]], top: Optional[int] = None) -> None:
    shown = rows if not top else rows[:top]
    print("=" * 100)
    print("LEADERBOARD (ranked by tuner score desc; over-15%-DD configs sink to the bottom)")
    print("=" * 100)
    header = "{:>2}  {:<26} {:>12} {:>8} {:>7} {:>7} {:>16}  {}".format(
        "#", "label", "net_profit", "relDD%", "PF", "trades", "score", "verdict",
    )
    print(header)
    print("-" * 100)
    notes = []  # (rank, label, note) to print under the table
    for i, row in enumerate(shown, start=1):
        m = row.get("metrics", {}) or {}
        diag = row.get("diagnosis", {}) or {}
        note = _warmup_note(m, row.get("meta", {}) or {})
        verdict = diag.get("verdict", "?")
        if note:
            # Flag under-warmed-up rows inline so a zero-trade row is not
            # misread as a losing/flat strategy.
            verdict = "insufficient warm-up"
            notes.append((i, str(row.get("label")), note))
        print("{:>2}  {:<26} {:>12} {:>8} {:>7} {:>7} {:>16}  {}".format(
            i,
            str(row.get("label"))[:26],
            _fmt(m.get("total_net_profit")),
            _fmt(m.get("relative_drawdown_pct")),
            _fmt(m.get("profit_factor")),
            _fmt(m.get("total_trades"), "{}"),
            _fmt(row.get("score"), "{:.4f}"),
            verdict,
        ))
    if top and len(rows) > top:
        print("... ({} more not shown; --top {})".format(len(rows) - top, top))
    print("-" * 100)
    for rank, label, note in notes:
        print("  [#{} {}] {}".format(rank, label[:26], note))
    if notes:
        print("-" * 100)


def _write_results(
    rows: List[Dict[str, object]],
    results_dir: str,
    meta: Dict[str, object],
) -> str:
    """Persist the full ranked results to a timestamped JSON file; return path."""
    os.makedirs(results_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(results_dir, "{}.results.json".format(ts))
    payload = {
        "generated_at": ts,
        "run": meta,
        "leaderboard": rows,
    }
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    return path


# -- CLI --------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m python_bt.research",
        description="Run a batch of strategy/param configs on a data slice, rank "
                    "them by the tuner score, print a leaderboard, and persist "
                    "results JSON for the agent to read back and iterate.",
    )
    p.add_argument("--data", default=DEFAULT_DATA, help="tick CSV path")
    p.add_argument("--configs", default=None,
                   help="inline JSON or @file.json: list of {strategy, params, label}")
    p.add_argument("--baseline", action="store_true",
                   help="always include GaganStrategy defaults as a comparison anchor")
    p.add_argument("--from", dest="date_from", default=None, help="YYYY.MM.DD")
    p.add_argument("--to", dest="date_to", default=None, help="YYYY.MM.DD")
    p.add_argument("--mode", choices=("bar", "tick"), default="bar")
    p.add_argument("--max-ticks", type=int, default=None, help="cap ticks (smoke)")
    p.add_argument("--top", type=int, default=None, help="show only the best N rows")
    p.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR,
                   help="directory for the results JSON (default: reports/pybt)")
    p.add_argument("--no-write", action="store_true",
                   help="do not persist a results JSON (print only)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    configs = _load_configs(args.configs)
    if not configs:
        configs = _default_configs()
    if args.baseline:
        # Prepend the baseline anchor unless an identically-labelled entry exists.
        labels = {c["label"] for c in configs}
        base = _baseline_config()
        if base["label"] not in labels:
            configs = [base] + configs

    rows = run_research(
        configs, args.data,
        date_from=args.date_from, date_to=args.date_to,
        mode=args.mode, max_ticks=args.max_ticks,
    )

    _print_leaderboard(rows, top=args.top)

    run_meta = {
        "data": args.data,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "mode": args.mode,
        "max_ticks": args.max_ticks,
        "config_count": len(configs),
    }

    if not args.no_write:
        path = _write_results(rows, args.results_dir, run_meta)
        print("wrote results: {}".format(path))
        print("NOTE: fast-search only. Validate any winner on a real MT5 run "
              "(MT5 is the source of truth).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
