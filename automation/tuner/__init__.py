"""Stdlib-only auto-tuner package for HappyBot.mq5.

Modules:
  scoring       - score(metrics) with a hard relative-drawdown ceiling.
  params        - tunable parameter space + validity/ordering repair.
  mq5_rewriter  - read/rewrite `input TYPE Name = value;` lines in HappyBot.mq5.
  state         - restart-safe JSON state (current/best/history).
  tuner         - CLI entry point (ingest report -> update -> propose -> write).

No third-party imports anywhere; targets python3 (3.9+).
"""
