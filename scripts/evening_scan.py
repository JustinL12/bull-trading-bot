"""Evening scan: RS Leader + VCP watchlist for next morning.

Runs at 4:00 PM ET after market close. Screens the S&P 500 + NASDAQ 100 universe
for stocks showing institutional accumulation (RS vs SPY) combined with volatility
compression (VCP). Outputs ranked candidates to data/watchlist_evening.json for the
8:30 AM premarket agent.

Filters applied (all must pass):
  EMA-9 > EMA-21 > EMA-50 (daily)   — bullish alignment
  RS_20day vs SPY  > RS_20DAY_MIN   — institutional accumulation
  VCP ATR ratio    < VCP_ATR_RATIO_MAX  — coiling, not yet extended
  Pct from 52w high < HIGH_PROXIMITY_PCT — one push takes it to new highs
  Vol dry ratio    < VOL_DRY_RATIO_MAX  — sellers exhausted

Batch strategy: fetch 400 calendar days of daily bars for all tickers in chunks
of 50 (≈12 API calls). SPY bars are fetched first for RS computation.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.alpaca_client import get_data_client
from lib.indicators import compute_ema, compute_rs_vs_spy, compute_vcp_compression, pct_from_52w_high
from lib.notify import post_attention
from lib.state import read_json, write_json
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

CALENDAR_DAYS = 400   # covers ~285 trading days, enough for 252-bar 52w high


def fetch_daily_bars_multi(data_client, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Batch-fetch daily bars for a list of symbols. Returns {symbol: DataFrame}."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=CALENDAR_DAYS)
    results = {}
    chunk_size = 50

    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        total_chunks = (len(symbols) + chunk_size - 1) // chunk_size
        print(f"  Fetching bars chunk {chunk_num}/{total_chunks} ({len(chunk)} symbols)...")
        try:
            req = StockBarsRequest(
                symbol_or_symbols=chunk,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
                feed="iex",
            )
            bars = data_client.get_stock_bars(req)
            df = bars.df.rename(columns=str.lower)
            if df.empty:
                continue
            if isinstance(df.index, pd.MultiIndex):
                for sym in chunk:
                    try:
                        sym_df = df.xs(sym, level="symbol").copy()
                        if not sym_df.empty:
                            results[sym] = sym_df
                    except KeyError:
                        pass
            elif len(chunk) == 1:
                results[chunk[0]] = df
        except Exception as e:
            print(f"  Chunk {chunk_num} error: {e}")

    return results


def compute_vol_dry_ratio(df: pd.DataFrame) -> float | None:
    """5-day avg volume / 20-day avg volume. < VOL_DRY_RATIO_MAX = sellers drying up."""
    if "volume" not in df.columns or len(df) < 20:
        return None
    vol5 = float(df["volume"].iloc[-5:].mean())
    vol20 = float(df["volume"].iloc[-20:].mean())
    if vol20 == 0:
        return None
    return round(vol5 / vol20, 4)


def composite_score(c: dict) -> float:
    """Higher is better. RS performance weighted most, then VCP tightness, then proximity."""
    rs_pts = (c["rs_20day"] - 1.0) * 40.0
    vcp_pts = (config.VCP_ATR_RATIO_MAX - c["vcp_ratio"]) * 30.0
    prox_pts = (config.HIGH_PROXIMITY_PCT - c["pct_from_52w_high"]) * 100.0
    vol_pts = (config.VOL_DRY_RATIO_MAX - c["vol_dry_ratio"]) * 10.0
    return round(rs_pts + vcp_pts + prox_pts + vol_pts, 4)


def main():
    data_client = get_data_client()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Load universe
    universe_data = read_json("universe.json", default={})
    tickers = universe_data.get("tickers", [])
    if not tickers:
        print("ERROR: data/universe.json is empty. Run scripts/build_universe.py first.")
        post_attention(
            "Evening Scan Failed — No Universe",
            "data/universe.json is empty or missing. Run scripts/build_universe.py.",
            level="warning",
        )
        write_json("watchlist_evening.json", [])
        return

    print(f"Universe: {len(tickers)} tickers. Fetching {CALENDAR_DAYS}-day daily bars...")

    # SPY first — needed for RS computation
    spy_bars = fetch_daily_bars_multi(data_client, ["SPY"])
    spy_df = spy_bars.get("SPY")
    if spy_df is None or len(spy_df) < 20:
        print("ERROR: Could not fetch SPY bars.")
        post_attention(
            "Evening Scan Failed — No SPY Data",
            "Could not fetch SPY daily bars from Alpaca. Check API connectivity.",
            level="warning",
        )
        write_json("watchlist_evening.json", [])
        return
    print(f"SPY: {len(spy_df)} daily bars.")

    # All universe tickers
    bars_map = fetch_daily_bars_multi(data_client, tickers)
    print(f"Bar data received for {len(bars_map)}/{len(tickers)} tickers.")

    # --- Screen each ticker ---
    counts = {k: 0 for k in ["no_data", "short", "price", "ema", "rs", "vcp", "high", "vol"]}
    candidates = []

    for sym, df in bars_map.items():
        if len(df) < 25:
            counts["short"] += 1
            continue

        # Price floor
        current_price = float(df["close"].iloc[-1])
        if current_price < config.PRICE_MIN:
            counts["price"] += 1
            continue

        # EMA alignment: EMA-9 > EMA-21 > EMA-50 on daily bars
        df = compute_ema(df.copy(), 9)
        df = compute_ema(df, 21)
        df = compute_ema(df, 50)
        row = df.iloc[-1]
        if not (row.get("ema_9", 0) > row.get("ema_21", 0) > row.get("ema_50", 0)):
            counts["ema"] += 1
            continue

        # RS vs SPY (20-day)
        rs = compute_rs_vs_spy(df, spy_df, period=20)
        if rs is None or rs < config.RS_20DAY_MIN:
            counts["rs"] += 1
            continue

        # VCP compression
        vcp = compute_vcp_compression(df)
        if vcp is None or vcp >= config.VCP_ATR_RATIO_MAX:
            counts["vcp"] += 1
            continue

        # 52-week high proximity
        pct_high = pct_from_52w_high(df)
        if pct_high is None or pct_high > config.HIGH_PROXIMITY_PCT:
            counts["high"] += 1
            continue

        # Volume drying up
        vol_dry = compute_vol_dry_ratio(df)
        if vol_dry is None or vol_dry >= config.VOL_DRY_RATIO_MAX:
            counts["vol"] += 1
            continue

        prev_day_high = round(float(df["high"].iloc[-2]), 2) if len(df) >= 2 else None
        prev_close = round(float(df["close"].iloc[-2]), 2) if len(df) >= 2 else None

        candidates.append({
            "symbol": sym,
            "rs_20day": rs,
            "vcp_ratio": vcp,
            "pct_from_52w_high": pct_high,
            "vol_dry_ratio": vol_dry,
            "ema_aligned": True,
            "close": round(current_price, 2),
            "prev_close": prev_close,
            "prev_day_high": prev_day_high,
        })

    counts["no_data"] = len(tickers) - len(bars_map)

    # Rank by composite score, output top N
    for c in candidates:
        c["rank_score"] = composite_score(c)
    candidates.sort(key=lambda x: x["rank_score"], reverse=True)
    top_n = candidates[:config.EVENING_SCAN_TOP_N]

    print(f"\n=== Evening Scan {today_str} ===")
    print(f"Universe {len(tickers)} → data {len(bars_map)} → passed all filters {len(candidates)}")
    print(f"Skipped: no_data={counts['no_data']}, short_history={counts['short']}, "
          f"price={counts['price']}, ema={counts['ema']}, rs={counts['rs']}, "
          f"vcp={counts['vcp']}, 52w_high={counts['high']}, vol={counts['vol']}")
    print(f"\nTop {len(top_n)} candidates:")
    for c in top_n:
        print(f"  {c['symbol']:6s}  RS={c['rs_20day']:.3f}  VCP={c['vcp_ratio']:.3f}  "
              f"pct_high={c['pct_from_52w_high']:.3f}  vol_dry={c['vol_dry_ratio']:.3f}  "
              f"score={c['rank_score']:.2f}  prev_high=${c['prev_day_high']}")

    write_json("watchlist_evening.json", top_n)
    print(f"\nWrote {len(top_n)} candidates to data/watchlist_evening.json")

    if not top_n:
        post_attention(
            "Evening Scan — Zero Candidates",
            f"Evening scan ({today_str}) found no RS Leader + VCP setups in the universe. "
            f"Market may be in a broad correction. Tomorrow's watchlist is empty.",
            level="warning",
        )


if __name__ == "__main__":
    main()
