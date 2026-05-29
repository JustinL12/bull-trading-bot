"""Emergency: market-sell all open positions immediately.

Usage:
    python scripts/close_all_positions.py [--reason "text"]
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.alpaca_client import get_trading_client
from lib.clickup import post_trade_alert
from lib.state import append_jsonl, read_json, write_json
from alpaca.trading.requests import ClosePositionRequest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reason", default="Emergency close all positions")
    args = parser.parse_args()

    client = get_trading_client()
    positions = read_json("positions.json", default={})

    if not positions:
        # Also check Alpaca directly for any positions not tracked locally
        alpaca_positions = client.get_all_positions()
        if not alpaca_positions:
            print("No open positions.")
            return
        symbols = [p.symbol for p in alpaca_positions]
    else:
        symbols = list(positions.keys())

    print(f"Closing {len(symbols)} position(s): {', '.join(symbols)}")
    print(f"Reason: {args.reason}")

    for symbol in symbols:
        try:
            client.close_position(symbol)
            pos = positions.get(symbol, {})
            entry_price = pos.get("entry_price", 0)
            shares = pos.get("shares", 0)

            append_jsonl("trade_log.jsonl", {
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "EMERGENCY_EXIT",
                "symbol": symbol,
                "reason": args.reason,
            })
            post_trade_alert("SELL", symbol, shares, 0, exit_reason=args.reason)
            print(f"  Closed {symbol}")
        except Exception as e:
            print(f"  Error closing {symbol}: {e}")

    # Clear local positions state
    write_json("positions.json", {})
    print("All positions closed and positions.json cleared.")


if __name__ == "__main__":
    main()
