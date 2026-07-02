"""Strategy C: Time-Series Momentum (TSMOM).

Entry:  N-month return > 0 (asset is in an uptrend over the lookback window)
Exit:   N-month return <= 0 (momentum has reversed)
Rebal:  Monthly — evaluated only on the first trading day of each month.
        Between rebalances, the hard ATR stop is the only exit mechanism.

Variants: lookback = 1, 3, 6, 12 months; composite = avg of 3+6+12.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
from backtest.base_strategy import BaseStrategy
from lib.indicators import tsmom_return, adx as compute_adx
import config


class TSMOMStrategy(BaseStrategy):
    def __init__(self, months: int | str = 12, use_adx_filter: bool = False):
        """months: integer lookback, or 'composite' for avg of 3/6/12."""
        self.months = months
        self._use_adx_filter = use_adx_filter
        self._last_signal_month: int | None = None
        self._cached_signal: str = "hold"

    def get_name(self) -> str:
        label = "composite" if self.months == "composite" else f"{self.months}m"
        suffix = "+ADX" if self._use_adx_filter else ""
        return f"TSMOM-{label}{suffix}"

    def get_adx_filter(self) -> bool:
        return self._use_adx_filter

    def _momentum_positive(self, history: pd.DataFrame) -> bool:
        if self.months == "composite":
            scores = [tsmom_return(history, m) for m in [3, 6, 12]]
            valid = [s for s in scores if s is not None]
            if not valid:
                return False
            return (sum(valid) / len(valid)) > 0
        else:
            ret = tsmom_return(history, self.months)
            return ret is not None and ret > 0

    def generate_signal(self, history: pd.DataFrame) -> str:
        # Only re-evaluate on the first trading day of each calendar month
        current_date = history.index[-1]
        current_month = current_date.month

        if self._last_signal_month == current_month:
            return self._cached_signal

        # New month — recompute
        self._last_signal_month = current_month
        pos = self._momentum_positive(history)

        if self._use_adx_filter and pos:
            adx_series = compute_adx(history, config.ADX_PERIOD)
            adx_val = adx_series.iloc[-1]
            if pd.isna(adx_val) or adx_val < config.ADX_TREND_THRESHOLD:
                pos = False

        if pos:
            self._cached_signal = "enter"
        else:
            self._cached_signal = "exit"

        return self._cached_signal
