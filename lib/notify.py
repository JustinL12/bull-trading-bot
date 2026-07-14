"""Discord webhook delivery for trade alerts and reports.

All Bull notifications funnel through Discord embeds for a consistent,
scannable look (color-coded by outcome, fields instead of raw text blocks).
"""

import os

import requests

# Discord caps: embed description 4096 chars, field value 1024 chars,
# 25 fields per embed. We stay well under those with headroom.
_MAX_DESCRIPTION = 4000
_MAX_FIELD_VALUE = 1000

_COLOR_POSITIVE = 0x2ECC71  # green
_COLOR_NEGATIVE = 0xE74C3C  # red
_COLOR_NEUTRAL = 0x95A5A6   # gray
_COLOR_WARNING = 0xF1C40F   # yellow
_COLOR_CRITICAL = 0xE74C3C  # red


def discord_enabled() -> bool:
    return bool(os.environ.get("DISCORD_WEBHOOK_URL"))


def _color_for(value: float) -> int:
    if value > 0:
        return _COLOR_POSITIVE
    if value < 0:
        return _COLOR_NEGATIVE
    return _COLOR_NEUTRAL


def _money(value: float) -> str:
    """Format a signed dollar amount as '+$1.23' / '-$1.23', not '$-1.23'."""
    sign = "-" if value < 0 else "+"
    return f"{sign}${abs(value):.2f}"


def _pct(value: float) -> str:
    return f"{'+' if value >= 0 else ''}{value:.2f}%"


def _chunk_text(text: str, size: int) -> list[str]:
    """Split text into <=size pieces, preferring newline boundaries."""
    if len(text) <= size:
        return [text]
    pieces, current = [], ""
    for line in text.split("\n"):
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


