"""
test_risk.py
Tests the risk manager in isolation using simulated account values.
No live MT5 connection required.

Usage:
    python test_risk.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from risk import RiskManager, RiskCheck
from core import (
    RISK_PER_TRADE, MAX_OPEN_TRADES,
    MAX_DAILY_LOSS, MAX_DRAWDOWN, MIN_RR_RATIO,
)

CONFIG = {
    "RISK_PER_TRADE":  RISK_PER_TRADE,
    "MAX_OPEN_TRADES": MAX_OPEN_TRADES,
    "MAX_DAILY_LOSS":  MAX_DAILY_LOSS,
    "MAX_DRAWDOWN":    MAX_DRAWDOWN,
    "MIN_RR_RATIO":    MIN_RR_RATIO,
}

# Simulated symbol info (EURUSD-like)
EURUSD_INFO = {
    "point":       0.00001,
    "contract_sz": 100_000,
    "min_lot":     0.01,
    "max_lot":     100.0,
    "lot_step":    0.01,
}

# Simulated XAUUSD info
XAUUSD_INFO = {
    "point":       0.01,
    "contract_sz": 100,
    "min_lot":     0.01,
    "max_lot":     50.0,
    "lot_step":    0.01,
}


def sep(title=""):
    print(f"\n{'─'*55}")
    if title:
        print(f"  {title}")
        print(f"{'─'*55}")


def run():
    print("\n" + "="*55)
    print("  RISK MANAGER TEST")
    print("="*55)

    rm = RiskManager(CONFIG)
    rm.start_session(balance=10_000.0, equity=10_000.0)

    # ── Test 1: Valid trade ───────────────────────────────────────────────
    sep("Test 1 — Valid BUY trade (EURUSD)")
    result = rm.check_trade(
        symbol="EURUSD", direction="BUY",
        entry=1.10000, sl=1.09700, tp=1.10750,
        rr_ratio=2.5, atr=0.00300,
        balance=10_000, equity=10_000,
        open_positions=1,
        symbol_info=EURUSD_INFO,
    )
    print(f"  {result}")

    # ── Test 2: R:R too low ───────────────────────────────────────────────
    sep("Test 2 — R:R below minimum")
    result = rm.check_trade(
        symbol="EURUSD", direction="BUY",
        entry=1.10000, sl=1.09700, tp=1.10200,
        rr_ratio=0.67, atr=0.00300,
        balance=10_000, equity=10_000,
        open_positions=1,
        symbol_info=EURUSD_INFO,
    )
    print(f"  {result}")

    # ── Test 3: Max trades hit ────────────────────────────────────────────
    sep("Test 3 — Max open trades reached")
    result = rm.check_trade(
        symbol="GBPUSD", direction="SELL",
        entry=1.27000, sl=1.27300, tp=1.26250,
        rr_ratio=2.5, atr=0.00300,
        balance=10_000, equity=10_000,
        open_positions=5,   # already at max
        symbol_info=EURUSD_INFO,
    )
    print(f"  {result}")

    # ── Test 4: Daily loss limit ──────────────────────────────────────────
    sep("Test 4 — Daily loss limit (simulate 3.5% loss)")
    rm2 = RiskManager(CONFIG)
    rm2.start_session(balance=10_000.0, equity=10_000.0)
    result = rm2.check_trade(
        symbol="EURUSD", direction="BUY",
        entry=1.10000, sl=1.09700, tp=1.10750,
        rr_ratio=2.5, atr=0.00300,
        balance=9_650,  # down 3.5% from 10,000
        equity=9_650,
        open_positions=0,
        symbol_info=EURUSD_INFO,
    )
    print(f"  {result}")

    # ── Test 5: Drawdown halt ─────────────────────────────────────────────
    sep("Test 5 — Max drawdown halt (simulate 11% drawdown)")
    rm3 = RiskManager(CONFIG)
    rm3.start_session(balance=10_000.0, equity=10_000.0)
    rm3._peak_equity = 11_000.0  # simulate previous high
    result = rm3.check_trade(
        symbol="XAUUSD", direction="BUY",
        entry=2000.0, sl=1990.0, tp=2025.0,
        rr_ratio=2.5, atr=10.0,
        balance=9_700, equity=9_790,  # 11% below peak
        open_positions=0,
        symbol_info=XAUUSD_INFO,
    )
    print(f"  {result}")

    # ── Test 6: Gold position sizing ─────────────────────────────────────
    sep("Test 6 — XAUUSD lot sizing (1% risk, 10-pt SL)")
    rm4 = RiskManager(CONFIG)
    rm4.start_session(balance=10_000.0, equity=10_000.0)
    result = rm4.check_trade(
        symbol="XAUUSD", direction="BUY",
        entry=2000.0, sl=1990.0, tp=2025.0,
        rr_ratio=2.5, atr=10.0,
        balance=10_000, equity=10_000,
        open_positions=0,
        symbol_info=XAUUSD_INFO,
    )
    print(f"  {result}")

    # ── Test 7: Trailing stop ─────────────────────────────────────────────
    sep("Test 7 — Trailing stop calculation")
    new_sl = rm.trail_stop("BUY", current_sl=1.09700, current_price=1.10500, atr=0.00300)
    print(f"  BUY  | Current SL: 1.09700 | Price: 1.10500 | New SL: {new_sl}")
    new_sl2 = rm.trail_stop("BUY", current_sl=1.09700, current_price=1.09800, atr=0.00300)
    print(f"  BUY  | Current SL: 1.09700 | Price: 1.09800 | New SL: {new_sl2} (no improvement)")

    # ── Risk status snapshot ──────────────────────────────────────────────
    sep("Risk status snapshot")
    status = rm.get_status(balance=9_850, equity=9_900)
    for k, v in status.items():
        print(f"  {k:<25}: {v}")

    print("\n" + "="*55)
    print("  Risk manager tests complete.")
    print("="*55 + "\n")


if __name__ == "__main__":
    run()
