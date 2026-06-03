"""Place a buy, sell, or partial-sell order via Alpaca. Updates data/positions.json.
Sends a Discord trade alert after every fill.

Usage:
    python scripts/place_order.py --action buy --symbol AAPL --shares 45 --stop 184.69 --rsi 58.3 --rel_vol 2.1 --sentiment positive
    python scripts/place_order.py --action sell --symbol AAPL --reason "Trailing stop"
    python scripts/place_order.py --action partial_sell --symbol AAPL --shares 22 --reason "Partial profit target"
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.alpaca_client import get_trading_client
from lib.notify import post_attention, post_trade_alert
from lib.risk import initial_stop_price
from lib.state import append_jsonl, read_json, write_json
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


def wait_for_fill(client, order_id: str, max_wait: int = 30) -> dict | None:
    """Poll until order is filled or max_wait seconds elapsed."""
    for _ in range(max_wait):
        order = client.get_order_by_id(order_id)
        if order.status in ("filled", "partially_filled"):
            return order
        if order.status in ("canceled", "expired", "rejected"):
            print(f"Order {order_id} ended with status: {order.status}")
            return None
        time.sleep(1)
    print(f"Order {order_id} not filled after {max_wait}s")
    return None


def place_buy(client, symbol: str, shares: int, stop_price: float, rsi: float, rel_vol: float, sentiment: str) -> None:
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
    filled = wait_for_fill(client, str(order.id))
    if not filled:
        print(f"Buy order for {symbol} did not fill.")
        return

    fill_price = float(filled.filled_avg_price)
    filled_qty = int(float(filled.filled_qty))
    actual_stop = initial_stop_price(fill_price, (fill_price - stop_price) / 1.5)

    # Submit stop loss order
    try:
        stop_req = StopOrderRequest(
            symbol=symbol,
            qty=filled_qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            stop_price=round(stop_price, 2),
        )
        stop_order = client.submit_order(stop_req)
        stop_order_id = str(stop_order.id)
    except Exception as e:
        print(f"Warning: stop order for {symbol} failed: {e}")
        post_attention(
            f"Stop Order Not Placed: {symbol}",
            f"Buy order for {symbol} filled but stop-loss order failed to submit.\n"
            f"Error: {e}\n"
            f"Position is unprotected. Place a stop manually in Alpaca.",
            level="warning",
        )
        stop_order_id = None

    position = {
        "symbol": symbol,
        "entry_price": fill_price,
        "shares": filled_qty,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "atr_at_entry": round((fill_price - stop_price) / 1.5, 4),
        "rsi_at_entry": rsi,
        "rel_vol_at_entry": rel_vol,
        "perplexity_sentiment_at_entry": sentiment,
        "initial_stop": stop_price,
        "current_stop": stop_price,
        "highest_close_since_entry": fill_price,
        "trailing_stop_active": False,
        "partial_sold": False,
        "partial_sold_shares": 0,
        "overnight_hold": False,
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
        "rsi": rsi,
        "rel_vol": rel_vol,
        "perplexity": sentiment,
    })

    print(f"BUY {filled_qty} {symbol} @ ${fill_price:.2f}, stop ${stop_price:.2f}")
    post_trade_alert("BUY", symbol, filled_qty, fill_price, stop=stop_price, rsi=rsi, rel_vol=rel_vol, sentiment=sentiment)


def place_sell(client, symbol: str, reason: str, shares: int | None = None, is_partial: bool = False) -> None:
    positions = read_json("positions.json", default={})
    if symbol not in positions:
        print(f"No open position for {symbol}.")
        return

    pos = positions[symbol]
    qty = shares if (is_partial and shares) else pos["shares"] - pos.get("partial_sold_shares", 0)
    if qty <= 0:
        print(f"No shares left to sell for {symbol}.")
        return

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
    parser.add_argument("--rsi", type=float, default=0)
    parser.add_argument("--rel_vol", type=float, default=0)
    parser.add_argument("--sentiment", default="neutral")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    client = get_trading_client()
    symbol = args.symbol.upper()

    if args.action == "buy":
        if not args.shares or not args.stop:
            print("--shares and --stop are required for buy.")
            sys.exit(1)
        place_buy(client, symbol, args.shares, args.stop, args.rsi, args.rel_vol, args.sentiment)
    elif args.action == "sell":
        place_sell(client, symbol, args.reason or "manual sell")
    elif args.action == "partial_sell":
        if not args.shares:
            print("--shares required for partial_sell.")
            sys.exit(1)
        place_sell(client, symbol, args.reason or "partial profit target", shares=args.shares, is_partial=True)


if __name__ == "__main__":
    main()
