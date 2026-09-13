"""python_bt - pure-Python, stdlib-only, in-sandbox tick backtester for XAUUSD.

This package lets XAUUSD strategies (a faithful port of GaganEA.mq5) be
developed and ranked entirely in the sandbox from real MT5 tick data, WITHOUT
a round-trip to MetaTrader 5. MT5 stays the source of truth for final
validation; results produced here are research signals, not broker-verified.

Modules (created across features):
  config.py   - instrument/account constants (parity assumptions, this feature)
  loader.py   - streaming tick loader (this feature)
  bars.py     - ticks -> M5 bar aggregator (this feature)
  engine.py   - event loop / fill model (FEAT-002)
  broker.py   - position + P&L accounting (FEAT-002)
  metrics.py  - metrics dict matching the analyzer schema (FEAT-002)
  strategy/   - strategy base + GaganEA port (FEAT-003)
  runner.py   - CLI runner (FEAT-003)
  research.py - research loop harness (FEAT-004)

Stdlib only. Pure ASCII. Target Python 3.9+.
"""
