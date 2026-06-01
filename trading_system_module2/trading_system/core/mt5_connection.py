"""
MT5 Connection Module
Handles connection, reconnection, and all data retrieval from MetaTrader 5.
"""

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from typing import Optional
import logging
import time

logger = logging.getLogger(__name__)


# ─── Timeframe map ────────────────────────────────────────────────────────────
TIMEFRAMES = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
}


# ─── Connection ───────────────────────────────────────────────────────────────

def connect(
    login: int,
    password: str,
    server: str,
    path: Optional[str] = None,
    retries: int = 3,
    retry_delay: float = 5.0,
) -> bool:
    """
    Initialize and log in to MetaTrader 5.

    Args:
        login:       MT5 account number
        password:    MT5 account password
        server:      Broker server name (e.g. 'ICMarkets-Demo')
        path:        Optional path to terminal64.exe
        retries:     Number of connection attempts before giving up
        retry_delay: Seconds between retries

    Returns:
        True if connected successfully, False otherwise
    """
    init_kwargs = {"login": login, "password": password, "server": server}
    if path:
        init_kwargs["path"] = path

    for attempt in range(1, retries + 1):
        logger.info(f"Connecting to MT5 (attempt {attempt}/{retries})...")
        if mt5.initialize(**init_kwargs):
            info = mt5.account_info()
            logger.info(
                f"Connected | Account: {info.login} | "
                f"Balance: {info.balance} {info.currency} | "
                f"Server: {info.server}"
            )
            return True

        err = mt5.last_error()
        logger.warning(f"MT5 init failed: {err}")
        if attempt < retries:
            time.sleep(retry_delay)

    logger.error("Could not connect to MT5 after all retries.")
    return False


def disconnect() -> None:
    """Cleanly shut down the MT5 connection."""
    mt5.shutdown()
    logger.info("MT5 connection closed.")


def is_connected() -> bool:
    """Return True if terminal is currently connected."""
    return mt5.terminal_info() is not None


def ensure_connected(login: int, password: str, server: str) -> bool:
    """Re-connect only if the terminal is not currently live."""
    if is_connected():
        return True
    logger.warning("MT5 not connected — attempting reconnect...")
    return connect(login, password, server)


# ─── Symbol helpers ───────────────────────────────────────────────────────────

def get_symbols(market: Optional[str] = None) -> list[str]:
    """
    Return available symbol names, optionally filtered by market group.

    market examples: 'Forex', 'Crypto', 'Stocks', 'Commodities'
    """
    symbols = mt5.symbols_get()
    if symbols is None:
        return []
    names = [s.name for s in symbols if s.visible]
    if market:
        names = [n for n in names if market.lower() in n.lower()]
    return names


def get_symbol_info(symbol: str) -> Optional[dict]:
    """Return key specification fields for a symbol."""
    info = mt5.symbol_info(symbol)
    if info is None:
        logger.warning(f"Symbol not found: {symbol}")
        return None
    return {
        "symbol":      info.name,
        "description": info.description,
        "digits":      info.digits,
        "point":       info.point,
        "spread":      info.spread,
        "trade_mode":  info.trade_mode,
        "min_lot":     info.volume_min,
        "max_lot":     info.volume_max,
        "lot_step":    info.volume_step,
        "contract_sz": info.trade_contract_size,
    }


# ─── OHLCV data ───────────────────────────────────────────────────────────────

