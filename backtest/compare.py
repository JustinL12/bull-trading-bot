"""Run all strategy variants against the same universe and print ranked results."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from typing import Any

import config
from backtest import engine, metrics
from backtest.strategies.donchian import DonchianStrategy
from backtest.strategies.ma_crossover import MACrossoverStrategy
from backtest.strategies.tsmom import TSMOMStrategy


def build_all_strategies() -> list:
    strategies = []

    # Strategy A: MA Crossover variants
    for fast, slow in config.MA_FAST_SLOW_PAIRS:
        strategies.append(MACrossoverStrategy(fast, slow))

    # Strategy B: Donchian variants
    for period in config.DONCHIAN_ENTRY_PERIODS:
        strategies.append(DonchianStrategy(period))

    # Strategy C: TSMOM variants
    for months in config.TSMOM_LOOKBACK_MONTHS:
        strategies.append(TSMOMStrategy(months))
    strategies.append(TSMOMStrategy("composite"))

    return strategies


def run_all(
    universe_history: dict[str, Any],
    start_capital: float = 100_000.0,
    adx_rerun_top_n: int = 2,
) -> list[dict]:
    """Run all strategies; then re-run top N with ADX filter for comparison."""
    strategies = build_all_strategies()
    summaries = []

    total = len(strategies)
    for i, strat in enumerate(strategies, 1):
        print(f"[{i}/{total}] Running {strat.get_name()} ...")
        result = engine.run(strat, universe_history, start_capital)
        s = metrics.summary(result)
        s["_result"] = result
        summaries.append(s)

    # Re-run top N by Sharpe with ADX filter
    ranked = sorted(summaries, key=lambda x: x["sharpe"], reverse=True)
    adx_strategies = []
    for s in ranked[:adx_rerun_top_n]:
        name = s["strategy"]
        if name.startswith("Donchian"):
            period = int(name.split("-")[1].replace("d", ""))
            adx_strategies.append(DonchianStrategy(period, use_adx_filter=True))
        elif name.startswith("MA-"):
            parts = name.split("-")[1].split("/")
            adx_strategies.append(MACrossoverStrategy(int(parts[0]), int(parts[1]), use_adx_filter=True))
        elif name.startswith("TSMOM-"):
            label = name.split("-")[1]
            months = "composite" if label == "composite" else int(label.replace("m", ""))
            adx_strategies.append(TSMOMStrategy(months, use_adx_filter=True))

    for strat in adx_strategies:
        print(f"[ADX] Running {strat.get_name()} ...")
        result = engine.run(strat, universe_history, start_capital)
        s = metrics.summary(result)
        s["_result"] = result
        summaries.append(s)

    return summaries
