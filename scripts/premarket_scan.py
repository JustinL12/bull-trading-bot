"""Pre-market scanner: build a sentiment-driven watchlist.

Runs at 8:30 AM ET (before the open). Writes data/watchlist.json and
data/daily_context.json. Also checks for no-trade conditions and sets
data/no_trade_today.flag if needed.

The watchlist is built purely from Perplexity news/sentiment discovery. This
agent does NOT place orders and does NOT judge trade volume or technical
indicators — that is the 10:00 AM open-market agent's job. The only hard filter
applied here is the earnings blackout (a safety exclude). Price and volume are
attached to each entry for context only and are never used to drop a candidate.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.alpaca_client import get_data_client, get_trading_client
from lib.state import clear_flag, read_json, set_flag, write_json
from scripts.check_earnings import load_earnings_blacklist
from scripts.compute_indicators import fetch_daily_bars, get_avg_volume
from scripts.research_symbols import discover_stocks_by_news
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame


def get_market_clock(trading_client):
    clock = trading_client.get_clock()
    return clock


def fetch_vix() -> float | None:
    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="1d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2)
    except Exception:
        pass
    return None


def fetch_spy_regime(data_client) -> dict:
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=60)
        req = StockBarsRequest(
            symbol_or_symbols="SPY",
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            limit=50,
            feed="iex",
        )
        bars = data_client.get_stock_bars(req)
        df = bars.df
        if hasattr(df.index, "levels"):
            df = df.xs("SPY", level="symbol")
        closes = df["close"]
        ema9 = float(closes.ewm(span=9, adjust=False).mean().iloc[-1])
        ema21 = float(closes.ewm(span=21, adjust=False).mean().iloc[-1])
        return {
            "spy_ema9": round(ema9, 2),
            "spy_ema21": round(ema21, 2),
            "trending_up": ema9 > ema21,
        }
    except Exception as e:
        return {"error": str(e), "trending_up": True}


def fetch_snapshots(data_client, symbols: list[str]) -> dict:
    """Batch-fetch latest snapshots for a given list of symbols."""
    results = {}
    chunk_size = 100
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        try:
            req = StockSnapshotRequest(symbol_or_symbols=chunk, feed="iex")
            snaps = data_client.get_stock_snapshot(req)
            results.update(snaps)
        except Exception:
            pass
    return results


def validate_candidates(data_client, discovered: list[dict], snapshots: dict, earnings_blacklist: set[str]) -> list[dict]:
    """Build the watchlist from Perplexity-discovered symbols.

    The watchlist is sentiment-driven: the ONLY hard filter applied here is the
    earnings blackout (a safety exclude). Trade volume and price are NOT used to
    drop candidates — judging volume and technical indicators is the 10:00 AM
    open-market agent's job. Price and volume below are best-effort context only;
    a symbol is kept on the watchlist even when Alpaca has no bars for it.
    """
    watchlist = []
    for item in discovered:
        symbol = item["symbol"]

        if symbol in earnings_blacklist:
            print(f"  {symbol}: earnings blackout — excluding")
            continue

        # Best-effort enrichment for context only; never used to filter.
        price = None
        prev_close = None
        avg_volume = None
        premarket_volume = 0
        try:
            daily_df = fetch_daily_bars(data_client, symbol, 30)
            if not daily_df.empty:
                avg_volume = get_avg_volume(daily_df)
                price = round(float(daily_df["close"].iloc[-1]), 2)
                prev_close = round(float(daily_df["close"].iloc[-2]), 2) if len(daily_df) >= 2 else price
        except Exception as e:
            print(f"  {symbol}: price/volume enrichment unavailable ({e}) — keeping anyway")

        snap = snapshots.get(symbol)
        if snap and getattr(snap, "daily_bar", None):
            try:
                premarket_volume = int(snap.daily_bar.volume)
            except Exception:
                premarket_volume = 0

        watchlist.append({
            "symbol": symbol,
            "price": price,
            "prev_close": prev_close,
            "premarket_volume": premarket_volume,
            "prev_volume": int(avg_volume) if avg_volume is not None else None,
            "earnings_blackout": False,
            "sentiment": item["sentiment"],
            "summary": item.get("summary", ""),
        })
    return watchlist


def main():
    trading_client = get_trading_client()
    data_client = get_data_client()

    # Check market clock
    clock = get_market_clock(trading_client)
    print(f"Market open: {clock.is_open}, next open: {clock.next_open}")

    # Check no-trade dates
    no_trade_dates = read_json("no_trade_dates.json", default=[])
    today_str = datetime.now().strftime("%Y-%m-%d")
    if today_str in no_trade_dates:
        set_flag("no_trade_today.flag")
        print(f"TODAY ({today_str}) IS A NO-TRADE DATE. Flag set.")
        write_json("daily_context.json", {"date": today_str, "no_trade": True})
        return

    clear_flag("no_trade_today.flag")

    # Fetch market context
    vix = fetch_vix()
    spy_regime = fetch_spy_regime(data_client)
    print(f"VIX: {vix}, SPY regime: {spy_regime}")

    if vix and vix > config.VIX_SUSPEND_THRESHOLD:
        set_flag("no_trade_today.flag")
        print(f"VIX {vix} > {config.VIX_SUSPEND_THRESHOLD}. Suspending trading today.")
        write_json("daily_context.json", {"date": today_str, "no_trade": True, "reason": f"VIX={vix}"})
        return

    daily_context = {
        "date": today_str,
        "no_trade": False,
        "vix": vix,
        "spy_ema9": spy_regime.get("spy_ema9"),
        "spy_ema21": spy_regime.get("spy_ema21"),
        "market_trending_up": spy_regime.get("trending_up", True),
    }
    write_json("daily_context.json", daily_context)

    # Load earnings blacklist
    earnings_bl = load_earnings_blacklist()

    # Discover stocks via Perplexity news sentiment
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        print("PERPLEXITY_API_KEY not set — cannot run Perplexity discovery. Watchlist will be empty.")
        write_json("watchlist.json", [])
        write_json("research.json", {"generated_at": datetime.now(timezone.utc).isoformat(), "results": {}})
        return

    print(f"Discovering up to {config.PERPLEXITY_DISCOVER_TOP_N} stocks via Perplexity news...")
    client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
    discovered = discover_stocks_by_news(client, config.PERPLEXITY_DISCOVER_TOP_N)

    if not discovered:
        print("Perplexity returned no stocks — watchlist will be empty.")
        write_json("watchlist.json", [])
        write_json("research.json", {"generated_at": datetime.now(timezone.utc).isoformat(), "results": {}})
        return

    # Validate discovered symbols against Alpaca (price, volume, tradability)
    symbols = [d["symbol"] for d in discovered]
    print(f"Fetching Alpaca snapshots for {len(symbols)} discovered symbols...")
    snapshots = fetch_snapshots(data_client, symbols)
    watchlist = validate_candidates(data_client, discovered, snapshots, earnings_bl)

    research_results = {
        item["symbol"]: {
            "symbol": item["symbol"],
            "sentiment": item["sentiment"],
            "summary": item.get("summary", ""),
            "key_points": item.get("key_points", []),
            "error": None,
        }
        for item in discovered
    }
    write_json("research.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": research_results,
    })

    write_json("watchlist.json", watchlist)
    print(f"Watchlist: {len(watchlist)} sentiment-driven candidates written.")
    for c in watchlist[:10]:
        price_str = f"${c['price']:.2f}" if c.get("price") is not None else "price n/a"
        print(f"  {c['symbol']}: {price_str}, sentiment {c['sentiment']}")


if __name__ == "__main__":
    main()
