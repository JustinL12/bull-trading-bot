"""Fetch account info from Alpaca and write to data/account.json."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.alpaca_client import get_trading_client
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
        "daytrade_count": int(acct.daytrade_count),
        "pattern_day_trader": acct.pattern_day_trader,
        "trading_blocked": acct.trading_blocked,
        "account_blocked": acct.account_blocked,
        "currency": acct.currency,
    }

    write_json("account.json", data)
    print(f"Account: equity=${data['equity']:,.2f}, buying_power=${data['buying_power']:,.2f}")
    return data


if __name__ == "__main__":
    main()
