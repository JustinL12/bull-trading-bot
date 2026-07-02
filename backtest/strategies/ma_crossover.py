"""Strategy A: Moving Average Crossover.

Entry:  fast EMA crosses above slow EMA (golden cross on daily bars)
Exit:   fast EMA crosses below slow EMA (death cross)
Stop:   2 × ATR(20) below entry (hard stop)

Variants: (fast, slow) = (10,50), (20,60), (50,200)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
from backtest.base_strategy import BaseStrategy
from lib.indicators import compute_ema, adx as compute_adx
import config


class MACrossoverStrategy(BaseStrategy):
    def __init__(self, fast: int = 20, slow: int = 60, use_adx_filter: bool = False):
        self.fast = fast
        self.slow = slow
        self._use_adx_filter = use_adx_filter

    def get_name(self) -> str:
        suffix = "+ADX" if self._use_adx_filter else ""
        return f"MA-{self.fast}/{self.slow}{suffix}"

    def get_adx_filter(self) -> bool:
        return self._use_adx_filter

    def generate_signal(self, history: pd.DataFrame) -> str:
        min_rows = self.slow + 2
        if len(history) < min_rows:
            return "hold"

        df = history.copy()
        compute_ema(df, self.fast)
        compute_ema(df, self.slow)

        fast_col = f"ema_{self.fast}"
        slow_col = f"ema_{self.slow}"

        cur_fast = df[fast_col].iloc[-1]
        cur_slow = df[slow_col].iloc[-1]
        prev_fast = df[fast_col].iloc[-2]
        prev_slow = df[slow_col].iloc[-2]

        if any(pd.isna(v) for v in [cur_fast, cur_slow, prev_fast, prev_slow]):
            return "hold"

        # Death cross → exit signal
        if cur_fast < cur_slow and prev_fast >= prev_slow:
            return "exit"

        # ADX filter
        if self._use_adx_filter:
            adx_series = compute_adx(history, config.ADX_PERIOD)
            adx_val = adx_series.iloc[-1]
            if pd.isna(adx_val) or adx_val < config.ADX_TREND_THRESHOLD:
                return "hold"

        # Golden cross → entry signal
        if cur_fast > cur_slow and prev_fast <= prev_slow:
            return "enter"

        return "hold"
