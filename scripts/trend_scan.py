"""Trend Following Evening Scan — MA-20/60 Crossover.

Runs at 4:00 PM ET after market close. Screens universe_trend.json for symbols
where the EMA-20 has crossed above the EMA-60 today (golden cross), and checks
all open positions for death cross exit signals (EMA-20 crosses below EMA-60).

Outputs:
  data/watchlist_trend.json  — entry candidates for tomorrow's open
  data/exit_signals.json     — open positions that triggered a death cross

Strategy parameters:
  FAST_PERIOD = 20  (EMA-20)
  SLOW_PERIOD = 60  (EMA-60)
  ATR_PERIOD  = 20  (position sizing)
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.alpaca_client import get_data_client
from lib.indicators import compute_atr, compute_ema
from lib.notify import post_attention
from lib.state import read_json, write_json

# Need ~120 trading days to get stable EMA-60; 180 calendar days provides ~126 trading days
CALENDAR_DAYS = 180
FAST_PERIOD = 20   # must match backtest winner MA-20/60
SLOW_PERIOD = 60
MIN_AVG_VOLUME = config.MIN_AVG_VOLUME
MIN_ATR_DOLLAR = config.MIN_ATR_DOLLAR
CHUNK_SIZE = 50


def fetch_daily_bars(data_client, symbols: list[str]) -> dict[str, pd.DataFrame]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=CALENDAR_DAYS)
    results = {}

    for i in range(0, len(symbols), CHUNK_SIZE):
        chunk = symbols[i:i + CHUNK_SIZE]
        chunk_num = i // CHUNK_SIZE + 1
        total_chunks = (len(symbols) + CHUNK_SIZE - 1) // CHUNK_SIZE
        print(f"  Fetching bars chunk {chunk_num}/{total_chunks} ({len(chunk)} symbols)...")
        live_chunk = list(chunk)
        for _attempt in range(len(chunk)):
            try:
                from alpaca.data.requests import StockBarsRequest
                from alpaca.data.timeframe import TimeFrame
                req = StockBarsRequest(
                    symbol_or_symbols=live_chunk,
                    timeframe=TimeFrame.Day,
                    start=start,
                    end=end,
                    feed="iex",
                )
                bars = data_client.get_stock_bars(req)
                df = bars.df.rename(columns=str.lower)
                if df.empty:
                    break
                if isinstance(df.index, pd.MultiIndex):
                    for sym in live_chunk:
                        try:
                            sym_df = df.xs(sym, level="symbol").copy()
                            if not sym_df.empty:
                                results[sym] = sym_df
                        except KeyError:
                            pass
                elif len(live_chunk) == 1:
                    results[live_chunk[0]] = df
                break
            except Exception as e:
                bad = re.search(r"invalid symbol:\s*([A-Za-z0-9.\-]+)", str(e))
                if bad and bad.group(1) in live_chunk:
                    print(f"  Dropping invalid symbol {bad.group(1)}, retrying...")
                    live_chunk.remove(bad.group(1))
                else:
                    print(f"  Chunk {chunk_num} error: {e}")
                    break

    return results


def _ma_signal(df: pd.DataFrame) -> str:
    """Return 'enter', 'exit', or 'hold' based on EMA-20/60 crossover.

    enter = fresh golden cross (EMA-20 crossed above EMA-60 today)
    exit  = fresh death cross  (EMA-20 crossed below EMA-60 today)
    hold  = no crossover today
    """
    if len(df) < SLOW_PERIOD + 2:
        return "hold"

    df = df.copy()
    compute_ema(df, FAST_PERIOD)
    compute_ema(df, SLOW_PERIOD)

    fast_col = f"ema_{FAST_PERIOD}"
    slow_col = f"ema_{SLOW_PERIOD}"

    cur_fast = df[fast_col].iloc[-1]
    cur_slow = df[slow_col].iloc[-1]
    prev_fast = df[fast_col].iloc[-2]
    prev_slow = df[slow_col].iloc[-2]

    if any(pd.isna(v) for v in [cur_fast, cur_slow, prev_fast, prev_slow]):
        return "hold"

    if cur_fast < cur_slow and prev_fast >= prev_slow:
        return "exit"
    if cur_fast > cur_slow and prev_fast <= prev_slow:
        return "enter"
    return "hold"


def scan_entries(bars: dict[str, pd.DataFrame]) -> list[dict]:
    """Find symbols with a fresh EMA-20/60 golden cross today."""
    entries = []
    for sym, df in bars.items():
        if len(df) < SLOW_PERIOD + 2:
            continue

        # Liquidity filter
        avg_vol = float(df["volume"].iloc[-20:].mean())
        if avg_vol < MIN_AVG_VOLUME:
            continue

        # ATR filter
        compute_atr(df, config.ATR_PERIOD)
        atr_val = df["atr"].iloc[-1]
        if pd.isna(atr_val) or float(atr_val) < MIN_ATR_DOLLAR:
            continue
        atr_val = float(atr_val)

        if _ma_signal(df) != "enter":
            continue

        df_tmp = df.copy()
        compute_ema(df_tmp, FAST_PERIOD)
        compute_ema(df_tmp, SLOW_PERIOD)

        current_close = float(df["close"].iloc[-1])
        ema_fast = float(df_tmp[f"ema_{FAST_PERIOD}"].iloc[-1])
        ema_slow = float(df_tmp[f"ema_{SLOW_PERIOD}"].iloc[-1])

        entries.append({
            "symbol": sym,
            "close": round(current_close, 4),
            "atr": round(atr_val, 4),
            "ema_fast": round(ema_fast, 4),
            "ema_slow": round(ema_slow, 4),
            "avg_volume_20d": int(avg_vol),
            "signal": "golden_cross",
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        })

    # Sort by ATR% (how much room to move relative to price — higher = more volatile trend)
    return sorted(entries, key=lambda x: x["atr"] / x["close"] if x["close"] > 0 else 0, reverse=True)


def scan_exits(positions: dict, bars: dict[str, pd.DataFrame]) -> list[dict]:
    """Check open positions for EMA-20/60 death cross exit signal."""
    exits = []
    for sym, pos in positions.items():
        df = bars.get(sym)
        if df is None or len(df) < SLOW_PERIOD + 2:
            continue

        if _ma_signal(df) != "exit":
            continue

        df_tmp = df.copy()
        compute_ema(df_tmp, FAST_PERIOD)
        compute_ema(df_tmp, SLOW_PERIOD)

        current_close = float(df["close"].iloc[-1])
        ema_fast = float(df_tmp[f"ema_{FAST_PERIOD}"].iloc[-1])
        ema_slow = float(df_tmp[f"ema_{SLOW_PERIOD}"].iloc[-1])

        exits.append({
            "symbol": sym,
            "exit_reason": "death_cross",
            "current_close": round(current_close, 4),
            "ema_fast": round(ema_fast, 4),
            "ema_slow": round(ema_slow, 4),
            "entry_price": pos.get("entry_price"),
        })
    return exits


def main():
    print("=== Trend Scan: MA-20/60 Crossover ===")
    data_client = get_data_client()

    # Load universe
    universe_file = Path(config.BACKTEST_UNIVERSE_FILE).resolve()
    if not universe_file.exists():
        universe_file = Path("data/universe.json").resolve()
    raw = read_json(universe_file)
    if isinstance(raw, list):
        tickers = raw
    elif raw is not None and isinstance(raw, dict) and "tickers" in raw:
        tickers = raw["tickers"]
    elif raw is not None:
        tickers = list(raw.keys())
    else:
        print(f"ERROR: Could not load universe from {universe_file}")
        sys.exit(1)
    print(f"Universe: {len(tickers)} tickers")

    # Load open positions to check for exit signals
    positions = read_json(Path("data/positions.json").resolve()) or {}

    # Add open position symbols to fetch list so we can check exits
    all_symbols = list(set(tickers) | set(positions.keys()))

    print(f"Fetching {CALENDAR_DAYS} days of daily bars...")
    bars = fetch_daily_bars(data_client, all_symbols)
    print(f"Retrieved data for {len(bars)} symbols")

    # Entry signals (golden cross on universe tickers)
    entry_candidates = scan_entries(
        {sym: df for sym, df in bars.items() if sym in set(tickers)}
    )

    # Exit signals on open positions (death cross)
    exit_signals = scan_exits(positions, bars)

    write_json("watchlist_trend.json", entry_candidates)
    write_json("exit_signals.json", exit_signals)

    print(f"\nEntry signals (golden cross): {len(entry_candidates)}")
    for c in entry_candidates[:10]:
        print(f"  {c['symbol']:<8}  close={c['close']:.2f}  ATR={c['atr']:.3f}  "
              f"EMA{FAST_PERIOD}={c['ema_fast']:.2f}  EMA{SLOW_PERIOD}={c['ema_slow']:.2f}")

    print(f"\nExit signals (death cross): {len(exit_signals)}")
    for e in exit_signals:
        print(f"  {e['symbol']:<8}  close={e['current_close']:.2f}  "
              f"EMA{FAST_PERIOD}={e['ema_fast']:.2f}  EMA{SLOW_PERIOD}={e['ema_slow']:.2f}")

    if not entry_candidates:
        post_attention(
            "Trend Scan: No Entry Signals",
            f"MA-{FAST_PERIOD}/{SLOW_PERIOD} scan found 0 golden cross candidates across "
            f"{len(bars)} symbols. Market may be in a broad downtrend or consolidation. "
            f"No new entries expected tomorrow.",
            level="warning",
        )


if __name__ == "__main__":
    main()
