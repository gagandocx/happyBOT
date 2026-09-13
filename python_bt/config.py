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
# CONFIRM vs broker (SYMBOL_TRADE_TICK_VALUE). Drives P&L parity.
TICK_VALUE = 1.0

# Contract size in ounces per 1.0 lot. Gold standard is 100 oz.
# CONFIRM vs broker (SYMBOL_TRADE_CONTRACT_SIZE).
CONTRACT_SIZE = 100

# Commission charged per 1.0 lot per side (entry and exit each charged).
# Fusion Markets is a commission broker; 3.5 USD/lot/side is a common default.
# CONFIRM vs the user's actual Fusion commission tier.
COMMISSION_PER_LOT_PER_SIDE = 3.5

# Starting account balance in account currency (USD), to mirror the MT5 tests.
# CONFIRM vs the deposit used in the user's MT5 backtests.
INITIAL_DEPOSIT = 1000.0

# Account leverage (1:LEVERAGE). Used for margin checks if the engine models
# them. CONFIRM vs the user's account leverage.
LEVERAGE = 500
