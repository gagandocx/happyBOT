"""Make automation/tuner/scoring.py importable from python_bt without dup.

The tuner's scoring.py is the single source of truth for ranking candidates
(it enforces the hard 15% relative-drawdown ceiling). Rather than reimplement
that logic here, this bridge inserts the automation/tuner directory on sys.path
(the same directory the tuner's own tests/_bootstrap.py adds) and re-exports
its score() function.

Usage:
    from python_bt.scoring_bridge import score
    value = score(metrics_dict)

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

import os
import sys

# python_bt/ -> repo root -> automation/tuner
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_TUNER_DIR = os.path.join(_REPO_ROOT, "automation", "tuner")

if _TUNER_DIR not in sys.path:
    sys.path.insert(0, _TUNER_DIR)

from scoring import score  # noqa: E402,F401  (re-exported)

__all__ = ["score"]
