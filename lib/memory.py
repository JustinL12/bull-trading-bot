"""Memory system: read/write compressed summary and raw stats."""

import json
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.state import append_jsonl, read_json, read_jsonl, write_json

MEMORY_DIR = Path(__file__).parent.parent / "data" / "memory"
SUMMARY_PATH = MEMORY_DIR / "compressed_summary.json"
STATS_PATH = MEMORY_DIR / "indicator_stats.json"
JOURNAL_PATH = MEMORY_DIR / "session_journal.jsonl"
ARCHIVE_PATH = MEMORY_DIR / "archive_summary.jsonl"

RSI_BUCKETS = ["50-55", "55-60", "60-65", "65-75"]
REL_VOL_BUCKETS = ["1.5-2.0", "2.0-3.0", "3.0+"]


def read_compressed_summary() -> dict:
    """Return the compressed memory summary for agent consumption."""
    data = read_json(SUMMARY_PATH, default={})
    return data if data else _default_summary()


def _default_summary() -> dict:
    return {
        "last_updated": None,
        "sessions_analyzed": 0,
        "total_trades": 0,
        "performance_overview": "No sessions yet — collecting baseline data.",
        "best_signals": [],
        "avoid": [],
        "active_parameter_adjustments": [],
        "overnight_hold_insights": "No overnight hold data yet.",
        "recent_market_context": "No prior sessions.",
        "current_open_positions": [],
        "notes_for_next_session": "",
    }


def _rsi_bucket(rsi: float) -> str:
    if rsi < 55:
        return "50-55"
    if rsi < 60:
        return "55-60"
    if rsi < 65:
        return "60-65"
    return "65-75"


def _rel_vol_bucket(rel_vol: float) -> str:
    if rel_vol < 2.0:
        return "1.5-2.0"
    if rel_vol < 3.0:
        return "2.0-3.0"
    return "3.0+"


def _increment_bucket(stats: dict, path: list[str], won: bool, pnl_pct: float) -> None:
    node = stats
    for key in path[:-1]:
        node = node.setdefault(key, {})
    bucket = path[-1]
    entry = node.setdefault(bucket, {"trades": 0, "wins": 0, "win_rate": 0.0, "avg_pnl_pct": 0.0})
    t = entry["trades"]
    w = entry["wins"]
    avg = entry["avg_pnl_pct"]
    new_t = t + 1
    new_w = w + (1 if won else 0)
    new_avg = round((avg * t + pnl_pct) / new_t, 4)
    entry["trades"] = new_t
    entry["wins"] = new_w
    entry["win_rate"] = round(new_w / new_t, 4)
    entry["avg_pnl_pct"] = new_avg


