from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast

from neutronx_sdk.indexer.api import FRAME_ERROR
from neutronx_sdk.models import POSITION_STATUS_OPEN
from neutronx_sdk.orders import ORDER_FLAG_SHORT_TERM, RESTING_ORDER_STATUSES

Json = Mapping[str, Any]

ROLE_TAKER = "taker"


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _optional_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    return _datetime(value)


def _items(value: Any) -> Sequence[Json]:
    return cast("list[Json]", value) if isinstance(value, list) else []


@dataclass(frozen=True)
class StatusV1:
    indexed_height: int | None
    chain_height: int | None
    lag_blocks: int | None
    indexed_age_seconds: float | None

    @classmethod
    def from_json(cls, data: Json) -> StatusV1:
        age = data.get("indexed_age_seconds")
        return cls(
            indexed_height=_optional_int(data.get("indexed_height")),
            chain_height=_optional_int(data.get("chain_height")),
            lag_blocks=_optional_int(data.get("lag_blocks")),
            indexed_age_seconds=None if age is None else float(age),
        )


@dataclass(frozen=True)
class TickerV1:
    pair: str
    last_price: Decimal | None
    mark_price: Decimal | None
    funding_rate: Decimal | None
    next_funding_at: datetime | None
    volume_24h: Decimal

    @classmethod
    def from_json(cls, data: Json) -> TickerV1:
        return cls(
            pair=str(data["pair"]),
            last_price=_optional_decimal(data.get("last_price")),
            mark_price=_optional_decimal(data.get("mark_price")),
            funding_rate=_optional_decimal(data.get("funding_rate")),
            next_funding_at=_optional_datetime(data.get("next_funding_at")),
            volume_24h=_decimal(data.get("volume_24h", "0")),
        )


@dataclass(frozen=True)
class OrderbookLevelV1:
    price: Decimal
    quantity: Decimal
    order_count: int
    settleable: bool | None

    @classmethod
    def from_json(cls, data: Json) -> OrderbookLevelV1:
        settleable = data.get("settleable")
        return cls(
            price=_decimal(data["price"]),
            quantity=_decimal(data["quantity"]),
            order_count=int(data.get("order_count", 0)),
            settleable=None if settleable is None else bool(settleable),
        )


@dataclass(frozen=True)
class OrderbookV1:
    pair: str
    bids: tuple[OrderbookLevelV1, ...]
    asks: tuple[OrderbookLevelV1, ...]
    best_bid: Decimal | None
    best_ask: Decimal | None
    block_height: int | None

    @classmethod
    def from_json(cls, data: Json) -> OrderbookV1:
        return cls(
            pair=str(data["pair"]),
            bids=tuple(OrderbookLevelV1.from_json(level) for level in _items(data.get("bids"))),
            asks=tuple(OrderbookLevelV1.from_json(level) for level in _items(data.get("asks"))),
            best_bid=_optional_decimal(data.get("best_bid")),
            best_ask=_optional_decimal(data.get("best_ask")),
            block_height=_optional_int(data.get("block_height")),
        )


@dataclass(frozen=True)
class TradeV1:
    trade_id: str
    pair: str
    price: Decimal
    quantity: Decimal
    buyer: str
    seller: str
    buyer_order_id: int
    seller_order_id: int
    block_height: int
    time: datetime
    taker_side: str | None

    @classmethod
    def from_json(cls, data: Json) -> TradeV1:
        taker_side = _optional_str(data.get("taker_side"))
        return cls(
            trade_id=str(data["id"]),
            pair=str(data["pair"]),
            price=_decimal(data["price"]),
            quantity=_decimal(data["quantity"]),
            buyer=str(data.get("buyer", "")),
            seller=str(data.get("seller", "")),
            buyer_order_id=int(data.get("buyer_order_id", 0)),
            seller_order_id=int(data.get("seller_order_id", 0)),
            block_height=int(data["block_height"]),
            time=_datetime(data["time"]),
            taker_side=None if taker_side is None else taker_side.upper(),
        )


@dataclass(frozen=True)
class OrderV1:
    order_id: int
    client_id: int | None
    subaccount_id: int
    pair: str
    side: str
    order_type: str
    status: str
    price: Decimal | None
    quantity: Decimal
    filled: Decimal
    average_fill_price: Decimal | None
    leverage: Decimal | None
    reduce_only: bool
    post_only: bool
    time_in_force: str
    good_til_block: int | None
    replaced_order_id: int | None
    block_height: int
    time: datetime
    updated_at: datetime
    flags: int
    cancel_reason: str | None

    @property
    def is_short_term(self) -> bool:
        return self.flags == ORDER_FLAG_SHORT_TERM

    @property
    def is_open(self) -> bool:
        return self.status in RESTING_ORDER_STATUSES

    @classmethod
    def from_json(cls, data: Json) -> OrderV1:
        return cls(
            order_id=int(data["id"]),
            client_id=_optional_int(data.get("client_id")),
            subaccount_id=int(data.get("subaccount_id", 0)),
            pair=str(data["pair"]),
            side=str(data["side"]).upper(),
            order_type=str(data.get("type", "LIMIT")).upper(),
            status=str(data["status"]).upper(),
            price=_optional_decimal(data.get("price")),
            quantity=_decimal(data["quantity"]),
            filled=_decimal(data.get("filled", "0")),
            average_fill_price=_optional_decimal(data.get("average_fill_price")),
            leverage=_optional_decimal(data.get("leverage")),
            reduce_only=bool(data.get("reduce_only", False)),
            post_only=bool(data.get("post_only", False)),
            time_in_force=str(data.get("time_in_force", "GTC")).upper(),
            good_til_block=_optional_int(data.get("good_til_block")),
            replaced_order_id=_optional_int(data.get("replaced_order_id")),
            block_height=int(data.get("block_height", 0)),
            time=_datetime(data["time"]),
            updated_at=_datetime(data.get("updated_at", data["time"])),
            flags=int(data.get("flags") or 0),
            cancel_reason=_optional_str(data.get("cancel_reason")),
        )


