"""Pre-market scanner: build a watchlist of momentum candidates.

Runs at 9:30 AM ET. Writes data/watchlist.json and data/daily_context.json.
Also checks for no-trade conditions and sets data/no_trade_today.flag if needed.
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.alpaca_client import get_data_client, get_trading_client
from lib.state import clear_flag, flag_exists, read_json, set_flag, write_json
from scripts.check_earnings import load_earnings_blacklist
from scripts.research_symbols import research_symbol
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass


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


def get_candidate_assets(trading_client) -> list[str]:
    """Pull tradable US equity assets from Alpaca."""
    req = GetAssetsRequest(asset_class=AssetClass.US_EQUITY)
    assets = trading_client.get_all_assets(req)
    symbols = [
        a.symbol for a in assets
        if a.tradable and a.status == "active" and a.symbol.isalpha() and len(a.symbol) <= 5
    ]
    return symbols[:3000]  # cap to avoid excessive API calls


def fetch_snapshots(data_client, symbols: list[str]) -> dict:
    """Batch-fetch latest snapshots for screening."""
    results = {}
    chunk_size = 100
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        try:
            req = StockSnapshotRequest(symbol_or_symbols=chunk, feed="sip")
            snaps = data_client.get_stock_snapshot(req)
            results.update(snaps)
        except Exception:
            pass
    return results


def screen_snapshots(snapshots: dict, earnings_blacklist: set[str]) -> list[dict]:
    candidates = []
    for symbol, snap in snapshots.items():
        try:
            if snap.prev_daily_bar is None:
                continue

            prev_close = float(snap.prev_daily_bar.close)
            prev_volume = float(snap.prev_daily_bar.volume)

            # Prefer latest trade price; fall back to prev close if no intraday data yet
            if snap.latest_trade:
                latest_price = float(snap.latest_trade.price)
            elif snap.daily_bar:
                latest_price = float(snap.daily_bar.close)
            else:
                latest_price = prev_close

            if latest_price < config.PRICE_MIN or latest_price > config.PRICE_MAX:
                continue
            if prev_volume < config.MIN_AVG_VOLUME:
                continue
            if symbol in earnings_blacklist:
                continue

            gap_pct = (latest_price - prev_close) / prev_close * 100
            if gap_pct < config.GAP_UP_MIN_PCT:
                continue

            # pre-market daily_bar.volume is partial — record it but don't filter on it
            premarket_volume = int(snap.daily_bar.volume) if snap.daily_bar else 0

            candidates.append({
                "symbol": symbol,
                "price": round(latest_price, 2),
                "prev_close": round(prev_close, 2),
                "gap_pct": round(gap_pct, 2),
                "premarket_volume": premarket_volume,
                "prev_volume": int(prev_volume),
                "earnings_blackout": False,
            })
        except Exception:
            continue

    candidates.sort(key=lambda x: x["gap_pct"], reverse=True)
    return candidates[:20]


def filter_by_sentiment(candidates: list[dict]) -> list[dict]:
    """Research each candidate with Perplexity and keep only positive-sentiment ones.

    Falls back to the full unfiltered list if the API key is missing or all calls fail,
    so a Perplexity outage never blocks the scan entirely.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        print("PERPLEXITY_API_KEY not set — skipping sentiment filter, keeping all candidates.")
        for c in candidates:
            c["sentiment"] = "neutral"
        write_json("research.json", {"generated_at": datetime.now(timezone.utc).isoformat(), "results": {}})
        return candidates

    client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
    results = {}
    enriched = []

    for candidate in candidates[:config.PREMARKET_RESEARCH_TOP_N]:
        symbol = candidate["symbol"]
        print(f"  Researching {symbol}...")
        result = research_symbol(client, symbol)
        results[symbol] = result
        candidate["sentiment"] = result["sentiment"]
        print(f"    → {result['sentiment']}")
        enriched.append(candidate)
        time.sleep(0.5)

    write_json("research.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    })

    positive = [c for c in enriched if c["sentiment"] == "positive"]
    if not positive:
        print("Warning: no positive-sentiment candidates — keeping all candidates as fallback.")
        return enriched

    print(f"Sentiment filter: {len(positive)}/{len(enriched)} candidates passed (positive sentiment).")
    return positive


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

    # Scan universe
    print("Fetching tradable assets...")
    symbols = get_candidate_assets(trading_client)
    print(f"Screening {len(symbols)} symbols...")
    snapshots = fetch_snapshots(data_client, symbols)
    candidates = screen_snapshots(snapshots, earnings_bl)

    candidates = filter_by_sentiment(candidates)
    write_json("watchlist.json", candidates)
    print(f"Watchlist: {len(candidates)} positive-sentiment candidates written.")
    for c in candidates[:10]:
        print(f"  {c['symbol']}: gap {c['gap_pct']:+.1f}%, sentiment {c['sentiment']}, price ${c['price']:.2f}")


if __name__ == "__main__":
    main()