def update_indicator_stats(completed_trades: list[dict]) -> None:
    """Update raw indicator stats from today's completed trades."""
    stats = read_json(STATS_PATH, default={})
    stats.setdefault("last_updated", None)
    stats.setdefault("total_trades", 0)
    stats.setdefault("by_signal", {})
    sig = stats["by_signal"]

    for trade in completed_trades:
        if trade.get("event") not in ("EXIT", "PARTIAL_EXIT"):
            continue
        pnl = trade.get("pnl_pct", 0.0) or 0.0
        won = pnl > 0
        stats["total_trades"] += 1

        # RSI bucket
        rsi = trade.get("rsi_at_entry")
        if rsi is not None and 50 <= rsi <= 75:
            sig.setdefault("rsi_at_entry", {})
            _increment_bucket(sig, ["rsi_at_entry", _rsi_bucket(rsi)], won, pnl)

        # Rel vol bucket
        rv = trade.get("rel_vol_at_entry")
        if rv is not None and rv >= 1.5:
            sig.setdefault("rel_vol_at_entry", {})
            _increment_bucket(sig, ["rel_vol_at_entry", _rel_vol_bucket(rv)], won, pnl)

        # Perplexity sentiment
        sentiment = trade.get("perplexity_at_entry") or trade.get("perplexity")
        if sentiment in ("positive", "neutral", "negative"):
            sig.setdefault("perplexity_sentiment", {})
            _increment_bucket(sig, ["perplexity_sentiment", sentiment], won, pnl)

        # Overnight hold
        held_overnight = trade.get("held_overnight", False)
        bucket = "held" if held_overnight else "closed_eod"
        sig.setdefault("overnight_holds", {})
        _increment_bucket(sig, ["overnight_holds", bucket], won, pnl)

    stats["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    write_json(STATS_PATH, stats)


def append_journal(entry: dict) -> None:
    append_jsonl(JOURNAL_PATH, entry)


def archive_old_sessions() -> None:
    """Move sessions beyond MEMORY_JOURNAL_ARCHIVE_SESSIONS into archive_summary.jsonl."""
    sessions = read_jsonl(JOURNAL_PATH)
    limit = config.MEMORY_JOURNAL_ARCHIVE_SESSIONS
    if len(sessions) <= limit:
        return

    to_archive = sessions[:len(sessions) - limit]
    to_keep = sessions[len(sessions) - limit:]

    # Summarize archived sessions as a quarterly digest
    if to_archive:
        dates = [s.get("date", "?") for s in to_archive]
        pnls = [s.get("pnl_pct", 0) for s in to_archive]
        avg_pnl = round(sum(pnls) / len(pnls), 3) if pnls else 0
        digest = {
            "type": "archive_digest",
            "date_range": f"{dates[0]} to {dates[-1]}",
            "sessions": len(to_archive),
            "avg_pnl_pct": avg_pnl,
            "total_pnl_pct": round(sum(pnls), 3),
            "archived_at": datetime.now().strftime("%Y-%m-%d"),
        }
        append_jsonl(ARCHIVE_PATH, digest)

    # Rewrite journal with only recent sessions
    with open(JOURNAL_PATH, "w", encoding="utf-8") as f:
        for s in to_keep:
            f.write(json.dumps(s, default=str) + "\n")


def get_recent_journal(n: int = 10) -> list[dict]:
    sessions = read_jsonl(JOURNAL_PATH)
    return sessions[-n:] if sessions else []


def build_insights_from_stats(stats: dict) -> tuple[list[str], list[str], list[str]]:
    """Return (best_signals, avoid_signals, parameter_suggestions)."""
    best = []
    avoid = []
    adjustments = []
    sig = stats.get("by_signal", {})
    min_trades = config.MEMORY_MIN_SAMPLE
    divergence = config.MEMORY_WIN_RATE_DIVERGENCE

    # Compute baseline win rate from signal-tracked trades only (not total_trades,
    # which may include trades without signal data captured)
    all_wins = sum(
        b.get("wins", 0)
        for group in sig.values()
        for b in (group.values() if isinstance(group, dict) else [])
    )
    total_tracked = sum(
        b.get("trades", 0)
        for group in sig.values()
        for b in (group.values() if isinstance(group, dict) else [])
    )
    baseline_wr = all_wins / total_tracked if total_tracked > 0 else 0.5

    for group_name, buckets in sig.items():
        if not isinstance(buckets, dict):
            continue
        for bucket, data in buckets.items():
            t = data.get("trades", 0)
            wr = data.get("win_rate", 0)
            avg_pnl = data.get("avg_pnl_pct", 0)
            if t < min_trades:
                continue
            if wr >= baseline_wr + divergence:
                best.append(f"{group_name} {bucket} → {wr*100:.0f}% win rate ({t} trades), avg {avg_pnl:+.2f}%")
            elif wr <= baseline_wr - divergence:
                avoid.append(f"{group_name} {bucket} → only {wr*100:.0f}% win rate ({t} trades)")
                if group_name == "rsi_at_entry" and bucket == "65-75":
                    adjustments.append("Consider tightening rsi_entry_max from 75 to 65")

    return best, avoid, adjustments
