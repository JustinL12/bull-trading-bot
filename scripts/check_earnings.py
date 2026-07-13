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
from lib.notify import post_attention
from lib.state import read_json, write_json


WATCHLIST_PATH = "watchlist_trend.json"
BLACKLIST_PATH = "earnings_blacklist.json"

# Above this fraction of lookup failures, treat the run as a systemic outage
# (e.g. yfinance blocked from this IP) rather than "no symbols have upcoming
# earnings" -- see scripts/update_pnl.py for the same yfinance-blocked issue.
FAILURE_RATE_ALERT_THRESHOLD = 0.5


def check_symbol_earnings(symbol: str, blackout_days: int) -> tuple[dict | None, bool]:
    """Return (earnings info if within blackout window else None, errored)."""
    try:
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        if cal is None or cal.empty:
            return None, False
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
                }, False
        return None, False
    except Exception:
        return None, True


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
    errors = 0
    for symbol in symbols:
        result, errored = check_symbol_earnings(symbol, config.EARNINGS_BLACKOUT_DAYS)
        errors += errored
        if result:
            blacklist.append(result)
            print(f"  {symbol}: earnings in {result['days_until']} days ({result['earnings_date']}) — BLACKOUT")

    error_rate = errors / len(symbols)
    if error_rate > FAILURE_RATE_ALERT_THRESHOLD:
        # Don't overwrite a real blacklist with an empty one built from mostly
        # failed lookups -- that would silently disable the earnings blackout.
        previous = read_json(BLACKLIST_PATH, default=[])
        post_attention(
            "Earnings check degraded",
            f"{errors}/{len(symbols)} symbol earnings lookups failed (yfinance may be "
            "blocked). Keeping the previous earnings_blacklist.json rather than "
            "overwriting it with an incomplete scan -- verify earnings dates manually "
            "before entering new positions.",
            level="warning",
        )
        print(f"Earnings check degraded: {errors}/{len(symbols)} lookups failed. Keeping previous blacklist ({len(previous)} symbols).")
        return previous

    write_json(BLACKLIST_PATH, blacklist)
    print(f"Earnings blacklist: {len(blacklist)} symbols blocked.")
    return blacklist


if __name__ == "__main__":
    main()
