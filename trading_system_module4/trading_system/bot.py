"""
bot.py — Main trading bot loop.

Orchestrates all modules:
  Data → Strategy → Risk → Execution → Journal

Run with:
    python bot.py

Stop with Ctrl+C (graceful shutdown).
"""

import time
import signal
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import (
    connect, disconnect, ensure_connected,
    get_multi_ohlcv, get_account_info, get_open_positions,
    get_symbol_info, setup_logger,
    MT5_LOGIN, MT5_PASSWORD, MT5_SERVER,
    ALL_SYMBOLS, MAGIC_NUMBER, ORDER_COMMENT,
    EMA_FAST, EMA_SLOW, EMA_TREND, ATR_PERIOD,
    ATR_SL_MULT, ATR_TP_MULT, MIN_RR_RATIO,
    RISK_PER_TRADE, MAX_OPEN_TRADES, MAX_DAILY_LOSS,
    MAX_DRAWDOWN, SLIPPAGE, LOG_FILE, TRADE_LOG,
)
from strategy import TrendFollowingStrategy
from risk     import RiskManager
from execution import Executor, TradeJournal

logger = setup_logger("bot", LOG_FILE)

# ─── Config dicts ─────────────────────────────────────────────────────────────

STRATEGY_CONFIG = {
    "EMA_FAST": EMA_FAST, "EMA_SLOW": EMA_SLOW, "EMA_TREND": EMA_TREND,
    "ATR_PERIOD": ATR_PERIOD, "ATR_SL_MULT": ATR_SL_MULT,
    "ATR_TP_MULT": ATR_TP_MULT, "MIN_RR_RATIO": MIN_RR_RATIO,
}
RISK_CONFIG = {
    "RISK_PER_TRADE": RISK_PER_TRADE, "MAX_OPEN_TRADES": MAX_OPEN_TRADES,
    "MAX_DAILY_LOSS": MAX_DAILY_LOSS, "MAX_DRAWDOWN": MAX_DRAWDOWN,
    "MIN_RR_RATIO": MIN_RR_RATIO,
}
EXEC_CONFIG = {
    "MAGIC_NUMBER": MAGIC_NUMBER, "ORDER_COMMENT": ORDER_COMMENT,
    "SLIPPAGE": SLIPPAGE, "ORDER_RETRIES": 3,
}

# ─── Loop interval ────────────────────────────────────────────────────────────
LOOP_INTERVAL_SECONDS = 60   # Check for signals every 60s (1 H1 candle = 3600s)
                              # Adjust to 3600 for candle-close execution


# ─── Graceful shutdown ────────────────────────────────────────────────────────

_running = True

def _handle_exit(sig, frame):
    global _running
    logger.info("Shutdown signal received — stopping after current loop...")
    _running = False

signal.signal(signal.SIGINT,  _handle_exit)
signal.signal(signal.SIGTERM, _handle_exit)


# ─── Bot class ────────────────────────────────────────────────────────────────

