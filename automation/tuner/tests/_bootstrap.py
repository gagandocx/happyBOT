"""Make the tuner modules importable regardless of how tests are launched.

Inserts automation/tuner/ (the package dir) onto sys.path so `import scoring`,
`import params`, etc. resolve when tests are run via
`python3 -m unittest discover -s automation/tuner/tests` from repo root, or from
inside the tests dir. This mirrors the existing tools/ test convention.
"""

import os
import sys

_TUNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TUNER_DIR not in sys.path:
    sys.path.insert(0, _TUNER_DIR)
