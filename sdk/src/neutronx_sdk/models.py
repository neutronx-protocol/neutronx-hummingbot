from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from neutronx_sdk.legacy_dec import from_legacy_dec, optional_legacy_dec, positive_legacy_dec
from neutronx_sdk.orders import (
    AGENT_KEY_MSG_TYPE_URLS,
    ORDER_FLAG_SHORT_TERM,
    RESTING_ORDER_STATUSES,
)

MARKET_STATUS_ACTIVE = "ACTIVE"
PPM = 1_000_000
POSITION_SIDE_LONG = "LONG"
POSITION_SIDE_SHORT = "SHORT"
POSITION_STATUS_OPEN = "OPEN"
MARGIN_TYPE_ISOLATED = "ISOLATED"
_PARKED_MARKER = "parked"


@dataclass(frozen=True)
class Coin:
    denom: str
    amount: int


@dataclass(frozen=True)
class Account:
    address: str
    account_number: int
    sequence: int


@dataclass(frozen=True)
class ChainStatus:
    height: int
    block_time: datetime

    @classmethod
    def from_proto(cls, message: Any) -> ChainStatus:
        seconds = int(message.timestamp.seconds)
        nanos = int(message.timestamp.nanos)
        block_time = datetime.fromtimestamp(seconds, tz=timezone.utc).replace(
            microsecond=nanos // 1000
        )
        return cls(height=int(message.height), block_time=block_time)


@dataclass(frozen=True)
class Market:
    pair: str
    status: str
    tick_size: Decimal
    min_quantity: Decimal
    max_leverage: Decimal
    maker_fee_rate: Decimal
    taker_fee_rate: Decimal
    maintenance_margin: Decimal
    price_band_percent: Decimal
    effective_max_leverage: Decimal
    max_slippage: Decimal

    @property
    def is_active(self) -> bool:
        return self.status == MARKET_STATUS_ACTIVE

    @classmethod
    def from_proto(cls, message: Any) -> Market:
        max_leverage = from_legacy_dec(str(message.max_leverage))
        effective = positive_legacy_dec(str(message.effective_max_leverage))
        return cls(
            pair=str(message.pair),
            status=str(message.status).strip().upper(),
            tick_size=from_legacy_dec(str(message.tick_size)).normalize(),
            min_quantity=from_legacy_dec(str(message.min_quantity)),
            max_leverage=max_leverage,
            maker_fee_rate=from_legacy_dec(str(message.maker_fee_rate)),
            taker_fee_rate=from_legacy_dec(str(message.taker_fee_rate)),
            maintenance_margin=from_legacy_dec(str(message.maintenance_margin)),
            price_band_percent=from_legacy_dec(str(message.price_band_percent)),
            effective_max_leverage=min(effective or max_leverage, max_leverage),
            max_slippage=Decimal(int(message.max_slippage_ppm)) / PPM,
        )


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    quantity: Decimal
    order_count: int
    parked: bool

    @classmethod
    def from_proto(cls, message: Any) -> BookLevel:
        return cls(
            price=from_legacy_dec(str(message.price)),
            quantity=from_legacy_dec(str(message.quantity)),
            order_count=int(message.order_count),
            parked=is_parked(str(message.band_state)),
        )


@dataclass(frozen=True)
class OrderBook:
    pair: str
    height: int
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    best_bid: Decimal | None
    best_ask: Decimal | None
    settleable_best_bid: Decimal | None
    settleable_best_ask: Decimal | None

    @classmethod
    def from_proto(cls, message: Any) -> OrderBook:
        return cls(
            pair=str(message.pair),
            height=int(message.height),
            bids=tuple(BookLevel.from_proto(level) for level in message.bids),
            asks=tuple(BookLevel.from_proto(level) for level in message.asks),
            best_bid=positive_legacy_dec(str(message.best_bid)),
            best_ask=positive_legacy_dec(str(message.best_ask)),
            settleable_best_bid=positive_legacy_dec(str(message.settleable_best_bid)),
            settleable_best_ask=positive_legacy_dec(str(message.settleable_best_ask)),
        )


