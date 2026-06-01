"""
signals.py — Trend-following signal generation.

Strategy logic:
  - Primary timeframe (H1): entry signals
  - Higher timeframe (H4):  trend filter (only trade in the direction of H4 trend)

LONG signal conditions (all must be true):
  1. H4 trend filter: price above EMA200 on H4
  2. H1 EMA fast (20) crosses above EMA slow (50)
  3. Price is above EMA trend (200) on H1
  4. MACD histogram turns positive (momentum confirmation)
  5. RSI between 40–70 (not overbought, has room to run)

SHORT signal conditions (mirror of above):
  1. H4 trend filter: price below EMA200 on H4
  2. H1 EMA fast crosses below EMA slow
  3. Price below EMA trend on H1
  4. MACD histogram turns negative
  5. RSI between 30–60 (not oversold)
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
from .indicators import add_all_indicators, ema


# ─── Signal dataclass ─────────────────────────────────────────────────────────

@dataclass
class Signal:
    symbol:     str
    direction:  str          # "BUY" | "SELL" | "NONE"
    entry:      float = 0.0
    sl:         float = 0.0
    tp:         float = 0.0
    rr_ratio:   float = 0.0
    atr:        float = 0.0
    timeframe:  str   = "H1"
    reasons:    list  = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.direction in ("BUY", "SELL")

    def __str__(self):
        if not self.is_valid:
            return f"[{self.symbol}] No signal"
        return (
            f"[{self.symbol}] {self.direction} | "
            f"Entry: {self.entry:.5f} | SL: {self.sl:.5f} | TP: {self.tp:.5f} | "
            f"R:R {self.rr_ratio:.2f} | Reasons: {', '.join(self.reasons)}"
        )


# ─── Strategy class ───────────────────────────────────────────────────────────

class TrendFollowingStrategy:
    """
    Multi-timeframe trend-following strategy.
    Uses H4 for direction bias and H1 for precise entry.
    """

    def __init__(self, config: dict):
        """
        config keys (from core/config.py):
            EMA_FAST, EMA_SLOW, EMA_TREND, ATR_PERIOD,
            ATR_SL_MULT, ATR_TP_MULT, MIN_RR_RATIO
        """
        self.cfg = {
            "ema_fast":    config.get("EMA_FAST",    20),
            "ema_slow":    config.get("EMA_SLOW",    50),
            "ema_trend":   config.get("EMA_TREND",  200),
            "atr_period":  config.get("ATR_PERIOD",  14),
            "atr_sl_mult": config.get("ATR_SL_MULT", 1.5),
            "atr_tp_mult": config.get("ATR_TP_MULT", 2.5),
            "min_rr":      config.get("MIN_RR_RATIO", 1.5),
        }

    # ── Trend filter (H4) ────────────────────────────────────────────────────

    def _trend_direction(self, df_h4: pd.DataFrame) -> str:
        """
        Determine H4 bias.
        Returns 'BULL', 'BEAR', or 'NEUTRAL'.
        """
        if len(df_h4) < self.cfg["ema_trend"] + 5:
            return "NEUTRAL"

        df = add_all_indicators(df_h4, self.cfg)
        last = df.iloc[-1]

        if last["close"] > last["ema_trend"] and last["ema_fast"] > last["ema_slow"]:
            return "BULL"
        if last["close"] < last["ema_trend"] and last["ema_fast"] < last["ema_slow"]:
            return "BEAR"
        return "NEUTRAL"

    # ── Entry signal (H1) ────────────────────────────────────────────────────

    def generate_signal(
        self,
        symbol: str,
        df_h1: pd.DataFrame,
        df_h4: pd.DataFrame,
    ) -> Signal:
        """
        Evaluate both timeframes and return a Signal.

        Args:
            symbol: instrument name
            df_h1:  H1 OHLCV DataFrame (from mt5_connection.get_ohlcv)
            df_h4:  H4 OHLCV DataFrame (trend filter)

        Returns:
            Signal object (check signal.is_valid before acting)
        """
        no_signal = Signal(symbol=symbol, direction="NONE")

        # Need enough bars
        min_bars = self.cfg["ema_trend"] + 10
        if len(df_h1) < min_bars or len(df_h4) < min_bars:
            no_signal.reasons = ["Insufficient bars"]
            return no_signal

        # Attach indicators
        df = add_all_indicators(df_h1, self.cfg)
        if len(df) < 3:
            return no_signal

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # H4 trend bias
        bias = self._trend_direction(df_h4)
        if bias == "NEUTRAL":
            no_signal.reasons = ["H4 trend neutral — no trade"]
            return no_signal

        atr_val = curr["atr"]
        entry   = curr["close"]

        # ── Check LONG conditions ─────────────────────────────────────────
        if bias == "BULL":
            reasons = []

            ema_cross = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]
            above_trend = curr["close"] > curr["ema_trend"]
            macd_pos = curr["macd_hist"] > 0 and prev["macd_hist"] <= 0
            rsi_ok   = 40 <= curr["rsi"] <= 70

            if ema_cross:     reasons.append("EMA20 crossed above EMA50")
            if above_trend:   reasons.append("Price above EMA200")
            if macd_pos:      reasons.append("MACD histogram turned positive")
            if rsi_ok:        reasons.append(f"RSI={curr['rsi']:.1f} in valid range")

            if ema_cross and above_trend and macd_pos and rsi_ok:
                sl = entry - atr_val * self.cfg["atr_sl_mult"]
                tp = entry + atr_val * self.cfg["atr_tp_mult"]
                rr = (tp - entry) / (entry - sl) if entry != sl else 0

                if rr >= self.cfg["min_rr"]:
                    return Signal(
                        symbol=symbol, direction="BUY",
                        entry=round(entry, 5), sl=round(sl, 5), tp=round(tp, 5),
                        rr_ratio=round(rr, 2), atr=round(atr_val, 5),
                        timeframe="H1", reasons=reasons,
                    )

        # ── Check SHORT conditions ────────────────────────────────────────
        if bias == "BEAR":
            reasons = []

            ema_cross    = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]
            below_trend  = curr["close"] < curr["ema_trend"]
            macd_neg     = curr["macd_hist"] < 0 and prev["macd_hist"] >= 0
            rsi_ok       = 30 <= curr["rsi"] <= 60

            if ema_cross:    reasons.append("EMA20 crossed below EMA50")
            if below_trend:  reasons.append("Price below EMA200")
            if macd_neg:     reasons.append("MACD histogram turned negative")
            if rsi_ok:       reasons.append(f"RSI={curr['rsi']:.1f} in valid range")

            if ema_cross and below_trend and macd_neg and rsi_ok:
                sl = entry + atr_val * self.cfg["atr_sl_mult"]
                tp = entry - atr_val * self.cfg["atr_tp_mult"]
                rr = (entry - tp) / (sl - entry) if sl != entry else 0

                if rr >= self.cfg["min_rr"]:
                    return Signal(
                        symbol=symbol, direction="SELL",
                        entry=round(entry, 5), sl=round(sl, 5), tp=round(tp, 5),
                        rr_ratio=round(rr, 2), atr=round(atr_val, 5),
                        timeframe="H1", reasons=reasons,
                    )

        no_signal.reasons = [f"H4={bias} but H1 entry conditions not met"]
        return no_signal

    # ── Scanner: run across all symbols ─────────────────────────────────────

    def scan(
        self,
        data_h1: dict[str, pd.DataFrame],
        data_h4: dict[str, pd.DataFrame],
    ) -> list[Signal]:
        """
        Scan all symbols and return a list of valid signals.

        Args:
            data_h1: dict of symbol -> H1 DataFrame
            data_h4: dict of symbol -> H4 DataFrame

        Returns:
            List of Signal objects where signal.is_valid == True
        """
        signals = []
        for symbol in data_h1:
            if symbol not in data_h4:
                continue
            sig = self.generate_signal(symbol, data_h1[symbol], data_h4[symbol])
            if sig.is_valid:
                signals.append(sig)
        return signals
