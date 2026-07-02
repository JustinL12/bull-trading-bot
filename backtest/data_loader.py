"""Historical OHLCV data loader with parquet cache.

Fetches daily bars from yfinance and caches them locally so repeated backtest
runs don't hammer the API. Cache is keyed by ticker; stale entries (older than
the requested end date) are refreshed automatically.
"""

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker.upper()}.parquet"


def fetch_history(
    ticker: str,
    start: str,
    end: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return daily OHLCV DataFrame for ticker between start and end (inclusive).

    Columns: open, high, low, close, volume (lowercase).
    Index: DatetimeIndex (UTC-normalised, tz-naive for simplicity).
    Returns empty DataFrame if ticker is delisted or has no data.
    """
    path = _cache_path(ticker)
    end_dt = pd.Timestamp(end)

    if not force_refresh and path.exists():
        cached = pd.read_parquet(path)
        if not cached.empty and cached.index[-1] >= end_dt - pd.Timedelta(days=5):
            mask = (cached.index >= pd.Timestamp(start)) & (cached.index <= end_dt)
            return cached.loc[mask]

    try:
        raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False, threads=False)
    except Exception:
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    # yfinance returns MultiIndex columns when downloading a single ticker with
    # some versions; flatten if needed.
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.dropna(subset=["close"])

    df.to_parquet(path)

    mask = (df.index >= pd.Timestamp(start)) & (df.index <= end_dt)
    return df.loc[mask]


def load_universe_history(
    tickers: list[str],
    start: str,
    end: str,
    min_rows: int = 60,
) -> dict[str, pd.DataFrame]:
    """Fetch history for a list of tickers, skipping any with insufficient data.

    Returns dict mapping ticker → DataFrame. Prints progress to stdout.
    """
    result = {}
    total = len(tickers)
    for i, ticker in enumerate(tickers, 1):
        if i % 50 == 0 or i == total:
            print(f"  Loading history: {i}/{total}", end="\r")
        df = fetch_history(ticker, start, end)
        if len(df) >= min_rows:
            result[ticker] = df
    print()
    return result
