"""Strategy B: Donchian Channel Breakout (Turtle Trader style).

Entry:  close > highest close of last N days (breakout)
Exit:   close < lowest low of last N//2 days
Stop:   2 × ATR(20) below entry (hard stop between exit signals)

Variants: N=20 (faster, more trades) and N=55 (slower, fewer trades).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
from backtest.base_strategy import BaseStrategy
from lib.indicators import donchian_high, donchian_low, adx as compute_adx
import config


class DonchianStrategy(BaseStrategy):
    def __init__(self, entry_period: int = 20, use_adx_filter: bool = False):
        self.entry_period = entry_period
        self.exit_period = max(entry_period // 2, 5)
        self._use_adx_filter = use_adx_filter

    def get_name(self) -> str:
        suffix = "+ADX" if self._use_adx_filter else ""
        return f"Donchian-{self.entry_period}d{suffix}"

    def get_adx_filter(self) -> bool:
        return self._use_adx_filter

    def generate_signal(self, history: pd.DataFrame) -> str:
        min_rows = self.entry_period + 1
        if len(history) < min_rows:
            return "hold"

        close = history["close"]
        # Entry: today's close breaks above the prior N-bar high (not including today)
        prior_high = donchian_high(history.iloc[:-1], self.entry_period).iloc[-1]
        current_close = float(close.iloc[-1])

        if pd.isna(prior_high):
            return "hold"

        # Exit: today's close below the prior N//2 day low (exclude today so close >= low[today] doesn't make it impossible)
        if len(history) > self.exit_period:
            exit_low = donchian_low(history.iloc[:-1], self.exit_period).iloc[-1]
            if not pd.isna(exit_low) and current_close < float(exit_low):
                return "exit"

        # ADX filter
        if self._use_adx_filter:
            adx_series = compute_adx(history, config.ADX_PERIOD)
            adx_val = adx_series.iloc[-1]
            if pd.isna(adx_val) or adx_val < config.ADX_TREND_THRESHOLD:
                return "hold"

        if current_close > float(prior_high):
            return "enter"

        return "hold"
