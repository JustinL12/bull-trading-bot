"""Tests for lib/risk.py"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from lib.risk import (
    check_buying_power,
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