class TradingBot:

    def __init__(self):
        self.strategy = TrendFollowingStrategy(STRATEGY_CONFIG)
        self.risk     = RiskManager(RISK_CONFIG)
        self.executor = Executor(EXEC_CONFIG)
        self.journal  = TradeJournal(TRADE_LOG)
        self._already_traded: set[str] = set()  # avoid double-entry same candle

    # ── Startup ──────────────────────────────────────────────────────────────

    def start(self):
        logger.info("=" * 55)
        logger.info("  TRADING BOT STARTING")
        logger.info("=" * 55)

        if not connect(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
            logger.critical("Cannot connect to MT5. Exiting.")
            sys.exit(1)

        acc = get_account_info()
        if not acc:
            logger.critical("Cannot retrieve account info. Exiting.")
            sys.exit(1)

        logger.info(
            f"Account: {acc['login']} | Balance: {acc['balance']} {acc['currency']} "
            f"| Leverage: 1:{acc['leverage']}"
        )
        self.risk.start_session(acc["balance"], acc["equity"])
        logger.info("Bot running. Press Ctrl+C to stop.\n")

    # ── Main loop ────────────────────────────────────────────────────────────

    def run(self):
        global _running
        self.start()

        while _running:
            try:
                self._loop_iteration()
            except Exception as e:
                logger.error(f"Unhandled error in loop: {e}", exc_info=True)

            if _running:
                logger.debug(f"Sleeping {LOOP_INTERVAL_SECONDS}s...")
                time.sleep(LOOP_INTERVAL_SECONDS)

        self._shutdown()

    def _loop_iteration(self):
        # 1. Check connection
        if not ensure_connected(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
            logger.warning("MT5 disconnected — skipping iteration.")
            return

        # 2. Account snapshot
        acc = get_account_info()
        if not acc:
            return

        self.risk.update_equity(acc["equity"])

        if self.risk.is_halted():
            logger.warning(f"Bot halted — skipping. Balance:{acc['balance']} Equity:{acc['equity']}")
            return

        # 3. Trailing stops on existing positions
        self.executor.apply_trailing_stops(self.risk)

        # 4. Fetch market data
        logger.info(f"Scanning {len(ALL_SYMBOLS)} symbols...")
        data_h1 = get_multi_ohlcv(ALL_SYMBOLS, "H1", bars=500)
        data_h4 = get_multi_ohlcv(ALL_SYMBOLS, "H4", bars=500)

        # 5. Generate signals
        signals = self.strategy.scan(data_h1, data_h4)
        logger.info(f"Signals found: {len(signals)}")

        open_positions = get_open_positions()
        open_count     = len(open_positions)
        open_symbols   = {p["symbol"] for p in open_positions}

        # 6. Process each signal
        for sig in signals:
            if sig.symbol in open_symbols:
                logger.info(f"Skipping {sig.symbol} — already have an open position.")
                continue

            sym_info = get_symbol_info(sig.symbol)
            if sym_info is None:
                continue

            risk_check = self.risk.check_trade(
                symbol=sig.symbol, direction=sig.direction,
                entry=sig.entry, sl=sig.sl, tp=sig.tp,
                rr_ratio=sig.rr_ratio, atr=sig.atr,
                balance=acc["balance"], equity=acc["equity"],
                open_positions=open_count,
                symbol_info=sym_info,
            )

            logger.info(f"{sig.symbol} risk check: {risk_check}")

            if not risk_check.approved:
                continue

            # Place order
            result = self.executor.place_order(sig, risk_check.lot_size)
            logger.info(str(result))

            if result.success:
                self.journal.log_open(
                    ticket=result.ticket, symbol=sig.symbol,
                    direction=sig.direction, volume=risk_check.lot_size,
                    open_price=result.price, sl=sig.sl, tp=sig.tp,
                    comment=f"R:R {sig.rr_ratio} | {'; '.join(sig.reasons)}",
                )
                open_count += 1

        # 7. Sync closed trades from MT5 history into journal
        self._sync_closed_trades()

        # 8. Log account state
        status = self.risk.get_status(acc["balance"], acc["equity"])
        logger.info(
            f"Account | Balance:{acc['balance']:.2f} Equity:{acc['equity']:.2f} "
            f"| Drawdown:{status['current_drawdown']}% "
            f"| Daily loss:{status['daily_loss_pct']}% "
            f"| Open trades:{open_count}"
        )

    def _sync_closed_trades(self):
        """Update journal for any positions closed by SL/TP since last check."""
        from datetime import datetime, timedelta
        from core import get_trade_history
        import MetaTrader5 as mt5

        since = datetime.now() - timedelta(hours=2)
        history = get_trade_history(since)

        if history.empty:
            return

        open_tickets = {t.ticket for t in self.journal.get_open_trades()}

        for _, deal in history.iterrows():
            if deal.get("ticket") in open_tickets:
                positions = mt5.positions_get(ticket=deal["ticket"])
                if not positions:
                    # Determine close reason
                    status = "CLOSED"
                    if "sl" in str(deal.get("comment", "")).lower():
                        status = "SL_HIT"
                    elif "tp" in str(deal.get("comment", "")).lower():
                        status = "TP_HIT"
                    self.journal.log_close(
                        ticket=deal["ticket"],
                        close_price=deal.get("price", 0),
                        profit=deal.get("profit", 0),
                        swap=deal.get("swap", 0),
                        commission=deal.get("commission", 0),
                        status=status,
                    )

    def _shutdown(self):
        logger.info("Shutting down bot...")
        self.journal.print_stats()
        disconnect()
        logger.info("Bot stopped cleanly.")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
