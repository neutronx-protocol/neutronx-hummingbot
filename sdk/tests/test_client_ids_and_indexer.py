from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from neutronx_sdk import MAINNET, TESTNET, ClientIdAllocator, NeutronXError
from neutronx_sdk.indexer import (
    AccountFundingV1,
    FillV1,
    OrderbookV1,
    OrderV1,
    PageV1,
    PositionV1,
    StatusV1,
    StreamFrame,
    TickerV1,
    TradeV1,
    compact_pair,
    ping_message,
    subscribe_message,
    unsubscribe_message,
)
from neutronx_sdk.indexer.api import (
    ANONYMOUS_MAX_SUBSCRIPTIONS,
    KEY_MAX_SUBSCRIPTIONS,
    account_fills_path,
    account_funding_path,
    account_orders_path,
    account_positions_path,
    max_subscriptions,
    orderbook_path,
    requests_per_minute,
    ticker_path,
    trades_path,
)
from neutronx_sdk.orders import CLIENT_ID_MAX


def test_allocator_seeds_past_open_ids_and_skips_used() -> None:
    allocator = ClientIdAllocator()
    allocator.seed([5, 9, 0, CLIENT_ID_MAX + 1])
    assert allocator.allocate() == 10
    assert 9 in allocator
    assert len(allocator) == 3
    allocator.release(9)
    assert 9 not in allocator


def test_allocator_wraps_and_never_returns_a_live_id() -> None:
    allocator = ClientIdAllocator(start=CLIENT_ID_MAX)
    allocator.seed([1])
    assert allocator.allocate() == CLIENT_ID_MAX
    assert allocator.allocate() == 2


def test_allocator_reports_exhaustion() -> None:
    allocator = ClientIdAllocator(limit=3)
    assert [allocator.allocate() for _ in range(3)] == [1, 2, 3]
    with pytest.raises(NeutronXError, match="exhausted"):
        allocator.allocate()
    allocator.release(2)
    assert allocator.allocate() == 2


def test_allocator_limit_is_bounded() -> None:
    assert ClientIdAllocator(limit=2**31 - 1).limit == 2**31 - 1
    with pytest.raises(ValueError, match="limit"):
        ClientIdAllocator(limit=0)
    with pytest.raises(ValueError, match="limit"):
        ClientIdAllocator(limit=CLIENT_ID_MAX + 1)


def test_compact_pair_and_paths() -> None:
    assert compact_pair("btc/usdc") == "BTCUSDC"
    assert compact_pair("BTC-USDC") == "BTCUSDC"
    assert ticker_path("BTC/USDC") == "/markets/BTCUSDC/ticker"
    assert orderbook_path("BTC/USDC") == "/markets/BTCUSDC/orderbook"
    assert trades_path("BTC/USDC") == "/markets/BTCUSDC/trades"
    assert account_orders_path("neutronx1a") == "/accounts/neutronx1a/orders"
    assert account_fills_path("neutronx1a") == "/accounts/neutronx1a/fills"
    assert account_positions_path("neutronx1a") == "/accounts/neutronx1a/positions"
    assert subscribe_message("orderbook", "BTC/USDC") == {
        "type": "subscribe",
        "channel": "orderbook",
        "id": "BTC/USDC",
    }
    assert unsubscribe_message("fills", "neutronx1a")["type"] == "unsubscribe"
    assert ping_message() == {"type": "ping"}


def test_orderbook_and_ticker() -> None:
    book = OrderbookV1.from_json(
        {
            "pair": "BTCUSDC",
            "bids": [{"price": "65000", "quantity": "0.5", "order_count": 2, "settleable": True}],
            "asks": [{"price": "65010.5", "quantity": "1", "order_count": 1, "settleable": None}],
            "best_bid": "65000",
            "best_ask": "65010.5",
            "spread": "10.5",
        }
    )
    assert book.bids[0].price == Decimal(65000)
    assert book.asks[0].settleable is None
    assert book.block_height is None
    ticker = TickerV1.from_json(
        {
            "pair": "BTCUSDC",
            "last_price": "65005",
            "mark_price": "65004.1",
            "funding_rate": "0.0001",
            "next_funding_at": "2026-11-10T12:00:00+00:00",
            "volume_24h": "1000",
        }
    )
    assert ticker.next_funding_at == datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    assert TickerV1.from_json({"pair": "X", "next_funding_at": None}).funding_rate is None


def test_trade_with_and_without_taker_side() -> None:
    base = {
        "id": "100:3",
        "pair": "BTCUSDC",
        "price": "65000",
        "quantity": "0.1",
        "buyer": "a",
        "seller": "b",
        "buyer_order_id": 1,
        "seller_order_id": 2,
        "block_height": 100,
        "time": "2026-11-10T12:00:00Z",
    }
    assert TradeV1.from_json(base).taker_side is None
    assert TradeV1.from_json({**base, "taker_side": "sell"}).taker_side == "SELL"


