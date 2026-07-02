"""Abstract base class for all backtest strategies."""

from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    """All strategies inherit from this. The engine calls only these methods."""

    @abstractmethod
    def get_name(self) -> str:
        """Human-readable strategy name (used in comparison table)."""

    @abstractmethod
    def generate_signal(self, history: pd.DataFrame) -> str:
        """Given history up to and including today, return "enter", "exit", or "hold".

        history: daily OHLCV DataFrame ending on the current simulation date.
        Must NOT look at any row beyond the last index (no lookahead).
        """

    def get_stop_price(self, entry_price: float, atr: float) -> float:
        """Hard stop price = entry - 2 × ATR(20). Shared across all strategies."""
        return entry_price - 2.0 * atr

    def get_adx_filter(self) -> bool:
        """If True, entry is blocked when ADX(14) < ADX_TREND_THRESHOLD."""
        return False
