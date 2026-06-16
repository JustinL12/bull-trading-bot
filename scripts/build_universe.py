"""One-time setup: fetch S&P 500 + NASDAQ 100 tickers and write data/universe.json.

Run this manually whenever the index composition changes (roughly quarterly).

    python scripts/build_universe.py

Requires: pandas (for Wikipedia table parsing)
"""

import io
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.state import write_json

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; bull-trading-bot/1.0)"}


def _fetch_html(url: str) -> io.StringIO:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return io.StringIO(resp.text)


def fetch_sp500() -> list[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(_fetch_html(url), attrs={"id": "constituents"})
    return tables[0]["Symbol"].tolist()


def fetch_nasdaq100() -> list[str]:
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    tables = pd.read_html(_fetch_html(url))
    for t in tables:
        for c in t.columns:
            if isinstance(c, str) and c.lower() == "ticker":
                return t[c].dropna().tolist()
    return []


def clean(tickers: list[str]) -> list[str]:
    cleaned = []
    for sym in tickers:
        sym = str(sym).strip()
        # Alpaca uses hyphens instead of dots (BRK.B → BRK-B)
        sym = sym.replace(".", "-")
        if sym and sym.isascii():
            cleaned.append(sym)
    return cleaned


def main():
    print("Fetching S&P 500 from Wikipedia...")
    sp500 = fetch_sp500()
    print(f"  {len(sp500)} tickers")

    print("Fetching NASDAQ 100 from Wikipedia...")
    ndx100 = fetch_nasdaq100()
    print(f"  {len(ndx100)} tickers")

    combined = clean(list(set(sp500 + ndx100)))
    combined.sort()

    write_json("universe.json", {"tickers": combined, "count": len(combined)})
    print(f"Written {len(combined)} unique tickers to data/universe.json")


if __name__ == "__main__":
    main()