def test_order_fill_position_status() -> None:
    order = OrderV1.from_json(
        {
            "id": 77,
            "client_id": 1234,
            "subaccount_id": 0,
            "pair": "BTCUSDC",
            "side": "BUY",
            "type": "LIMIT",
            "status": "PARTIALLY_FILLED",
            "price": "65000",
            "quantity": "0.3",
            "filled": "0.1",
            "leverage": "3",
            "reduce_only": False,
            "post_only": True,
            "time_in_force": "GTC",
            "good_til_block": None,
            "block_height": 99,
            "time": "2026-11-10T12:00:00+00:00",
            "updated_at": "2026-11-10T12:00:05+00:00",
        }
    )
    assert (order.order_id, order.client_id, order.filled) == (77, 1234, Decimal("0.1"))
    fill = FillV1.from_json(
        {
            "id": "100:3",
            "pair": "BTCUSDC",
            "side": "BUY",
            "price": "65000",
            "quantity": "0.1",
            "fee": "1.3",
            "order_id": 77,
            "subaccount_id": 0,
            "block_height": 100,
            "time": "2026-11-10T12:00:00+00:00",
        }
    )
    assert fill.is_taker is None
    maker = FillV1.from_json({**fill_json(), "role": "maker", "tx_hash": None, "client_id": 9})
    assert maker.is_taker is False
    assert (maker.client_id, maker.tx_hash) == (9, None)
    taker = FillV1.from_json({**fill_json(), "id": "1:1:SELL", "role": "TAKER", "tx_hash": "AB12"})
    assert (taker.is_taker, taker.tx_hash, taker.fill_id) == (True, "AB12", "1:1:SELL")
    position = PositionV1.from_json(
        {
            "id": 5,
            "subaccount_id": 0,
            "pair": "BTCUSDC",
            "side": "SHORT",
            "status": "OPEN",
            "quantity": "0.2",
            "entry_price": "65000",
            "leverage": "3",
            "margin_type": "cross",
            "liquidation_price": "70000",
            "unrealized_pnl": "-1.5",
            "funding_accrued": "0.01",
        }
    )
    assert position.margin_type == "CROSS"
    assert position.unrealized_pnl == Decimal("-1.5")
    status = StatusV1.from_json(
        {"indexed_height": 10, "chain_height": 11, "lag_blocks": 1, "indexed_age_seconds": 0.5}
    )
    assert status.lag_blocks == 1


def fill_json() -> dict[str, object]:
    return {
        "id": "1:1",
        "pair": "BTCUSDC",
        "side": "SELL",
        "price": "1",
        "quantity": "1",
        "order_id": 1,
        "block_height": 1,
        "time": "2026-11-10T12:00:00+00:00",
    }


def test_stream_frames_and_pages() -> None:
    frame = StreamFrame.from_json(
        {
            "type": "snapshot",
            "channel": "fills",
            "id": "neutronx1a",
            "seq": 1,
            "data": [fill_json()],
        }
    )
    assert frame.is_data
    assert frame.is_snapshot
    assert len(frame.rows()) == 1
    single = StreamFrame.from_json(
        {"type": "update", "channel": "orderbook", "id": "BTCUSDC", "seq": 4, "data": {}}
    )
    assert not single.is_snapshot
    assert single.rows() == [{}]
    control = StreamFrame.from_json({"type": "pong"})
    assert not control.is_data
    assert control.rows() == []
    page = PageV1.from_json({"items": [fill_json()], "next_cursor": None})
    assert page.next_cursor is None
    assert len(page.items) == 1


def test_order_flags_cancel_reason_and_open_state() -> None:
    base = {
        "id": 5,
        "pair": "BTCUSDC",
        "side": "SELL",
        "status": "CANCELLED",
        "quantity": "1",
        "time": "2026-11-10T12:00:00+00:00",
    }
    final = OrderV1.from_json({**base, "flags": 1, "cancel_reason": "replaced"})
    assert final.is_short_term
    assert not final.is_open
    assert final.cancel_reason == "replaced"
    legacy = OrderV1.from_json({**base, "status": "OPEN", "flags": None})
    assert (legacy.flags, legacy.is_open, legacy.cancel_reason) == (0, True, None)


def test_account_funding_payment() -> None:
    payment = AccountFundingV1.from_json(
        {
            "position_id": 3,
            "subaccount_id": 0,
            "pair": "BTCUSDC",
            "side": "long",
            "quantity": "0.5",
            "amount": "-0.12",
            "rate": None,
            "mark_price": "65000",
            "block_height": 7,
            "time": "2026-11-10T12:00:00+00:00",
        }
    )
    assert (payment.amount, payment.rate, payment.side) == (Decimal("-0.12"), None, "LONG")
    assert account_funding_path("neutronx1a") == "/accounts/neutronx1a/funding"


def test_error_frames_and_limits() -> None:
    error = StreamFrame.from_json(
        {"type": "error", "code": "TOO_MANY_SUBSCRIPTIONS", "message": "max 50"}
    )
    assert error.is_error
    assert not error.is_data
    assert (error.code, error.message, error.channel) == ("TOO_MANY_SUBSCRIPTIONS", "max 50", None)
    assert not StreamFrame.from_json({"type": "snapshot", "channel": "orders"}).is_error
    assert max_subscriptions(None) == ANONYMOUS_MAX_SUBSCRIPTIONS == 50
    assert max_subscriptions("nx_key") == KEY_MAX_SUBSCRIPTIONS == 200
    assert (requests_per_minute(""), requests_per_minute("nx_key")) == (120, 600)


def test_network_presets_carry_the_public_indexer() -> None:
    assert MAINNET.indexer_url == "https://api.neutronx.com/v1"
    assert MAINNET.indexer_ws_url == "wss://api.neutronx.com/v1/ws"
    assert TESTNET.indexer_url == "https://indexer-test.neutronchain.io/v1"
    assert TESTNET.indexer_ws_url == "wss://indexer-test.neutronchain.io/v1/ws"
    custom = TESTNET.with_indexer("https://example.test/v1/", "wss://example.test/v1/ws")
    assert custom.indexer_url == "https://example.test/v1"
