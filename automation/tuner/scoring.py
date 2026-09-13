"""Scoring for auto-tuner candidates.

Objective (authoritative):
  Maximize NET PROFIT subject to a HARD relative-drawdown ceiling.
  Any candidate whose relative drawdown exceeds the ceiling MUST score
  strictly worse than ANY candidate that respects the ceiling.

Implementation is a two-tier score built on a large fixed offset:
  - Tier A (DD <= ceiling): score = TIER_A_OFFSET + net_profit (+ tiny PF
    tiebreaker, minus a low-trade penalty). Because net profit and the penalty
    are bounded well within the offset, every compliant score stays above
    TIER_SEPARATOR.
  - Tier B (DD > ceiling): score = TIER_SEPARATOR - overage. Always at or below
    TIER_SEPARATOR, so it is ALWAYS below any Tier A score, and within the tier
    it is ordered by how far over the ceiling it is (bigger overage = worse).

TIER_A_OFFSET is chosen far larger than any realistic net profit or penalty so
the tiers never overlap even for a deeply losing but compliant candidate.

The 15% ceiling and other knobs are named, editable module constants below.
"""

# Editable knobs -----------------------------------------------------------

# Hard relative-drawdown ceiling, in percent. Candidates above this are
# banished to the lower scoring tier.
MAX_RELATIVE_DD_PCT = 15.0

# Hard separator between the two tiers. Every compliant (Tier A) score is
# strictly above this value; every over-ceiling (Tier B) score is at or below it.
TIER_SEPARATOR = 0.0

# Large fixed offset added to compliant candidates so that even a deeply losing
# but compliant candidate stays above the separator (and thus above any
# over-ceiling candidate). Must exceed any realistic |net profit| + penalty, yet
# stay small enough that the tiny PF tiebreaker is not lost to float precision.
TIER_A_OFFSET = 1.0e9

# Minimum trade count for a sample to be considered statistically meaningful.
MIN_MEANINGFUL_TRADES = 30

# Penalty (score points) applied per missing trade below MIN_MEANINGFUL_TRADES.
LOW_TRADE_PENALTY_PER_TRADE = 50.0

# Weight of the profit-factor tiebreaker within Tier A. Kept tiny so it only
# breaks ties between near-equal net-profit candidates and never overrides a
# real net-profit difference.
#
# FLOAT-HEADROOM CONSTRAINT: the tiebreaker is added on top of TIER_A_OFFSET, so
# it must stay resolvable at that magnitude. At an offset of ~1e9 the float64
# resolution near a score is ~1.2e-7; a PF gap of 0.001 (the smallest meaningful
# delta) contributes PF_TIEBREAK_WEIGHT * 0.001 = 1e-6, which is ~10x above that
# resolution and so still distinguishable. If you RAISE TIER_A_OFFSET or LOWER
# PF_TIEBREAK_WEIGHT, keep that product comfortably above the resolution at the
# offset (roughly offset * 2**-52), or the tiebreaker silently collapses to
# noise. tests/test_scoring.py::test_pf_tiebreaker_smallest_delta_headroom pins
# this so the interaction cannot regress unnoticed.
PF_TIEBREAK_WEIGHT = 1e-3

# Worst-case fallbacks for missing/None metrics (treated pessimistically). The
# worst net profit is kept well within TIER_A_OFFSET so tier separation holds.
_WORST_NET_PROFIT = -1.0e6
_WORST_DD_PCT = 1.0e6
_WORST_PF = 0.0
_WORST_TRADES = 0


def _num(value, fallback):
    """Coerce value to float, using fallback for None/missing/non-numeric."""
    if value is None:
        return float(fallback)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def score(metrics):
    """Return a single float score for a candidate's result metrics.

    Higher is better. Guarantees:
      * A candidate with relative_drawdown_pct <= MAX_RELATIVE_DD_PCT always
        scores strictly higher than one above the ceiling.
      * Among compliant candidates, higher net profit wins; profit factor is a
        tiny tiebreaker.
      * Fewer than MIN_MEANINGFUL_TRADES trades incurs a penalty.
      * Missing/None metrics are treated as worst-case.

    metrics: a dict such as summary['metrics'] from analyze_report.py. May be
    None or partially populated.
    """
    if not isinstance(metrics, dict):
        metrics = {}

    net_profit = _num(metrics.get("total_net_profit"), _WORST_NET_PROFIT)
    dd_pct = _num(metrics.get("relative_drawdown_pct"), _WORST_DD_PCT)
    pf = _num(metrics.get("profit_factor"), _WORST_PF)
    trades = _num(metrics.get("total_trades"), _WORST_TRADES)

    if dd_pct > MAX_RELATIVE_DD_PCT:
        # Tier B: at or below the separator. Larger overage -> worse (more
        # negative). Ordering within the tier is purely by overage so no
        # compliant candidate can ever be beaten by an over-ceiling one.
        overage = dd_pct - MAX_RELATIVE_DD_PCT
        return TIER_SEPARATOR - overage

    # Tier A: compliant. Lifted above the separator by a large fixed offset so
    # even a losing compliant candidate outranks every over-ceiling candidate.
    base = TIER_SEPARATOR + TIER_A_OFFSET + net_profit

    # Profit-factor tiebreaker (tiny).
    base += PF_TIEBREAK_WEIGHT * max(pf, 0.0)

    # Low-trade penalty.
    if trades < MIN_MEANINGFUL_TRADES:
        shortfall = MIN_MEANINGFUL_TRADES - trades
        base -= LOW_TRADE_PENALTY_PER_TRADE * shortfall

    return base
