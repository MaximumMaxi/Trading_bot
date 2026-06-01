"""
config.py — Central configuration for the trading system.
Edit this file to set your credentials, symbols, and parameters.
"""

# ─── MT5 Credentials ──────────────────────────────────────────────────────────
MT5_LOGIN    = 0               # Replace with your account number
MT5_PASSWORD = "your_password" # Replace with your password
MT5_SERVER   = "ICMarkets-Demo"# Replace with your broker server
MT5_PATH     = None            # Optional: path to terminal64.exe

# ─── Symbols by market ────────────────────────────────────────────────────────
SYMBOLS = {
    "forex":       ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"],
    "crypto":      ["BTCUSD", "ETHUSD"],
    "commodities": ["XAUUSD", "XAGUSD", "USOIL"],
    "indices":     ["US500", "US30", "GER40"],
}

# Flat list of all symbols
ALL_SYMBOLS = [s for group in SYMBOLS.values() for s in group]

# ─── Strategy parameters ──────────────────────────────────────────────────────
TIMEFRAME     = "H1"     # Primary timeframe
HIGHER_TF     = "H4"     # Higher timeframe for trend filter
EMA_FAST      = 20       # Fast EMA period
EMA_SLOW      = 50       # Slow EMA period
EMA_TREND     = 200      # Trend filter EMA
ATR_PERIOD    = 14       # ATR period (for SL/TP)
ATR_SL_MULT   = 1.5      # SL = ATR × this multiplier
ATR_TP_MULT   = 2.5      # TP = ATR × this multiplier
BARS_TO_FETCH = 500      # Historical bars per symbol

# ─── Risk management ──────────────────────────────────────────────────────────
RISK_PER_TRADE   = 0.01  # 1% account risk per trade
MAX_OPEN_TRADES  = 5     # Maximum simultaneous open trades
MAX_DAILY_LOSS   = 0.03  # Stop trading if daily loss > 3% of balance
MAX_DRAWDOWN     = 0.10  # Halt bot if equity drawdown > 10%
MIN_RR_RATIO     = 1.5   # Minimum reward:risk ratio to take a trade

# ─── Execution ────────────────────────────────────────────────────────────────
MAGIC_NUMBER  = 20240101 # Unique ID for bot orders
ORDER_COMMENT = "AlgoBot_v1"
SLIPPAGE      = 10       # Max slippage in points

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL  = "INFO"
LOG_FILE   = "logs/trading_bot.log"
TRADE_LOG  = "logs/trades.csv"
