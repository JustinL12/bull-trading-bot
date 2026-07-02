"""Place a buy, sell, or partial-sell order via Alpaca. Updates data/positions.json.
Sends a Discord trade alert after every fill.

Usage:
    python scripts/place_order.py --action buy --symbol XLK --shares 45 --stop 192.40
    python scripts/place_order.py --action sell --symbol XLK --reason "Trend exit: 10-day low"
    python scripts/place_order.py --action partial_sell --symbol XLK --shares 22 --reason "Manual partial"
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from lib.alpaca_client import get_trading_client
from lib.notify import post_attention, post_trade_alert
from lib.state import append_jsonl, read_json, write_json
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


def wait_for_fill(client, order_id: str, max_wait: int = 30, require_full: bool = False) -> dict | None:
    """Poll until an order fills or max_wait seconds elapse.

    When require_full is True (use this for entries), wait for the order to be
    completely filled before returning. Returning on a partial fill would both
    record the wrong share count and leave the buy order open — and an open buy
    causes Alpaca to reject the opposite-side stop-loss as a wash trade.
    """
    for _ in range(max_wait):
        order = client.get_order_by_id(order_id)
        if order.status == "filled":
            return order
        if order.status == "partially_filled" and not require_full:
            return order
        if order.status in ("canceled", "expired", "rejected"):
            print(f"Order {order_id} ended with status: {order.status}")
            return None
        time.sleep(1)
    # Timed out: fall back to whatever filled so the position is still recorded
    # and protected, rather than dropping it on the floor.
    order = client.get_order_by_id(order_id)
    if order.status in ("filled", "partially_filled"):
        print(f"Order {order_id} only {order.status} after {max_wait}s; proceeding with filled qty.")
        return order
    print(f"Order {order_id} not filled after {max_wait}s (status: {order.status})")
    return None


def place_buy(client, symbol: str, shares: int, stop_price: float) -> None:
    positions = read_json("positions.json", default={})

    if symbol in positions:
        print(f"Already holding {symbol} — skipping buy.")
        return

    # Submit market buy
    buy_req = MarketOrderRequest(
        symbol=symbol,
        qty=shares,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(buy_req)
    # require_full: wait for the buy to fully fill before placing the stop, so
    # filled_qty is correct and no open buy order remains to trip Alpaca's
    # wash-trade protection on the opposite-side stop.
    filled = wait_for_fill(client, str(order.id), require_full=True)
    if not filled:
        print(f"Buy order for {symbol} did not fill.")
        return

    fill_price = float(filled.filled_avg_price)
    filled_qty = int(float(filled.filled_qty))

    # Submit stop loss order. Retry on wash-trade rejection: if any part of the
    # buy is still settling, Alpaca rejects the opposite-side stop — a short
    # delay lets it clear before we give up and alert.
    stop_req = StopOrderRequest(
        symbol=symbol,
        qty=filled_qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.GTC,
        stop_price=round(stop_price, 2),
    )
    stop_order_id = None
    max_stop_attempts = 3
    for attempt in range(max_stop_attempts):
        try:
            stop_order = client.submit_order(stop_req)
            stop_order_id = str(stop_order.id)
            break
        except Exception as e:
            is_wash = "wash trade" in str(e).lower()
            if is_wash and attempt < max_stop_attempts - 1:
                print(f"Stop for {symbol} rejected (wash trade); retrying in 3s "
                      f"(attempt {attempt + 1}/{max_stop_attempts})...")
                time.sleep(3)
                continue
            print(f"Warning: stop order for {symbol} failed: {e}")
            post_attention(
                f"Stop Order Not Placed: {symbol}",
                f"Buy order for {symbol} filled ({filled_qty} sh @ ${fill_price:.2f}) but the "
                f"stop-loss order failed to submit after {attempt + 1} attempt(s).\n"
                f"Error: {e}\n"
                f"Position is UNPROTECTED. Place a stop manually in Alpaca.",
                level="critical",
            )
            break

    position = {
        "symbol": symbol,
        "entry_price": fill_price,
        "shares": filled_qty,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "atr_at_entry": round((fill_price - stop_price) / config.BACKTEST_STOP_ATR_MULT, 4),
        "initial_stop": stop_price,
        "current_stop": stop_price,
        "highest_close_since_entry": fill_price,
        "partial_sold": False,
        "partial_sold_shares": 0,
        "alpaca_order_id": str(filled.id),
        "stop_order_id": stop_order_id,
    }
    positions[symbol] = position
    write_json("positions.json", positions)

    append_jsonl("trade_log.jsonl", {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "ENTRY",
        "symbol": symbol,
        "shares": filled_qty,
        "price": fill_price,
        "stop": stop_price,
    })

    print(f"BUY {filled_qty} {symbol} @ ${fill_price:.2f}, stop ${stop_price:.2f}")
    post_trade_alert("BUY", symbol, filled_qty, fill_price, stop=stop_price)


def broker_position_qty(client, symbol: str) -> int:
    """Return the signed share quantity the broker actually holds for *symbol*
    (positive = long, negative = short, 0 = flat).

    This is the source of truth we reconcile against before selling. positions.json
    can drift from reality when a protective stop self-fills (that fill is never
    written back here), so trusting our local share count and selling it blindly
    can flip a flat book into an unintended short.
    """
    try:
        pos = client.get_open_position(symbol)
    except Exception:
        # Alpaca raises when there is no open position for the symbol.
        return 0
    return int(float(pos.qty))


def plan_sell_qty(intended: int, broker_held: int) -> int:
    """Decide how many shares we may actually sell.

    Never exceeds ``broker_held`` (so we cannot oversell long shares into a short)
    and never goes negative. A return of 0 means there is nothing safe to sell —
    the book is already flat (e.g. the stop self-filled) and the caller should
    reconcile local state instead of submitting an order.
    """
    if broker_held <= 0:
        return 0
    return max(0, min(intended, broker_held))


def cancel_stop_order(client, stop_order_id: str | None) -> None:
    """Cancel a still-open protective stop before a manual close.

    Without this, the GTC stop can fire after we've already sold the shares,
    selling them a second time and opening a short — the same failure mode the
    broker-reconcile guard protects against, from the other direction.
    """
    if not stop_order_id:
        return
    try:
        order = client.get_order_by_id(stop_order_id)
        if str(order.status) not in ("OrderStatus.FILLED", "OrderStatus.CANCELED",
                                     "OrderStatus.EXPIRED", "OrderStatus.REJECTED",
                                     "filled", "canceled", "expired", "rejected"):
            client.cancel_order_by_id(stop_order_id)
            print(f"Canceled open stop order {stop_order_id[:8]} before selling {order.symbol}.")
    except Exception as e:
        print(f"Note: could not cancel stop order {stop_order_id}: {e}")


def place_sell(client, symbol: str, reason: str, shares: int | None = None, is_partial: bool = False) -> None:
    positions = read_json("positions.json", default={})
    if symbol not in positions:
        print(f"No open position for {symbol}.")
        return

    pos = positions[symbol]
    recorded_remaining = pos["shares"] - pos.get("partial_sold_shares", 0)

    # --- Reconcile against the broker BEFORE selling -------------------------
    # If the broker shows no long position, the stop almost certainly self-filled
    # and was never written back to positions.json. Submitting a sell here would
    # open a short (this is exactly how the MPC -18 short happened on 2026-06-04).
    held = broker_position_qty(client, symbol)
    if held <= 0:
        del positions[symbol]
        write_json("positions.json", positions)
        append_jsonl("trade_log.jsonl", {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "RECONCILE",
            "symbol": symbol,
            "note": (f"Skipped {'partial ' if is_partial else ''}sell: broker holds no long position "
                     f"(held={held}) but positions.json recorded {recorded_remaining} sh. The protective "
                     f"stop most likely self-filled and was never reconciled. Cleared stale local state "
                     f"instead of selling, which would have opened a short."),
            "reason": reason,
        })
        print(f"{symbol}: broker is flat (stop likely already filled). Cleared stale state; no sell submitted.")
        post_attention(
            f"Auto-reconciled stale position: {symbol}",
            f"A {'partial ' if is_partial else ''}sell for {symbol} was requested ({reason}), but the broker "
            f"holds no long position (positions.json had {recorded_remaining} sh). The stop almost certainly "
            f"self-filled earlier. Local state was cleared and NO sell was submitted, avoiding an unintended "
            f"short. Verify realized P&L for {symbol}.",
            level="warning",
        )
        return

    # For a full close, cancel the still-open protective stop first so it can't
    # fire on the shares we're about to sell and flip us short from the other side.
    if not is_partial:
        cancel_stop_order(client, pos.get("stop_order_id"))

    intended = shares if (is_partial and shares) else recorded_remaining
    qty = plan_sell_qty(intended, held)
    if qty <= 0:
        print(f"No shares left to sell for {symbol}.")
        return
    if qty < intended:
        print(f"{symbol}: clamping sell qty {intended} -> {qty} to match broker-held shares "
              f"(avoids overselling into a short).")

    sell_req = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(sell_req)
    filled = wait_for_fill(client, str(order.id))
    if not filled:
        print(f"Sell order for {symbol} did not fill.")
        return

    fill_price = float(filled.filled_avg_price)
    filled_qty = int(float(filled.filled_qty))
    entry_price = pos["entry_price"]
    pnl_dollars = (fill_price - entry_price) * filled_qty
    pnl_pct = (fill_price - entry_price) / entry_price * 100

    entry_time = pos.get("entry_time", "")
    hold_str = ""
    if entry_time:
        try:
            from datetime import datetime as dt
            entry_dt = dt.fromisoformat(entry_time)
            delta = datetime.now(timezone.utc) - entry_dt
            hours = int(delta.total_seconds() / 3600)
            hold_str = f"{hours}h" if hours < 24 else f"{hours//24}d {hours%24}h"
        except Exception:
            pass

    if is_partial:
        positions[symbol]["partial_sold"] = True
        positions[symbol]["partial_sold_shares"] = pos.get("partial_sold_shares", 0) + filled_qty
        event = "PARTIAL_EXIT"
    else:
        del positions[symbol]
        event = "EXIT"

    write_json("positions.json", positions)

    append_jsonl("trade_log.jsonl", {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "symbol": symbol,
        "shares": filled_qty,
        "price": fill_price,
        "pnl_dollars": round(pnl_dollars, 2),
        "pnl_pct": round(pnl_pct, 2),
        "exit_reason": reason,
    })

    action = "PARTIAL SELL" if is_partial else "SELL"
    sign = "+" if pnl_dollars >= 0 else ""
    print(f"{action} {filled_qty} {symbol} @ ${fill_price:.2f} | P&L: {sign}${pnl_dollars:.2f} ({sign}{pnl_pct:.2f}%) | {reason}")
    post_trade_alert("SELL", symbol, filled_qty, fill_price, pnl_dollars=pnl_dollars, pnl_pct=pnl_pct, exit_reason=reason, hold_duration=hold_str)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=["buy", "sell", "partial_sell"])
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--shares", type=int, default=0)
    parser.add_argument("--stop", type=float, default=0)
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    client = get_trading_client()
    symbol = args.symbol.upper()

    if args.action == "buy":
        if not args.shares or not args.stop:
            print("--shares and --stop are required for buy.")
            sys.exit(1)
        place_buy(client, symbol, args.shares, args.stop)
    elif args.action == "sell":
        place_sell(client, symbol, args.reason or "manual sell")
    elif args.action == "partial_sell":
        if not args.shares:
            print("--shares required for partial_sell.")
            sys.exit(1)
        place_sell(client, symbol, args.reason or "partial profit target", shares=args.shares, is_partial=True)


if __name__ == "__main__":
    main()
