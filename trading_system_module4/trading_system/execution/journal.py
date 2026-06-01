"""
journal.py — Trade journal.

Logs every order open/close to:
  - In-memory list (for dashboard and stats)
  - CSV file (persistent, survives restarts)

Also computes running P&L stats.
"""

import csv
import os
import logging
import pandas as pd
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    ticket:      int
    symbol:      str
    direction:   str
    volume:      float
    open_price:  float
    close_price: float  = 0.0
    sl:          float  = 0.0
    tp:          float  = 0.0
    profit:      float  = 0.0
    swap:        float  = 0.0
    commission:  float  = 0.0
    open_time:   str    = ""
    close_time:  str    = ""
    status:      str    = "OPEN"   # OPEN | CLOSED | SL_HIT | TP_HIT
    comment:     str    = ""

    @property
    def net_profit(self) -> float:
        return round(self.profit + self.swap + self.commission, 2)


class TradeJournal:
    """Persistent trade log with in-memory stats."""

    def __init__(self, csv_path: str = "logs/trades.csv"):
        self.csv_path = csv_path
        self._trades: dict[int, TradeRecord] = {}
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        self._init_csv()
        self._load_existing()

    def _init_csv(self):
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(TradeRecord.__dataclass_fields__.keys()))
                w.writeheader()

    def _load_existing(self):
        """Load any existing trades from the CSV on startup."""
        try:
            df = pd.read_csv(self.csv_path)
            for _, row in df.iterrows():
                rec = TradeRecord(**{k: row[k] for k in TradeRecord.__dataclass_fields__})
                self._trades[rec.ticket] = rec
            if self._trades:
                logger.info(f"Journal loaded {len(self._trades)} existing trades from {self.csv_path}")
        except Exception:
            pass

    def _write_row(self, record: TradeRecord):
        """Append or overwrite a row in the CSV."""
        # Rewrite full CSV (ensures updates to existing rows are reflected)
        rows = list(self._trades.values())
        with open(self.csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(TradeRecord.__dataclass_fields__.keys()))
            w.writeheader()
            for r in rows:
                w.writerow(asdict(r))

    # ── Public API ───────────────────────────────────────────────────────────

    def log_open(
        self,
        ticket:     int,
        symbol:     str,
        direction:  str,
        volume:     float,
        open_price: float,
        sl:         float,
        tp:         float,
        comment:    str = "",
    ) -> None:
        """Record a newly opened trade."""
        rec = TradeRecord(
            ticket=ticket, symbol=symbol, direction=direction,
            volume=volume, open_price=open_price, sl=sl, tp=tp,
            open_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            comment=comment, status="OPEN",
        )
        self._trades[ticket] = rec
        self._write_row(rec)
        logger.info(f"Journal: OPEN #{ticket} {symbol} {direction} {volume} @ {open_price}")

    def log_close(
        self,
        ticket:      int,
        close_price: float,
        profit:      float,
        swap:        float       = 0.0,
        commission:  float       = 0.0,
        status:      str         = "CLOSED",
    ) -> None:
        """Update an existing trade record when it closes."""
        if ticket not in self._trades:
            logger.warning(f"Journal: close called for unknown ticket #{ticket}")
            return
        rec = self._trades[ticket]
        rec.close_price = close_price
        rec.profit      = profit
        rec.swap        = swap
        rec.commission  = commission
        rec.close_time  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rec.status      = status
        self._write_row(rec)
        logger.info(
            f"Journal: CLOSE #{ticket} {rec.symbol} | "
            f"P&L: {rec.net_profit:+.2f} | Status: {status}"
        )

    def get_open_trades(self) -> list[TradeRecord]:
        return [t for t in self._trades.values() if t.status == "OPEN"]

    def get_closed_trades(self) -> list[TradeRecord]:
        return [t for t in self._trades.values() if t.status != "OPEN"]

    # ── Stats ────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Compute performance statistics from closed trades."""
        closed = self.get_closed_trades()
        if not closed:
            return {"message": "No closed trades yet."}

        profits = [t.net_profit for t in closed]
        winners = [p for p in profits if p > 0]
        losers  = [p for p in profits if p <= 0]

        total_pnl    = round(sum(profits), 2)
        win_rate     = round(len(winners) / len(profits) * 100, 1) if profits else 0
        avg_win      = round(sum(winners) / len(winners), 2) if winners else 0
        avg_loss     = round(sum(losers)  / len(losers),  2) if losers  else 0
        profit_factor = round(abs(sum(winners) / sum(losers)), 2) if sum(losers) != 0 else float("inf")

        # Max drawdown on equity curve
        equity_curve = pd.Series(profits).cumsum()
        roll_max     = equity_curve.cummax()
        drawdown     = equity_curve - roll_max
        max_dd       = round(drawdown.min(), 2)

        # Sharpe (simplified, daily returns assumed)
        import numpy as np
        pnl_series = pd.Series(profits)
        sharpe = round(
            pnl_series.mean() / pnl_series.std() * (252 ** 0.5), 2
        ) if pnl_series.std() > 0 else 0.0

        return {
            "total_trades":   len(closed),
            "winners":        len(winners),
            "losers":         len(losers),
            "win_rate":       f"{win_rate}%",
            "total_pnl":      f"${total_pnl:+.2f}",
            "avg_win":        f"${avg_win:.2f}",
            "avg_loss":       f"${avg_loss:.2f}",
            "profit_factor":  profit_factor,
            "max_drawdown":   f"${max_dd:.2f}",
            "sharpe_ratio":   sharpe,
        }

    def print_stats(self) -> None:
        stats = self.get_stats()
        print("\n" + "─"*40)
        print("  TRADE JOURNAL STATS")
        print("─"*40)
        for k, v in stats.items():
            print(f"  {k:<20}: {v}")
        print("─"*40 + "\n")
