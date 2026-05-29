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
from lib.indicators import apply_all_intraday, latest
from lib.state import read_json, write_json
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame


def fetch_5min_bars(client, symbol: str, limit: int) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=5)  # pull enough history for indicators
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        limit=limit,
        feed="iex",
    )
    bars = client.get_stock_bars(req)
    df = bars.df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    return df.rename(columns=str.lower)


def fetch_daily_bars(client, symbol: str, limit: int) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=limit * 2)
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        limit=limit,
        feed="iex",
    )
    bars = client.get_stock_bars(req)
    df = bars.df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    return df.rename(columns=str.lower)


def get_avg_volume(daily_df: pd.DataFrame, days: int = 20) -> float:
    if len(daily_df) < days:
        return float(daily_df["volume"].mean())
    return float(daily_df["volume"].iloc[-days:].mean())


def compute_for_symbol(client, symbol: str) -> dict:
    try:
        intraday_df = fetch_5min_bars(client, symbol, config.INDICATOR_BAR_LIMIT_5MIN)
        daily_df = fetch_daily_bars(client, symbol, config.INDICATOR_BAR_LIMIT_DAILY)

        if intraday_df.empty:
            return {"symbol": symbol, "error": "no intraday bars"}

        avg_vol = get_avg_volume(daily_df)
        intraday_df = apply_all_intraday(intraday_df, avg_vol)

        vals = latest(intraday_df)
        vals["symbol"] = symbol
        vals["avg_volume_20d"] = round(avg_vol, 0)

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

    write_json("indicators.json", results)
    print(f"Indicators written for {len(results)} symbols.")
    return results


if __name__ == "__main__":
    main()
