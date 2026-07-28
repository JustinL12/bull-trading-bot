"""Reconcile unlogged GTC stop fills.

Runs at the start of every agent session. For each position in positions.json,
checks whether the broker-side GTC stop-loss order filled while no agent was
active. When it has, writes an EXIT event to trade_log.jsonl with full P&L,
removes the position from positions.json, and fires a Discord attention alert.

This covers the recurring "self-fill" bug where a protective stop executes
overnight or intraday between agent sessions and is never logged.

Usage:
    python scripts/reconcile_fills.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.alpaca_client import get_trading_client
from lib.notify import post_attention
from lib.state import append_jsonl, read_json, write_json


def reconcile() -> int:
    """Check all open positions for unlogged stop fills. Return count reconciled."""
    client = get_trading_client()
    positions = read_json("positions.json", default={})
    if not positions:
        print("reconcile_fills: no open positions to check")
        return 0

    total = len(positions)
    to_remove = []

    for sym, pos in positions.items():
        stop_order_id = pos.get("stop_order_id")
        entry_price = float(pos.get("entry_price", 0))

        if stop_order_id:
            # Look up the known stop order directly — if it filled, the stop hit.
            try:
                order = client.get_order_by_id(stop_order_id)
                # Normalize status string: SDK may return "OrderStatus.filled" or "filled"
                status = str(order.status).lower().replace("orderstatus.", "")
                if status != "filled":
                    # Stop is still open, expired, or canceled — no self-fill to reconcile.
                    continue

                fill_price = float(order.filled_avg_price)
                filled_qty = int(float(order.filled_qty))
                fill_ts = (
                    order.filled_at.isoformat()
                    if order.filled_at
                    else datetime.now(timezone.utc).isoformat()
                )

                pnl_dollars = round((fill_price - entry_price) * filled_qty, 2)
                pnl_pct = round(
                    (fill_price - entry_price) / entry_price * 100, 2
                ) if entry_price else 0.0
                sign = "+" if pnl_dollars >= 0 else ""

                append_jsonl("trade_log.jsonl", {
                    "ts": fill_ts,
                    "event": "EXIT",
                    "symbol": sym,
                    "shares": filled_qty,
                    "price": fill_price,
                    "pnl_dollars": pnl_dollars,
                    "pnl_pct": pnl_pct,
                    "exit_reason": "stop_fill (reconciled)",
                })

                print(
                    f"RECONCILED  {sym:<6}  {filled_qty}sh @ ${fill_price:.2f}  "
                    f"P&L: {sign}${abs(pnl_dollars):.2f} ({sign}{pnl_pct:.2f}%)"
                )
                post_attention(
                    f"Stop fill reconciled: {sym}",
                    f"{sym} GTC stop order filled ({filled_qty} sh @ ${fill_price:.2f}) "
                    f"while no agent was active. "
                    f"P&L: {sign}${abs(pnl_dollars):.2f} ({sign}{pnl_pct:.2f}%). "
                    f"EXIT logged to trade_log.jsonl; position cleared from positions.json.",
                    level="warning",
                )
                to_remove.append(sym)

            except Exception as e:
                print(f"reconcile_fills: could not check stop order for {sym}: {e}")

        else:
            # No stop_order_id recorded (stop placement failed at entry).
            # Fall back to checking whether the broker still holds shares.
            try:
                client.get_open_position(sym)
                # Broker confirms the position is open — nothing to reconcile.
            except Exception:
                # Broker raised (no open position) — shares are gone.
                append_jsonl("trade_log.jsonl", {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "event": "RECONCILE",
                    "symbol": sym,
                    "note": (
                        "Position found in positions.json but broker holds no shares. "
                        "stop_order_id was never recorded (stop placement failed at entry). "
                        "P&L unknown — verify in Alpaca order history."
                    ),
                })
                print(
                    f"RECONCILED  {sym:<6}  broker flat, no stop_order_id — "
                    f"cleared stale entry. Check Alpaca history for P&L."
                )
                post_attention(
                    f"Stale position cleared: {sym}",
                    f"{sym} was in positions.json but the broker holds no shares and no "
                    f"stop_order_id was recorded. Stale entry cleared. "
                    f"Check Alpaca order history to determine actual exit price and P&L.",
                    level="warning",
                )
                to_remove.append(sym)

    if to_remove:
        for sym in to_remove:
            del positions[sym]
        write_json("positions.json", positions)

    reconciled = len(to_remove)
    remaining = total - reconciled
    print(
        f"reconcile_fills: {reconciled} reconciled, {remaining} still open "
        f"(checked {total} total)"
    )
    return reconciled


def main():
    reconcile()


if __name__ == "__main__":
    main()
