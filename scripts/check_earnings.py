"""Fetch upcoming earnings dates and write data/earnings_blacklist.json.

Uses the Nasdaq public earnings calendar API instead of yfinance — yfinance's
Yahoo endpoint is blocked from cloud/CI IPs (the same issue that affected the
VIX and SPY lookups, see scripts/get_vix.py and scripts/update_pnl.py).

The Nasdaq API returns a day-by-day earnings schedule with no auth required.
We query every calendar day from today through today + EARNINGS_BLACKOUT_DAYS
and flag any watchlist symbol that appears.
"""

import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.notify import post_attention
from lib.state import read_json, write_json


WATCHLIST_PATH = "watchlist_trend.json"
BLACKLIST_PATH = "earnings_blacklist.json"

NASDAQ_CALENDAR_URL = "https://api.nasdaq.com/api/calendar/earnings"
NASDAQ_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# Fraction of date-queries that must succeed; below this we treat the run as
# a network outage and keep the previous blacklist rather than clearing it.
FAILURE_RATE_ALERT_THRESHOLD = 0.5


def fetch_earnings_on_date(d: date) -> tuple[list[dict], bool]:
    """Return (rows, errored) for the given calendar date."""
    try:
        resp = requests.get(
            NASDAQ_CALENDAR_URL,
            params={"date": d.isoformat()},
            headers=NASDAQ_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json().get("data", {}).get("rows") or []
        return rows, False
    except Exception:
        return [], True


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
    symbols = {item["symbol"] for item in watchlist if "symbol" in item}

    if not symbols:
        print("No watchlist symbols to check.")
        write_json(BLACKLIST_PATH, [])
        return []

    today = date.today()
    days_to_check = config.EARNINGS_BLACKOUT_DAYS + 1  # inclusive of the boundary day

    found: dict[str, dict] = {}  # symbol -> first match
    errors = 0

    for i in range(days_to_check):
        d = today + timedelta(days=i)
        rows, errored = fetch_earnings_on_date(d)
        if errored:
            errors += 1
        for row in rows:
            sym = row.get("symbol", "")
            if sym in symbols and sym not in found:
                found[sym] = {
                    "symbol": sym,
                    "earnings_date": d.isoformat(),
                    "days_until": i,
                    "time_of_day": row.get("time", ""),
                }
                print(f"  {sym}: earnings in {i} days ({d}) — BLACKOUT")
        # Light rate-limit courtesy (15 requests over 14 days is already gentle)
        if i < days_to_check - 1:
            time.sleep(0.1)

    error_rate = errors / days_to_check
    if error_rate > FAILURE_RATE_ALERT_THRESHOLD:
        previous = read_json(BLACKLIST_PATH, default=[])
        post_attention(
            "Earnings check degraded",
            f"{errors}/{days_to_check} Nasdaq calendar date queries failed. "
            "Keeping the previous earnings_blacklist.json rather than overwriting "
            "it with an incomplete scan — verify earnings dates manually before "
            "entering new positions.",
            level="warning",
        )
        print(
            f"Earnings check degraded: {errors}/{days_to_check} date queries failed. "
            f"Keeping previous blacklist ({len(previous)} symbols)."
        )
        return previous

    blacklist = list(found.values())
    write_json(BLACKLIST_PATH, blacklist)
    print(f"Earnings blacklist: {len(blacklist)} symbols blocked. ({errors} date-query errors out of {days_to_check})")
    return blacklist


if __name__ == "__main__":
    main()
