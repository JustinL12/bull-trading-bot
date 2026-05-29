"""ClickUp API integration for trade alerts and daily reports."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))


def _base_url() -> str:
    return "https://api.clickup.com/api/v2"


def _headers() -> dict:
    return {
        "Authorization": os.environ.get("CLICKUP_API_KEY", ""),
        "Content-Type": "application/json",
    }


def _list_id() -> str:
    return os.environ.get("CLICKUP_LIST_ID", "")


def _post_task(title: str, description: str) -> bool:
    """Create a new task in the configured ClickUp list. Returns True on success."""
    list_id = _list_id()
    if not list_id or not os.environ.get("CLICKUP_API_KEY"):
        print("ClickUp: API key or list ID not configured — skipping.")
        return False

    payload = {"name": title, "description": description, "status": "open"}
    try:
        resp = requests.post(
            f"{_base_url()}/list/{list_id}/task",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True
        print(f"ClickUp error {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"ClickUp request failed: {e}")
        return False


def post_trade_alert(
    action: str,
    symbol: str,
    shares: int,
    price: float,
    stop: float | None = None,
    rsi: float | None = None,
    rel_vol: float | None = None,
    sentiment: str | None = None,
    pnl_dollars: float | None = None,
    pnl_pct: float | None = None,
    exit_reason: str | None = None,
    hold_duration: str | None = None,
) -> None:
    """Send a real-time trade notification to ClickUp. Never raises."""
    try:
        action_upper = action.upper()
        title = f"Bull Trade — {action_upper} {symbol}"

        if action_upper == "BUY":
            lines = [
                f"Action: {action_upper}",
                f"Symbol: {symbol}",
                f"Shares: {shares} @ ${price:.2f}",
            ]
            if stop:
                lines.append(f"Stop: ${stop:.2f}")
            if rsi:
                lines.append(f"RSI at entry: {rsi:.1f}")
            if rel_vol:
                lines.append(f"Rel Vol: {rel_vol:.1f}x")
            if sentiment:
                lines.append(f"Perplexity: {sentiment}")
        else:
            lines = [
                f"Action: {action_upper}",
                f"Symbol: {symbol}",
                f"Shares: {shares} @ ${price:.2f}",
            ]
            if pnl_dollars is not None and pnl_pct is not None:
                sign = "+" if pnl_dollars >= 0 else ""
                lines.append(f"P&L: {sign}${pnl_dollars:.2f} ({sign}{pnl_pct:.2f}%)")
            if exit_reason:
                lines.append(f"Exit reason: {exit_reason}")
            if hold_duration:
                lines.append(f"Hold duration: {hold_duration}")

        description = "\n".join(lines)
        _post_task(title, description)
    except Exception as e:
        print(f"ClickUp trade alert failed silently: {e}")


def post_daily_report(
    date: str,
    pnl_dollars: float,
    pnl_pct: float,
    spy_return_pct: float,
    trades: list[dict],
    overnight_holds: list[str],
    memory_update: str,
    top_watchlist: list[str],
    cumulative_bull_pct: float,
    cumulative_spy_pct: float,
) -> None:
    """Post the EOD daily report task to ClickUp. Never raises."""
    try:
        vs_spy = pnl_pct - spy_return_pct
        alpha_total = cumulative_bull_pct - cumulative_spy_pct
        sign = lambda x: "+" if x >= 0 else ""

        title = f"Bull Daily Report — {date} | {sign(pnl_pct)}{pnl_pct:.2f}% | vs SPY {sign(spy_return_pct)}{spy_return_pct:.2f}%"

        winners = [t for t in trades if t.get("pnl_dollars", 0) > 0]
        losers = [t for t in trades if t.get("pnl_dollars", 0) <= 0]

        lines = [
            f"Net P&L: {sign(pnl_dollars)}${pnl_dollars:.2f} ({sign(pnl_pct)}{pnl_pct:.2f}%)  |  S&P 500 today: {sign(spy_return_pct)}{spy_return_pct:.2f}%  |  Outperformance: {sign(vs_spy)}{vs_spy:.2f}%",
            "",
            f"Positions held overnight: {', '.join(overnight_holds) if overnight_holds else 'None'}",
            "",
            "Trades today:",
        ]
        for t in trades:
            sym = t.get("symbol", "?")
            action = t.get("action", "?")
            p = t.get("price", 0)
            pnl = t.get("pnl_dollars", 0)
            reason = t.get("exit_reason", "")
            sign_pnl = "+" if pnl >= 0 else ""
            lines.append(f"  - {sym}: {action} @ ${p:.2f} | {sign_pnl}${pnl:.2f} | {reason}")

        lines += [
            "",
            f"Memory update: {memory_update}",
            "",
            f"Tomorrow's top watchlist: {', '.join(top_watchlist[:5]) if top_watchlist else 'TBD'}",
            "",
            f"Running portfolio vs S&P 500: Bull {sign(cumulative_bull_pct)}{cumulative_bull_pct:.2f}%  |  SPY {sign(cumulative_spy_pct)}{cumulative_spy_pct:.2f}%  |  Alpha: {sign(alpha_total)}{alpha_total:.2f}%",
        ]

        description = "\n".join(lines)
        _post_task(title, description)
    except Exception as e:
        print(f"ClickUp daily report failed silently: {e}")
