"""Singleton Finnhub client factory. Import get_finnhub_client()."""

import os
from dotenv import load_dotenv
import finnhub

load_dotenv()

_client: finnhub.Client | None = None


def get_finnhub_client() -> finnhub.Client:
    """Return a cached Finnhub client instance."""
    global _client
    if _client is None:
        api_key = os.environ.get("FINNHUB_API_KEY", "")
        if not api_key:
            raise EnvironmentError("FINNHUB_API_KEY is not set.")
        _client = finnhub.Client(api_key=api_key)
    return _client
