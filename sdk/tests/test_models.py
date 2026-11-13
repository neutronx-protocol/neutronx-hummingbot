from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from neutronx_sdk.models import (
    AgentKey,
    AgentKeyProblem,
    ChainStatus,
    FeeTier,
    Market,
    Order,
    OrderBook,
    Position,
    SubaccountEquity,
    agent_key_problem,
    position_side,
)
from neutronx_sdk.orders import AGENT_KEY_MSG_TYPE_URLS
from neutronx_sdk.proto import new


def test_market_reads_plain_decimal_fields() -> None:
    market = Market.from_proto(
        new(
            "neutronx.perps.v1.QueryMarketResponse",
            pair="ADA/USDC",
            status="active",
            tick_size="0.000100000000000000",
            min_quantity="1.000000000000000000",
            max_leverage="10.000000000000000000",
            maker_fee_rate="0.000200000000000000",
            taker_fee_rate="0.000500000000000000",
            maintenance_margin="0.010000000000000000",
            price_band_percent="0.500000000000000000",
        )
    )
    assert market.is_active
    assert market.tick_size == Decimal("0.0001")
    assert str(market.tick_size) == "0.0001"
    assert market.maker_fee_rate == Decimal("0.0002")
    assert market.max_leverage == 10


def test_order_book_reads_legacy_dec_and_empty_sides() -> None:
    book = OrderBook.from_proto(
        new(
            "neutronx.orderbook.v1.QueryOrderBookResponse",
            pair="ADA/USDC",
            best_bid="0",
            best_ask="222000000000000000",
            settleable_best_ask="223000000000000000",
            height=23157913,
            asks=[
                new(
                    "neutronx.orderbook.v1.PriceLevelProto",
                    price="222000000000000000",
                    quantity="5000000000000000000",
                    order_count=2,
                    band_state="parked_outside_settle_band",
                )
            ],
        )
    )
    assert book.best_bid is None
    assert book.best_ask == Decimal("0.222")
    assert book.settleable_best_bid is None
    assert book.settleable_best_ask == Decimal("0.223")
    assert book.asks[0].parked
    assert book.asks[0].quantity == 5
    assert book.height == 23157913


def test_user_order_flags_and_state() -> None:
    order = Order.from_user_order(
        new(
            "neutronx.orderbook.v1.OrderProto",
            order_id=10,
            pair="BTC/USDC",
            side="BUY",
            order_type="LIMIT",
            status="open",
            price="65000.500000000000000000",
            quantity="0.003000000000000000",
            filled_quantity="0.001000000000000000",
            flags=1,
            client_id=7,
            band_state="",
        )
    )
    assert order.is_short_term
    assert order.is_resting
    assert not order.is_parked
    assert order.price == Decimal("65000.5")
    assert order.remaining_quantity == Decimal("0.002")
    assert order.leverage is None


def test_order_query_response_is_flat() -> None:
    order = Order.from_order(
        new(
            "neutronx.orderbook.v1.QueryOrderResponse",
            id=11,
            pair="BTC/USDC",
            status="PARTIALLY_FILLED",
            price="65000500000000000000000",
            quantity="3000000000000000",
            filled="1000000000000000",
            leverage="3000000000000000000",
        )
    )
    assert order.order_id == 11
    assert order.is_resting
    assert not order.is_short_term
    assert order.filled_quantity == Decimal("0.001")
    assert order.leverage == 3


@pytest.mark.parametrize(
    ("margin_type", "isolated", "cross", "price", "reachable"),
    [
        ("ISOLATED", "60000.000000000000000000", "1", Decimal(60000), True),
        ("CROSS", "60000.000000000000000000", "", None, None),
        ("CROSS", "1", "-5.000000000000000000", None, False),
        ("", "1", "55000.000000000000000000", Decimal(55000), True),
    ],
)
def test_position_liquidation_follows_margin_type(
    margin_type: str,
    isolated: str,
    cross: str,
    price: Decimal | None,
    reachable: bool | None,
) -> None:
    position = Position.from_proto(
        new(
            "neutronx.perps.v1.PositionProto",
            id=3,
            pair="BTC/USDC",
            side="SELL",
            quantity="0.5",
            entry_price="65000.0",
            margin_type=margin_type,
            liquidation_price=isolated,
            cross_liquidation_price=cross,
        )
    )
    assert position.side == "SHORT"
    assert position.leverage == 1
    assert position.status == "OPEN"
    assert position.liquidation_price == price
    assert position.liquidation_reachable is reachable


