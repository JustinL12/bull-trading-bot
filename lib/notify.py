"""Discord webhook delivery for trade alerts and reports.

All Bull notifications funnel through send_discord.
Messages are plain Discord markdown so they read like a chat/text thread on
desktop and mobile.
"""

import os

import requests

# Discord rejects message content longer than 2000 characters, so we chunk
# below that with headroom for the bold title wrapper.
_MAX_CONTENT = 1900


def discord_enabled() -> bool:
    return bool(os.environ.get("DISCORD_WEBHOOK_URL"))


def _chunks(text: str, size: int = _MAX_CONTENT) -> list[str]:
    """Split text into <=size pieces, preferring newline boundaries."""
    if len(text) <= size:
        return [text]
    pieces, current = [], ""
    for line in text.split("\n"):
        # A single line longer than the limit: hard-split it.
        while len(line) > size:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:size])
            line = line[size:]
        if len(current) + len(line) + 1 > size:
            pieces.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        pieces.append(current)
    return pieces


def send_discord(title: str, description: str) -> bool:
    """Post a message to the configured Discord webhook. Never raises.

    Returns True if every chunk was delivered, False otherwise.
    """
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return False

    body = f"**{title}**\n{description}" if description else f"**{title}**"
    ok = True
    try:
        for chunk in _chunks(body):
            resp = requests.post(
                url,
                json={"content": chunk},
                timeout=10,
            )
            # Discord webhooks return 204 No Content on success.
            if resp.status_code not in (200, 204):
                print(f"Discord error {resp.status_code}: {resp.text[:200]}")
                ok = False
    except Exception as e:
        print(f"Discord request failed: {e}")
        return False
    return ok


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
    """Send a real-time trade notification to Discord. Never raises."""
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

        send_discord(title, "\n".join(lines))
    except Exception as e:
        print(f"Discord trade alert failed silently: {e}")


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
    """Post the EOD daily report to Discord. Never raises."""
    try:
        vs_spy = pnl_pct - spy_return_pct
        alpha_total = cumulative_bull_pct - cumulative_spy_pct
        sign = lambda x: "+" if x >= 0 else ""

        title = f"Bull Daily Report — {date} | {sign(pnl_pct)}{pnl_pct:.2f}% | vs SPY {sign(spy_return_pct)}{spy_return_pct:.2f}%"

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

        send_discord(title, "\n".join(lines))
    except Exception as e:
        print(f"Discord daily report failed silently: {e}")


def post_attention(title: str, description: str, level: str = "warning") -> None:
    """Send a needs-attention alert to the attention webhook. Never raises.

    Uses DISCORD_ATTENTION_WEBHOOK_URL; falls back to DISCORD_WEBHOOK_URL if not set.
    """
    try:
        url = os.environ.get("DISCORD_ATTENTION_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_URL")
        if not url:
            print(f"[notify] No attention webhook configured — skipping: {title}")
            return
        level_label = "Critical" if level == "critical" else "Warning"
        full_title = f"Bull Bot — {level_label}: {title}"
        body = f"**{full_title}**\n{description}" if description else f"**{full_title}**"
        for chunk in _chunks(body):
            requests.post(url, json={"content": chunk}, timeout=10)
    except Exception as e:
        print(f"Discord attention alert failed silently: {e}")
