from __future__ import annotations

from dataclasses import dataclass

import grpc

from neutronx_sdk.exceptions import NeutronXError
from neutronx_sdk.models import (
    Account,
    AgentKey,
    ChainStatus,
    Coin,
    FeeTier,
    Market,
    OraclePrice,
    Order,
    OrderBook,
    OrderbookParams,
    PerpsParams,
    Position,
    SubaccountBalance,
    SubaccountEquity,
)
from neutronx_sdk.node.rpc import RpcClient
from neutronx_sdk.proto import unpack_any

AUTH = "cosmos.auth.v1beta1.Query"
BANK = "cosmos.bank.v1beta1.Query"
NODE = "cosmos.base.node.v1beta1.Service"
ORDERBOOK = "neutronx.orderbook.v1.Query"
PERPS = "neutronx.perps.v1.Query"
ORACLE = "neutronx.oracle.v1.Query"
AGENTKEYS = "neutronx.agentkeys.v1.Query"
BASE_ACCOUNT = "cosmos.auth.v1beta1.BaseAccount"
DEFAULT_PAGE_SIZE = 100
MAX_PAGES = 200


@dataclass(frozen=True)
class OrdersPage:
    orders: tuple[Order, ...]
    has_next: bool


@dataclass(frozen=True)
class PositionsPage:
    positions: tuple[Position, ...]
    has_next: bool


class _Queries:
    __slots__ = ("_rpc",)

    def __init__(self, rpc: RpcClient) -> None:
        self._rpc = rpc


class AuthQueries(_Queries):
    __slots__ = ()

    async def account(self, address: str) -> Account:
        response = await self._rpc.call(AUTH, "Account", address=address)
        account = unpack_any(response.account, BASE_ACCOUNT)
        return Account(
            address=str(account.address),
            account_number=int(account.account_number),
            sequence=int(account.sequence),
        )


class BankQueries(_Queries):
    __slots__ = ()

    async def balances(self, address: str) -> tuple[Coin, ...]:
        coins: list[Coin] = []
        next_key = b""
        for _ in range(MAX_PAGES):
            response = await self._rpc.call(
                BANK,
                "AllBalances",
                address=address,
                pagination={"key": next_key, "limit": DEFAULT_PAGE_SIZE},
            )
            coins.extend(Coin(denom=str(c.denom), amount=int(c.amount)) for c in response.balances)
            next_key = bytes(response.pagination.next_key)
            if not next_key:
                return tuple(coins)
        raise NeutronXError(f"balances of {address} span more than {MAX_PAGES} pages")


class NodeQueries(_Queries):
    __slots__ = ()

    async def status(self) -> ChainStatus:
        return ChainStatus.from_proto(await self._rpc.call(NODE, "Status"))


class OrderbookQueries(_Queries):
    __slots__ = ()

    async def params(self) -> OrderbookParams:
        response = await self._rpc.call(ORDERBOOK, "Params")
        return OrderbookParams.from_proto(response.params)

    async def order_book(self, pair: str, depth: int = 20) -> OrderBook:
        response = await self._rpc.call(ORDERBOOK, "OrderBook", pair=pair, depth=max(1, depth))
        return OrderBook.from_proto(response)

    async def order(self, order_id: int) -> Order | None:
        try:
            response = await self._rpc.call(ORDERBOOK, "Order", order_id=order_id)
        except grpc.aio.AioRpcError as err:
            if err.code() == grpc.StatusCode.NOT_FOUND:
                return None
            raise
        return Order.from_order(response)

    async def user_orders(
        self,
        owner: str,
        *,
        pair: str = "",
        status_filter: str = "",
        include: str = "",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> OrdersPage:
        response = await self._rpc.call(
            ORDERBOOK,
            "UserOrders",
            owner=owner,
            pair=pair,
            status_filter=status_filter,
            include=include,
            page=page,
            page_size=page_size,
        )
        return OrdersPage(
            orders=tuple(Order.from_user_order(o) for o in response.orders),
            has_next=bool(response.pagination.has_next),
        )

    async def all_user_orders(
        self,
        owner: str,
        *,
        pair: str = "",
        status_filter: str = "",
        include: str = "",
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = MAX_PAGES,
    ) -> tuple[Order, ...]:
        orders: list[Order] = []
        for page in range(1, max_pages + 1):
            result = await self.user_orders(
                owner,
                pair=pair,
                status_filter=status_filter,
                include=include,
                page=page,
                page_size=page_size,
            )
            if page > 1 and not result.orders and result.has_next:
                raise NeutronXError(f"inconsistent pagination of user orders at page {page}")
            orders.extend(result.orders)
            if not result.has_next:
                return tuple(orders)
        raise NeutronXError(f"user orders of {owner} span more than {max_pages} pages")

    async def fee_tier(self, owner: str) -> FeeTier:
        return FeeTier.from_proto(await self._rpc.call(ORDERBOOK, "FeeTier", owner=owner))


class PerpsQueries(_Queries):
    __slots__ = ()

    async def params(self) -> PerpsParams:
        response = await self._rpc.call(PERPS, "Params")
        return PerpsParams.from_proto(response.params)

    async def markets(self) -> tuple[Market, ...]:
        response = await self._rpc.call(PERPS, "Markets")
        return tuple(Market.from_proto(m) for m in response.markets if m.pair)

    async def market(self, pair: str) -> Market:
        return Market.from_proto(await self._rpc.call(PERPS, "Market", pair=pair))

    async def positions(
        self,
        owner: str,
        *,
        pair: str = "",
        status_filter: str = "",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PositionsPage:
        response = await self._rpc.call(
            PERPS,
            "Positions",
            owner=owner,
            pair=pair,
            status_filter=status_filter,
            page=page,
            page_size=page_size,
        )
        return PositionsPage(
            positions=tuple(Position.from_proto(p) for p in response.positions),
            has_next=bool(response.pagination.has_next),
        )

    async def subaccount_equity(self, owner: str, subaccount_id: int = 0) -> SubaccountEquity:
        response = await self._rpc.call(
            PERPS, "SubaccountEquity", owner=owner, subaccount_id=subaccount_id
        )
        return SubaccountEquity.from_proto(response)

    async def subaccount_balance(self, owner: str, subaccount_id: int = 0) -> SubaccountBalance:
        response = await self._rpc.call(
            PERPS, "SubaccountBalance", owner=owner, subaccount_id=subaccount_id
        )
        return SubaccountBalance.from_proto(response, subaccount_id)


class OracleQueries(_Queries):
    __slots__ = ()

    async def price(self, pair: str) -> OraclePrice:
        return OraclePrice.from_proto(await self._rpc.call(ORACLE, "Price", pair=pair))

    async def prices(self) -> tuple[OraclePrice, ...]:
        response = await self._rpc.call(ORACLE, "AllPrices")
        return tuple(OraclePrice.from_proto(p) for p in response.prices)


class AgentKeysQueries(_Queries):
    __slots__ = ()

    async def enabled(self) -> bool:
        response = await self._rpc.call(AGENTKEYS, "Params")
        return bool(response.params.enabled)

    async def agent_key(self, account: str, key_id: int) -> AgentKey | None:
        try:
            response = await self._rpc.call(AGENTKEYS, "AgentKey", account=account, id=key_id)
        except grpc.aio.AioRpcError as err:
            if err.code() == grpc.StatusCode.NOT_FOUND:
                return None
            raise
        return AgentKey.from_proto(response.key)