@dataclass(frozen=True)
class FillV1:
    fill_id: str
    pair: str
    side: str
    price: Decimal
    quantity: Decimal
    fee: Decimal
    order_id: int
    subaccount_id: int
    block_height: int
    time: datetime
    client_id: int | None
    role: str | None
    tx_hash: str | None

    @property
    def is_taker(self) -> bool | None:
        if self.role is None:
            return None
        return self.role == ROLE_TAKER

    @classmethod
    def from_json(cls, data: Json) -> FillV1:
        role = _optional_str(data.get("role"))
        return cls(
            fill_id=str(data["id"]),
            pair=str(data["pair"]),
            side=str(data["side"]).upper(),
            price=_decimal(data["price"]),
            quantity=_decimal(data["quantity"]),
            fee=_decimal(data.get("fee", "0")),
            order_id=int(data["order_id"]),
            subaccount_id=int(data.get("subaccount_id", 0)),
            block_height=int(data["block_height"]),
            time=_datetime(data["time"]),
            client_id=_optional_int(data.get("client_id")),
            role=None if role is None else role.lower(),
            tx_hash=_optional_str(data.get("tx_hash")),
        )


@dataclass(frozen=True)
class PositionV1:
    position_id: int
    subaccount_id: int
    pair: str
    side: str
    status: str
    quantity: Decimal
    entry_price: Decimal
    leverage: Decimal
    margin_type: str
    mark_price: Decimal | None
    unrealized_pnl: Decimal | None
    liquidation_price: Decimal | None
    funding_accrued: Decimal

    @classmethod
    def from_json(cls, data: Json) -> PositionV1:
        return cls(
            position_id=int(data["id"]),
            subaccount_id=int(data.get("subaccount_id", 0)),
            pair=str(data["pair"]),
            side=str(data["side"]).upper(),
            status=str(data.get("status", POSITION_STATUS_OPEN)).upper(),
            quantity=_decimal(data["quantity"]),
            entry_price=_decimal(data["entry_price"]),
            leverage=_decimal(data.get("leverage", "1")),
            margin_type=str(data.get("margin_type", "")).upper(),
            mark_price=_optional_decimal(data.get("mark_price")),
            unrealized_pnl=_optional_decimal(data.get("unrealized_pnl")),
            liquidation_price=_optional_decimal(data.get("liquidation_price")),
            funding_accrued=_decimal(data.get("funding_accrued", "0")),
        )


@dataclass(frozen=True)
class AccountFundingV1:
    position_id: int
    subaccount_id: int
    pair: str
    side: str
    quantity: Decimal
    amount: Decimal
    rate: Decimal | None
    mark_price: Decimal
    block_height: int
    time: datetime

    @classmethod
    def from_json(cls, data: Json) -> AccountFundingV1:
        return cls(
            position_id=int(data["position_id"]),
            subaccount_id=int(data.get("subaccount_id", 0)),
            pair=str(data["pair"]),
            side=str(data.get("side", "")).upper(),
            quantity=_decimal(data.get("quantity", "0")),
            amount=_decimal(data["amount"]),
            rate=_optional_decimal(data.get("rate")),
            mark_price=_decimal(data.get("mark_price", "0")),
            block_height=int(data["block_height"]),
            time=_datetime(data["time"]),
        )


@dataclass(frozen=True)
class PageV1:
    items: tuple[Json, ...]
    next_cursor: str | None

    @classmethod
    def from_json(cls, data: Json) -> PageV1:
        return cls(
            items=tuple(_items(data.get("items"))),
            next_cursor=_optional_str(data.get("next_cursor")),
        )


@dataclass(frozen=True)
class StreamFrame:
    frame_type: str
    channel: str | None
    stream_id: str | None
    seq: int | None
    data: Any
    code: str | None = None
    message: str | None = None

    @property
    def is_error(self) -> bool:
        return self.frame_type == FRAME_ERROR

    @property
    def is_data(self) -> bool:
        return self.frame_type in ("snapshot", "update")

    @property
    def is_snapshot(self) -> bool:
        return self.frame_type == "snapshot"

    @classmethod
    def from_json(cls, data: Json) -> StreamFrame:
        return cls(
            frame_type=str(data.get("type", "")),
            channel=_optional_str(data.get("channel")),
            stream_id=_optional_str(data.get("id")),
            seq=_optional_int(data.get("seq")),
            data=data.get("data"),
            code=_optional_str(data.get("code")),
            message=_optional_str(data.get("message")),
        )

    def rows(self) -> Sequence[Json]:
        payload: Any = self.data
        if isinstance(payload, dict):
            return [cast(Json, payload)]
        return _items(payload)
