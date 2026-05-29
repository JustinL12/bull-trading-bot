"""Pre-market scanner: build a watchlist of momentum candidates.

Runs at 9:30 AM ET. Writes data/watchlist.json and data/daily_context.json.
Also checks for no-trade conditions and sets data/no_trade_today.flag if needed.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.alpaca_client import get_data_client, get_trading_client
from lib.state import clear_flag, flag_exists, read_json, set_flag, write_json
from scripts.check_earnings import load_earnings_blacklist
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
            req = StockSnapshotRequest(symbol_or_symbols=chunk, feed="iex")
            snaps = data_client.get_stock_snapshot(req)
            results.update(snaps)
        except Exception:
            pass
    return results


def screen_snapshots(snapshots: dict, earnings_blacklist: set[str]) -> list[dict]:
    candidates = []
    for symbol, snap in snapshots.items():
        try:
            if snap.daily_bar is None or snap.prev_daily_bar is None:
                continue

            prev_close = float(snap.prev_daily_bar.close)
            latest_price = float(snap.latest_trade.price) if snap.latest_trade else float(snap.daily_bar.close)
            daily_volume = float(snap.daily_bar.volume)
            prev_volume = float(snap.prev_daily_bar.volume)

            if latest_price < config.PRICE_MIN or latest_price > config.PRICE_MAX:
                continue
            if prev_volume < config.MIN_AVG_VOLUME:
                continue
            if symbol in earnings_blacklist:
                continue

            gap_pct = (latest_price - prev_close) / prev_close * 100
            if gap_pct < config.GAP_UP_MIN_PCT:
                continue

            rel_vol = daily_volume / prev_volume if prev_volume > 0 else 0
            if rel_vol < config.REL_VOL_MIN:
                continue

            candidates.append({
                "symbol": symbol,
                "price": round(latest_price, 2),
                "prev_close": round(prev_close, 2),
                "gap_pct": round(gap_pct, 2),
                "daily_volume": int(daily_volume),
                "prev_volume": int(prev_volume),
                "rel_vol": round(rel_vol, 2),
                "earnings_blackout": False,
            })
        except Exception:
            continue

    candidates.sort(key=lambda x: x["rel_vol"], reverse=True)
    return candidates[:20]


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

    write_json("watchlist.json", candidates)
    print(f"Watchlist: {len(candidates)} candidates written.")
    for c in candidates[:10]:
        print(f"  {c['symbol']}: gap {c['gap_pct']:+.1f}%, rel_vol {c['rel_vol']:.1f}x, price ${c['price']:.2f}")


if __name__ == "__main__":
    main()
