"""Fetch upcoming earnings dates and write data/earnings_blacklist.json.

Uses yfinance as a free earnings calendar source.
Returns a set of symbol strings that are within the blackout window.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.state import read_json, write_json


WATCHLIST_PATH = "watchlist.json"
BLACKLIST_PATH = "earnings_blacklist.json"


def check_symbol_earnings(symbol: str, blackout_days: int) -> dict | None:
    """Return earnings info if within blackout window, else None."""
    try:
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        if cal is None or cal.empty:
            return None
        # calendar index has 'Earnings Date' etc.
        if "Earnings Date" in cal.index:
            earnings_date = cal.loc["Earnings Date"].iloc[0]
            if not isinstance(earnings_date, datetime):
                earnings_date = datetime.combine(earnings_date, datetime.min.time())
            days_until = (earnings_date.date() - datetime.now().date()).days
            if -1 <= days_until <= blackout_days:
                return {
                    "symbol": symbol,
                    "earnings_date": earnings_date.strftime("%Y-%m-%d"),
                    "days_until": days_until,
                }
    except Exception:
        pass
    return None


def load_earnings_blacklist() -> set[str]:
    data = read_json(BLACKLIST_PATH, default=[])
    today = datetime.now().date()
    return {
        item["symbol"]
        for item in data
        if isinstance(item, dict)
        and "earnings_date" in item
        and (
            datetime.strptime(item["earnings_date"], "%Y-%m-%d").date() - today
        ).days
        <= config.EARNINGS_BLACKOUT_DAYS
    }


def main():
    watchlist = read_json(WATCHLIST_PATH, default=[])
    symbols = [item["symbol"] for item in watchlist if "symbol" in item]

    if not symbols:
        print("No watchlist symbols to check.")
        write_json(BLACKLIST_PATH, [])
        return

    blacklist = []
    for symbol in symbols:
        result = check_symbol_earnings(symbol, config.EARNINGS_BLACKOUT_DAYS)
        if result:
            blacklist.append(result)
            print(f"  {symbol}: earnings in {result['days_until']} days ({result['earnings_date']}) — BLACKOUT")

    write_json(BLACKLIST_PATH, blacklist)
    print(f"Earnings blacklist: {len(blacklist)} symbols blocked.")
    return blacklist


if __name__ == "__main__":
    main()
