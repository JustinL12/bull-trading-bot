"""Build data/universe_trend.json: S&P 500 tickers + trend-friendly ETFs.

Reads existing data/universe.json and appends a curated list of ETFs that
exhibit strong trending behaviour across asset classes (equities, commodities,
bonds, international). Writes the merged list to data/universe_trend.json
so the live universe.json is untouched during backtesting.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

TREND_ETFS = [
    # Sector ETFs
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLB", "XLRE", "XLP", "XLU",
    # Broad market
    "QQQ", "IWM", "MDY", "VTI",
    # International
    "EEM", "EFA", "FXI", "EWJ", "EWZ", "EWG", "EWU", "IEMG",
    # Commodities
    "GLD", "SLV", "USO", "UNG", "DBC", "PDBC", "CORN", "WEAT",
    # Fixed income / rates
    "TLT", "IEF", "SHY", "HYG", "LQD", "EMB",
    # Volatility / alternatives
    "VIXY", "UVXY",
]


def main():
    base_path = Path("data/universe.json")
    if not base_path.exists():
        print(f"ERROR: {base_path} not found. Run build_universe.py first.")
        sys.exit(1)

    with open(base_path) as f:
        base = json.load(f)

    # universe.json is either a list of tickers or {"tickers": [...], "count": N}
    if isinstance(base, list):
        existing = set(base)
    elif isinstance(base, dict) and "tickers" in base:
        existing = set(base["tickers"])
    elif isinstance(base, dict):
        existing = set(base.keys())
    else:
        print("ERROR: unexpected universe.json format")
        sys.exit(1)

    merged = sorted(existing | set(TREND_ETFS))

    merged.sort()
    out_path = Path("data/universe_trend.json")
    with open(out_path, "w") as f:
        json.dump(merged, f, indent=2)

    added = len(merged) - len(existing)
    print(f"universe_trend.json: {len(merged)} tickers ({len(existing)} base + {added} trend ETFs)")
    print(f"Written to {out_path}")


if __name__ == "__main__":
    main()
