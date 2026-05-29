"""Risk management: position sizing, kill switch, PDT, overnight hold safety."""

import math
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.state import flag_exists, read_json, set_flag


def position_size(equity: float, atr: float, price: float) -> int:
    """Return number of whole shares to buy, respecting risk and position caps."""
    if atr <= 0 or price <= 0 or equity <= 0:
        return 0

    stop_distance = config.STOP_ATR_MULTIPLIER * atr
    risk_dollars = equity * config.RISK_PER_TRADE_PCT
    shares_by_risk = math.floor(risk_dollars / stop_distance)

    max_notional = equity * config.MAX_POSITION_PCT
    shares_by_cap = math.floor(max_notional / price)

    shares = min(shares_by_risk, shares_by_cap)

    if shares * price < config.MIN_NOTIONAL:
        return 0

    return shares


def initial_stop_price(entry_price: float, atr: float) -> float:
    stop = entry_price - config.STOP_ATR_MULTIPLIER * atr
    return round(stop, 2)


def updated_trail_stop(
    current_stop: float,
    highest_close: float,
    atr: float,
) -> float:
    """Calculate new trailing stop; only raises, never lowers."""
    new_stop = highest_close - config.TRAIL_ATR_MULTIPLIER * atr
    return round(max(current_stop, new_stop), 2)


def check_kill_switch(equity: float, starting_equity: float) -> bool:
    """Return True (and set flag) if daily loss limit is breached."""
    if flag_exists("kill_switch.flag"):
        return True
    pnl_pct = (equity - starting_equity) / starting_equity * 100
    if pnl_pct <= -config.DAILY_LOSS_LIMIT_PCT:
        set_flag("kill_switch.flag")
        print(f"KILL SWITCH: daily loss {pnl_pct:.2f}% exceeded -{config.DAILY_LOSS_LIMIT_PCT}%")
        return True
    return False


def check_pdt(daytrade_count: int, equity: float) -> bool:
    """Return True if a new day trade is allowed (False = blocked by PDT)."""
    if equity >= config.PDT_ACCOUNT_THRESHOLD:
        return True  # PDT rule doesn't apply above $25k
    return daytrade_count < config.PDT_MAX_DAY_TRADES


def check_buying_power(equity: float, positions: dict) -> bool:
    """Return True if we have enough free buying power for a new position."""
    total_deployed = sum(
        p.get("entry_price", 0) * p.get("shares", 0)
        for p in positions.values()
    )
    max_deployed = equity * config.MAX_EQUITY_DEPLOYED_PCT / 100
    return total_deployed < max_deployed


def is_safe_to_hold_overnight(
    position: dict,
    indicators: dict,
    earnings_blacklist: set[str],
    unrealized_pnl: float,
) -> tuple[bool, str]:
    """
    Evaluate whether a position is safe to hold overnight.
    Returns (bool, reason_string).
    """
    symbol = position.get("symbol", position.get("Symbol", "?"))

    # 1. Must be profitable
    if unrealized_pnl <= 0:
        return False, "position is in loss"

    # 2. Trailing stop must be active (at least +1.5 ATR profitable)
    if not position.get("trailing_stop_active", False):
        return False, "trailing stop not yet active — insufficient cushion"

    # 3. Price > EMA-21 at close
    ind = indicators.get(symbol, {})
    close = ind.get("close")
    ema21 = ind.get("ema_21")
    if close and ema21 and close < ema21:
        return False, f"price {close} below EMA-21 {ema21} — trend deteriorating"

    # 4. No earnings within OVERNIGHT_EARNINGS_DAYS trading days
    if symbol in earnings_blacklist:
        return False, "earnings within blackout window"

    # 5. Perplexity sentiment at entry was not negative
    if position.get("perplexity_sentiment_at_entry") == "negative":
        return False, "Perplexity sentiment at entry was negative"

    # 6. Gap-risk cushion: survive a 5% adverse gap above initial stop
    entry_price = position.get("entry_price", 0)
    initial_stop = position.get("initial_stop", 0)
    if entry_price > 0:
        worst_case_price = entry_price * (1 - config.OVERNIGHT_GAP_RISK_PCT / 100)
        if worst_case_price < initial_stop:
            return False, f"gap-risk check failed: {config.OVERNIGHT_GAP_RISK_PCT}% gap would pierce initial stop"

    return True, "all overnight criteria met"
