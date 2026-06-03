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


def compute_vwap(df: pd.DataFrame, market_tz: str = "America/New_York") -> pd.DataFrame:
    """Intraday VWAP — resets each session. Requires intraday bars.

    The cumulative sums are grouped by local session date so VWAP stays correct
    even when the DataFrame spans multiple days (as it now does, since intraday
    bars are fetched over a multi-day window).
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical * df["volume"]
    idx = df.index
    if getattr(idx, "tz", None) is not None:
        session = idx.tz_convert(market_tz).date
    else:
        session = idx.date
    df["vwap"] = pv.groupby(session).cumsum() / df["volume"].groupby(session).cumsum()
    return df


def compute_relative_volume(df: pd.DataFrame, avg_volume: float) -> pd.DataFrame:
    """Legacy per-bar relative volume: today's cumulative volume vs the 20-day
    average daily volume. Retained for backward compatibility; the open-market
    agent now uses time_of_day_rvol() instead, which is feed-agnostic and
    time-of-day aware. See that function for why this definition was replaced.
    """
    df["rel_vol"] = df["volume"].cumsum() / avg_volume
    return df


def time_of_day_rvol(
    df: pd.DataFrame,
    lookback_days: int = 14,
    market_tz: str = "America/New_York",
):
    """Time-of-day relative volume (RVOL).

    RVOL = today's cumulative volume up to the latest bar, divided by the
    average cumulative volume up to that *same time of day* over the prior
    ``lookback_days`` trading days.

    Both the numerator and the denominator are drawn from the same intraday
    feed, so the ratio is feed-agnostic — unlike comparing an intraday volume
    sum against a full-day average (the old definition), which read structurally
    low on the partial/IEX feed and rejected nearly every liquid name.

    Expects a multi-day intraday bar DataFrame with a tz-aware DatetimeIndex and
    a ``volume`` column. Returns a float, or ``None`` if there is not enough
    history to form a baseline (in which case the caller's entry gate fails
    closed, which is the safe outcome).
    """
    if df is None or df.empty or "volume" not in df.columns:
        return None

    idx = df.index
    if getattr(idx, "tz", None) is None:
        idx = idx.tz_localize("UTC")
    local = idx.tz_convert(market_tz)
    minutes = local.hour * 60 + local.minute
    # regular trading hours only (09:30–16:00 ET) so the baseline is comparable
    rth = (minutes >= 9 * 60 + 30) & (minutes < 16 * 60)

    work = pd.DataFrame({
        "date": local.date,
        "tod": minutes,
        "vol": df["volume"].to_numpy(dtype="float64"),
    })
    work = work[rth & (work["vol"] > 0)]
    if work.empty:
        return None

    days = sorted(work["date"].unique())
    if len(days) < 2:
        return None

    today = days[-1]
    today_rows = work[work["date"] == today]
    cutoff = int(today_rows["tod"].max())  # latest time-of-day we have today
    today_cum = float(today_rows.loc[today_rows["tod"] <= cutoff, "vol"].sum())

    prior_cums = []
    for d in days[:-1][-lookback_days:]:
        c = float(work.loc[(work["date"] == d) & (work["tod"] <= cutoff), "vol"].sum())
        if c > 0:
            prior_cums.append(c)
    if not prior_cums:
        return None

    baseline = sum(prior_cums) / len(prior_cums)
    if baseline <= 0:
        return None
    return round(today_cum / baseline, 4)


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