def get_ohlcv(
    symbol: str,
    timeframe: str = "H1",
    bars: int = 500,
    from_date: Optional[datetime] = None,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV bars from MT5 and return as a clean DataFrame.

    Args:
        symbol:    e.g. 'EURUSD', 'BTCUSD', 'XAUUSD'
        timeframe: one of TIMEFRAMES keys ('H1', 'H4', etc.)
        bars:      number of bars to fetch (used when from_date is None)
        from_date: if set, fetch from this date forward

    Returns:
        DataFrame with columns: time, open, high, low, close, volume
        or None on failure.
    """
    tf = TIMEFRAMES.get(timeframe.upper())
    if tf is None:
        logger.error(f"Unknown timeframe: {timeframe}. Use one of {list(TIMEFRAMES)}")
        return None

    # Ensure symbol is available
    if not mt5.symbol_select(symbol, True):
        logger.warning(f"Could not select symbol: {symbol}")

    if from_date:
        rates = mt5.copy_rates_from(symbol, tf, from_date, bars)
    else:
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)

    if rates is None or len(rates) == 0:
        logger.warning(f"No data returned for {symbol} {timeframe}")
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    df = df[["time", "open", "high", "low", "close", "volume"]].copy()
    df.set_index("time", inplace=True)
    return df


def get_multi_ohlcv(
    symbols: list[str],
    timeframe: str = "H1",
    bars: int = 500,
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV for multiple symbols in one call.

    Returns:
        Dict mapping symbol -> DataFrame (skips failed symbols)
    """
    result = {}
    for sym in symbols:
        df = get_ohlcv(sym, timeframe, bars)
        if df is not None:
            result[sym] = df
        else:
            logger.warning(f"Skipped {sym} — no data.")
    logger.info(f"Fetched data for {len(result)}/{len(symbols)} symbols.")
    return result


# ─── Live tick ────────────────────────────────────────────────────────────────

def get_tick(symbol: str) -> Optional[dict]:
    """Return the latest bid/ask tick for a symbol."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return {
        "symbol": symbol,
        "time":   datetime.fromtimestamp(tick.time),
        "bid":    tick.bid,
        "ask":    tick.ask,
        "spread": round((tick.ask - tick.bid) / mt5.symbol_info(symbol).point, 1),
    }


def get_ticks(symbols: list[str]) -> dict[str, dict]:
    """Return latest ticks for a list of symbols."""
    return {s: get_tick(s) for s in symbols if get_tick(s)}


# ─── Account snapshot ─────────────────────────────────────────────────────────

def get_account_info() -> Optional[dict]:
    """Return current account balance, equity, margin, and free margin."""
    info = mt5.account_info()
    if info is None:
        return None
    return {
        "login":       info.login,
        "balance":     info.balance,
        "equity":      info.equity,
        "margin":      info.margin,
        "free_margin": info.margin_free,
        "margin_pct":  round(info.margin_level, 2) if info.margin_level else 0.0,
        "currency":    info.currency,
        "leverage":    info.leverage,
    }


def get_open_positions(symbol: Optional[str] = None) -> list[dict]:
    """
    Return all open positions, optionally filtered by symbol.
    """
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if not positions:
        return []
    return [
        {
            "ticket":     p.ticket,
            "symbol":     p.symbol,
            "type":       "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
            "volume":     p.volume,
            "open_price": p.price_open,
            "sl":         p.sl,
            "tp":         p.tp,
            "profit":     p.profit,
            "open_time":  datetime.fromtimestamp(p.time),
            "comment":    p.comment,
        }
        for p in positions
    ]


def get_trade_history(from_date: datetime, to_date: Optional[datetime] = None) -> pd.DataFrame:
    """
    Pull closed trade history between two dates.

    Returns a DataFrame with columns: ticket, symbol, type, volume,
    open_price, close_price, profit, swap, commission, open_time, close_time.
    """
    to_date = to_date or datetime.now()
    deals = mt5.history_deals_get(from_date, to_date)
    if not deals:
        return pd.DataFrame()

    rows = []
    for d in deals:
        if d.entry == mt5.DEAL_ENTRY_OUT:   # closed trades only
            rows.append({
                "ticket":      d.ticket,
                "symbol":      d.symbol,
                "type":        "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
                "volume":      d.volume,
                "price":       d.price,
                "profit":      d.profit,
                "swap":        d.swap,
                "commission":  d.commission,
                "time":        datetime.fromtimestamp(d.time),
                "comment":     d.comment,
            })

    return pd.DataFrame(rows)
