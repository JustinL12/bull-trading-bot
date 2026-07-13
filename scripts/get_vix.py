"""Fetch the latest VIX close and write data/vix.json.

Uses CBOE's public daily-prices CSV (the source Yahoo itself relays) instead
of yfinance -- yfinance's Yahoo endpoint is blocked from cloud/CI IPs (see
scripts/update_pnl.py), and unlike a price-history lookup this check gates
whether the bot enters new positions at all, so a silent/crashing failure
here is worse than a stale P&L stat.

Usage:
    python scripts/get_vix.py
"""

import csv
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.notify import post_attention
from lib.state import write_json

VIX_CSV_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


def fetch_latest_vix_close() -> tuple[str, float]:
    """Return (date, close) for the most recent VIX session. Raises on failure."""
    resp = requests.get(VIX_CSV_URL, timeout=15)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    if not rows:
        raise ValueError("CBOE VIX CSV returned no rows")
    last = rows[-1]
    date = datetime.strptime(last["DATE"], "%m/%d/%Y").strftime("%Y-%m-%d")
    return date, float(last["CLOSE"])


def main():
    try:
        date, close = fetch_latest_vix_close()
    except Exception as e:
        # Fail closed: a risk gate that can't verify current volatility should
        # not silently assume "calm" -- treat as suspended and flag it loudly.
        post_attention(
            "VIX fetch failed",
            f"Could not fetch VIX from CBOE ({e}). Treating as suspended "
            "(no new entries) until this resolves -- exits still process normally.",
            level="warning",
        )
        data = {
            "date": None,
            "close": None,
            "suspend_entries": True,
            "fetch_failed": True,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json("vix.json", data)
        print("VIX: fetch failed -- suspending new entries as a precaution")
        return data

    suspend = close > config.VIX_SUSPEND_THRESHOLD
    data = {
        "date": date,
        "close": close,
        "suspend_entries": suspend,
        "fetch_failed": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json("vix.json", data)
    print(f"VIX: {close:.2f} ({date}){' -- SUSPEND new entries' if suspend else ''}")
    return data


if __name__ == "__main__":
    main()