@dataclass(frozen=True)
class Order:
    order_id: int
    pair: str
    side: str
    order_type: str
    status: str
    price: Decimal | None
    quantity: Decimal
    filled_quantity: Decimal
    leverage: Decimal | None
    time_in_force: str
    reduce_only: bool
    post_only: bool
    client_id: int
    flags: int
    good_til_block: int
    subaccount_id: int
    band_state: str
    agent_key_id: int
    block_height: int

    @property
    def is_short_term(self) -> bool:
        return self.flags == ORDER_FLAG_SHORT_TERM

    @property
    def is_resting(self) -> bool:
        return self.status in RESTING_ORDER_STATUSES

    @property
    def is_parked(self) -> bool:
        return is_parked(self.band_state)

    @property
    def remaining_quantity(self) -> Decimal:
        return max(self.quantity - self.filled_quantity, Decimal(0))

    @classmethod
    def from_user_order(cls, message: Any) -> Order:
        return cls(
            order_id=int(message.order_id),
            pair=str(message.pair),
            side=str(message.side),
            order_type=str(message.order_type),
            status=str(message.status).upper(),
            price=positive_legacy_dec(str(message.price)),
            quantity=from_legacy_dec(str(message.quantity)),
            filled_quantity=from_legacy_dec(str(message.filled_quantity)),
            leverage=optional_legacy_dec(str(message.leverage)),
            time_in_force=str(message.time_in_force),
            reduce_only=bool(message.reduce_only),
            post_only=bool(message.post_only),
            client_id=int(message.client_id),
            flags=int(message.flags),
            good_til_block=int(message.good_til_block),
            subaccount_id=int(message.subaccount_id),
            band_state=str(message.band_state),
            agent_key_id=int(message.agent_key_id),
            block_height=int(message.block_height),
        )

    @classmethod
    def from_order(cls, message: Any) -> Order:
        return cls(
            order_id=int(message.id),
            pair=str(message.pair),
            side=str(message.side),
            order_type=str(message.order_type),
            status=str(message.status).upper(),
            price=positive_legacy_dec(str(message.price)),
            quantity=from_legacy_dec(str(message.quantity)),
            filled_quantity=from_legacy_dec(str(message.filled)),
            leverage=optional_legacy_dec(str(message.leverage)),
            time_in_force=str(message.time_in_force),
            reduce_only=bool(message.reduce_only),
            post_only=bool(message.post_only),
            client_id=int(message.client_id),
            flags=int(message.flags),
            good_til_block=int(message.good_til_block),
            subaccount_id=int(message.subaccount_id),
            band_state="",
            agent_key_id=int(message.agent_key_id),
            block_height=0,
        )


@dataclass(frozen=True)
class Position:
    position_id: int
    pair: str
    side: str
    status: str
    quantity: Decimal
    entry_price: Decimal
    leverage: Decimal
    initial_margin: Decimal
    margin_type: str
    subaccount_id: int
    unrealized_pnl: Decimal | None
    maintenance_margin: Decimal | None
    mark_price: Decimal | None
    liquidation_price: Decimal | None
    liquidation_reachable: bool | None

    @classmethod
    def from_proto(cls, message: Any) -> Position:
        margin_type = str(message.margin_type).strip().upper()
        raw_liquidation = (
            message.liquidation_price
            if margin_type == MARGIN_TYPE_ISOLATED
            else message.cross_liquidation_price
        )
        liquidation_price, reachable = _liquidation(str(raw_liquidation))
        leverage = optional_legacy_dec(str(message.leverage))
        return cls(
            position_id=int(message.id),
            pair=str(message.pair),
            side=position_side(str(message.side)),
            status=str(message.status).strip().upper() or POSITION_STATUS_OPEN,
            quantity=from_legacy_dec(str(message.quantity)),
            entry_price=from_legacy_dec(str(message.entry_price)),
            leverage=leverage if leverage is not None else Decimal(1),
            initial_margin=from_legacy_dec(str(message.initial_margin)),
            margin_type=margin_type,
            subaccount_id=int(message.subaccount_id),
            unrealized_pnl=optional_legacy_dec(str(message.unrealized_pnl)),
            maintenance_margin=optional_legacy_dec(str(message.maintenance_margin)),
            mark_price=positive_legacy_dec(str(message.mark_price)),
            liquidation_price=liquidation_price,
            liquidation_reachable=reachable,
        )


