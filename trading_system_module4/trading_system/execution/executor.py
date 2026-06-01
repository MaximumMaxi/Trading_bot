"""
executor.py — Order execution layer.

Responsibilities:
  1. Send market orders (BUY / SELL) with SL and TP
  2. Modify SL / TP on open positions
  3. Close positions (full or partial)
  4. Apply trailing stops across all open positions
  5. Retry failed orders with configurable attempts
  6. Log every action to the trade journal
"""

import MetaTrader5 as mt5
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ─── Order result ─────────────────────────────────────────────────────────────

@dataclass
class OrderResult:
    success:   bool
    ticket:    int   = 0
    symbol:    str   = ""
    direction: str   = ""
    volume:    float = 0.0
    price:     float = 0.0
    sl:        float = 0.0
    tp:        float = 0.0
    error:     str   = ""
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def __str__(self):
        if self.success:
            return (
                f"✅ ORDER #{self.ticket} | {self.symbol} {self.direction} "
                f"{self.volume} lots @ {self.price} | SL:{self.sl} TP:{self.tp}"
            )
        return f"❌ ORDER FAILED | {self.symbol} {self.direction} | {self.error}"


# ─── Executor ─────────────────────────────────────────────────────────────────

class Executor:
    """
    Handles all order operations against MT5.
    Every method returns an OrderResult so the caller can log/react.
    """

    def __init__(self, config: dict):
        """
        config keys:
            MAGIC_NUMBER   — unique int to tag bot orders
            ORDER_COMMENT  — string comment on orders
            SLIPPAGE       — max slippage in points
        """
        self.magic    = config.get("MAGIC_NUMBER",  20240101)
        self.comment  = config.get("ORDER_COMMENT", "AlgoBot_v1")
        self.slippage = config.get("SLIPPAGE",      10)
        self._retries = config.get("ORDER_RETRIES", 3)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _get_filling_mode(self, symbol: str) -> int:
        """Return the first supported filling mode for a symbol."""
        info = mt5.symbol_info(symbol)
        if info is None:
            return mt5.ORDER_FILLING_IOC
        modes = {
            0: mt5.ORDER_FILLING_FOK,
            1: mt5.ORDER_FILLING_IOC,
            2: mt5.ORDER_FILLING_RETURN,
        }
        filling_type = info.filling_mode
        for bit, mode in modes.items():
            if filling_type & (1 << bit):
                return mode
        return mt5.ORDER_FILLING_IOC

    def _send_request(self, request: dict) -> OrderResult:
        """Send an MT5 request with retry logic."""
        symbol    = request.get("symbol", "")
        direction = "BUY" if request.get("type") == mt5.ORDER_TYPE_BUY else "SELL"

        for attempt in range(1, self._retries + 1):
            result = mt5.order_send(request)

            if result is None:
                err = mt5.last_error()
                logger.warning(f"order_send returned None (attempt {attempt}): {err}")
                continue

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(
                    f"Order placed | #{result.order} | {symbol} {direction} "
                    f"{result.volume} lots @ {result.price}"
                )
                return OrderResult(
                    success=True, ticket=result.order,
                    symbol=symbol, direction=direction,
                    volume=result.volume, price=result.price,
                    sl=request.get("sl", 0.0), tp=request.get("tp", 0.0),
                )

            # Retriable codes
            retriable = {
                mt5.TRADE_RETCODE_REQUOTE,
                mt5.TRADE_RETCODE_PRICE_CHANGED,
                mt5.TRADE_RETCODE_PRICE_OFF,
                mt5.TRADE_RETCODE_OFF_QUOTES,
            }
            if result.retcode in retriable:
                logger.warning(
                    f"Retriable error {result.retcode} on attempt {attempt}/{self._retries}"
                )
                # Refresh price on requote
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    if request.get("type") == mt5.ORDER_TYPE_BUY:
                        request["price"] = tick.ask
                    else:
                        request["price"] = tick.bid
                continue

            # Non-retriable failure
            error_msg = f"retcode={result.retcode} | {result.comment}"
            logger.error(f"Order failed: {error_msg}")
            return OrderResult(success=False, symbol=symbol, direction=direction, error=error_msg)

        return OrderResult(
            success=False, symbol=symbol, direction=direction,
            error=f"Failed after {self._retries} attempts"
        )

    # ── Market orders ────────────────────────────────────────────────────────

    def buy(
        self,
        symbol:  str,
        volume:  float,
        sl:      float,
        tp:      float,
        comment: Optional[str] = None,
    ) -> OrderResult:
        """Open a market BUY order."""
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return OrderResult(False, symbol=symbol, direction="BUY", error="No tick data")

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       volume,
            "type":         mt5.ORDER_TYPE_BUY,
            "price":        tick.ask,
            "sl":           sl,
            "tp":           tp,
            "deviation":    self.slippage,
            "magic":        self.magic,
            "comment":      comment or self.comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        }
        return self._send_request(request)

    def sell(
        self,
        symbol:  str,
        volume:  float,
        sl:      float,
        tp:      float,
        comment: Optional[str] = None,
    ) -> OrderResult:
        """Open a market SELL order."""
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return OrderResult(False, symbol=symbol, direction="SELL", error="No tick data")

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       volume,
            "type":         mt5.ORDER_TYPE_SELL,
            "price":        tick.bid,
            "sl":           sl,
            "tp":           tp,
            "deviation":    self.slippage,
            "magic":        self.magic,
            "comment":      comment or self.comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        }
        return self._send_request(request)

    def place_order(self, signal, volume: float) -> OrderResult:
        """
        Convenience: place an order directly from a Signal object.
        signal must have: symbol, direction, sl, tp attributes.
        """
        if signal.direction == "BUY":
            return self.buy(signal.symbol, volume, signal.sl, signal.tp)
        elif signal.direction == "SELL":
            return self.sell(signal.symbol, volume, signal.sl, signal.tp)
        return OrderResult(False, symbol=signal.symbol, error="Invalid direction")

    # ── Modify / close ───────────────────────────────────────────────────────

    def modify_position(
        self,
        ticket: int,
        sl:     Optional[float] = None,
        tp:     Optional[float] = None,
    ) -> OrderResult:
        """Modify SL and/or TP on an open position."""
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return OrderResult(False, error=f"Position #{ticket} not found")

        pos = position[0]
        new_sl = sl if sl is not None else pos.sl
        new_tp = tp if tp is not None else pos.tp

        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   pos.symbol,
            "position": ticket,
            "sl":       new_sl,
            "tp":       new_tp,
            "magic":    self.magic,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Modified #{ticket} | SL:{new_sl} TP:{new_tp}")
            return OrderResult(
                success=True, ticket=ticket,
                symbol=pos.symbol, sl=new_sl, tp=new_tp,
            )
        err = result.comment if result else str(mt5.last_error())
        logger.error(f"Modify failed #{ticket}: {err}")
        return OrderResult(False, ticket=ticket, error=err)

    def close_position(self, ticket: int, volume: Optional[float] = None) -> OrderResult:
        """
        Close a position fully or partially.
        If volume is None, closes the full position.
        """
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return OrderResult(False, error=f"Position #{ticket} not found")

        pos    = position[0]
        vol    = volume or pos.volume
        tick   = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return OrderResult(False, error=f"No tick for {pos.symbol}")

        # Closing a BUY = SELL; closing a SELL = BUY
        if pos.type == mt5.ORDER_TYPE_BUY:
            close_type  = mt5.ORDER_TYPE_SELL
            close_price = tick.bid
            direction   = "SELL"
        else:
            close_type  = mt5.ORDER_TYPE_BUY
            close_price = tick.ask
            direction   = "BUY"

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       pos.symbol,
            "volume":       vol,
            "type":         close_type,
            "position":     ticket,
            "price":        close_price,
            "deviation":    self.slippage,
            "magic":        self.magic,
            "comment":      f"close #{ticket}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(pos.symbol),
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Closed #{ticket} | {pos.symbol} {vol} lots @ {close_price}")
            return OrderResult(
                success=True, ticket=ticket,
                symbol=pos.symbol, direction=direction,
                volume=vol, price=close_price,
            )
        err = result.comment if result else str(mt5.last_error())
        logger.error(f"Close failed #{ticket}: {err}")
        return OrderResult(False, ticket=ticket, symbol=pos.symbol, error=err)

    def close_all(self, symbol: Optional[str] = None) -> list[OrderResult]:
        """Close all open positions, optionally filtered by symbol."""
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if not positions:
            logger.info("close_all: no open positions.")
            return []
        results = []
        for pos in positions:
            if pos.magic == self.magic:
                results.append(self.close_position(pos.ticket))
        return results

    # ── Trailing stop manager ────────────────────────────────────────────────

    def apply_trailing_stops(self, risk_manager) -> list[OrderResult]:
        """
        Iterate all open bot positions and apply ATR-based trailing stops.
        Calls risk_manager.trail_stop() to compute the new SL.

        Returns list of modify results where SL was moved.
        """
        positions = mt5.positions_get()
        if not positions:
            return []

        results = []
        for pos in positions:
            if pos.magic != self.magic:
                continue

            # Need current ATR — fetch last 20 H1 bars
            rates = mt5.copy_rates_from_pos(pos.symbol, mt5.TIMEFRAME_H1, 0, 20)
            if rates is None or len(rates) < 15:
                continue

            import pandas as pd
            from strategy.indicators import atr as calc_atr
            df = pd.DataFrame(rates)
            df.rename(columns={"tick_volume": "volume"}, inplace=True)
            atr_val = calc_atr(df, 14).iloc[-1]

            direction = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                continue

            current_price = tick.bid if direction == "BUY" else tick.ask
            new_sl = risk_manager.trail_stop(
                direction, pos.sl, current_price, atr_val
            )
            if new_sl is not None:
                result = self.modify_position(pos.ticket, sl=new_sl)
                if result.success:
                    logger.info(
                        f"Trailing stop moved | #{pos.ticket} {pos.symbol} "
                        f"{direction} | SL: {pos.sl:.5f} → {new_sl:.5f}"
                    )
                results.append(result)

        return results
