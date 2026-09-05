"""Tests for lib/risk.py"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from lib.risk import (
    check_buying_power,
    partial_profit_shares,
    profit_lock_triggered,
    trailing_stop_price,
    turtle_unit_size,
    turtle_stop_price,
)


def test_buying_power_ok():
    equity = 5000.0
    positions = {
        "AAPL": {"entry_price": 100.0, "shares": 10},  # $1000
        "NVDA": {"entry_price": 100.0, "shares": 10},  # $1000
    }
    assert check_buying_power(equity, positions) is True


def test_buying_power_exceeded():
    equity = 5000.0
    positions = {
        "AAPL": {"entry_price": 100.0, "shares": 40},  # $4000 > 80% of $5000
    }
    assert check_buying_power(equity, positions) is False


def test_turtle_unit_size_basic():
    equity = 100_000.0
    atr = 2.0    # $2 ATR on a $50 stock
    price = 50.0
    shares = turtle_unit_size(equity, atr, price)
    # risk sizing: (100000 × 0.01) / 2.0 = 500 shares
    # notional cap: (100000 × 0.10) / 50 = 200 shares → capped here
    assert shares == 200


def test_turtle_unit_size_risk_dominated():
    equity = 100_000.0
    atr = 5.0    # large ATR on a cheap stock
    price = 10.0
    shares = turtle_unit_size(equity, atr, price)
    # risk sizing: (100000 × 0.01) / 5.0 = 200 shares
    # notional cap: (100000 × 0.10) / 10 = 1000 shares → risk dominates
    assert shares == 200


def test_turtle_unit_size_zero_on_bad_inputs():
    assert turtle_unit_size(0, 2.0, 50.0) == 0
    assert turtle_unit_size(100_000, 0, 50.0) == 0
    assert turtle_unit_size(100_000, 2.0, 0) == 0


def test_turtle_stop_price():
    stop = turtle_stop_price(100.0, 2.0)
    assert stop == round(100.0 - config.BACKTEST_STOP_ATR_MULT * 2.0, 2)


def test_turtle_stop_below_entry():
    stop = turtle_stop_price(50.0, 1.0)
    assert stop < 50.0


def test_profit_lock_not_triggered_below_threshold():
    # gain of $3 vs a $2 ATR at entry (1.5x) is below the 2x PROFIT_LOCK_ATR_MULT
    assert profit_lock_triggered(current_close=103.0, entry_price=100.0, atr_at_entry=2.0) is False


def test_profit_lock_triggered_at_threshold():
    # gain of exactly 2x ATR at entry triggers (boundary is inclusive)
    assert profit_lock_triggered(current_close=104.0, entry_price=100.0, atr_at_entry=2.0) is True


def test_profit_lock_triggered_above_threshold():
    assert profit_lock_triggered(current_close=110.0, entry_price=100.0, atr_at_entry=2.0) is True


def test_profit_lock_false_on_nonpositive_atr():
    assert profit_lock_triggered(current_close=110.0, entry_price=100.0, atr_at_entry=0) is False
    assert profit_lock_triggered(current_close=110.0, entry_price=100.0, atr_at_entry=-1.0) is False


def test_partial_profit_shares_normal_fraction():
    # PARTIAL_PROFIT_FRACTION defaults to 1/3
    assert partial_profit_shares(shares=90, already_partial_sold=False) == 30


def test_partial_profit_shares_floors():
    assert partial_profit_shares(shares=100, already_partial_sold=False) == 33


def test_partial_profit_shares_zero_when_already_sold():
    assert partial_profit_shares(shares=90, already_partial_sold=True) == 0


def test_partial_profit_shares_zero_on_small_position():
    assert partial_profit_shares(shares=2, already_partial_sold=False) == 0


def test_trailing_stop_price_below_highest_close():
    stop = trailing_stop_price(highest_close=120.0, atr=3.0)
    assert stop == round(120.0 - config.TRAILING_STOP_ATR_MULT * 3.0, 2)
    assert stop < 120.0


def test_trailing_stop_ratchets_up_after_new_high():
    # Position ran from 100 to a new high of 140 on tightening ATR: the caller's
    # "only raise" rule (candidate > current_stop) should say yes, raise it.
    current_stop = 92.0  # e.g. the original 2xATR hard stop
    candidate = trailing_stop_price(highest_close=140.0, atr=3.0)
    assert candidate > current_stop


def test_trailing_stop_does_not_ratchet_down_on_pullback():
    # Price pulled back from its high and ATR widened: the caller must not
    # lower current_stop just because a fresh candidate comes out lower.
    current_stop = 130.0  # already raised on a prior, higher high
    candidate = trailing_stop_price(highest_close=135.0, atr=10.0)  # wide ATR narrows the cushion
    assert candidate < current_stop
    # The caller's rule is `if candidate > current_stop: raise it` — since that's
    # False here, current_stop must be left unchanged.
