"""
indicators.py — Technical indicators for the trend-following strategy.
All functions take a DataFrame with OHLCV columns and return a Series or DataFrame.
"""

import pandas as pd
import numpy as np


# ─── Moving Averages ──────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


# ─── ATR ──────────────────────────────────────────────────────────────────────

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range.
    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    """
    high = df["high"]
    low  = df["low"]
    close = df["close"]

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()


# ─── RSI ──────────────────────────────────────────────────────────────────────

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (0–100)."""
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ─── MACD ─────────────────────────────────────────────────────────────────────

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """
    MACD indicator.
    Returns DataFrame with columns: macd, signal, histogram.
    """
    ema_fast   = ema(series, fast)
    ema_slow   = ema(series, slow)
    macd_line  = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return pd.DataFrame({
        "macd":      macd_line,
        "signal":    signal_line,
        "histogram": histogram,
    })


# ─── Bollinger Bands ──────────────────────────────────────────────────────────

def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """
    Bollinger Bands.
    Returns DataFrame with columns: upper, middle, lower, bandwidth, %b.
    """
    middle = sma(series, period)
    std    = series.rolling(window=period).std()
    upper  = middle + std_dev * std
    lower  = middle - std_dev * std
    bw     = (upper - lower) / middle
    pct_b  = (series - lower) / (upper - lower)
    return pd.DataFrame({
        "upper":     upper,
        "middle":    middle,
        "lower":     lower,
        "bandwidth": bw,
        "pct_b":     pct_b,
    })


# ─── Stochastic ───────────────────────────────────────────────────────────────

def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    """
    Stochastic oscillator.
    Returns DataFrame with columns: k, d.
    """
    low_min  = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    k = 100 * (df["close"] - low_min) / (high_max - low_min)
    d = k.rolling(d_period).mean()
    return pd.DataFrame({"k": k, "d": d})


# ─── Swing Highs / Lows ───────────────────────────────────────────────────────

def swing_highs(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """Returns True at bars that are swing highs (local maxima)."""
    highs = df["high"]
    return highs == highs.rolling(window=2 * lookback + 1, center=True).max()


def swing_lows(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """Returns True at bars that are swing lows (local minima)."""
    lows = df["low"]
    return lows == lows.rolling(window=2 * lookback + 1, center=True).min()


# ─── Utility ──────────────────────────────────────────────────────────────────

def higher_highs(df: pd.DataFrame, lookback: int = 5) -> bool:
    """True if the last two swing highs are ascending."""
    sh = df[swing_highs(df, lookback)]["high"]
    return len(sh) >= 2 and sh.iloc[-1] > sh.iloc[-2]


def higher_lows(df: pd.DataFrame, lookback: int = 5) -> bool:
    """True if the last two swing lows are ascending."""
    sl = df[swing_lows(df, lookback)]["low"]
    return len(sl) >= 2 and sl.iloc[-1] > sl.iloc[-2]


def lower_highs(df: pd.DataFrame, lookback: int = 5) -> bool:
    """True if the last two swing highs are descending."""
    sh = df[swing_highs(df, lookback)]["high"]
    return len(sh) >= 2 and sh.iloc[-1] < sh.iloc[-2]


def lower_lows(df: pd.DataFrame, lookback: int = 5) -> bool:
    """True if the last two swing lows are descending."""
    sl = df[swing_lows(df, lookback)]["low"]
    return len(sl) >= 2 and sl.iloc[-1] < sl.iloc[-2]


def add_all_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Attach all strategy indicators to a DataFrame in one call.
    config keys: ema_fast, ema_slow, ema_trend, atr_period
    """
    df = df.copy()
    close = df["close"]

    df["ema_fast"]  = ema(close, config.get("ema_fast",  20))
    df["ema_slow"]  = ema(close, config.get("ema_slow",  50))
    df["ema_trend"] = ema(close, config.get("ema_trend", 200))
    df["atr"]       = atr(df,   config.get("atr_period", 14))
    df["rsi"]       = rsi(close, 14)

    macd_df = macd(close)
    df["macd"]      = macd_df["macd"]
    df["macd_sig"]  = macd_df["signal"]
    df["macd_hist"] = macd_df["histogram"]

    return df.dropna()
