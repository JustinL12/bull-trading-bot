"""Pure technical indicator functions operating on pandas DataFrames.

All functions expect a DataFrame with columns: open, high, low, close, volume.
Index should be a DatetimeTzAware index (as returned by Alpaca bar data).
Returns are added as new columns; the DataFrame is returned for chaining.
"""

import numpy as np
import pandas as pd


def compute_ema(df: pd.DataFrame, period: int, col: str = "close") -> pd.DataFrame:
    df[f"ema_{period}"] = df[col].ewm(span=period, adjust=False).mean()
    return df


def compute_rsi(df: pd.DataFrame, period: int = 14, col: str = "close") -> pd.DataFrame:
    delta = df[col].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    # pure uptrend: avg_loss==0 → rs=NaN → set RSI=100 where we have valid gain data
    df["rsi"] = rsi.where(~((avg_loss == 0) & avg_gain.notna()), 100.0)
    return df


def compute_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    col: str = "close",
) -> pd.DataFrame:
    ema_fast = df[col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[col].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.ewm(com=period - 1, min_periods=period).mean()
    return df


def compute_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Intraday VWAP — resets daily. Requires intraday bars."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (typical * df["volume"]).cumsum() / df["volume"].cumsum()
    return df


def compute_relative_volume(df: pd.DataFrame, avg_volume: float) -> pd.DataFrame:
    """Ratio of today's cumulative volume vs the 20-day average daily volume."""
    df["rel_vol"] = df["volume"].cumsum() / avg_volume
    return df


def macd_histogram_rising(df: pd.DataFrame, bars: int = 2) -> bool:
    """Returns True if macd_hist has been rising for the last `bars` consecutive bars."""
    if "macd_hist" not in df.columns or len(df) < bars + 1:
        return False
    recent = df["macd_hist"].iloc[-(bars + 1):]
    return all(recent.iloc[i] < recent.iloc[i + 1] for i in range(bars))


def apply_all_intraday(df: pd.DataFrame, avg_volume: float) -> pd.DataFrame:
    """Apply all intraday indicators in one call."""
    df = df.copy()
    df = df.ffill()  # fill any missing bars before computing indicators
    compute_ema(df, 9)
    compute_ema(df, 21)
    compute_rsi(df)
    compute_macd(df)
    compute_atr(df)
    compute_vwap(df)
    compute_relative_volume(df, avg_volume)
    return df


def latest(df: pd.DataFrame) -> dict:
    """Return the most recent bar's indicator values as a plain dict."""
    row = df.iloc[-1]
    result = {}
    for col in ["close", "ema_9", "ema_21", "rsi", "macd", "macd_signal", "macd_hist", "atr", "vwap", "rel_vol"]:
        if col in df.columns:
            result[col] = round(float(row[col]), 4) if not pd.isna(row[col]) else None
    result["macd_hist_rising"] = macd_histogram_rising(df)
    return result
