"""EOD memory update: processes today's trades, updates stats, appends journal.

The compressed_summary.json rewrite is handled by the Claude agent (eod-review routine)
which reads the stats and journal, then synthesizes new insights. This script handles
the raw data layer: parsing trade_log.jsonl and updating indicator_stats.json.

Usage:
    python scripts/update_memory.py --date 2026-05-28
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.memory import (
    append_journal,
    archive_old_sessions,
    build_insights_from_stats,
    get_recent_journal,
    update_indicator_stats,
)
from lib.state import read_json, read_jsonl, write_json

MEMORY_STATS_PATH = Path(__file__).parent.parent / "data" / "memory" / "indicator_stats.json"
MEMORY_SUMMARY_PATH = Path(__file__).parent.parent / "data" / "memory" / "compressed_summary.json"


def get_todays_trades(date_str: str) -> list[dict]:
    """Read trade_log.jsonl and return completed trades from today."""
    all_records = read_jsonl("trade_log.jsonl")
    trades = []
    for r in all_records:
        ts = r.get("ts", "")
        if ts.startswith(date_str):
            trades.append(r)
    return trades


def enrich_trades_with_positions(trades: list[dict]) -> list[dict]:
    """Cross-reference exit events with their corresponding entry events for context."""
    entries = {r["symbol"]: r for r in trades if r.get("event") == "ENTRY"}
    enriched = []
    for trade in trades:
        if trade.get("event") in ("EXIT", "PARTIAL_EXIT"):
            symbol = trade.get("symbol")
            entry = entries.get(symbol, {})
            trade = trade.copy()
            trade.setdefault("rsi_at_entry", entry.get("rsi"))
            trade.setdefault("rel_vol_at_entry", entry.get("rel_vol"))
            trade.setdefault("perplexity_at_entry", entry.get("perplexity"))
            enriched.append(trade)
    return enriched


def build_journal_entry(date_str: str, trades: list[dict], pnl_data: dict, spy_return: float) -> dict:
    exits = [t for t in trades if t.get("event") in ("EXIT", "PARTIAL_EXIT")]
    winners = [t for t in exits if (t.get("pnl_dollars") or 0) > 0]
    losers = [t for t in exits if (t.get("pnl_dollars") or 0) <= 0]

    best = max(exits, key=lambda t: t.get("pnl_dollars", 0), default=None)
    worst = min(exits, key=lambda t: t.get("pnl_dollars", 0), default=None)

    positions = read_json("positions.json", default={})
    overnight = [s for s, p in positions.items() if p.get("overnight_hold")]

    pnl_pct = pnl_data.get("pnl_pct", 0)
    vs_spy = round(pnl_pct - spy_return, 3)

    entry = {
        "date": date_str,
        "pnl_pct": pnl_pct,
        "pnl_dollars": pnl_data.get("pnl_dollars", 0),
        "trades": len(exits),
        "winners": len(winners),
        "losers": len(losers),
        "overnight_holds": overnight,
        "best_trade": f"{best['symbol']} {'+' if best['pnl_dollars']>0 else ''}{best['pnl_dollars']:.2f}" if best else "none",
        "worst_trade": f"{worst['symbol']} {'+' if worst['pnl_dollars']>0 else ''}{worst['pnl_dollars']:.2f}" if worst else "none",
        "spy_return_today": spy_return,
        "vs_spy": f"{'+' if vs_spy>=0 else ''}{vs_spy:.2f}%",
        "kill_switch": pnl_data.get("kill_switch_triggered", False),
        "observations": "",  # Claude fills this in via the routine prompt
    }
    return entry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()
    date_str = args.date

    print(f"Updating memory for {date_str}...")

    # Get today's trades
    raw_trades = get_todays_trades(date_str)
    enriched = enrich_trades_with_positions(raw_trades)

    # Update indicator stats
    update_indicator_stats(enriched)
    print(f"  Updated indicator stats with {len(enriched)} exit events.")

    # Load P&L data
    pnl_data = read_json("daily_pnl.json", default={})
    spy_return = pnl_data.get("spy_return_today", 0.0)

    # Build and append journal entry
    journal_entry = build_journal_entry(date_str, raw_trades, pnl_data, spy_return)
    append_journal(journal_entry)
    print(f"  Appended journal entry: {journal_entry['winners']}W/{journal_entry['losers']}L, P&L {journal_entry['pnl_pct']:+.2f}%")

    # Archive old sessions if needed
    archive_old_sessions()

    # Read updated stats and recent journal for Claude to synthesize
    from lib.state import read_json as rj
    stats = rj(MEMORY_STATS_PATH, default={})
    best, avoid, adjustments = build_insights_from_stats(stats)
    recent = get_recent_journal(10)

    print(f"\n--- MEMORY ANALYSIS FOR CLAUDE TO REVIEW ---")
    print(f"Best signals found: {best}")
    print(f"Signals to avoid: {avoid}")
    print(f"Suggested adjustments: {adjustments}")
    print(f"Recent journal ({len(recent)} sessions):")
    for j in recent[-3:]:
        print(f"  {j.get('date')}: {j.get('pnl_pct',0):+.2f}% ({j.get('winners',0)}W/{j.get('losers',0)}L)")

    print("\nNOTE: Claude (eod-review routine) should now rewrite data/memory/compressed_summary.json")
    print("      using the above insights and the full indicator_stats.json + recent journal.")

    return {
        "journal_entry": journal_entry,
        "best_signals": best,
        "avoid": avoid,
        "adjustments": adjustments,
        "stats": stats,
        "recent_journal": recent,
    }


if __name__ == "__main__":
    main()