def _post_embeds(url: str, embeds: list[dict], timeout: int = 10) -> bool:
    try:
        resp = requests.post(url, json={"embeds": embeds}, timeout=timeout)
        # Discord webhooks return 204 No Content on success.
        if resp.status_code not in (200, 204):
            print(f"Discord error {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"Discord request failed: {e}")
        return False


def send_discord(title: str, description: str = "", color: int | None = None) -> bool:
    """Post a single-embed message to the configured Discord webhook. Never raises.

    Splits into multiple embeds (one webhook call per chunk) if description
    exceeds Discord's per-embed limit. Returns True if every chunk was delivered.
    """
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return False

    chunks = _chunk_text(description, _MAX_DESCRIPTION) if description else [""]
    ok = True
    for i, chunk in enumerate(chunks):
        embed: dict = {"title": title[:256] if i == 0 else f"{title} (cont.)"[:256]}
        if chunk:
            embed["description"] = chunk
        if color is not None:
            embed["color"] = color
        if not _post_embeds(url, [embed]):
            ok = False
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
        fields = [
            {"name": "Symbol", "value": symbol, "inline": True},
            {"name": "Shares", "value": f"{shares} @ ${price:.2f}", "inline": True},
        ]

        if action_upper == "BUY":
            color = _COLOR_POSITIVE
            if stop:
                fields.append({"name": "Stop", "value": f"${stop:.2f}", "inline": True})
        else:
            color = _color_for(pnl_dollars) if pnl_dollars is not None else _COLOR_NEUTRAL
            if pnl_dollars is not None and pnl_pct is not None:
                fields.append({
                    "name": "P&L",
                    "value": f"{_money(pnl_dollars)} ({_pct(pnl_pct)})",
                    "inline": True,
                })
            if exit_reason:
                fields.append({"name": "Exit reason", "value": exit_reason, "inline": False})
            if hold_duration:
                fields.append({"name": "Hold duration", "value": hold_duration, "inline": True})

        url = os.environ.get("DISCORD_WEBHOOK_URL")
        if not url:
            return
        _post_embeds(url, [{"title": title, "color": color, "fields": fields}])
    except Exception as e:
        print(f"Discord trade alert failed silently: {e}")


def post_daily_report(
    date: str,
    pnl_dollars: float,
    pnl_pct: float,
    spy_return_pct: float,
    trades: list[dict],
    current_holds: list[dict],
    cumulative_bull_pct: float,
    cumulative_spy_pct: float,
) -> None:
    """Post the EOD daily report to Discord as a single embed. Never raises.

    trades: today's ENTRY/EXIT/PARTIAL_EXIT/EMERGENCY_EXIT dicts from trade_log
        (each needs 'event' and 'symbol'; sells should carry 'pnl_dollars'/'pnl_pct').
    current_holds: list of dicts with 'symbol', 'shares', 'entry_price',
        'current_price', 'unrealized_pnl_pct', 'current_stop' -- build this from
        positions.json (the source of truth), not compressed_summary.json, since
        the memory file's schema is agent-authored and not guaranteed complete.
    """
    try:
        vs_spy = pnl_pct - spy_return_pct
        alpha_total = cumulative_bull_pct - cumulative_spy_pct

        title = f"Bull Daily Report — {date}"

        fields = [
            {
                "name": "Net P&L",
                "value": f"{_money(pnl_dollars)} ({_pct(pnl_pct)})",
                "inline": True,
            },
            {
                "name": "vs SPY",
                "value": f"{_pct(spy_return_pct)} (alpha {_pct(vs_spy)})",
                "inline": True,
            },
        ]

        # ── Current holds ──────────────────────────────────────────────────
        holds_rows = []
        for p in current_holds:
            sym = p.get("symbol", "?")
            shares = p.get("shares")
            entry = p.get("entry_price")
            current = p.get("current_price")
            upnl = p.get("unrealized_pnl_pct")
            stop = p.get("current_stop")

            shares_str = f"{shares}sh" if shares is not None else "—"
            entry_str = f"${entry:.2f}" if entry is not None else "—"
            current_str = f"${current:.2f}" if current is not None else "—"
            upnl_str = _pct(upnl) if upnl is not None else "—"
            stop_str = f"${stop:.2f}" if stop is not None else "—"

            holds_rows.append(
                f"{sym:<5} {shares_str:>6}  entry {entry_str:>8}  now {current_str:>8}"
                f"  {upnl_str:>7}  stop {stop_str}"
            )
        holds_value = "```\n" + "\n".join(holds_rows) + "\n```" if holds_rows else "None"
        fields.append({
            "name": f"Current Holds ({len(current_holds)})",
            "value": holds_value[:_MAX_FIELD_VALUE],
            "inline": False,
        })

        # ── Today's trades (BUY/SELL indicator) ────────────────────────────
        trade_rows = []
        for t in trades:
            sym = t.get("symbol", "?")
            event = t.get("event", "?")
            side = "BUY" if event == "ENTRY" else "SELL"
            price = t.get("price", 0)
            row = f"{side:<4} {sym:<5} {t.get('shares', '')}sh @ ${price:.2f}"
            if side == "SELL":
                pnl_d = t.get("pnl_dollars", 0)
                pnl_p = t.get("pnl_pct", 0)
                row += f"  {_money(pnl_d)} ({_pct(pnl_p)})"
            trade_rows.append(row)
        trades_value = "```\n" + "\n".join(trade_rows) + "\n```" if trade_rows else "None"
        fields.append({
            "name": f"Today's Trades ({len(trades)})",
            "value": trades_value[:_MAX_FIELD_VALUE],
            "inline": False,
        })

        # ── Running total ───────────────────────────────────────────────────
        fields.append({
            "name": "Running Total (since inception)",
            "value": (
                f"Bull {_pct(cumulative_bull_pct)}"
                f"  |  SPY {_pct(cumulative_spy_pct)}"
                f"  |  Alpha {_pct(alpha_total)}"
            ),
            "inline": False,
        })

        url = os.environ.get("DISCORD_WEBHOOK_URL")
        if not url:
            return
        _post_embeds(url, [{"title": title, "color": _color_for(pnl_dollars), "fields": fields}])
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
        color = _COLOR_CRITICAL if level == "critical" else _COLOR_WARNING
        full_title = f"Bull Bot — {level_label}: {title}"
        for chunk in _chunk_text(description, _MAX_DESCRIPTION):
            _post_embeds(url, [{"title": full_title, "description": chunk, "color": color}])
    except Exception as e:
        print(f"Discord attention alert failed silently: {e}")
