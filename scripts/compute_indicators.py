"""Compute all intraday indicators for a list of symbols and write to data/indicators.json.

Usage:
    python scripts/compute_indicators.py --symbols AAPL,NVDA,TSLA
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.alpaca_client import get_data_client
from lib.indicators import apply_all_intraday, latest, time_of_day_rvol
from lib.notify import post_attention
from lib.state import read_json, write_json
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame


def fetch_5min_bars(client, symbol: str, lookback_days: int) -> pd.DataFrame:
    """Fetch recent intraday bars, end-anchored at *now*.

    We deliberately do NOT pass ``limit``: Alpaca caps a limited request to the
    OLDEST bars in the window, which used to return days-stale bars for liquid
    names (and silently fed stale prices into RSI/EMA/MACD). Fetching the full
    window keeps the most recent bar — including the current session — present.
    The window also spans multiple days so time_of_day_rvol() has prior sessions
    to baseline against.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        feed="iex",
    )
    bars = client.get_stock_bars(req)
    df = bars.df
    if df.empty:
        return df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    return df.rename(columns=str.lower)


def fetch_daily_bars(client, symbol: str, limit: int) -> pd.DataFrame:
    """Fetch the most recent ``limit`` daily bars, end-anchored at *now*.

    As with the intraday fetch, we avoid the ``limit`` request param (which
    returns the oldest bars in the range) and instead pull a wide window and
    keep the tail, so EMA-200 and the latest close are computed on current data.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=limit * 2)
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        feed="iex",
    )
    bars = client.get_stock_bars(req)
    df = bars.df
    if df.empty:
        return df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    return df.rename(columns=str.lower).tail(limit)


def get_avg_volume(daily_df: pd.DataFrame, days: int = 20) -> float:
    if len(daily_df) < days:
        return float(daily_df["volume"].mean())
    return float(daily_df["volume"].iloc[-days:].mean())


def compute_for_symbol(client, symbol: str) -> dict:
    try:
        intraday_df = fetch_5min_bars(client, symbol, config.INDICATOR_INTRADAY_LOOKBACK_DAYS)
        daily_df = fetch_daily_bars(client, symbol, config.INDICATOR_BAR_LIMIT_DAILY)

        if intraday_df.empty:
            return {"symbol": symbol, "error": "no intraday bars"}

        avg_vol = get_avg_volume(daily_df)
        ind_df = apply_all_intraday(intraday_df, avg_vol)

        vals = latest(ind_df)
        vals["symbol"] = symbol
        vals["avg_volume_20d"] = round(avg_vol, 0)

        # Relative volume: time-of-day RVOL (today so far vs. the average for this
        # same time of day over prior sessions). Overrides the legacy per-bar
        # rel_vol that latest() copies from the indicator frame.
        vals["rel_vol"] = time_of_day_rvol(intraday_df, config.RVOL_LOOKBACK_DAYS)

        # EMA-200 on daily bars
        if len(daily_df) >= 20:
            daily_df["ema_200"] = daily_df["close"].ewm(span=200, adjust=False).mean()
            vals["ema_200_daily"] = round(float(daily_df["ema_200"].iloc[-1]), 4)
        else:
            vals["ema_200_daily"] = None

        # ATR as % of price
        if vals.get("atr") and vals.get("close"):
            vals["atr_pct"] = round(vals["atr"] / vals["close"] * 100, 3)

        return vals

    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True, help="Comma-separated symbol list")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    client = get_data_client()

    results = {}
    for symbol in symbols:
        print(f"  Computing indicators for {symbol}...")
        results[symbol] = compute_for_symbol(client, symbol)

    positions = read_json("positions.json", default={})
    for symbol, result in results.items():
        if "error" in result and symbol in positions:
            post_attention(
                f"Indicator Compute Failed: {symbol}",
                f"compute_for_symbol() failed for {symbol}, which has an open position.\n"
                f"Error: {result['error']}\n"
                f"Exit decisions for this symbol may be unreliable.",
                level="warning",
            )

    write_json("indicators.json", results)
    print(f"Indicators written for {len(results)} symbols.")
    return results


if __name__ == "__main__":
    main()
