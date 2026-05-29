"""Singleton Alpaca client factory. Import get_trading_client() or get_data_client()."""

import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient

load_dotenv()

_trading_client: TradingClient | None = None
_data_client: StockHistoricalDataClient | None = None


def get_trading_client() -> TradingClient:
    global _trading_client
    if _trading_client is None:
        key = os.environ["ALPACA_API_KEY"]
        secret = os.environ["ALPACA_SECRET_KEY"]
        base_url = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        paper = "paper" in base_url
        _trading_client = TradingClient(key, secret, paper=paper)
    return _trading_client


def get_data_client() -> StockHistoricalDataClient:
    global _data_client
    if _data_client is None:
        key = os.environ["ALPACA_API_KEY"]
        secret = os.environ["ALPACA_SECRET_KEY"]
        _data_client = StockHistoricalDataClient(key, secret)
    return _data_client
