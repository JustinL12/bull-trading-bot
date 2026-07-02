"""Universal backtest simulation engine.

Strategy-agnostic: any BaseStrategy subclass can be plugged in.
Fills at next-day open to avoid lookahead bias.
Uses Turtle-style ATR position sizing (1% equity risk per unit).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backtest.base_strategy import BaseStrategy
import config


@dataclass
class Position:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: float
    stop_price: float
    atr_at_entry: float
    strategy_name: str


@dataclass
class ClosedTrade:
    ticker: str
    strategy_name: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    shares: float
    pnl: float
    pnl_pct: float
    exit_reason: str


def _atr20(df: pd.DataFrame) -> float:
    """ATR(20) using EWM, same as lib/indicators.compute_atr."""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.ewm(com=config.ATR_PERIOD - 1, min_periods=config.ATR_PERIOD).mean()
    val = atr.iloc[-1]
    return float(val) if not pd.isna(val) else 0.0


def _unit_shares(equity: float, atr_dollar: float, price: float) -> float:
    """Turtle unit size: 1% equity risk / ATR dollars, floored to whole shares."""
    if atr_dollar <= 0 or price <= 0:
        return 0.0
    shares = (equity * config.TURTLE_RISK_PER_UNIT) / atr_dollar
    # Also cap at 10% equity per position
    max_shares_by_equity = (equity * 0.10) / price
    shares = min(shares, max_shares_by_equity)
    return max(0.0, shares)


def run(
    strategy: BaseStrategy,
    universe_history: dict[str, pd.DataFrame],
    start_capital: float = 100_000.0,
) -> dict[str, Any]:
    """Run a full backtest simulation.

    Returns dict with keys:
      trade_log: list of ClosedTrade dicts
      equity_curve: list of (date, equity) tuples
      daily_returns: list of float
      strategy: strategy name
    """
    # Build sorted union of all trading dates across the universe
    all_dates: pd.DatetimeIndex = pd.DatetimeIndex(
        sorted(set().union(*[set(df.index) for df in universe_history.values()]))
    )

    equity = start_capital
    open_positions: dict[str, Position] = {}  # ticker → Position
    trade_log: list[dict] = []
    equity_curve: list[tuple] = []
    prev_equity = equity

    # pending_entries: filled at next-day open
    # dict: ticker → (entry_open_price_date, stop_price, atr)
    pending_entries: dict[str, tuple] = {}

    for i, today in enumerate(all_dates):
        today_open_fills: list[str] = []

        # --- Fill pending entries at today's open ---
        for ticker, (target_date, stop, atr) in list(pending_entries.items()):
            if today != target_date:
                continue
            if ticker in open_positions:
                continue
            if len(open_positions) >= config.TURTLE_MAX_POSITIONS:
                continue
            hist = universe_history[ticker]
            if today not in hist.index:
                continue
            open_price = float(hist.loc[today, "open"])
            shares = _unit_shares(equity, atr, open_price)
            if shares < 1:
                continue
            cost = shares * open_price
            if cost > equity * 0.10:
                continue
            open_positions[ticker] = Position(
                ticker=ticker,
                entry_date=today,
                entry_price=open_price,
                shares=shares,
                stop_price=stop,
                atr_at_entry=atr,
                strategy_name=strategy.get_name(),
            )
            today_open_fills.append(ticker)
        for t in today_open_fills:
            pending_entries.pop(t, None)

        # --- Check exits for open positions ---
        for ticker in list(open_positions.keys()):
            pos = open_positions[ticker]
            hist = universe_history[ticker]
            if today not in hist.index:
                continue
            today_low = float(hist.loc[today, "low"])
            today_close = float(hist.loc[today, "close"])

            exit_reason = None
            exit_price = today_close

            # Hard stop hit (use today's low as proxy for intraday fill)
            if today_low <= pos.stop_price:
                exit_price = pos.stop_price
                exit_reason = "stop"
            else:
                # Strategy signal (evaluated on history up to and including today)
                history_slice = hist.loc[:today]
                sig = strategy.generate_signal(history_slice)
                if sig == "exit":
                    exit_reason = "signal"

            if exit_reason:
                pnl = (exit_price - pos.entry_price) * pos.shares
                pnl_pct = (exit_price - pos.entry_price) / pos.entry_price
                trade_log.append({
                    "ticker": ticker,
                    "strategy": strategy.get_name(),
                    "entry_date": pos.entry_date.strftime("%Y-%m-%d"),
                    "exit_date": today.strftime("%Y-%m-%d"),
                    "entry_price": round(pos.entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "shares": round(pos.shares, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 6),
                    "exit_reason": exit_reason,
                })
                equity += pnl
                del open_positions[ticker]

        # --- Scan for new entries (fill tomorrow's open) ---
        if i + 1 < len(all_dates):
            next_date = all_dates[i + 1]
            for ticker, hist in universe_history.items():
                if ticker in open_positions or ticker in pending_entries:
                    continue
                if len(open_positions) + len(pending_entries) >= config.TURTLE_MAX_POSITIONS:
                    break
                if today not in hist.index:
                    continue
                history_slice = hist.loc[:today]
                if len(history_slice) < config.ATR_PERIOD + 5:
                    continue
                sig = strategy.generate_signal(history_slice)
                if sig == "enter":
                    atr = _atr20(history_slice)
                    if atr <= 0:
                        continue
                    today_close = float(hist.loc[today, "close"])
                    stop = strategy.get_stop_price(today_close, atr)
                    pending_entries[ticker] = (next_date, stop, atr)

        # Mark-to-market equity (unrealised P&L on open positions)
        mtm = equity
        for ticker, pos in open_positions.items():
            hist = universe_history[ticker]
            if today in hist.index:
                current = float(hist.loc[today, "close"])
                mtm += (current - pos.entry_price) * pos.shares

        daily_return = (mtm - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        equity_curve.append((today, mtm))
        prev_equity = mtm

    return {
        "strategy": strategy.get_name(),
        "trade_log": trade_log,
        "equity_curve": equity_curve,
        "start_capital": start_capital,
        "end_equity": equity,
    }
