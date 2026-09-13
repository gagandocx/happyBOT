"""Pluggable strategy package for the XAUUSD backtester.

A strategy is a subclass of python_bt.strategy.base.Strategy that self-registers
under a NAME via the @register decorator. The runner looks strategies up by name
through get_strategy / STRATEGY_REGISTRY, so adding a new strategy idea is just:

    from python_bt.strategy.base import Strategy, register

    @register
    class MyIdea(Strategy):
        NAME = "myidea"
        @classmethod
        def default_params(cls):
            return {...}
        def on_bar(self, bar, ctx):
            ...

Importing this package imports the bundled strategies so they register.

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

from python_bt.strategy.base import (  # noqa: F401
    STRATEGY_REGISTRY,
    Strategy,
    get_strategy,
    register,
)

# Import bundled strategies so they self-register on `import python_bt.strategy`.
from python_bt.strategy import gagan  # noqa: F401,E402

__all__ = ["Strategy", "register", "get_strategy", "STRATEGY_REGISTRY"]
