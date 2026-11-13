from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from neutronx_sdk import OrderRequest, OrderType, Side, TimeInForce
from neutronx_sdk.legacy_dec import (
    from_legacy_dec,
    optional_legacy_dec,
    positive_legacy_dec,
    to_legacy_dec,
)
from neutronx_sdk.orders import (
    AGENT_KEY_MSG_TYPE_URLS,
    BATCH_CANCEL_MAX_IDS,
    batch_cancel_orders_msg,
    batch_place_orders_msg,
    cancel_short_term_order_msg,
    close_position_msg,
    deposit_to_subaccount_msg,
    good_til_block,
    is_batchable,
    place_order_msg,
    place_short_term_order_msg,
    snap_to_tick,
    withdraw_from_subaccount_msg,
)

CREATOR = "neutronx1creator"
BASE_REQUEST = OrderRequest(
    pair="BTC/USDC",
    side=Side.BUY,
    price=Decimal("65000.5"),
    quantity=Decimal("0.001"),
    leverage=Decimal(3),
    client_id=7,
)


def _request(**overrides: Any) -> OrderRequest:
    return replace(BASE_REQUEST, **overrides)


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        (Decimal("65000.5"), "65000500000000000000000"),
        (Decimal("0.001"), "1000000000000000"),
        (Decimal("1e-19"), "0"),
        (Decimal("-1.5"), "-1500000000000000000"),
        (3, "3000000000000000000"),
        ("0.25", "250000000000000000"),
    ],
)
def test_legacy_dec_encoding(value: Decimal | int | str, encoded: str) -> None:
    assert to_legacy_dec(value) == encoded


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_legacy_dec_refuses_non_finite(value: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        to_legacy_dec(value)


@pytest.mark.parametrize(
    ("raw", "decoded"),
    [
        ("222000000000000000", Decimal("0.222")),
        ("0.000200000000000000", Decimal("0.0002")),
        ("-1500000000000000000", Decimal("-1.5")),
        ("15", Decimal("15e-18")),
        ("", Decimal(0)),
        (" 7 ", Decimal("7e-18")),
    ],
)
def test_legacy_dec_decoding(raw: str, decoded: Decimal) -> None:
    assert from_legacy_dec(raw) == decoded


def test_optional_and_positive_decoding() -> None:
    assert optional_legacy_dec("") is None
    assert optional_legacy_dec("0") == 0
    assert positive_legacy_dec("0") is None
    assert positive_legacy_dec("-1000000000000000000") is None
    assert positive_legacy_dec("1000000000000000000") == 1


def test_place_order_msg_fields() -> None:
    msg = place_order_msg(CREATOR, _request(time_in_force=TimeInForce.IOC, reduce_only=True))
    assert msg.DESCRIPTOR.full_name == "neutronx.orderbook.v1.MsgPlaceOrder"
    assert (msg.side, msg.order_type, msg.time_in_force) == ("BUY", "LIMIT", "IOC")
    assert msg.price == "65000500000000000000000"
    assert msg.reduce_only
    assert msg.post_only
    assert msg.client_id == 7


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"pair": ""}, "pair"),
        ({"quantity": Decimal(0)}, "quantity"),
        ({"leverage": Decimal(0)}, "leverage"),
        ({"price": Decimal(0)}, "positive price"),
        ({"client_id": 2**32}, "uint32"),
        ({"subaccount_id": -1}, "subaccount_id"),
    ],
)
def test_order_request_validation(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _request(**overrides)


def test_market_order_may_omit_price() -> None:
    request = _request(order_type=OrderType.MARKET, price=Decimal(0))
    assert place_order_msg(CREATOR, request).price == "0"


def test_short_term_order_rules() -> None:
    msg = place_short_term_order_msg(CREATOR, _request(), 120)
    assert msg.good_til_block == 120
    with pytest.raises(ValueError, match="LIMIT"):
        place_short_term_order_msg(CREATOR, _request(order_type=OrderType.MARKET), 120)
    with pytest.raises(ValueError, match="client_id"):
        place_short_term_order_msg(CREATOR, _request(client_id=0), 120)
    with pytest.raises(ValueError, match="good_til_block"):
        place_short_term_order_msg(CREATOR, _request(), 0)
    with pytest.raises(ValueError, match="client_id"):
        cancel_short_term_order_msg(CREATOR, 0, "BTC/USDC", 10)


def test_batch_limits() -> None:
    assert list(batch_cancel_orders_msg(CREATOR, range(1, 51)).order_ids) == list(range(1, 51))
    with pytest.raises(ValueError, match=f"1-{BATCH_CANCEL_MAX_IDS}"):
        batch_cancel_orders_msg(CREATOR, [])
    with pytest.raises(ValueError, match=f"1-{BATCH_CANCEL_MAX_IDS}"):
        batch_cancel_orders_msg(CREATOR, range(51))
    assert batch_cancel_orders_msg(CREATOR, [1]).pair == ""
    assert len(batch_place_orders_msg(CREATOR, [_request(), _request(client_id=8)]).orders) == 2
    with pytest.raises(ValueError, match="1-50"):
        batch_place_orders_msg(CREATOR, [])
    with pytest.raises(ValueError, match="1-50"):
        batch_place_orders_msg(CREATOR, [_request(client_id=i) for i in range(1, 52)])
    with pytest.raises(ValueError, match="only GTC limit"):
        batch_place_orders_msg(CREATOR, [_request(), _request(time_in_force=TimeInForce.IOC)])
    with pytest.raises(ValueError, match="only GTC limit"):
        batch_place_orders_msg(CREATOR, [_request(order_type=OrderType.MARKET, price=Decimal(0))])


def test_batchable_orders_are_gtc_limits() -> None:
    assert is_batchable(_request())
    assert not is_batchable(_request(time_in_force=TimeInForce.IOC))
    assert not is_batchable(_request(time_in_force=TimeInForce.FOK))
    assert not is_batchable(_request(order_type=OrderType.MARKET, price=Decimal(0)))


def test_perps_messages() -> None:
    assert close_position_msg(CREATOR, 5).position_id == 5
    assert deposit_to_subaccount_msg(CREATOR, 1_000_000).amount == "1000000"
    assert withdraw_from_subaccount_msg(CREATOR, 1, subaccount_id=2).subaccount_id == 2
    with pytest.raises(ValueError, match="amount"):
        deposit_to_subaccount_msg(CREATOR, 0)


def test_good_til_block_is_capped_at_chain_ttl() -> None:
    assert good_til_block(100, 5) == 105
    assert good_til_block(100, 50) == 120
    with pytest.raises(ValueError, match="current_height"):
        good_til_block(0)


@pytest.mark.parametrize(
    ("price", "side", "tick", "snapped"),
    [
        (Decimal("1.2345"), Side.BUY, Decimal("0.01"), Decimal("1.23")),
        (Decimal("1.2345"), Side.SELL, Decimal("0.01"), Decimal("1.24")),
        (Decimal("1.23"), Side.SELL, Decimal("0.01"), Decimal("1.23")),
        (Decimal("0.004"), Side.BUY, Decimal("0.01"), Decimal("0.004")),
        (Decimal("1.2345"), Side.BUY, None, Decimal("1.2345")),
        (Decimal("1.2345"), Side.BUY, Decimal(0), Decimal("1.2345")),
    ],
)
def test_snap_to_tick(price: Decimal, side: Side, tick: Decimal | None, snapped: Decimal) -> None:
    assert snap_to_tick(price, side, tick) == snapped


def test_agent_key_msg_types_are_canonical() -> None:
    assert list(AGENT_KEY_MSG_TYPE_URLS) == sorted(set(AGENT_KEY_MSG_TYPE_URLS))
    assert len(AGENT_KEY_MSG_TYPE_URLS) == 6
