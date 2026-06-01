"""
risk_manager.py — Position sizing, drawdown control, and trade filters.

Responsibilities:
  1. Calculate lot size based on % account risk and ATR-based stop loss
  2. Enforce max open trades limit
  3. Enforce daily loss limit — pause trading if breached
  4. Enforce max drawdown limit — halt bot entirely if breached
  5. Validate minimum R:R ratio before approving a trade
  6. Normalize lot size to broker constraints (min/max/step)
"""

import math
import logging
from datetime import datetime, date
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ─── Trade approval result ────────────────────────────────────────────────────

@dataclass
class RiskCheck:
    approved:   bool
    lot_size:   float = 0.0
    reason:     str   = ""
    risk_amount: float = 0.0   # $ amount being risked
    risk_pct:   float = 0.0    # % of balance being risked

    def __str__(self):
        status = "✅ APPROVED" if self.approved else "❌ REJECTED"
        if self.approved:
            return f"{status} | Lots: {self.lot_size} | Risk: ${self.risk_amount:.2f} ({self.risk_pct:.2f}%)"
        return f"{status} | Reason: {self.reason}"


# ─── Risk Manager ─────────────────────────────────────────────────────────────

class RiskManager:
    """
    Centralised risk management for the trading bot.
    All trade decisions must pass through check_trade() before execution.
    """

    def __init__(self, config: dict):
        """
        config keys (from core/config.py):
            RISK_PER_TRADE   — fraction of balance to risk per trade (e.g. 0.01 = 1%)
            MAX_OPEN_TRADES  — max simultaneous positions
            MAX_DAILY_LOSS   — daily loss limit as fraction of balance (e.g. 0.03)
            MAX_DRAWDOWN     — max equity drawdown fraction before halt (e.g. 0.10)
            MIN_RR_RATIO     — minimum reward:risk ratio
        """
        self.risk_pct       = config.get("RISK_PER_TRADE",  0.01)
        self.max_trades     = config.get("MAX_OPEN_TRADES",  5)
        self.max_daily_loss = config.get("MAX_DAILY_LOSS",   0.03)
        self.max_drawdown   = config.get("MAX_DRAWDOWN",     0.10)
        self.min_rr         = config.get("MIN_RR_RATIO",     1.5)

        # Internal state
        self._session_start_balance: Optional[float] = None
        self._daily_start_balance:   Optional[float] = None
        self._daily_date:            Optional[date]  = None
        self._peak_equity:           float = 0.0
        self._halted:                bool  = False
        self._halt_reason:           str   = ""

    # ── Session init ─────────────────────────────────────────────────────────

    def start_session(self, balance: float, equity: float) -> None:
        """Call once at bot startup with current account figures."""
        self._session_start_balance = balance
        self._peak_equity = equity
        self._reset_daily_if_needed(balance)
        logger.info(
            f"Risk manager started | Balance: {balance:.2f} | "
            f"Peak equity: {equity:.2f} | "
            f"Risk/trade: {self.risk_pct*100:.1f}% | "
            f"Max daily loss: {self.max_daily_loss*100:.1f}% | "
            f"Max drawdown: {self.max_drawdown*100:.1f}%"
        )

    def update_equity(self, equity: float) -> None:
        """Call on every loop iteration to track peak equity."""
        if equity > self._peak_equity:
            self._peak_equity = equity

    def _reset_daily_if_needed(self, balance: float) -> None:
        today = date.today()
        if self._daily_date != today:
            self._daily_date          = today
            self._daily_start_balance = balance
            logger.info(f"Daily balance reset: {balance:.2f}")

    # ── Core check ───────────────────────────────────────────────────────────

    def check_trade(
        self,
        symbol:        str,
        direction:     str,
        entry:         float,
        sl:            float,
        tp:            float,
        rr_ratio:      float,
        atr:           float,
        balance:       float,
        equity:        float,
        open_positions: int,
        symbol_info:   dict,
    ) -> RiskCheck:
        """
        Full risk check for a proposed trade.

        Returns RiskCheck with approved=True and calculated lot_size,
        or approved=False with the reason it was rejected.
        """
        self._reset_daily_if_needed(balance)
        self.update_equity(equity)

        # 1. Bot halted?
        if self._halted:
            return RiskCheck(False, reason=f"Bot halted: {self._halt_reason}")

        # 2. Max drawdown check
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown >= self.max_drawdown:
                self._halted = True
                self._halt_reason = f"Max drawdown breached ({drawdown*100:.1f}%)"
                logger.critical(self._halt_reason)
                return RiskCheck(False, reason=self._halt_reason)

        # 3. Daily loss check
        if self._daily_start_balance and self._daily_start_balance > 0:
            daily_loss = (self._daily_start_balance - balance) / self._daily_start_balance
            if daily_loss >= self.max_daily_loss:
                reason = f"Daily loss limit hit ({daily_loss*100:.1f}% of {self._daily_start_balance:.2f})"
                logger.warning(reason)
                return RiskCheck(False, reason=reason)

        # 4. Max open trades
        if open_positions >= self.max_trades:
            return RiskCheck(False, reason=f"Max open trades reached ({open_positions}/{self.max_trades})")

        # 5. R:R ratio
        if rr_ratio < self.min_rr:
            return RiskCheck(False, reason=f"R:R {rr_ratio:.2f} below minimum {self.min_rr}")

        # 6. SL distance sanity check
        sl_distance = abs(entry - sl)
        if sl_distance == 0:
            return RiskCheck(False, reason="SL distance is zero")

        # 7. Position sizing
        lot_size = self._calculate_lot_size(
            balance, sl_distance, symbol_info
        )
        if lot_size <= 0:
            return RiskCheck(False, reason="Calculated lot size is zero — check symbol info")

        risk_amount = balance * self.risk_pct

        logger.info(
            f"Risk check APPROVED | {symbol} {direction} | "
            f"Lots: {lot_size} | Risk: ${risk_amount:.2f} ({self.risk_pct*100:.1f}%)"
        )
        return RiskCheck(
            approved=True,
            lot_size=lot_size,
            risk_amount=round(risk_amount, 2),
            risk_pct=round(self.risk_pct * 100, 2),
        )

    # ── Position sizing ───────────────────────────────────────────────────────

    def _calculate_lot_size(
        self,
        balance:     float,
        sl_distance: float,
        symbol_info: dict,
    ) -> float:
        """
        Calculate lot size using fixed fractional position sizing.

        Formula:
            risk_amount   = balance × risk_pct
            pip_value     ≈ point × contract_size (simplified; broker adjusts)
            lots          = risk_amount / (sl_points × pip_value_per_lot)

        Then normalised to broker min/max/step constraints.
        """
        risk_amount   = balance * self.risk_pct
        point         = symbol_info.get("point", 0.00001)
        contract_size = symbol_info.get("contract_sz", 100_000)
        min_lot       = symbol_info.get("min_lot", 0.01)
        max_lot       = symbol_info.get("max_lot", 100.0)
        lot_step      = symbol_info.get("lot_step", 0.01)

        if point == 0 or contract_size == 0:
            return 0.0

        sl_points        = sl_distance / point
        pip_value_per_lot = point * contract_size   # value per point per lot

        if pip_value_per_lot == 0 or sl_points == 0:
            return 0.0

        raw_lots = risk_amount / (sl_points * pip_value_per_lot)

        # Normalise to step
        lots = math.floor(raw_lots / lot_step) * lot_step
        lots = round(lots, 2)

        # Clamp to broker limits
        lots = max(min_lot, min(lots, max_lot))

        return lots

    # ── Trailing stop helper ──────────────────────────────────────────────────

    def trail_stop(
        self,
        direction:   str,
        current_sl:  float,
        current_price: float,
        atr:         float,
        atr_mult:    float = 1.5,
    ) -> Optional[float]:
        """
        Calculate a new trailing stop level.
        Returns new SL if it improves the position, otherwise None.

        ATR-based trail: move SL to price ± (ATR × multiplier)
        """
        if direction == "BUY":
            new_sl = current_price - atr * atr_mult
            if new_sl > current_sl:
                return round(new_sl, 5)
        elif direction == "SELL":
            new_sl = current_price + atr * atr_mult
            if new_sl < current_sl:
                return round(new_sl, 5)
        return None

    # ── Status ───────────────────────────────────────────────────────────────

    def is_halted(self) -> bool:
        return self._halted

    def get_status(self, balance: float, equity: float) -> dict:
        """Return a snapshot of current risk state."""
        self._reset_daily_if_needed(balance)
        daily_loss = 0.0
        if self._daily_start_balance and self._daily_start_balance > 0:
            daily_loss = (self._daily_start_balance - balance) / self._daily_start_balance

        drawdown = 0.0
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity

        return {
            "halted":            self._halted,
            "halt_reason":       self._halt_reason,
            "peak_equity":       self._peak_equity,
            "current_drawdown":  round(drawdown * 100, 2),
            "max_drawdown_limit": round(self.max_drawdown * 100, 2),
            "daily_loss_pct":    round(daily_loss * 100, 2),
            "daily_loss_limit":  round(self.max_daily_loss * 100, 2),
            "risk_per_trade":    round(self.risk_pct * 100, 2),
            "max_open_trades":   self.max_trades,
        }

    def resume(self) -> None:
        """Manually resume a halted bot (use with caution)."""
        self._halted = False
        self._halt_reason = ""
        logger.warning("Bot manually resumed by operator.")