def test_fee_tier_volumes_stay_in_base_units() -> None:
    tier = FeeTier.from_proto(
        new(
            "neutronx.orderbook.v1.QueryFeeTierResponse",
            tier_index=1,
            maker_fee_rate="200000000000000",
            taker_fee_rate="500000000000000",
            trailing_volume="27350047738",
            next_threshold="250000000000",
            volume_to_next="222649952262",
            has_next_tier=True,
        )
    )
    assert tier.maker_fee_rate == Decimal("0.0002")
    assert tier.trailing_volume + tier.volume_to_next == tier.next_threshold


def test_subaccount_equity_collateral_is_base_units() -> None:
    equity = SubaccountEquity.from_proto(
        new(
            "neutronx.perps.v1.QuerySubaccountEquityResponse",
            collateral="4000000000",
            equity="4000000000000000000000",
            maintenance_required="0",
            marks_fresh=True,
        )
    )
    assert equity.collateral == 4_000_000_000
    assert equity.equity == 4000
    assert equity.marks_fresh


def test_chain_status_time_is_utc() -> None:
    status = ChainStatus.from_proto(
        new(
            "cosmos.base.node.v1beta1.StatusResponse",
            height=99,
            timestamp=new("google.protobuf.Timestamp", seconds=1_762_000_000, nanos=123_456_789),
        )
    )
    assert status.height == 99
    assert status.block_time == datetime(2025, 11, 1, 12, 26, 40, 123456, tzinfo=timezone.utc)


BASE_AGENT_KEY = AgentKey(
    account="neutronx1acc",
    key_id=5,
    name="bot",
    pubkey=b"\x02" * 33,
    expires_at=2_000,
    created_block=1,
    msg_type_urls=AGENT_KEY_MSG_TYPE_URLS,
    pairs=(),
    subaccount_ids=(),
)


def _agent_key(**overrides: Any) -> AgentKey:
    return replace(BASE_AGENT_KEY, **overrides)


@pytest.mark.parametrize(
    ("enabled", "key", "problem"),
    [
        (False, _agent_key(), AgentKeyProblem.MODULE_DISABLED),
        (True, None, AgentKeyProblem.NOT_FOUND),
        (True, _agent_key(pubkey=b"\x03" * 33), AgentKeyProblem.PUBKEY_MISMATCH),
        (True, _agent_key(expires_at=1_000), AgentKeyProblem.EXPIRED),
        (
            True,
            _agent_key(msg_type_urls=AGENT_KEY_MSG_TYPE_URLS[:2]),
            AgentKeyProblem.MISSING_MSG_TYPES,
        ),
        (True, _agent_key(pairs=("BTC/USDC",)), AgentKeyProblem.SCOPE_RESTRICTED),
        (True, _agent_key(subaccount_ids=(1,)), AgentKeyProblem.SCOPE_RESTRICTED),
        (True, _agent_key(msg_type_urls=()), None),
        (True, _agent_key(), None),
    ],
)
def test_agent_key_problem(
    enabled: bool, key: AgentKey | None, problem: AgentKeyProblem | None
) -> None:
    assert agent_key_problem(enabled, key, b"\x02" * 33, now=1_500) is problem


def test_agent_key_from_proto() -> None:
    key = AgentKey.from_proto(
        new(
            "neutronx.agentkeys.v1.AgentKey",
            account="neutronx1acc",
            id=5,
            pubkey=b"\x02" * 33,
            expires_at=2_000,
            permissions=new("neutronx.agentkeys.v1.Permissions", msg_type_urls=["/a"], pairs=["X"]),
        )
    )
    assert key.key_id == 5
    assert key.msg_type_urls == ("/a",)
    assert key.pairs == ("X",)


@pytest.mark.parametrize(
    ("side", "expected"),
    [("BUY", "LONG"), ("long", "LONG"), ("SELL", "SHORT"), ("SHORT", "SHORT"), ("x", "X")],
)
def test_position_side(side: str, expected: str) -> None:
    assert position_side(side) == expected
