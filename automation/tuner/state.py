"""Restart-safe JSON state for the auto-tuner.

State file (tracked): automation/tuner/tuner_state.json

Schema:
  {
    "version": 1,
    "iteration": <int>,                 # number of ingested iterations
    "current": {param: value, ...},     # the param vector currently in the EA
    "best": {                           # best-scoring so far, or null
      "params": {...},
      "metrics": {...},
      "score": <float>
    } | null,
    "history": [
      {
        "iteration": <int>,
        "params": {...},
        "delta": {param: [old, new], ...},
        "metrics_summary": {...},
        "score": <float>,
        "accepted": <bool>,             # improved best?
        "best_score": <float|null>      # best-so-far score after this record
      }, ...
    ]
  }

Writes are atomic: a temp file is written then os.replace'd into place, so a
killed process cannot leave a half-written (corrupt) state file.
"""

import json
import os
import tempfile

try:
    from . import mq5_rewriter
except ImportError:  # flat import (tools/-style: package dir on sys.path)
    import mq5_rewriter

STATE_VERSION = 1


def _empty_state(current_vector):
    return {
        "version": STATE_VERSION,
        "iteration": 0,
        "current": dict(current_vector),
        "best": None,
        "history": [],
    }


def init_from_mq5(mq5_path):
    """Build a fresh state seeded from the current HappyBot.mq5 input values.

    The seed reflects the LIVE file values as-is (no ordering repair) so state
    faithfully records what is currently compiled in. Ordering/bounds repair is
    applied later when a NEXT vector is proposed and written (see params.validate
    in the tuner), so the EA is only ever written a valid vector.
    """
    vector = mq5_rewriter.read_file_vector(mq5_path)
    return _empty_state(vector)


def load_or_init(state_path, mq5_path):
    """Load the state file, or initialize from mq5 if missing/empty/corrupt."""
    if not os.path.exists(state_path):
        return init_from_mq5(mq5_path)
    try:
        with open(state_path, "r") as fh:
            raw = fh.read()
        if not raw.strip():
            return init_from_mq5(mq5_path)
        data = json.loads(raw)
    except (ValueError, OSError):
        return init_from_mq5(mq5_path)
    if not isinstance(data, dict) or "current" not in data:
        return init_from_mq5(mq5_path)
    # Backfill any missing schema keys defensively.
    data.setdefault("version", STATE_VERSION)
    data.setdefault("iteration", 0)
    data.setdefault("best", None)
    data.setdefault("history", [])
    if not isinstance(data.get("current"), dict):
        data["current"] = init_from_mq5(mq5_path)["current"]
    return data


def save(state_path, state):
    """Atomically write state as pretty JSON to state_path."""
    directory = os.path.dirname(os.path.abspath(state_path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".tuner_state.", suffix=".tmp", dir=directory or None
    )
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, state_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def compute_delta(old_vector, new_vector):
    """Return {name: [old, new]} for params whose value changed."""
    delta = {}
    keys = set(old_vector.keys()) | set(new_vector.keys())
    for name in keys:
        old_v = old_vector.get(name)
        new_v = new_vector.get(name)
        if old_v != new_v:
            delta[name] = [old_v, new_v]
    return delta


def metrics_summary(metrics):
    """Return a compact subset of metrics for the history log."""
    if not isinstance(metrics, dict):
        return {}
    keys = [
        "total_net_profit",
        "profit_factor",
        "relative_drawdown_pct",
        "maximal_drawdown_pct",
        "total_trades",
        "win_rate_pct",
        "recovery_factor",
    ]
    out = {}
    for k in keys:
        if k in metrics:
            out[k] = metrics[k]
    return out


def record_iteration(state, metrics, score_value, accepted, best_params=None):
    """Append a history record and bump the iteration count.

    If accepted is True, update state['best'] with the given params/metrics/score
    (best_params defaults to state['current']).
    """
    state["iteration"] = int(state.get("iteration", 0)) + 1
    if accepted:
        params_for_best = best_params if best_params is not None else state["current"]
        state["best"] = {
            "params": dict(params_for_best),
            "metrics": dict(metrics) if isinstance(metrics, dict) else {},
            "score": score_value,
        }
    best_score = state["best"]["score"] if state.get("best") else None
    record = {
        "iteration": state["iteration"],
        "params": dict(state["current"]),
        "metrics_summary": metrics_summary(metrics),
        "score": score_value,
        "accepted": bool(accepted),
        "best_score": best_score,
    }
    state.setdefault("history", []).append(record)
    return record
