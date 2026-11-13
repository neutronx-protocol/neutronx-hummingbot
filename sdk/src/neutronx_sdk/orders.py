from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import Enum
from typing import Any

from neutronx_sdk.legacy_dec import to_legacy_dec
from neutronx_sdk.proto import new

TYPE_URL_PLACE_ORDER = "/neutronx.orderbook.v1.MsgPlaceOrder"
TYPE_URL_CANCEL_ORDER = "/neutronx.orderbook.v1.MsgCancelOrder"
TYPE_URL_BATCH_PLACE_ORDERS = "/neutronx.orderbook.v1.MsgBatchPlaceOrders"
TYPE_URL_BATCH_CANCEL_ORDERS = "/neutronx.orderbook.v1.MsgBatchCancelOrders"
TYPE_URL_PLACE_SHORT_TERM_ORDER = "/neutronx.orderbook.v1.MsgPlaceShortTermOrder"
TYPE_URL_CANCEL_SHORT_TERM_ORDER = "/neutronx.orderbook.v1.MsgCancelShortTermOrder"

AGENT_KEY_MSG_TYPE_URLS = tuple(
    sorted(
        {
            TYPE_URL_PLACE_ORDER,
            TYPE_URL_CANCEL_ORDER,
            TYPE_URL_BATCH_PLACE_ORDERS,
            TYPE_URL_BATCH_CANCEL_ORDERS,
            TYPE_URL_PLACE_SHORT_TERM_ORDER,
            TYPE_URL_CANCEL_SHORT_TERM_ORDER,
        }
    )
)

ORDER_FLAG_SHORT_TERM = 1
SHORT_TERM_MAX_TTL_BLOCKS = 20
BATCH_CANCEL_MAX_IDS = 50
BATCH_PLACE_MAX_ORDERS = 50
CLIENT_ID_MAX = 2**32 - 1


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


RESTING_ORDER_STATUSES = frozenset({OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value})


@dataclass(frozen=True)
class OrderRequest:
    pair: str
    side: Side
    price: Decimal
    quantity: Decimal
    leverage: Decimal
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.GTC
    post_only: bool = True
    reduce_only: bool = False
    subaccount_id: int = 0
    client_id: int = 0
    good_til_block: int = 0

    def __post_init__(self) -> None:
        if not self.pair:
            raise ValueError("pair is required")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.leverage <= 0:
            raise ValueError(f"leverage must be positive, got {self.leverage}")
        if self.order_type is OrderType.LIMIT and self.price <= 0:
            raise ValueError(f"a limit order needs a positive price, got {self.price}")
        if not 0 <= self.client_id <= CLIENT_ID_MAX:
            raise ValueError(f"client_id must fit uint32, got {self.client_id}")
        if self.subaccount_id < 0:
            raise ValueError(f"subaccount_id must not be negative, got {self.subaccount_id}")


def _order_fields(request: OrderRequest) -> dict[str, Any]:
    return {
        "pair": request.pair,
        "side": request.side.value,
        "order_type": request.order_type.value,
        "price": to_legacy_dec(request.price),
        "quantity": to_legacy_dec(request.quantity),
        "leverage": to_legacy_dec(request.leverage),
        "reduce_only": request.reduce_only,
        "post_only": request.post_only,
        "time_in_force": request.time_in_force.value,
        "subaccount_id": request.subaccount_id,
        "client_id": request.client_id,
    }


def place_order_msg(creator: str, request: OrderRequest) -> Any:
    return new(
        "neutronx.orderbook.v1.MsgPlaceOrder",
        creator=creator,
        good_til_block=request.good_til_block,
        **_order_fields(request),
    )


def is_batchable(request: OrderRequest) -> bool:
    return request.order_type is OrderType.LIMIT and request.time_in_force is TimeInForce.GTC


def batch_place_orders_msg(creator: str, requests: Iterable[OrderRequest]) -> Any:
    batch = list(requests)
    if not 1 <= len(batch) <= BATCH_PLACE_MAX_ORDERS:
        raise ValueError(f"batch place takes 1-{BATCH_PLACE_MAX_ORDERS} orders, got {len(batch)}")
    if not all(is_batchable(request) for request in batch):
        raise ValueError("only GTC limit orders are batched")
    orders = [place_order_msg(creator, request) for request in batch]
    return new("neutronx.orderbook.v1.MsgBatchPlaceOrders", creator=creator, orders=orders)


def cancel_order_msg(creator: str, order_id: int, pair: str, subaccount_id: int = 0) -> Any:
    return new(
        "neutronx.orderbook.v1.MsgCancelOrder",
        creator=creator,
        order_id=order_id,
        pair=pair,
        subaccount_id=subaccount_id,
    )


def batch_cancel_orders_msg(creator: str, order_ids: Iterable[int]) -> Any:
    ids = list(order_ids)
    if not 1 <= len(ids) <= BATCH_CANCEL_MAX_IDS:
        raise ValueError(f"batch cancel takes 1-{BATCH_CANCEL_MAX_IDS} order ids, got {len(ids)}")
    return new("neutronx.orderbook.v1.MsgBatchCancelOrders", creator=creator, order_ids=ids)


def place_short_term_order_msg(creator: str, request: OrderRequest, good_til_block: int) -> Any:
    if request.order_type is not OrderType.LIMIT:
        raise ValueError(f"a short-term order must be LIMIT, got {request.order_type.value}")
    _require_positive("client_id", request.client_id)
    _require_positive("good_til_block", good_til_block)
    return new(
        "neutronx.orderbook.v1.MsgPlaceShortTermOrder",
        creator=creator,
        good_til_block=good_til_block,
        **_order_fields(request),
    )


def cancel_short_term_order_msg(
    creator: str,
    client_id: int,
    pair: str,
    good_til_block: int,
    subaccount_id: int = 0,
) -> Any:
    _require_positive("client_id", client_id)
    _require_positive("good_til_block", good_til_block)
    return new(
        "neutronx.orderbook.v1.MsgCancelShortTermOrder",
        creator=creator,
        client_id=client_id,
        pair=pair,
        good_til_block=good_til_block,
        subaccount_id=subaccount_id,
    )


def close_position_msg(creator: str, position_id: int) -> Any:
    return new("neutronx.perps.v1.MsgClosePosition", creator=creator, position_id=position_id)


def deposit_to_subaccount_msg(owner: str, amount: int, subaccount_id: int = 0) -> Any:
    _require_positive("amount", amount)
    return new(
        "neutronx.perps.v1.MsgDepositToSubaccount",
        owner=owner,
        subaccount_id=subaccount_id,
        amount=str(amount),
    )


def withdraw_from_subaccount_msg(owner: str, amount: int, subaccount_id: int = 0) -> Any:
    _require_positive("amount", amount)
    return new(
        "neutronx.perps.v1.MsgWithdrawFromSubaccount",
        owner=owner,
        subaccount_id=subaccount_id,
        amount=str(amount),
    )


def good_til_block(current_height: int, window: int = SHORT_TERM_MAX_TTL_BLOCKS) -> int:
    _require_positive("current_height", current_height)
    _require_positive("window", window)
    return current_height + min(window, SHORT_TERM_MAX_TTL_BLOCKS)


def snap_to_tick(price: Decimal, side: Side, tick: Decimal | None) -> Decimal:
    if not tick or tick <= 0 or price <= 0:
        return price
    rounding = ROUND_FLOOR if side is Side.BUY else ROUND_CEILING
    snapped = (price / tick).to_integral_value(rounding=rounding) * tick
    if snapped == price or snapped <= 0:
        return price
    return snapped


def _require_positive(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
