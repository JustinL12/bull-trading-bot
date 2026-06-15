"""Pre-market scanner: sort RS watchlist by Finnhub pre-market momentum.

Runs at 8:30 AM ET. Loads the RS Leader + VCP evening watchlist built at 4 PM,
enriches each candidate with a Finnhub pre-market quote, sorts by pre-market %
change (strongest mover first), applies the earnings blackout, and writes
data/watchlist.json + data/daily_context.json for the 9:31 AM entry agent.

Perplexity discovery has been removed. Candidate discovery happens at 4 PM in
scripts/evening_scan.py. This agent's sole job is pre-market enrichment + sort.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import finnhub
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.alpaca_client import get_data_client, get_trading_client
from lib.notify import post_attention
from lib.state import clear_flag, read_json, set_flag, write_json
from scripts.check_earnings import load_earnings_blacklist
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


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


def fetch_premarket_quotes(finnhub_client, symbols: list[str]) -> dict[str, dict]:
    """Fetch Finnhub quotes for each symbol; during pre-market hours (4–9:30 AM ET)
    the 'c' field reflects the latest pre-market trade price."""
    quotes = {}
    for sym in symbols:
        try:
            q = finnhub_client.quote(sym)
            if not q or not q.get("c"):
                continue
            prev_close = q.get("pc") or q["c"]
            pm_change_pct = round((q["c"] - prev_close) / prev_close * 100, 3) if prev_close else 0.0
            quotes[sym] = {
                "pm_price": round(float(q["c"]), 2),
                "pm_change_pct": pm_change_pct,
            }
        except Exception as e:
            print(f"  Finnhub quote error for {sym}: {e}")
    return quotes


def main():
    trading_client = get_trading_client()
    data_client = get_data_client()

    finnhub_key = os.environ.get("FINNHUB_API_KEY")
    finnhub_client = finnhub.Client(api_key=finnhub_key) if finnhub_key else None

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
        post_attention(
            "VIX Suspend — No Trade Today",
            f"VIX is {vix:.1f}, above the {config.VIX_SUSPEND_THRESHOLD} threshold.\n"
            f"Trading suspended for {today_str}. no_trade_today.flag set.",
            level="warning",
        )
        return

    write_json("daily_context.json", {
        "date": today_str,
        "no_trade": False,
        "vix": vix,
        "spy_ema9": spy_regime.get("spy_ema9"),
        "spy_ema21": spy_regime.get("spy_ema21"),
        "market_trending_up": spy_regime.get("trending_up", True),
    })

    # Load earnings blacklist
    earnings_bl = load_earnings_blacklist()

    # Load evening watchlist (built by the 4 PM evening scan)
    evening_watchlist = read_json("watchlist_evening.json", default=[])
    if not evening_watchlist:
        print("WARNING: data/watchlist_evening.json is empty or missing.")
        post_attention(
            "Empty Watchlist — No Evening Scan Data",
            f"data/watchlist_evening.json is empty for {today_str}. "
            f"The 4 PM evening scan may not have run. No trades possible today.",
            level="warning",
        )
        write_json("watchlist.json", [])
        return

    # Apply earnings blackout
    excluded = [c["symbol"] for c in evening_watchlist if c["symbol"] in earnings_bl]
    watchlist = [c for c in evening_watchlist if c["symbol"] not in earnings_bl]
    if excluded:
        print(f"  Earnings blackout excluded: {excluded}")

    # Enrich with Finnhub pre-market quotes and sort by pre-market momentum
    symbols = [c["symbol"] for c in watchlist]
    if finnhub_client and symbols:
        print(f"Fetching Finnhub pre-market quotes for {len(symbols)} candidates...")
        pm_quotes = fetch_premarket_quotes(finnhub_client, symbols)
        for c in watchlist:
            q = pm_quotes.get(c["symbol"], {})
            c["pm_price"] = q.get("pm_price")
            c["pm_change_pct"] = q.get("pm_change_pct", 0.0)
    else:
        if not finnhub_client:
            print("FINNHUB_API_KEY not set — skipping pre-market sort, using RS rank order.")
        for c in watchlist:
            c["pm_price"] = None
            c["pm_change_pct"] = 0.0

    # Sort: strongest pre-market mover first; fall back to RS rank if no Finnhub data
    watchlist.sort(key=lambda x: x.get("pm_change_pct", 0.0), reverse=True)

    write_json("watchlist.json", watchlist)
    print(f"Watchlist: {len(watchlist)} RS candidates written.")
    for c in watchlist:
        pm = c.get("pm_change_pct", 0.0) or 0.0
        sign = "+" if pm >= 0 else ""
        print(f"  {c['symbol']:6s}  pm={sign}{pm:.2f}%  RS={c.get('rs_20day', 0):.3f}  "
              f"VCP={c.get('vcp_ratio', 0):.3f}  prev_high=${c.get('prev_day_high')}")


if __name__ == "__main__":
    main()
