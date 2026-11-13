from __future__ import annotations

import binascii
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from google.protobuf.message import DecodeError

from neutronx_sdk.legacy_dec import from_legacy_dec
from neutronx_sdk.proto import parse

_PLACE_ORDER_RESPONSE = "neutronx.orderbook.v1.MsgPlaceOrderResponse"
_BATCH_PLACE_RESPONSE = "neutronx.orderbook.v1.MsgBatchPlaceOrdersResponse"
_SHORT_TERM_PLACE_RESPONSE = "neutronx.orderbook.v1.MsgPlaceShortTermOrderResponse"
_BATCH_CANCEL_RESPONSE = "neutronx.orderbook.v1.MsgBatchCancelOrdersResponse"


@dataclass(frozen=True)
class PlaceOrderOutcome:
    order_id: int = 0
    status: str = ""
    trades_count: int = 0
    filled: Decimal = Decimal(0)
    placement_result: str = ""


@dataclass(frozen=True)
class ShortTermPlaceOutcome:
    order_id: int = 0
    status: str = ""
    trades_count: int = 0
    replaced_order_id: int = 0


@dataclass(frozen=True)
class BatchCancelOutcome:
    cancelled_ids: tuple[int, ...]
    gone_ids: tuple[int, ...]
    rejected_ids: tuple[int, ...]

    @property
    def settled_ids(self) -> tuple[int, ...]:
        return self.cancelled_ids + self.gone_ids


def decode_tx_msg_data(data: bytes | str) -> list[bytes]:
    if not data:
        return []
    try:
        blob = binascii.unhexlify(data) if isinstance(data, str) else bytes(data)
        parsed = parse("cosmos.base.abci.v1beta1.TxMsgData", blob)
    except (binascii.Error, ValueError, DecodeError):
        return []
    if parsed.msg_responses:
        return [bytes(response.value) for response in parsed.msg_responses]
    return [bytes(item.data) for item in parsed.data if item.data]


def parse_place_order_outcomes(msg_responses: Sequence[bytes]) -> list[PlaceOrderOutcome]:
    outcomes: list[PlaceOrderOutcome] = []
    for raw in msg_responses:
        parsed = _decode(_PLACE_ORDER_RESPONSE, raw)
        outcomes.append(PlaceOrderOutcome() if parsed is None else _place_order_outcome(parsed))
    return outcomes


def parse_batch_place_outcomes(msg_responses: Sequence[bytes]) -> list[PlaceOrderOutcome]:
    outcomes: list[PlaceOrderOutcome] = []
    for raw in msg_responses:
        parsed = _decode(_BATCH_PLACE_RESPONSE, raw)
        if parsed is not None:
            outcomes.extend(_place_order_outcome(result) for result in parsed.results)
    return outcomes


def parse_short_term_place_outcomes(msg_responses: Sequence[bytes]) -> list[ShortTermPlaceOutcome]:
    outcomes: list[ShortTermPlaceOutcome] = []
    for raw in msg_responses:
        parsed = _decode(_SHORT_TERM_PLACE_RESPONSE, raw)
        if parsed is None:
            outcomes.append(ShortTermPlaceOutcome())
            continue
        outcomes.append(
            ShortTermPlaceOutcome(
                order_id=int(parsed.order_id),
                status=str(parsed.status).upper(),
                trades_count=int(parsed.trades_count),
                replaced_order_id=int(parsed.replaced_order_id),
            )
        )
    return outcomes


def parse_batch_cancel_outcome(msg_responses: Sequence[bytes]) -> BatchCancelOutcome | None:
    for raw in msg_responses:
        parsed = _decode(_BATCH_CANCEL_RESPONSE, raw)
        if parsed is not None and (parsed.cancelled_ids or parsed.gone_ids or parsed.rejected_ids):
            return BatchCancelOutcome(
                cancelled_ids=tuple(int(i) for i in parsed.cancelled_ids),
                gone_ids=tuple(int(i) for i in parsed.gone_ids),
                rejected_ids=tuple(int(i) for i in parsed.rejected_ids),
            )
    return None


def _decode(full_name: str, raw: bytes) -> Any | None:
    try:
        return parse(full_name, raw)
    except DecodeError:
        return None


def _place_order_outcome(parsed: Any) -> PlaceOrderOutcome:
    return PlaceOrderOutcome(
        order_id=int(parsed.order_id),
        status=str(parsed.status).upper(),
        trades_count=int(parsed.trades_count),
        filled=from_legacy_dec(str(parsed.filled)),
        placement_result=str(parsed.placement_result),
    )
