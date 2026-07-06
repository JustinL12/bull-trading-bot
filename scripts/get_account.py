"""Fetch account info from Alpaca and write to data/account.json."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.alpaca_client import get_trading_client
from lib.notify import post_attention
from lib.state import write_json


def main():
    client = get_trading_client()
    acct = client.get_account()

    data = {
        "equity": float(acct.equity),
        "cash": float(acct.cash),
        "buying_power": float(acct.buying_power),
        "portfolio_value": float(acct.portfolio_value),
        "last_equity": float(acct.last_equity),
        "daytrade_count": int(acct.daytrade_count or 0),
        "pattern_day_trader": acct.pattern_day_trader,
        "trading_blocked": acct.trading_blocked,
        "account_blocked": acct.account_blocked,
        "currency": acct.currency,
    }

    write_json("account.json", data)
    print(f"Account: equity=${data['equity']:,.2f}, buying_power=${data['buying_power']:,.2f}")

    if data.get("account_blocked"):
        post_attention(
            "Account Blocked",
            "Alpaca reports account_blocked=True. No trades can be placed.\n"
            "Check the Alpaca dashboard for the block reason.",
            level="critical",
        )
    elif data.get("trading_blocked"):
        post_attention(
            "Trading Blocked",
            "Alpaca reports trading_blocked=True. Verify account standing before the next session.",
            level="warning",
        )

    return data


if __name__ == "__main__":
    main()
