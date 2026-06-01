"""
test_strategy.py
Connects to MT5, fetches H1 + H4 data, runs the strategy scanner,
and prints any signals found.

Usage:
    python test_strategy.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import (
    connect, disconnect, get_multi_ohlcv, setup_logger,
    MT5_LOGIN, MT5_PASSWORD, MT5_SERVER,
    ALL_SYMBOLS, TIMEFRAME, HIGHER_TF,
    EMA_FAST, EMA_SLOW, EMA_TREND, ATR_PERIOD,
    ATR_SL_MULT, ATR_TP_MULT, MIN_RR_RATIO,
)
from strategy import TrendFollowingStrategy

logger = setup_logger("test_strategy")

CONFIG = {
    "EMA_FAST":    EMA_FAST,
    "EMA_SLOW":    EMA_SLOW,
    "EMA_TREND":   EMA_TREND,
    "ATR_PERIOD":  ATR_PERIOD,
    "ATR_SL_MULT": ATR_SL_MULT,
    "ATR_TP_MULT": ATR_TP_MULT,
    "MIN_RR_RATIO": MIN_RR_RATIO,
}


def run():
    print("\n" + "="*58)
    print("  STRATEGY ENGINE TEST — Multi-Symbol Scanner")
    print("="*58)

    if not connect(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
        print("❌  Could not connect to MT5.")
        return

    print(f"\nFetching H1 data for {len(ALL_SYMBOLS)} symbols...")
    data_h1 = get_multi_ohlcv(ALL_SYMBOLS, timeframe="H1", bars=500)

    print(f"Fetching H4 data for {len(ALL_SYMBOLS)} symbols...")
    data_h4 = get_multi_ohlcv(ALL_SYMBOLS, timeframe="H4", bars=500)

    strategy = TrendFollowingStrategy(CONFIG)

    print("\nRunning scanner...\n")
    signals = strategy.scan(data_h1, data_h4)

    if signals:
        print(f"✅  {len(signals)} signal(s) found:\n")
        for sig in signals:
            print(f"  {sig}\n")
    else:
        print("📭  No signals found on current bar — market conditions not met.")

    # Also show per-symbol analysis for first 3 symbols
    print("\n" + "-"*58)
    print("Individual symbol breakdown (first 5):")
    print("-"*58)
    for sym in list(data_h1.keys())[:5]:
        if sym in data_h4:
            sig = strategy.generate_signal(sym, data_h1[sym], data_h4[sym])
            status = f"✅ {sig.direction}" if sig.is_valid else "—"
            reason = sig.reasons[0] if sig.reasons else ""
            print(f"  {sym:<12} {status:<10} {reason}")

    disconnect()
    print("\n" + "="*58 + "\n")


if __name__ == "__main__":
    run()
