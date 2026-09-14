"""Instrument and account constants for the XAUUSD backtester.

IMPORTANT: every constant below is a PARITY ASSUMPTION. The sandbox cannot run
MetaTrader 5, so none of these are broker-verified here. Each is flagged
CONFIRM: the user must confirm it against their actual broker (Fusion Markets)
and MT5 symbol specification before treating any backtest P&L as trustworthy.
These values drive P&L, lot sizing and drawdown, so a wrong constant silently
biases every result.

All values are for XAUUSD (gold) as observed in the supplied tick window
(prices ~3975-4367, 2-decimal quotes).
"""

# Smallest price increment the symbol quotes in. Detected from the data: quotes
# carry 2 decimals (e.g. 3975.95), so one point is 0.01.
# CONFIRM vs broker symbol spec (SYMBOL_POINT).
POINT_SIZE = 0.01

# Tick size = smallest tradable price change. For XAUUSD this equals the point.
# CONFIRM vs broker (SYMBOL_TRADE_TICK_SIZE).
TICK_SIZE = 0.01

# Account currency (USD) value of one TICK_SIZE move per 1.0 lot.
# Gold contract is 100 oz, so a $1.00 price move = $100 per 1.0 lot; therefore
# a 0.01 (one tick) move = $1.00 per 1.0 lot.
# CONFIRMED via MT5 deal reconciliation (FEAT-001/FEAT-002 calibration harness,
# data/ReportTester-470903.html): e.g. buy 0.01 @ 4166.33 -> sell 0.01 @ 4164.97
# = -1.36 price move reported as -1.36 USD, i.e. 1.00 USD per 1.00 price move per
# 0.01 lot. Across all 209 trades the harness derives 1.0000 USD per 1.00 move
# per 0.01 lot with max abs error 0.0000 (tol 0.02) => TICK_VALUE=1.0 confirmed.
# Do NOT change.
TICK_VALUE = 1.0

# Contract size in ounces per 1.0 lot. Gold standard is 100 oz.
# CONFIRMED via the same MT5 deal reconciliation as TICK_VALUE above: 1.00 USD
# per 0.01 move per 0.01 lot implies 100 oz per 1.0 lot. Do NOT change.
CONTRACT_SIZE = 100

# Commission charged per 1.0 lot per side (entry and exit each charged).
# CONFIRMED via MT5 deal reconciliation (FEAT-001): every 0.01-lot deal in
# data/ReportTester-470903.html was charged exactly -0.03 (3.00/side, 6.00/lot
# round-turn). 418 deals * 0.03 = 12.54 total commission; the report reconciles
# as 64.68 gross profit - 12.54 commission - 0.64 swap = 51.50 net, exactly the
# reported net. Charging both sides at 3.00 reproduces this. Do NOT change.
# SWAP is deliberately NOT modeled: the whole 209-trade run had a single nonzero
# swap entry (-0.64), immaterial to P&L parity, so no swap model is added.
COMMISSION_PER_LOT_PER_SIDE = 3.0

# Starting account balance in account currency (USD), to mirror the MT5 tests.
# CONFIRM vs the deposit used in the user's MT5 backtests.
INITIAL_DEPOSIT = 1000.0

# Account leverage (1:LEVERAGE). Used for margin checks if the engine models
# them. CONFIRM vs the user's account leverage.
LEVERAGE = 500
