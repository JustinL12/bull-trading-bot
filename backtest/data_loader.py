"""Historical OHLCV data loader with parquet cache.

Fetches daily bars from Alpaca and caches them locally so repeated backtest
runs don't hammer the API. Cache is keyed by ticker; stale entries (older than
the requested end date) are refreshed automatically.

Replaces the previous yfinance implementation — yfinance's Yahoo endpoint is
blocked from cloud/CI IPs (see scripts/get_vix.py for the same issue).
"""

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from alpaca.data import StockBarsRequest, StockHistoricalDataClient, TimeFrame
from alpaca.data.enums import Adjustment

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# Module-level client — created once so load_universe_history doesn't
# re-initialise for every ticker.
_client: StockHistoricalDataClient | None = None


def _get_client() -> StockHistoricalDataClient:
    global _client
    if _client is None:
        _client = StockHistoricalDataClient(
            api_key=os.environ["ALPACA_API_KEY"],
            secret_key=os.environ["ALPACA_SECRET_KEY"],
        )
    return _client


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
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            start=pd.Timestamp(start, tz="UTC"),
            end=pd.Timestamp(end, tz="UTC"),
            timeframe=TimeFrame.Day,
            adjustment=Adjustment.ALL,
        )
        raw = _get_client().get_stock_bars(req).df
    except Exception:
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    # Alpaca returns a MultiIndex (symbol, timestamp); drop the symbol level.
    df = raw.droplevel("symbol")[["open", "high", "low", "close", "volume"]].copy()

    # Convert tz-aware UTC timestamps to tz-naive (matches prior yfinance behaviour).
    df.index = df.index.tz_convert(None)
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
