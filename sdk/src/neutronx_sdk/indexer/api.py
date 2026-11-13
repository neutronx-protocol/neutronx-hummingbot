from __future__ import annotations

from typing import Any

CHANNEL_TICKER = "ticker"
CHANNEL_ORDERBOOK = "orderbook"
CHANNEL_TRADES = "trades"
CHANNEL_POSITIONS = "positions"
CHANNEL_ORDERS = "orders"
CHANNEL_FILLS = "fills"
PAIR_CHANNELS = frozenset({CHANNEL_TICKER, CHANNEL_ORDERBOOK, CHANNEL_TRADES})
OWNER_CHANNELS = frozenset({CHANNEL_POSITIONS, CHANNEL_ORDERS, CHANNEL_FILLS})

FRAME_CONNECTED = "connected"
FRAME_SUBSCRIBED = "subscribed"
FRAME_ERROR = "error"
FRAME_PONG = "pong"

PING_INTERVAL_SECONDS = 20.0
API_KEY_HEADER = "X-API-Key"
MAX_PAGE_LIMIT = 200
ANONYMOUS_MAX_SUBSCRIPTIONS = 50
KEY_MAX_SUBSCRIPTIONS = 200
ANONYMOUS_REQUESTS_PER_MINUTE = 120
KEY_REQUESTS_PER_MINUTE = 600

PATH_STATUS = "/status"
PATH_TICKERS = "/markets/tickers"


def compact_pair(pair: str) -> str:
    return "".join(ch for ch in pair.upper() if ch.isalnum())


def ticker_path(pair: str) -> str:
    return f"/markets/{compact_pair(pair)}/ticker"


def orderbook_path(pair: str) -> str:
    return f"/markets/{compact_pair(pair)}/orderbook"


def trades_path(pair: str) -> str:
    return f"/markets/{compact_pair(pair)}/trades"


def account_orders_path(owner: str) -> str:
    return f"/accounts/{owner}/orders"


def account_fills_path(owner: str) -> str:
    return f"/accounts/{owner}/fills"


def account_positions_path(owner: str) -> str:
    return f"/accounts/{owner}/positions"


def account_funding_path(owner: str) -> str:
    return f"/accounts/{owner}/funding"


def max_subscriptions(api_key: str | None) -> int:
    return KEY_MAX_SUBSCRIPTIONS if api_key else ANONYMOUS_MAX_SUBSCRIPTIONS


def requests_per_minute(api_key: str | None) -> int:
    return KEY_REQUESTS_PER_MINUTE if api_key else ANONYMOUS_REQUESTS_PER_MINUTE


def subscribe_message(channel: str, stream_id: str) -> dict[str, Any]:
    return {"type": "subscribe", "channel": channel, "id": stream_id}


def unsubscribe_message(channel: str, stream_id: str) -> dict[str, Any]:
    return {"type": "unsubscribe", "channel": channel, "id": stream_id}


def ping_message() -> dict[str, Any]:
    return {"type": "ping"}
