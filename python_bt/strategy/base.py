"""Strategy base class + registry for the pluggable backtester.

The engine (python_bt.engine) drives a strategy through a tiny protocol:

    strategy.on_bar(bar, ctx)     # REQUIRED - called on every closed M5 bar
    strategy.on_tick(tick, ctx)   # OPTIONAL - called on every tick (tick mode)

Both callbacks receive a Context (python_bt.engine.Context) exposing broker
actions and the latest market state:

    ctx.buy(volume, sl, tp) / ctx.sell(volume, sl, tp)  -> open a position
    ctx.close_partial(pos, volume, reason) / ctx.close_full(pos, reason)
    ctx.modify_sl(pos, new_sl)
    ctx.positions        # list of open python_bt.broker.Position
    ctx.bid / ctx.ask    # latest quote
    ctx.ts               # latest quote timestamp (datetime)
    ctx.bar              # most recent closed Bar (or None)

To add a strategy: subclass Strategy, set NAME, implement default_params() and
on_bar (and optionally on_tick), and decorate the class with @register. The
runner then finds it by NAME.

Stdlib only. Pure ASCII. Target Python 3.9+.
"""

from __future__ import annotations

from typing import Dict, Optional, Type

# name -> Strategy subclass. Populated by the @register decorator.
STRATEGY_REGISTRY = {}  # type: Dict[str, Type["Strategy"]]


class Strategy:
    """Abstract base for a pluggable backtesting strategy.

    Subclasses set a class attribute NAME (the registry key) and implement
    default_params() and on_bar(). __init__ merges supplied params over the
    defaults so a caller may pass only the params they want to override.
    """

    NAME = "base"

    def __init__(self, params: Optional[Dict] = None):
        merged = dict(self.default_params())
        if params:
            merged.update(params)
        self.params = merged

    @classmethod
    def default_params(cls) -> Dict[str, object]:
        """Return a fresh dict of default params for this strategy."""
        return {}

    def on_bar(self, bar, ctx) -> None:
        """Called on every closed bar. Subclasses MUST override."""
        raise NotImplementedError

    # on_tick is intentionally NOT defined here: the engine checks for its
    # presence with getattr, so a strategy that does not trade intrabar simply
    # omits it. Subclasses that need per-tick logic define on_tick(self, tick,
    # ctx).

    def warmup_info(self) -> Optional[Dict[str, object]]:
        """Optional: report indicator warm-up / entry-eligibility state.

        The engine calls this (via getattr, so it is optional) after a run and
        stashes the result in result['meta']['warmup']. Returning a dict lets
        the runner and research leaderboard tell "the strategy is flat" apart
        from "there was not enough data to warm up", which otherwise both read
        as zero trades. A None return means the strategy does not track this.

        Recommended keys: {"warmed_up": bool, "entry_ever_eligible": bool,
        "note": str} where `note` is a short human-readable explanation when
        warm-up was not reached.
        """
        return None


def register(cls: Type[Strategy]) -> Type[Strategy]:
    """Class decorator: register a Strategy subclass under its NAME."""
    name = getattr(cls, "NAME", None)
    if not name or name == "base":
        raise ValueError("Strategy subclass must set a unique NAME class attribute")
    if name in STRATEGY_REGISTRY and STRATEGY_REGISTRY[name] is not cls:
        raise ValueError("duplicate strategy NAME: {}".format(name))
    STRATEGY_REGISTRY[name] = cls
    return cls


def get_strategy(name: str) -> Type[Strategy]:
    """Look up a registered strategy class by name (raises KeyError if absent)."""
    if name not in STRATEGY_REGISTRY:
        raise KeyError(
            "unknown strategy '{}'; registered: {}".format(
                name, ", ".join(sorted(STRATEGY_REGISTRY)) or "(none)"
            )
        )
    return STRATEGY_REGISTRY[name]