@dataclass(frozen=True)
class FeeTier:
    tier_index: int
    maker_fee_rate: Decimal
    taker_fee_rate: Decimal
    trailing_volume: int
    pending_volume: int
    has_next_tier: bool
    next_threshold: int
    volume_to_next: int

    @classmethod
    def from_proto(cls, message: Any) -> FeeTier:
        return cls(
            tier_index=int(message.tier_index),
            maker_fee_rate=from_legacy_dec(str(message.maker_fee_rate)),
            taker_fee_rate=from_legacy_dec(str(message.taker_fee_rate)),
            trailing_volume=_int(str(message.trailing_volume)),
            pending_volume=_int(str(message.pending_volume)),
            has_next_tier=bool(message.has_next_tier),
            next_threshold=_int(str(message.next_threshold)),
            volume_to_next=_int(str(message.volume_to_next)),
        )


@dataclass(frozen=True)
class OraclePrice:
    pair: str
    price: Decimal
    block_height: int

    @classmethod
    def from_proto(cls, message: Any) -> OraclePrice:
        return cls(
            pair=str(message.pair),
            price=from_legacy_dec(str(message.price)),
            block_height=int(message.block_height),
        )


@dataclass(frozen=True)
class OrderbookParams:
    maker_fee_rate: Decimal
    taker_fee_rate: Decimal
    min_order_notional: int
    max_open_orders_per_user: int
    rate_limit_per_block: int
    short_term_enabled: bool
    short_term_order_ttl_blocks: int
    short_term_per_block_limit: int
    short_term_max_gas_wanted: int
    trading_halted: bool
    min_gas_price: Decimal
    max_gas_wanted: int

    @classmethod
    def from_proto(cls, message: Any) -> OrderbookParams:
        return cls(
            min_gas_price=from_legacy_dec(str(message.min_gas_price)),
            max_gas_wanted=int(message.max_gas_wanted),
            maker_fee_rate=from_legacy_dec(str(message.maker_fee_rate)),
            taker_fee_rate=from_legacy_dec(str(message.taker_fee_rate)),
            min_order_notional=int(message.min_order_notional),
            max_open_orders_per_user=int(message.max_open_orders_per_user),
            rate_limit_per_block=int(message.rate_limit_per_block),
            short_term_enabled=bool(message.short_term_enabled),
            short_term_order_ttl_blocks=int(message.short_term_order_ttl_blocks),
            short_term_per_block_limit=int(message.short_term_per_block_limit),
            short_term_max_gas_wanted=int(message.short_term_max_gas_wanted),
            trading_halted=bool(message.trading_halted),
        )


@dataclass(frozen=True)
class PerpsParams:
    margin_denom: str
    trading_halted: bool

    @classmethod
    def from_proto(cls, message: Any) -> PerpsParams:
        return cls(
            margin_denom=str(message.margin_denom).strip(),
            trading_halted=bool(message.trading_halted),
        )


@dataclass(frozen=True)
class SubaccountEquity:
    collateral: int
    equity: Decimal
    maintenance_required: Decimal
    liquidatable: bool
    marks_fresh: bool

    @classmethod
    def from_proto(cls, message: Any) -> SubaccountEquity:
        return cls(
            collateral=_int(str(message.collateral)),
            equity=from_legacy_dec(str(message.equity)),
            maintenance_required=from_legacy_dec(str(message.maintenance_required)),
            liquidatable=bool(message.liquidatable),
            marks_fresh=bool(message.marks_fresh),
        )


