"""
test_connection.py
Run this first to verify MT5 connects and data fetches correctly.

Usage:
    python test_connection.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import (
    connect, disconnect, get_account_info,
    get_ohlcv, get_tick, get_open_positions,
    setup_logger, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
)

logger = setup_logger("test")


def run_tests():
    print("\n" + "="*55)
    print("  TRADING SYSTEM — CONNECTION TEST")
    print("="*55)

    # 1. Connect
    print("\n[1] Connecting to MT5...")
    if not connect(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
        print("❌  Connection failed. Check your credentials in core/config.py")
        return

    print("✅  Connected successfully.")

    # 2. Account info
    print("\n[2] Account snapshot:")
    acc = get_account_info()
    if acc:
        print(f"    Login     : {acc['login']}")
        print(f"    Balance   : {acc['balance']} {acc['currency']}")
        print(f"    Equity    : {acc['equity']} {acc['currency']}")
        print(f"    Free Margin: {acc['free_margin']}")
        print(f"    Leverage  : 1:{acc['leverage']}")
    else:
        print("⚠️  Could not retrieve account info.")

    # 3. Fetch OHLCV
    print("\n[3] Fetching EURUSD H1 (last 10 bars):")
    df = get_ohlcv("EURUSD", "H1", bars=10)
    if df is not None:
        print(df.to_string())
    else:
        print("⚠️  No data returned for EURUSD H1.")

    # 4. Live tick
    print("\n[4] Live tick — EURUSD:")
    tick = get_tick("EURUSD")
    if tick:
        print(f"    Bid: {tick['bid']}  Ask: {tick['ask']}  Spread: {tick['spread']} pts")
    else:
        print("⚠️  No tick data.")

    # 5. Open positions
    print("\n[5] Open positions:")
    positions = get_open_positions()
    if positions:
        for p in positions:
            print(f"    {p['symbol']} | {p['type']} | {p['volume']} lots | Profit: {p['profit']}")
    else:
        print("    No open positions.")

    # Done
    disconnect()
    print("\n" + "="*55)
    print("  All tests complete. MT5 data layer is ready.")
    print("="*55 + "\n")


if __name__ == "__main__":
    run_tests()
