"""CLI entry point for the backtesting framework.

Usage:
  # Full comparison of all strategies
  python backtest/run_backtest.py --start 2015-01-01 --end 2025-12-31 --compare

  # Single strategy
  python backtest/run_backtest.py --strategy donchian --period 55 --start 2015-01-01 --end 2025-12-31

  # Out-of-sample split (train on first half, validate on second)
  python backtest/run_backtest.py --compare --start 2015-01-01 --end 2025-12-31 --oos-split 2021-01-01
"""

import sys
import argparse
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from backtest.data_loader import load_universe_history
from backtest import engine, metrics, compare
from backtest.strategies.donchian import DonchianStrategy
from backtest.strategies.ma_crossover import MACrossoverStrategy
from backtest.strategies.tsmom import TSMOMStrategy


RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def load_universe(universe_file: str) -> list[str]:
    path = Path(universe_file)
    if not path.exists():
        path = Path("data") / universe_file
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    # Handle universe.json format: {"tickers": [...]} or dict of ticker→info
    if "tickers" in data:
        return data["tickers"]
    return list(data.keys())


def save_results(summaries: list[dict], label: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"run_{label}_{ts}.json"
    # Strip _result key (engine output, too large to save cleanly)
    clean = [{k: v for k, v in s.items() if k != "_result"} for s in summaries]
    with open(out_path, "w") as f:
        json.dump(clean, f, indent=2)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Trend Following Backtest")
    parser.add_argument("--start", default="2015-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="2025-12-31", help="End date YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Starting capital")
    parser.add_argument("--universe", default=config.BACKTEST_UNIVERSE_FILE, help="Universe JSON file")
    parser.add_argument("--compare", action="store_true", help="Run all strategy variants")
    parser.add_argument("--strategy", choices=["donchian", "ma", "tsmom"], help="Single strategy type")
    parser.add_argument("--period", type=int, default=20, help="Period for donchian/ma fast period")
    parser.add_argument("--slow", type=int, default=60, help="Slow period for MA crossover")
    parser.add_argument("--months", default="12", help="Lookback months for TSMOM (or 'composite')")
    parser.add_argument("--adx", action="store_true", help="Apply ADX filter to strategy")
    parser.add_argument("--oos-split", default=None, help="Out-of-sample split date; runs train then validate")
    args = parser.parse_args()

    print(f"Loading universe from {args.universe} ...")
    try:
        tickers = load_universe(args.universe)
    except FileNotFoundError:
        # Fall back to base universe
        print(f"  {args.universe} not found, falling back to data/universe_trend.json then data/universe.json")
        for fallback in ["data/universe_trend.json", "data/universe.json"]:
            try:
                tickers = load_universe(fallback)
                break
            except FileNotFoundError:
                continue
        else:
            print("ERROR: no universe file found.")
            sys.exit(1)

    print(f"Universe: {len(tickers)} tickers | Period: {args.start} to {args.end}")

    if args.oos_split:
        # Train + validate run
        for label, start, end in [("train", args.start, args.oos_split), ("validate", args.oos_split, args.end)]:
            print(f"\n{'='*50}\n{label.upper()}: {start} to {end}\n{'='*50}")
            hist = load_universe_history(tickers, start, end)
            print(f"Loaded {len(hist)} tickers with sufficient history.")
            summaries = compare.run_all(hist, args.capital)
            metrics.print_table(summaries)
            path = save_results(summaries, label)
            print(f"Results saved to {path}")
        return

    print(f"Fetching historical data ...")
    universe_history = load_universe_history(tickers, args.start, args.end)
    print(f"Loaded {len(universe_history)} tickers with sufficient history.\n")

    if args.compare:
        summaries = compare.run_all(universe_history, args.capital)
        metrics.print_table(summaries)
        path = save_results(summaries, "compare")
        print(f"\nResults saved to {path}")

    elif args.strategy:
        if args.strategy == "donchian":
            strat = DonchianStrategy(args.period, use_adx_filter=args.adx)
        elif args.strategy == "ma":
            strat = MACrossoverStrategy(args.period, args.slow, use_adx_filter=args.adx)
        elif args.strategy == "tsmom":
            months = "composite" if args.months == "composite" else int(args.months)
            strat = TSMOMStrategy(months, use_adx_filter=args.adx)

        print(f"Running {strat.get_name()} ...")
        result = engine.run(strat, universe_history, args.capital)
        s = metrics.summary(result)
        metrics.print_table([s])

        path = save_results([s], strat.get_name().lower().replace("/", "-").replace(" ", "_"))
        print(f"\nResults saved to {path}")

        # Print individual trades
        if result["trade_log"]:
            print(f"\nTrade log ({len(result['trade_log'])} trades):")
            print(f"  {'Ticker':<8} {'Entry':<12} {'Exit':<12} {'Entry$':>8} {'Exit$':>8} {'P&L':>9} {'Reason'}")
            for t in result["trade_log"]:
                print(f"  {t['ticker']:<8} {t['entry_date']:<12} {t['exit_date']:<12} "
                      f"{t['entry_price']:>8.2f} {t['exit_price']:>8.2f} "
                      f"{t['pnl']:>+9.2f} {t['exit_reason']}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