@dataclass(frozen=True)
class SubaccountBalance:
    subaccount_id: int
    denom: str
    total: Decimal
    locked: Decimal
    available: Decimal
    withdrawable: Decimal
    margin_in_positions: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    maintenance_required: Decimal
    open_positions_count: int
    locked_orders_count: int

    @classmethod
    def from_proto(cls, message: Any, subaccount_id: int) -> SubaccountBalance:
        return cls(
            subaccount_id=subaccount_id,
            denom=str(message.denom),
            total=from_legacy_dec(str(message.total)),
            locked=from_legacy_dec(str(message.locked)),
            available=from_legacy_dec(str(message.available)),
            withdrawable=from_legacy_dec(str(message.withdrawable)),
            margin_in_positions=from_legacy_dec(str(message.margin_in_positions)),
            unrealized_pnl=from_legacy_dec(str(message.unrealized_pnl)),
            equity=from_legacy_dec(str(message.equity)),
            maintenance_required=from_legacy_dec(str(message.maintenance_required)),
            open_positions_count=int(message.open_positions_count),
            locked_orders_count=int(message.locked_orders_count),
        )


class AgentKeyProblem(str, Enum):
    MODULE_DISABLED = "module_disabled"
    NOT_FOUND = "not_found"
    PUBKEY_MISMATCH = "pubkey_mismatch"
    EXPIRED = "expired"
    MISSING_MSG_TYPES = "missing_msg_types"
    SCOPE_RESTRICTED = "scope_restricted"


@dataclass(frozen=True)
class AgentKey:
    account: str
    key_id: int
    name: str
    pubkey: bytes
    expires_at: int
    created_block: int
    msg_type_urls: tuple[str, ...]
    pairs: tuple[str, ...]
    subaccount_ids: tuple[int, ...]

    @classmethod
    def from_proto(cls, message: Any) -> AgentKey:
        permissions = message.permissions
        return cls(
            account=str(message.account),
            key_id=int(message.id),
            name=str(message.name),
            pubkey=bytes(message.pubkey),
            expires_at=int(message.expires_at),
            created_block=int(message.created_block),
            msg_type_urls=tuple(str(url) for url in permissions.msg_type_urls),
            pairs=tuple(str(pair) for pair in permissions.pairs),
            subaccount_ids=tuple(int(i) for i in permissions.subaccount_ids),
        )


def agent_key_problem(
    enabled: bool,
    key: AgentKey | None,
    public_key: bytes,
    now: float,
    required_msg_type_urls: tuple[str, ...] = AGENT_KEY_MSG_TYPE_URLS,
) -> AgentKeyProblem | None:
    if not enabled:
        return AgentKeyProblem.MODULE_DISABLED
    if key is None:
        return AgentKeyProblem.NOT_FOUND
    if key.pubkey != public_key:
        return AgentKeyProblem.PUBKEY_MISMATCH
    if key.expires_at <= now:
        return AgentKeyProblem.EXPIRED
    if key.msg_type_urls and not set(required_msg_type_urls) <= set(key.msg_type_urls):
        return AgentKeyProblem.MISSING_MSG_TYPES
    if key.pairs or key.subaccount_ids:
        return AgentKeyProblem.SCOPE_RESTRICTED
    return None


def position_side(side: str) -> str:
    normalized = side.strip().upper()
    if normalized in ("BUY", POSITION_SIDE_LONG):
        return POSITION_SIDE_LONG
    if normalized in ("SELL", POSITION_SIDE_SHORT):
        return POSITION_SIDE_SHORT
    return normalized


def is_parked(band_state: str) -> bool:
    return _PARKED_MARKER in band_state.lower()


def _liquidation(raw: str) -> tuple[Decimal | None, bool | None]:
    price = optional_legacy_dec(raw)
    if price is None:
        return None, None
    if price <= 0:
        return None, False
    return price, True


def _int(raw: str) -> int:
    text = raw.strip()
    return int(text) if text else 0
