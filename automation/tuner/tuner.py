"""Auto-tuner CLI: one idempotent invocation.

Flow per invocation:
  1. Ingest the latest backtest result (a --summary-json, a raw --report .html
     parsed via tools/analyze_report.py, or the newest reports/tuner/*.summary.json).
  2. Score the CURRENT param set's metrics; update state (record new best if
     improved) and append a history record with the accept/reject decision.
  3. Propose the NEXT param vector via coordinate-descent local search plus a
     rule-based nudge layer keyed off the diagnosis (high DD, overtrading, PF<1).
  4. Validate the proposal through params.py.
  5. Write it into HappyBot.mq5 (unless --dry-run), write a human-readable log
     line, and update automation/tuner/current_params.json.

Exit code is non-zero only on real errors. A 'nothing changed' proposal logs
and exits 0.

Runnable as:  python3 automation/tuner/tuner.py [flags]
or:           python3 -m automation.tuner.tuner [flags]

Stdlib only. analyze_report.py (in tools/) is imported lazily and its absence
is tolerated: raw .html ingestion is then unavailable but .summary.json still
works.
"""

import argparse
import datetime
import glob
import json
import os
import sys

# Support both `python3 automation/tuner/tuner.py` (no package context) and
# `python3 -m automation.tuner.tuner` (package context).
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import params as params_mod
    import scoring as scoring_mod
    import state as state_mod
    import mq5_rewriter
else:
    from . import params as params_mod
    from . import scoring as scoring_mod
    from . import state as state_mod
    from . import mq5_rewriter


# Path helpers -------------------------------------------------------------

def _repo_root():
    # automation/tuner/tuner.py -> repo root is two levels up.
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _default_state_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "tuner_state.json")


def _default_current_params_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "current_params.json")


def _default_mq5_path():
    return os.path.join(_repo_root(), "HappyBot.mq5")


def _default_log_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def _reports_tuner_glob():
    return os.path.join(_repo_root(), "reports", "tuner", "*.summary.json")


# Report ingestion ---------------------------------------------------------

