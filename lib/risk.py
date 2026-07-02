"""Risk management: position sizing, kill switch, PDT, overnight hold safety."""

import math
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.notify import post_attention
from lib.state import flag_exists, read_json, set_flag


def turtle_unit_size(equity: float, atr_dollar: float, price: float) -> int:
    """Turtle-style position size: 1% equity risk per unit.

    Unit = (equity × TURTLE_RISK_PER_UNIT) / ATR_dollar, capped at 10% notional.
    Returns whole shares; returns 0 if inputs are invalid or position too small.
    """
    if atr_dollar <= 0 or price <= 0 or equity <= 0:
        return 0
    shares = (equity * config.TURTLE_RISK_PER_UNIT) / atr_dollar
    max_shares_by_notional = (equity * 0.10) / price
    shares = min(shares, max_shares_by_notional)
    shares = math.floor(shares)
    if shares * price < config.MIN_NOTIONAL:
        return 0
    return shares


def turtle_stop_price(entry_price: float, atr: float) -> float:
    """Hard stop = entry - BACKTEST_STOP_ATR_MULT × ATR(20)."""
    return round(entry_price - config.BACKTEST_STOP_ATR_MULT * atr, 2)


def check_kill_switch(equity: float, starting_equity: float) -> bool:
    """Return True (and set flag) if daily loss limit is breached."""
    if flag_exists("kill_switch.flag"):
        return True
    pnl_pct = (equity - starting_equity) / starting_equity * 100
    if pnl_pct <= -config.DAILY_LOSS_LIMIT_PCT:
        set_flag("kill_switch.flag")
        print(f"KILL SWITCH: daily loss {pnl_pct:.2f}% exceeded -{config.DAILY_LOSS_LIMIT_PCT}%")
        post_attention(
            "Kill Switch Triggered",
            f"Daily loss of {pnl_pct:.2f}% exceeded the -{config.DAILY_LOSS_LIMIT_PCT}% limit.\n"
            f"Kill switch flag set. No new entries will be placed today.",
            level="critical",
        )
        return True
    return False


def check_buying_power(equity: float, positions: dict) -> bool:
    """Return True if we have enough free buying power for a new position."""
    total_deployed = sum(
        p.get("entry_price", 0) * p.get("shares", 0)
        for p in positions.values()
    )
    max_deployed = equity * config.MAX_EQUITY_DEPLOYED_PCT / 100
    return total_deployed < max_deployed


