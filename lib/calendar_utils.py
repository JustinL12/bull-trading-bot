"""Market calendar utilities."""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.alpaca_client import get_trading_client
from lib.state import read_json


def is_market_open() -> bool:
    """Check with Alpaca's clock endpoint — authoritative source."""
    try:
        client = get_trading_client()
        clock = client.get_clock()
        return clock.is_open
    except Exception as e:
        print(f"Warning: could not check market clock: {e}")
        return False


def is_fomc_day() -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    no_trade_dates = read_json("no_trade_dates.json", default=[])
    return today in no_trade_dates


def is_earnings_blackout(symbol: str) -> bool:
    blacklist = read_json("earnings_blacklist.json", default=[])
    blocked = {item["symbol"] for item in blacklist if isinstance(item, dict)}
    return symbol in blocked


def current_et_time() -> tuple[int, int]:
    """Return (hour, minute) in US Eastern time."""
    import pytz
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    return now.hour, now.minute


def is_within_entry_window() -> bool:
    """Return True if current ET time is within the allowed entry window."""
    import config
    h, m = current_et_time()
    start = config.ENTRY_START_HOUR_ET * 60 + config.ENTRY_START_MIN_ET
    end = config.ENTRY_END_HOUR_ET * 60 + config.ENTRY_END_MIN_ET
    current = h * 60 + m
    return start <= current <= end
