"""Compute and write today's P&L including SPY benchmark comparison.

Usage:
    python scripts/update_pnl.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.alpaca_client import get_trading_client
from lib.state import read_json, write_json


def get_spy_return_today() -> float:
    """Return SPY's % return for today."""
    try:
        spy = yf.Ticker("SPY")
        hist = spy.history(period="2d")
        if len(hist) >= 2:
            prev_close = float(hist["Close"].iloc[-2])
            today_close = float(hist["Close"].iloc[-1])
            return round((today_close - prev_close) / prev_close * 100, 4)
    except Exception as e:
        print(f"Could not fetch SPY return: {e}")
    return 0.0


def get_cumulative_spy(start_date: str | None = None) -> float:
    """Return SPY cumulative % return since start_date (or bot inception)."""
    if not start_date:
        return 0.0
    try:
        spy = yf.Ticker("SPY")
        hist = spy.history(start=start_date)
        if len(hist) >= 2:
            start_price = float(hist["Close"].iloc[0])
            end_price = float(hist["Close"].iloc[-1])
            return round((end_price - start_price) / start_price * 100, 4)
    except Exception:
        pass
    return 0.0


def main():
    client = get_trading_client()
    acct = client.get_account()
    equity = float(acct.equity)
    last_equity = float(acct.last_equity)

    existing = read_json("daily_pnl.json", default={})
    today = datetime.now().strftime("%Y-%m-%d")

    starting_equity = existing.get("starting_equity", last_equity)
    if existing.get("date") != today:
        starting_equity = last_equity  # reset for new day

    pnl_dollars = round(equity - starting_equity, 2)
    pnl_pct = round((equity - starting_equity) / starting_equity * 100, 4) if starting_equity else 0.0

    spy_return = get_spy_return_today()
    vs_spy = round(pnl_pct - spy_return, 4)

    overnight_holds = [s for s, p in read_json("positions.json", default={}).items() if p.get("overnight_hold")]

    # Cumulative tracking
    inception_date = existing.get("inception_date", today)
    cumulative_bull = round((equity - existing.get("inception_equity", equity)) / existing.get("inception_equity", equity) * 100, 4) if existing.get("inception_equity") else 0.0
    cumulative_spy = get_cumulative_spy(inception_date)

    data = {
        "date": today,
        "starting_equity": round(starting_equity, 2),
        "current_equity": round(equity, 2),
        "pnl_dollars": pnl_dollars,
        "pnl_pct": pnl_pct,
        "spy_return_today": spy_return,
        "vs_spy_pct": vs_spy,
        "pdt_trades_today": existing.get("pdt_trades_today", 0),
        "overnight_holds": overnight_holds,
        "kill_switch_triggered": existing.get("kill_switch_triggered", False),
        "inception_date": inception_date,
        "inception_equity": existing.get("inception_equity", round(equity, 2)),
        "cumulative_bull_pct": cumulative_bull,
        "cumulative_spy_pct": cumulative_spy,
    }

    write_json("daily_pnl.json", data)
    sign = "+" if pnl_pct >= 0 else ""
    print(f"P&L: {sign}${pnl_dollars:.2f} ({sign}{pnl_pct:.2f}%) | SPY: {'+' if spy_return>=0 else ''}{spy_return:.2f}% | Alpha: {'+' if vs_spy>=0 else ''}{vs_spy:.2f}%")
    return data


if __name__ == "__main__":
    main()
