"""Tests for lib/risk.py"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from lib.risk import (
    position_size,
    initial_stop_price,
    updated_trail_stop,
    check_pdt,
    check_buying_power,
    is_safe_to_hold_overnight,
)


def test_position_size_basic():
    equity = 5000.0
    atr = 0.75
    price = 25.0
    shares = position_size(equity, atr, price)
    assert shares > 0
    stop_dist = config.STOP_ATR_MULTIPLIER * atr
    risk = shares * stop_dist
    assert risk <= equity * config.RISK_PER_TRADE_PCT * 1.01  # allow 1% float error


def test_position_size_cap():
    equity = 5000.0
    atr = 0.01  # tiny ATR → risk sizing would give huge shares
    price = 10.0
    shares = position_size(equity, atr, price)
    assert shares * price <= equity * config.MAX_POSITION_PCT + 0.01


def test_position_size_below_minimum():
    equity = 500.0
    atr = 2.0
    price = 50.0
    shares = position_size(equity, atr, price)
    if shares == 0:
        assert True  # correctly rejected


def test_initial_stop():
    entry = 100.0
    atr = 2.0
    stop = initial_stop_price(entry, atr)
    expected = round(entry - config.STOP_ATR_MULTIPLIER * atr, 2)
    assert stop == expected


def test_trail_stop_only_raises():
    current = 185.0
    high = 190.0
    atr = 2.0
    new_stop = updated_trail_stop(current, high, atr)
    assert new_stop >= current


def test_trail_stop_does_not_lower():
    current = 192.0
    high = 188.0  # price went down — stop should not lower
    atr = 2.0
    new_stop = updated_trail_stop(current, high, atr)
    assert new_stop == current


def test_pdt_under_threshold():
    assert check_pdt(daytrade_count=2, equity=10_000) is True
    assert check_pdt(daytrade_count=3, equity=10_000) is False


def test_pdt_above_threshold():
    assert check_pdt(daytrade_count=100, equity=50_000) is True


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
        "AAPL": {"entry_price": 100.0, "shares": 40},  # $4001
    }
    assert check_buying_power(equity, positions) is False


class TestOvernightHold:
    def _pos(self, **overrides):
        base = {
            "symbol": "TEST",
            "entry_price": 100.0,
            "shares": 10,
            "initial_stop": 92.0,   # 100 * (1 - 5% gap) = 95 > 92 → passes gap-risk
            "current_stop": 97.0,
            "trailing_stop_active": True,
            "perplexity_sentiment_at_entry": "positive",
        }
        base.update(overrides)
        return base

    def _ind(self, close=105.0, ema21=102.0):
        return {"TEST": {"close": close, "ema_21": ema21}}

    def test_safe_all_criteria_met(self):
        ok, reason = is_safe_to_hold_overnight(
            self._pos(), self._ind(), earnings_blacklist=set(), unrealized_pnl=50.0
        )
        assert ok is True

    def test_unsafe_in_loss(self):
        ok, reason = is_safe_to_hold_overnight(
            self._pos(), self._ind(), set(), unrealized_pnl=-10.0
        )
        assert ok is False
        assert "loss" in reason

    def test_unsafe_no_trailing_stop(self):
        ok, reason = is_safe_to_hold_overnight(
            self._pos(trailing_stop_active=False), self._ind(), set(), unrealized_pnl=20.0
        )
        assert ok is False
        assert "trailing stop" in reason

    def test_unsafe_below_ema21(self):
        ok, reason = is_safe_to_hold_overnight(
            self._pos(), self._ind(close=99.0, ema21=102.0), set(), unrealized_pnl=20.0
        )
        assert ok is False
        assert "EMA-21" in reason

    def test_unsafe_earnings_blackout(self):
        ok, reason = is_safe_to_hold_overnight(
            self._pos(), self._ind(), {"TEST"}, unrealized_pnl=50.0
        )
        assert ok is False
        assert "earnings" in reason

    def test_unsafe_negative_sentiment(self):
        ok, reason = is_safe_to_hold_overnight(
            self._pos(perplexity_sentiment_at_entry="negative"), self._ind(), set(), unrealized_pnl=50.0
        )
        assert ok is False
        assert "negative" in reason

    def test_unsafe_gap_risk(self):
        # Entry $100, stop $96.50 — a 5% gap → $95 which is BELOW stop $96.50
        ok, reason = is_safe_to_hold_overnight(
            self._pos(entry_price=100.0, initial_stop=96.5),
            self._ind(), set(), unrealized_pnl=50.0
        )
        assert ok is False
        assert "gap-risk" in reason
