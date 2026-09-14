"""Tunable parameter space for HappyBot.mq5 and validity/ordering repair.

Each entry maps an EXACT HappyBot.mq5 input name to its bounds, step, and numeric
type. The `validate` function takes any proposed vector and returns a VALID one:
clamped to bounds, snapped to step, ordering-repaired (T1 < T2 < T3 <= StopLoss),
with int params kept int and double params kept float. This guarantees the tuner
NEVER writes an invalid EA.

On gold, *_Pips inputs are POINTS. Bounds/steps are grounded in the v2.11
defaults.
"""

# Parameter type tags.
INT = "int"
DOUBLE = "double"


class Param(object):
    """One tunable parameter: name, bounds, step, and numeric type."""

    def __init__(self, name, minimum, maximum, step, ptype, default):
        self.name = name
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.ptype = ptype
        self.default = default


# The tunable space. Order is stable and used for deterministic iteration.
# v2.11 defaults referenced in each `default`.
PARAM_LIST = [
    Param("Risk_Percent", 0.25, 2.0, 0.25, DOUBLE, 1.0),
    Param("Min_EMA_Distance", 100, 1200, 50, INT, 400),
    Param("Min_Trade_Distance", 100, 1500, 50, INT, 500),
    Param("StopLoss_Pips", 400, 3000, 50, INT, 1000),
    Param("T1_Pips", 100, 2000, 50, INT, 500),
    Param("T2_Pips", 200, 2500, 50, INT, 1000),
    Param("T3_Pips", 300, 3000, 50, INT, 1800),
    Param("T1_ClosePercent", 10.0, 90.0, 1.0, DOUBLE, 33.0),
    Param("T2_ClosePercent", 10.0, 90.0, 1.0, DOUBLE, 50.0),
    Param("Entry_Cooldown_Bars", 0, 20, 1, INT, 3),
    Param("Max_Concurrent_Positions", 1, 5, 1, INT, 2),
]

PARAMS = dict((p.name, p) for p in PARAM_LIST)
PARAM_NAMES = [p.name for p in PARAM_LIST]

# Ordering chain that must hold: T1 < T2 < T3 <= StopLoss.
_ORDER_CHAIN = ["T1_Pips", "T2_Pips", "T3_Pips"]
_ORDER_CAP = "StopLoss_Pips"


def defaults():
    """Return a fresh dict of the v2.11 default vector, correctly typed."""
    out = {}
    for p in PARAM_LIST:
        out[p.name] = int(p.default) if p.ptype == INT else float(p.default)
    return out


def _coerce_type(param, value):
    """Coerce value to the parameter's numeric type."""
    if param.ptype == INT:
        return int(round(float(value)))
    return float(value)


def _clamp(param, value):
    """Clamp value to [minimum, maximum]."""
    if value < param.minimum:
        return param.minimum
    if value > param.maximum:
        return param.maximum
    return value


def _snap(param, value):
    """Snap value to the nearest multiple of step, anchored at minimum."""
    if not param.step:
        return value
    n = round((float(value) - param.minimum) / float(param.step))
    snapped = param.minimum + n * param.step
    return snapped


def _sanitize_one(param, value):
    """Clamp, snap, re-clamp, and type-coerce a single param value."""
    if value is None:
        value = param.default
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = float(param.default)
    value = _clamp(param, value)
    value = _snap(param, value)
    value = _clamp(param, value)
    return _coerce_type(param, value)


def _repair_ordering(vector):
    """Enforce T1 < T2 < T3 <= StopLoss using integer step gaps.

    Walk the chain upward forcing strict increase by at least one step, then
    cap the whole chain at StopLoss (pulling StopLoss up if needed within its
    bounds, else pulling the chain down)."""
    # Ensure strictly increasing T1 < T2 < T3 by nudging up.
    for i in range(1, len(_ORDER_CHAIN)):
        lower = vector[_ORDER_CHAIN[i - 1]]
        cur = vector[_ORDER_CHAIN[i]]
        p = PARAMS[_ORDER_CHAIN[i]]
        if cur <= lower:
            candidate = lower + max(p.step, 1)
            candidate = _sanitize_one(p, candidate)
            if candidate <= lower:
                candidate = lower + max(int(p.step), 1)
            vector[_ORDER_CHAIN[i]] = candidate

    # Cap T3 <= StopLoss. Prefer raising StopLoss to fit; otherwise lower the
    # chain from the top down so ordering is preserved.
    sl_p = PARAMS[_ORDER_CAP]
    t3 = vector["T3_Pips"]
    sl = vector[_ORDER_CAP]
    if t3 > sl:
        raised = _sanitize_one(sl_p, t3)
        if raised >= t3:
            vector[_ORDER_CAP] = raised
        else:
            # Cannot raise StopLoss enough; pull the chain down under SL.
            vector[_ORDER_CAP] = sl_p.maximum
            cap = vector[_ORDER_CAP]
            for name in reversed(_ORDER_CHAIN):
                p = PARAMS[name]
                if vector[name] > cap:
                    vector[name] = _sanitize_one(p, cap)
                cap = vector[name] - max(int(p.step), 1)
            # Re-assert strict increase after the downward pass.
            for i in range(1, len(_ORDER_CHAIN)):
                lower = vector[_ORDER_CHAIN[i - 1]]
                if vector[_ORDER_CHAIN[i]] <= lower:
                    p = PARAMS[_ORDER_CHAIN[i]]
                    vector[_ORDER_CHAIN[i]] = lower + max(int(p.step), 1)
    return vector


def validate(proposed):
    """Return a VALID param vector from any proposed dict.

    - Ignores unknown keys; fills missing keys with defaults.
    - Clamps to bounds, snaps to step, preserves int/double types.
    - Repairs ordering: T1_Pips < T2_Pips < T3_Pips <= StopLoss_Pips.

    The returned dict always contains exactly the tunable param names.
    """
    if not isinstance(proposed, dict):
        proposed = {}
    vector = {}
    for p in PARAM_LIST:
        vector[p.name] = _sanitize_one(p, proposed.get(p.name, p.default))
    vector = _repair_ordering(vector)
    return vector


def is_valid(vector):
    """True if vector respects bounds and the ordering chain."""
    for p in PARAM_LIST:
        if p.name not in vector:
            return False
        v = vector[p.name]
        if v < p.minimum or v > p.maximum:
            return False
    if not (vector["T1_Pips"] < vector["T2_Pips"] < vector["T3_Pips"]):
        return False
    if vector["T3_Pips"] > vector["StopLoss_Pips"]:
        return False
    return True
