"""Fetch upcoming earnings dates and write data/earnings_blacklist.json.

Uses Finnhub as the earnings calendar source.
Returns a set of symbol strings that are within the blackout window.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.finnhub_client import get_finnhub_client
from lib.state import read_json, write_json


WATCHLIST_PATH = "watchlist.json"
BLACKLIST_PATH = "earnings_blacklist.json"


def check_symbol_earnings(symbol: str, blackout_days: int) -> dict | None:
    """Return earnings info if within blackout window, else None."""
    try:
        client = get_finnhub_client()
        today = datetime.now().date()
        from_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        to_date = (today + timedelta(days=blackout_days)).strftime("%Y-%m-%d")
        res = client.earnings_calendar(
            _from=from_date, to=to_date, symbol=symbol, international=False
        )
        calendar = res.get("earningsCalendar", [])
        if not calendar:
            return None
        entry = calendar[0]
        earnings_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
        days_until = (earnings_date - today).days
        if -1 <= days_until <= blackout_days:
            return {
                "symbol": symbol,
                "earnings_date": entry["date"],
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
