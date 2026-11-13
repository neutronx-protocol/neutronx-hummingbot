from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

SHORT_TERM_DEFAULT_GAS_LIMIT = 1_000_000
SHORT_TERM_MAX_GAS_LIMIT = 10_000_000
PREFILL_GAS_BASE = 60_000
PREFILL_GAS_PER_ORDER = 90_000
PREFILL_GAS_PER_CANCEL = 40_000
PREFILL_GAS_SPOT_ORDER_EXTRA = 30_000
PREFILL_GAS_SPOT_CANCEL_EXTRA = 15_000
SPOT_MARKET_PREFIX = "SPOT:"
GAS_SAMPLE_WINDOW = 50
GAS_HEADROOM_NUMERATOR = 9
GAS_HEADROOM_DENOMINATOR = 10


class MsgKind(str, Enum):
    PLACE = "place"
    CANCEL = "cancel"


_FLOOR_PER_MSG = {
    MsgKind.PLACE: PREFILL_GAS_PER_ORDER,
    MsgKind.CANCEL: PREFILL_GAS_PER_CANCEL,
}

_SINGLE_ORDERS = frozenset(
    {
        "neutronx.orderbook.v1.MsgPlaceOrder",
        "neutronx.orderbook.v1.MsgPlaceShortTermOrder",
    }
)
_REPLACE = "neutronx.orderbook.v1.MsgReplaceOrder"
_BATCH_PLACE = "neutronx.orderbook.v1.MsgBatchPlaceOrders"
_CANCEL_BY_ID = "neutronx.orderbook.v1.MsgCancelOrder"
_CANCEL_SHORT_TERM = "neutronx.orderbook.v1.MsgCancelShortTermOrder"
_BATCH_CANCEL = "neutronx.orderbook.v1.MsgBatchCancelOrders"


@dataclass(frozen=True)
class PrefillCounts:
    orders: int = 0
    cancels: int = 0
    spot_orders: int = 0
    spot_cancels: int = 0


def is_spot_market(pair: str) -> bool:
    return pair.startswith(SPOT_MARKET_PREFIX)


def prefill_counts(msgs: Sequence[Any]) -> PrefillCounts:
    placed: list[str] = []
    cancelled: list[bool] = []
    for msg in msgs:
        name = msg.DESCRIPTOR.full_name
        if name in _SINGLE_ORDERS:
            placed.append(msg.pair)
        elif name == _REPLACE:
            placed.append(msg.pair)
            cancelled.append(is_spot_market(msg.pair))
        elif name == _BATCH_PLACE:
            placed.extend(order.pair for order in msg.orders)
        elif name == _CANCEL_BY_ID:
            cancelled.append(True)
        elif name == _CANCEL_SHORT_TERM:
            cancelled.append(is_spot_market(msg.pair))
        elif name == _BATCH_CANCEL:
            cancelled.extend(True for _ in msg.order_ids)
    return PrefillCounts(
        orders=len(placed),
        cancels=len(cancelled),
        spot_orders=sum(1 for pair in placed if is_spot_market(pair)),
        spot_cancels=sum(cancelled),
    )


def prefill_gas_floor(counts: PrefillCounts) -> int:
    if min(counts.orders, counts.cancels, counts.spot_orders, counts.spot_cancels) < 0:
        raise ValueError("message counts must not be negative")
    return (
        PREFILL_GAS_BASE
        + counts.orders * PREFILL_GAS_PER_ORDER
        + counts.cancels * PREFILL_GAS_PER_CANCEL
        + counts.spot_orders * PREFILL_GAS_SPOT_ORDER_EXTRA
        + counts.spot_cancels * PREFILL_GAS_SPOT_CANCEL_EXTRA
    )


def tx_prefill_gas_floor(msgs: Sequence[Any]) -> int:
    counts = prefill_counts(msgs)
    return prefill_gas_floor(counts) if counts.orders else 0


def short_term_gas_floor(places: int, cancels: int) -> int:
    return prefill_gas_floor(PrefillCounts(orders=places, cancels=cancels))


def orders_within_prefill_ceiling(gas_ceiling: int, msgs: Sequence[Any] = ()) -> int:
    room = gas_ceiling - prefill_gas_floor(prefill_counts(msgs))
    return max(0, room // PREFILL_GAS_PER_ORDER)


def msgs_within_floor(gas_limit: int, kind: MsgKind) -> int:
    return max(1, (gas_limit - PREFILL_GAS_BASE) // _FLOOR_PER_MSG[kind])


class ShortTermGasEstimator:
    def __init__(self, window: int = GAS_SAMPLE_WINDOW) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        self._samples: dict[MsgKind, deque[int]] = {kind: deque(maxlen=window) for kind in MsgKind}

    def per_msg(self, kind: MsgKind) -> int:
        samples = self._samples[kind]
        return max(samples) if samples else 0

    def capacity(self, kind: MsgKind, gas_limit: int) -> int:
        within_floor = msgs_within_floor(gas_limit, kind)
        per_msg = self.per_msg(kind)
        if not per_msg:
            return within_floor
        packed = gas_limit * GAS_HEADROOM_NUMERATOR // GAS_HEADROOM_DENOMINATOR // per_msg
        return max(1, min(within_floor, packed))

    def observe(self, kind: MsgKind, msgs: int, gas_used: int) -> None:
        if msgs > 0 and gas_used > 0:
            self._samples[kind].append(-(-gas_used // msgs))

    def observe_out_of_gas(self, kind: MsgKind, msgs: int, gas_limit: int) -> None:
        if msgs > 0 and gas_limit > 0:
            self._samples[kind].append(gas_limit // msgs + 1)