def _import_analyze_report():
    """Return the analyze_report module, or None if not importable."""
    tools_dir = os.path.join(_repo_root(), "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import analyze_report  # noqa: E402
        return analyze_report
    except Exception:
        return None


def load_metrics(summary_json=None, report=None):
    """Load a summary dict from a .summary.json, a raw .html, or the newest
    reports/tuner/*.summary.json. Returns (summary_dict, source_path) or
    (None, None) if nothing is available."""
    if summary_json:
        with open(summary_json, "r") as fh:
            return json.load(fh), summary_json

    if report:
        analyze_report = _import_analyze_report()
        if analyze_report is None:
            raise RuntimeError(
                "cannot parse raw report: tools/analyze_report.py not importable"
            )
        summary = analyze_report.analyze_file(report, write_json=False)
        return summary, report

    candidates = sorted(
        glob.glob(_reports_tuner_glob()), key=os.path.getmtime, reverse=True
    )
    if candidates:
        newest = candidates[0]
        with open(newest, "r") as fh:
            return json.load(fh), newest
    return None, None


# Proposal engine ----------------------------------------------------------

def _diagnosis_flags(summary):
    """Return the set of diagnosis flag codes present in the summary."""
    codes = set()
    if isinstance(summary, dict):
        diag = summary.get("diagnosis") or {}
        for flag in diag.get("flags", []) or []:
            code = flag.get("code")
            if code:
                codes.add(code)
    return codes


def _step_up(vector, name, steps=1):
    p = params_mod.PARAMS[name]
    vector[name] = vector[name] + p.step * steps


def _step_down(vector, name, steps=1):
    p = params_mod.PARAMS[name]
    vector[name] = vector[name] - p.step * steps


def rule_based_nudges(vector, metrics):
    """Apply explainable rule-based nudges. Returns (new_vector, notes list).

    Rules:
      * DD > ceiling -> cut Risk_Percent, widen Min_EMA_Distance/Min_Trade_Distance.
      * Overtrading (very high trade count) -> widen Min_* distances, raise cooldown.
      * PF < 1 -> shift target/SL ratio (pull StopLoss in toward T3, nudge T1 down).
    """
    v = dict(vector)
    notes = []
    if not isinstance(metrics, dict):
        metrics = {}

    dd = metrics.get("relative_drawdown_pct")
    pf = metrics.get("profit_factor")
    trades = metrics.get("total_trades")

    try:
        dd = float(dd) if dd is not None else None
    except (TypeError, ValueError):
        dd = None
    try:
        pf = float(pf) if pf is not None else None
    except (TypeError, ValueError):
        pf = None
    try:
        trades = float(trades) if trades is not None else None
    except (TypeError, ValueError):
        trades = None

    if dd is not None and dd > scoring_mod.MAX_RELATIVE_DD_PCT:
        _step_down(v, "Risk_Percent", 1)
        _step_up(v, "Min_EMA_Distance", 1)
        _step_up(v, "Min_Trade_Distance", 1)
        notes.append("dd>%.1f%%: cut risk, widen distances" % scoring_mod.MAX_RELATIVE_DD_PCT)

    if trades is not None and trades > 400:
        _step_up(v, "Min_EMA_Distance", 1)
        _step_up(v, "Min_Trade_Distance", 1)
        _step_up(v, "Entry_Cooldown_Bars", 1)
        notes.append("overtrading(%d): widen distances, raise cooldown" % int(trades))

    if pf is not None and pf < 1.0:
        # Pull StopLoss toward T3 (tighten) and nudge T1 down so reward:risk shifts.
        _step_down(v, "StopLoss_Pips", 2)
        _step_down(v, "T1_Pips", 1)
        notes.append("pf<1: tighten StopLoss, lower T1")

    return v, notes


def _coordinate_descent_step(vector, state):
    """Deterministic 1-param perturbation. Cycles through the tunable params by
    iteration count and steps the selected param up one step. Kept simple and
    explainable; the accept-if-better keep-best logic lives in the best tracking.
    """
    v = dict(vector)
    idx = int(state.get("iteration", 0)) % len(params_mod.PARAM_NAMES)
    name = params_mod.PARAM_NAMES[idx]
    _step_up(v, name, 1)
    return v, "coordinate-descent: step %s up" % name


def _classify_changes(base, stepped, valid):
    """Classify every param that validate touched into two groups by ORIGIN.

    Given three snapshots of a proposal:
      * base     - the pre-nudge starting vector (best-or-current),
      * stepped  - after rule-based nudges + the coordinate-descent step,
      * valid    - after params.validate (clamp / snap / ordering-repair),

    a param is examined only if validate actually changed it
    (valid != stepped). For each such param:
      * NUDGED?  stepped != base  -> a nudge or the coordinate step moved it.
      * REPAIRED? valid  != stepped (always true here by construction).

    Two ORIGIN buckets result:
      * repair_only - validate moved it AND no nudge/step touched it
                      (stepped == base). This is a pure legality repair.
      * collision   - a nudge/step moved it AND validate then OVERRODE that
                      move (stepped != base and valid != stepped). Here a
                      diagnosis rule DID target the param; the repair won, but
                      it is NOT accurate to call it "not a nudge".

    Returns (repair_only, collision), each a sorted list of param names. Their
    union is exactly the set of params validate changed (the old repair_names).
    """
    repair_only = []
    collision = []
    keys = set(base.keys()) | set(stepped.keys()) | set(valid.keys())
    for name in keys:
        if valid.get(name) == stepped.get(name):
            continue  # validate did not change this param
        if stepped.get(name) != base.get(name):
            collision.append(name)  # nudge/step moved it, repair overrode it
        else:
            repair_only.append(name)  # only validate moved it
    return sorted(repair_only), sorted(collision)


def propose_next(state, metrics, summary):
    """Propose the next VALID param vector plus notes and repair classification.

    Starts from the best-known vector if available (keep-best), else current.
    Applies rule-based nudges first, then a coordinate-descent perturbation,
    then validates (clamp/snap/ordering-repair).

    Returns (valid_vector, notes, repair_names, repair_only, collision) where:
      * repair_names is the full set of params validate changed (repair_only +
        collision), used to route the logged delta into repair_delta,
      * repair_only lists params changed ONLY by validate (pure legality
        repair, no nudge touched them),
      * collision lists params a nudge/step moved AND validate then overrode
        (a diagnosis rule DID target them, so they must not be called "not a
        nudge").
    """
    if state.get("best") and isinstance(state["best"].get("params"), dict):
        base = dict(state["best"]["params"])
    else:
        base = dict(state["current"])

    nudged, notes = rule_based_nudges(base, metrics)
    stepped, cd_note = _coordinate_descent_step(nudged, state)
    notes.append(cd_note)
    valid = params_mod.validate(stepped)

    repair_only, collision = _classify_changes(base, stepped, valid)
    repair_names = sorted(set(repair_only) | set(collision))

    if repair_only:
        notes.append(
            "ordering/bounds repair (not a nudge): " + ", ".join(repair_only)
        )
    if collision:
        notes.append(
            "repair overrode nudge: " + ", ".join(collision)
        )
    return valid, notes, repair_names, repair_only, collision


# Logging ------------------------------------------------------------------

def _timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_log_line(log_dir, line, dry_run=False):
    """Append a log line to logs/tuner.log and echo to stdout."""
    sys.stdout.write(line + "\n")
    if dry_run:
        return
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    with open(os.path.join(log_dir, "tuner.log"), "a") as fh:
        fh.write(line + "\n")


def write_current_params(path, vector, dry_run=False):
    """Write the identifiable current param set to a tracked JSON marker."""
    if dry_run:
        return
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as fh:
        json.dump({"params": vector, "updated": _timestamp()}, fh, indent=2, sort_keys=True)
        fh.write("\n")


# Main ---------------------------------------------------------------------

def build_arg_parser():
    p = argparse.ArgumentParser(description="HappyBot auto-tuner (one iteration).")
    p.add_argument("--summary-json", default=None, help="Path to a .summary.json to ingest.")
    p.add_argument("--report", default=None, help="Path to a raw report .html to parse.")
    p.add_argument("--state", default=None, help="Path to tuner_state.json.")
    p.add_argument("--mq5", default=None, help="Path to HappyBot.mq5.")
    p.add_argument("--dry-run", action="store_true", help="Compute and log but do not write mq5/state.")
    p.add_argument("--reset", action="store_true", help="Reinitialize state from current mq5 and exit.")
    return p


def run(argv=None):
    args = build_arg_parser().parse_args(argv)

    state_path = args.state or _default_state_path()
    mq5_path = args.mq5 or _default_mq5_path()
    log_dir = _default_log_dir()
    current_params_path = _default_current_params_path()

    if not os.path.exists(mq5_path):
        sys.stderr.write("error: mq5 file not found: %s\n" % mq5_path)
        return 2

    if args.reset:
        state = state_mod.init_from_mq5(mq5_path)
        if not args.dry_run:
            state_mod.save(state_path, state)
        write_log_line(
            log_dir,
            "[%s] RESET state from %s: current=%s"
            % (_timestamp(), os.path.basename(mq5_path), json.dumps(state["current"], sort_keys=True)),
            dry_run=args.dry_run,
        )
        return 0

    state = state_mod.load_or_init(state_path, mq5_path)

    # Ingest latest result (optional; may be absent on first run).
    try:
        summary, source = load_metrics(args.summary_json, args.report)
    except (OSError, ValueError, RuntimeError) as exc:
        sys.stderr.write("error: failed to load report: %s\n" % exc)
        return 3

    metrics = summary.get("metrics", {}) if isinstance(summary, dict) else {}
    if summary is None:
        # No result yet: nothing to score. Log and exit 0 (idempotent no-op).
        write_log_line(
            log_dir,
            "[%s] no report found to ingest; state unchanged (iteration=%d)"
            % (_timestamp(), int(state.get("iteration", 0))),
            dry_run=args.dry_run,
        )
        return 0

    # Score CURRENT params against the ingested result and update best/history.
    current_score = scoring_mod.score(metrics)
    prev_best = state["best"]["score"] if state.get("best") else None
    accepted = prev_best is None or current_score > prev_best
    state_mod.record_iteration(state, metrics, current_score, accepted)

    # Propose next vector.
    proposed, notes, repair_names, repair_only, collision = propose_next(
        state, metrics, summary
    )
    old_vector = dict(state["current"])
    delta = state_mod.compute_delta(old_vector, proposed)

    # Split the delta into repair-origin entries (validate changed them to
    # satisfy bounds/step/ordering, e.g. the seeded-invalid v2.11 T3>StopLoss
    # case that raises StopLoss_Pips on the first write) versus nudge/step
    # entries, so an operator eyeballing the log can tell an intentional move
    # from a legality repair. repair_names is repair_only + collision.
    #
    # A COLLISION param (a nudge moved it AND validate then overrode that move)
    # keeps its full old->final move in repair_delta because the final written
    # value is what matters, but the notes above call it out as "repair overrode
    # nudge" rather than "not a nudge", so the log never claims the nudge layer
    # left a collision param alone.
    repair_delta = dict((k, v) for k, v in delta.items() if k in repair_names)
    nudge_delta = dict((k, v) for k, v in delta.items() if k not in repair_names)

    best_score = state["best"]["score"] if state.get("best") else None
    log_line = (
        "[%s] iter=%d src=%s score=%.4f accepted=%s best=%s delta=%s repair_delta=%s notes=%s"
        % (
            _timestamp(),
            int(state.get("iteration", 0)),
            os.path.basename(source) if source else "-",
            current_score,
            accepted,
            ("%.4f" % best_score) if best_score is not None else "none",
            json.dumps(nudge_delta, sort_keys=True),
            json.dumps(repair_delta, sort_keys=True),
            "; ".join(notes),
        )
    )

    if not delta:
        # Nothing changed: log and exit 0.
        state["current"] = proposed
        if not args.dry_run:
            state_mod.save(state_path, state)
            write_current_params(current_params_path, proposed)
        write_log_line(log_dir, log_line + " (no param change)", dry_run=args.dry_run)
        return 0

    # Write proposal into HappyBot.mq5 and persist state.
    if not args.dry_run:
        try:
            mq5_rewriter.rewrite_file(mq5_path, proposed)
        except mq5_rewriter.MissingInputError as exc:
            sys.stderr.write("error: rewrite failed: %s\n" % exc)
            return 4
        state["current"] = proposed
        state_mod.save(state_path, state)
        write_current_params(current_params_path, proposed)

    write_log_line(log_dir, log_line, dry_run=args.dry_run)
    return 0


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
