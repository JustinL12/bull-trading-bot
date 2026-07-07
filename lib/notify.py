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
    trades: "int | list[dict]",
    overnight_holds: "int | list[str] | list[dict]",
    memory_update: str,
    top_watchlist: list[str],
    cumulative_bull_pct: float,
    cumulative_spy_pct: float,
) -> None:
    """Post the EOD daily report to Discord. Never raises.

    trades: list of EXIT/PARTIAL_EXIT dicts from trade_log, or an int count.
    overnight_holds: list of position dicts (from compressed_summary
        current_open_positions — each has symbol, shares, entry_price,
        current_stop, eod_price, unrealized_pnl_pct), or a list of symbol
        strings, or an int count. Pass the full position dicts for the richest
        block output; passing an int will show "0 held" which is almost always
        wrong.
    """
    try:
        vs_spy = pnl_pct - spy_return_pct
        alpha_total = cumulative_bull_pct - cumulative_spy_pct
        sign = lambda x: "+" if x >= 0 else ""

        title = (
            f"Bull Daily Report — {date} | {sign(pnl_pct)}{pnl_pct:.2f}%"
            f" | vs SPY {sign(spy_return_pct)}{spy_return_pct:.2f}%"
        )

        # Normalise trades
        trades_list: list[dict] = trades if isinstance(trades, list) else []
        trades_count: int = len(trades_list) if isinstance(trades, list) else int(trades)

        # Normalise overnight_holds — accept list[dict], list[str], or int
        if isinstance(overnight_holds, list) and overnight_holds and isinstance(overnight_holds[0], dict):
            holds_dicts: list[dict] = overnight_holds
            holds_count = len(holds_dicts)
        elif isinstance(overnight_holds, list):
            holds_dicts = [{"symbol": s} for s in overnight_holds]
            holds_count = len(holds_dicts)
        else:
            holds_dicts = []
            holds_count = int(overnight_holds)

        lines = [
            f"Net P&L: {sign(pnl_dollars)}${pnl_dollars:.2f} ({sign(pnl_pct)}{pnl_pct:.2f}%)"
            f"  |  SPY: {sign(spy_return_pct)}{spy_return_pct:.2f}%"
            f"  |  Alpha: {sign(vs_spy)}{vs_spy:.2f}%",
            "",
        ]

        # ── Overnight holds block ──────────────────────────────────────────
        lines.append(f"**Overnight holds ({holds_count})**")
        if holds_dicts:
            block_rows = []
            for p in holds_dicts:
                sym = p.get("symbol", "?")
                shares = p.get("shares", "")
                entry = p.get("entry_price")
                eod = p.get("eod_price")
                upnl = p.get("unrealized_pnl_pct")
                stop = p.get("current_stop")

                entry_str = f"${entry:.2f}" if entry is not None else "—"
                eod_str   = f"${eod:.2f}"   if eod   is not None else "—"
                upnl_str  = (f"{sign(upnl)}{upnl:.2f}%" if upnl is not None else "—")
                stop_str  = f"${stop:.2f}"  if stop  is not None else "—"
                shares_str = f"{shares}sh" if shares else ""

                block_rows.append(
                    f"{sym:<5} {shares_str:>6}  entry {entry_str:>8}  eod {eod_str:>8}"
                    f"  {upnl_str:>7}  stop {stop_str}"
                )
            lines.append("```")
            lines.extend(block_rows)
            lines.append("```")
        else:
            lines.append("None")
        lines.append("")

        # ── Trades block ───────────────────────────────────────────────────
        lines.append(f"**Trades today ({trades_count})**")
        if trades_list:
            for t in trades_list:
                sym    = t.get("symbol", "?")
                action = t.get("event", t.get("action", "?"))
                price  = t.get("price", 0)
                pnl_d  = t.get("pnl_dollars", 0)
                pnl_p  = t.get("pnl_pct", 0)
                reason = t.get("exit_reason", "")
                lines.append("```")
                lines.append(f"{sym} — {action} @ ${price:.2f}")
                lines.append(f"P&L: {sign(pnl_d)}${pnl_d:.2f} ({sign(pnl_p)}{pnl_p:.2f}%)")
                if reason:
                    lines.append(f"Reason: {reason}")
                lines.append("```")
        else:
            lines.append("None")
        lines.append("")

        # ── Watchlist & cumulative ─────────────────────────────────────────
        watchlist_str = ", ".join(top_watchlist[:5]) if top_watchlist else "TBD"
        lines += [
            f"**Tomorrow's watchlist:** {watchlist_str}",
            "",
            f"**Running total:** Bull {sign(cumulative_bull_pct)}{cumulative_bull_pct:.2f}%"
            f"  |  SPY {sign(cumulative_spy_pct)}{cumulative_spy_pct:.2f}%"
            f"  |  Alpha {sign(alpha_total)}{alpha_total:.2f}%",
            "",
            f"**Memory:** {memory_update}",
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
