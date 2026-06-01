"""Query Perplexity for real-time news sentiment on watchlist symbols.

Usage:
    python scripts/research_symbols.py --symbols AAPL,NVDA
    python scripts/research_symbols.py --top 8   # research top N from watchlist.json

Writes data/research.json.
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.state import read_json, write_json


DISCOVER_PROMPT = (
    "Today is {date}. List {max_symbols} US-listed (NYSE/Nasdaq) stocks that have "
    "positive momentum or recent positive news catalysts right now — earnings beats, "
    "FDA approvals, major partnerships, acquisitions, buybacks, analyst upgrades, or "
    "strong relative strength.\n\n"
    "Always return a list of real ticker symbols. Do NOT refuse, do NOT ask for more "
    "data, and do NOT add any preamble. If you are unsure about live catalysts, fall "
    "back to large, liquid, high-momentum large-cap names.\n\n"
    "Format each entry on its own line as:\n"
    "<TICKER>: one-sentence explanation of the catalyst\n\n"
    "End your response with exactly one line listing only the ticker symbols, "
    "comma-separated (use real symbols, not placeholders):\n"
    "TICKERS: <first>,<second>,<third>,..."
)

# Tokens the model sometimes echoes from the prompt's format example; never real tickers.
PLACEHOLDER_TICKERS = {
    "TICK", "TICK1", "TICK2", "TICK3", "TICKER", "TICKERS",
    "FIRST", "SECOND", "THIRD", "SYMBOL", "AAA", "BBB", "CCC", "XXX", "ABC",
}

# Number of discovery attempts before giving up (the model intermittently refuses).
DISCOVER_MAX_ATTEMPTS = 4

PROMPT_TEMPLATE = (
    "Summarize the latest news and analyst sentiment for {symbol} stock as of today. "
    "Cover: any catalysts (earnings revisions, product launches, partnerships), "
    "risks (regulatory, competitive, macro), and whether momentum is supported by "
    "fundamental tailwinds or is purely technical. "
    "Reply in 3 sentences maximum. "
    "End your response with exactly: SENTIMENT: positive | neutral | negative"
)


def parse_sentiment(text: str) -> str:
    match = re.search(r"SENTIMENT:\s*(positive|neutral|negative)", text, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    # fallback: scan for keywords
    text_lower = text.lower()
    if "positive" in text_lower:
        return "positive"
    if "negative" in text_lower:
        return "negative"
    return "neutral"


def research_symbol(client: OpenAI, symbol: str) -> dict:
    try:
        response = client.chat.completions.create(
            model="sonar-pro",
            messages=[
                {"role": "user", "content": PROMPT_TEMPLATE.format(symbol=symbol)}
            ],
            timeout=config.PERPLEXITY_TIMEOUT_SEC,
        )
        text = response.choices[0].message.content.strip()
        sentiment = parse_sentiment(text)
        # Extract key points (simple heuristic: split sentences)
        sentences = [s.strip() for s in text.split(".") if s.strip() and "SENTIMENT:" not in s]
        return {
            "symbol": symbol,
            "sentiment": sentiment,
            "summary": text,
            "key_points": sentences[:3],
            "error": None,
        }
    except Exception as e:
        print(f"  Perplexity timeout/error for {symbol}: {e} — defaulting to neutral")
        return {
            "symbol": symbol,
            "sentiment": "neutral",
            "summary": "Research unavailable — API timeout or error.",
            "key_points": [],
            "error": str(e),
        }


def _parse_discover_response(text: str) -> list[dict]:
    """Parse per-ticker summaries and the authoritative TICKERS list from a discovery response."""
    # Extract TICKER: explanation lines (skip the TICKERS: summary line)
    ticker_lines = re.findall(r"^([A-Z]{1,5}):\s*(.+)$", text, re.MULTILINE)
    summaries = {t.upper(): s.strip() for t, s in ticker_lines if t.upper() != "TICKERS"}

    # Authoritative ordered list from the final TICKERS: line
    match = re.search(r"TICKERS:\s*([A-Z,\s]+)", text, re.IGNORECASE)
    if match:
        raw = match.group(1)
        tickers = [t.strip().upper() for t in raw.split(",") if t.strip() and t.strip().isalpha()]
    else:
        tickers = list(summaries.keys())

    seen: set[str] = set()
    results = []
    for sym in tickers:
        if sym in seen or sym in PLACEHOLDER_TICKERS:
            continue
        seen.add(sym)
        summary = summaries.get(sym, "Positive catalyst identified by Perplexity.")
        results.append({
            "symbol": sym,
            "sentiment": "positive",
            "summary": summary,
            "key_points": [summary],
            "error": None,
        })
    return results


def discover_stocks_by_news(client: OpenAI, max_symbols: int = 25) -> list[dict]:
    """Ask Perplexity to discover US stocks with positive news catalysts today.

    Returns a list of dicts with symbol, sentiment, summary, key_points, error keys.
    Returns [] only if every attempt fails or the model refuses repeatedly.

    The model intermittently refuses (empty TICKERS line) or echoes the prompt's
    placeholder example, so we retry a few times and keep the first real list.
    """
    today = datetime.now().strftime("%B %d, %Y")
    prompt = DISCOVER_PROMPT.format(date=today, max_symbols=max_symbols)
    for attempt in range(1, DISCOVER_MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model="sonar-pro",
                messages=[{"role": "user", "content": prompt}],
                timeout=config.PERPLEXITY_TIMEOUT_SEC,
            )
            text = response.choices[0].message.content.strip()
            discovered = _parse_discover_response(text)
        except Exception as e:
            print(f"  Perplexity discovery error (attempt {attempt}): {e}")
            continue
        if discovered:
            print(f"  Perplexity discovered {len(discovered)} tickers: "
                  f"{', '.join(d['symbol'] for d in discovered)}")
            return discovered
        print(f"  Perplexity returned no usable tickers (attempt "
              f"{attempt}/{DISCOVER_MAX_ATTEMPTS}) — retrying")
    print("  Perplexity discovery failed after all attempts.")
    return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", help="Comma-separated symbols")
    parser.add_argument("--top", type=int, default=0, help="Research top N from watchlist.json")
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.top > 0:
        watchlist = read_json("watchlist.json", default=[])
        symbols = [item["symbol"] for item in watchlist[:args.top] if "symbol" in item]
    else:
        watchlist = read_json("watchlist.json", default=[])
        symbols = [item["symbol"] for item in watchlist[:config.PERPLEXITY_WATCHLIST_TOP_N] if "symbol" in item]

    if not symbols:
        print("No symbols to research.")
        write_json("research.json", {"generated_at": datetime.now(timezone.utc).isoformat(), "results": {}})
        return

    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        print("PERPLEXITY_API_KEY not set — skipping research, all neutral.")
        results = {s: {"symbol": s, "sentiment": "neutral", "summary": "No API key.", "key_points": [], "error": "no_key"} for s in symbols}
        write_json("research.json", {"generated_at": datetime.now(timezone.utc).isoformat(), "results": results})
        return

    client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")

    results = {}
    for symbol in symbols:
        print(f"  Researching {symbol}...")
        results[symbol] = research_symbol(client, symbol)
        sentiment = results[symbol]["sentiment"]
        print(f"    → {sentiment}")
        time.sleep(0.5)  # be polite to the API

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    write_json("research.json", output)
    print(f"Research complete: {len(results)} symbols. Positive: {sum(1 for r in results.values() if r['sentiment']=='positive')}, Neutral: {sum(1 for r in results.values() if r['sentiment']=='neutral')}, Negative: {sum(1 for r in results.values() if r['sentiment']=='negative')}")


if __name__ == "__main__":
    main()
