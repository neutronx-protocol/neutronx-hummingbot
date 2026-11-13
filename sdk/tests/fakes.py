from __future__ import annotations

from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import grpc

from neutronx_sdk import TESTNET, NodeClient
from neutronx_sdk.proto import method, new, pack_any

Handler = Callable[[Any, grpc.aio.ServicerContext[Any, Any]], Awaitable[Any]]
Context = grpc.aio.ServicerContext[Any, Any]

BUDGET_LOG = "queued for height 900: per-block rate limit exceeded"
MISMATCH_LOG = "account sequence mismatch, expected 8, got 7: incorrect account sequence"


class FakeChain:
    def __init__(self) -> None:
        self.handlers: dict[tuple[str, str], Handler] = {}
        self.requests: list[tuple[str, Any]] = []
        self.sequence = 7
        self.pending_polls = 1
        self.check_tx_results: deque[tuple[int, str]] = deque()
        self.deliver_code = 0
        self.height = 1000
        self.block_seconds = 1_762_000_000
        self.simulate_gas = 100_000
        self._install_defaults()

    def on(self, service: str, name: str, handler: Handler) -> None:
        self.handlers[(service, name)] = handler

    def calls(self, name: str) -> list[Any]:
        return [request for called, request in self.requests if called == name]

    def generic_handlers(self) -> list[grpc.GenericRpcHandler]:
        by_service: dict[str, dict[str, grpc.RpcMethodHandler[Any, Any]]] = {}
        for (service, name), handler in self.handlers.items():
            rpc = method(service, name)
            by_service.setdefault(service, {})[name] = grpc.unary_unary_rpc_method_handler(
                self._recorded(name, handler),
                request_deserializer=rpc.request_type.FromString,
                response_serializer=lambda message: message.SerializeToString(),
            )
        return [grpc.method_handlers_generic_handler(s, h) for s, h in by_service.items()]

    def _recorded(self, name: str, handler: Handler) -> Handler:
        async def wrapped(request: Any, context: Context) -> Any:
            self.requests.append((name, request))
            return await handler(request, context)

        return wrapped

    def _install_defaults(self) -> None:
        self.on("cosmos.auth.v1beta1.Query", "Account", self._account)
        self.on("cosmos.base.node.v1beta1.Service", "Status", self._status)
        self.on("neutronx.perps.v1.Query", "Markets", self._markets)
        self.on("neutronx.orderbook.v1.Query", "UserOrders", self._user_orders)
        self.on("neutronx.agentkeys.v1.Query", "AgentKey", self._agent_key)
        self.on("cosmos.tx.v1beta1.Service", "BroadcastTx", self._broadcast)
        self.on("cosmos.tx.v1beta1.Service", "GetTx", self._get_tx)
        self.on("cosmos.tx.v1beta1.Service", "Simulate", self._simulate)

    async def _account(self, request: Any, context: Context) -> Any:
        base = new(
            "cosmos.auth.v1beta1.BaseAccount",
            address=request.address,
            account_number=12,
            sequence=self.sequence,
        )
        return new("cosmos.auth.v1beta1.QueryAccountResponse", account=pack_any(base))

    async def _status(self, request: Any, context: Context) -> Any:
        return new(
            "cosmos.base.node.v1beta1.StatusResponse",
            height=self.height,
            timestamp=new("google.protobuf.Timestamp", seconds=self.block_seconds),
        )

    async def _markets(self, request: Any, context: Context) -> Any:
        return new(
            "neutronx.perps.v1.QueryMarketsResponse",
            markets=[
                new(
                    "neutronx.perps.v1.QueryMarketResponse",
                    pair="BTC/USDC",
                    status="ACTIVE",
                    tick_size="0.100000000000000000",
                ),
                new("neutronx.perps.v1.QueryMarketResponse", pair=""),
            ],
        )

    async def _user_orders(self, request: Any, context: Context) -> Any:
        orders = [new("neutronx.orderbook.v1.OrderProto", order_id=request.page, pair="BTC/USDC")]
        return new(
            "neutronx.orderbook.v1.QueryUserOrdersResponse",
            orders=orders,
            pagination=new("neutronx.orderbook.v1.PaginationMetaProto", has_next=request.page < 3),
        )

    async def _agent_key(self, request: Any, context: Context) -> Any:
        await context.abort(grpc.StatusCode.NOT_FOUND, "agent key not found")

    async def _broadcast(self, request: Any, context: Context) -> Any:
        code, raw_log = self.check_tx_results.popleft() if self.check_tx_results else (0, "")
        response = new(
            "cosmos.base.abci.v1beta1.TxResponse", txhash="ABCD", code=code, raw_log=raw_log
        )
        return new("cosmos.tx.v1beta1.BroadcastTxResponse", tx_response=response)

    async def _get_tx(self, request: Any, context: Context) -> Any:
        if self.pending_polls > 0:
            self.pending_polls -= 1
            await context.abort(grpc.StatusCode.NOT_FOUND, "tx not found")
        msg_data = new("cosmos.base.abci.v1beta1.TxMsgData")
        msg_data.msg_responses.append(
            pack_any(new("neutronx.orderbook.v1.MsgPlaceShortTermOrderResponse", order_id=55))
        )
        event = new(
            "tendermint.abci.Event",
            type="short_term_placed",
            attributes=[new("tendermint.abci.EventAttribute", key="order_id", value="55")],
        )
        response = new(
            "cosmos.base.abci.v1beta1.TxResponse",
            txhash=request.hash,
            height=self.height + 1,
            code=self.deliver_code,
            raw_log="out of gas" if self.deliver_code else "",
            gas_used=130_000,
            gas_wanted=1_000_000,
            data=msg_data.SerializeToString().hex().upper(),
            events=[event],
        )
        return new("cosmos.tx.v1beta1.GetTxResponse", tx_response=response)

    async def _simulate(self, request: Any, context: Context) -> Any:
        return new(
            "cosmos.tx.v1beta1.SimulateResponse",
            gas_info=new("cosmos.base.abci.v1beta1.GasInfo", gas_used=self.simulate_gas),
        )


@asynccontextmanager
async def serve(chain: FakeChain, timeout: float = 5.0) -> AsyncGenerator[NodeClient, None]:
    server = grpc.aio.server()
    server.add_generic_rpc_handlers(chain.generic_handlers())
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    node = NodeClient(TESTNET.with_endpoint(f"127.0.0.1:{port}", secure=False), timeout=timeout)
    try:
        yield node
    finally:
        await node.close()
        await server.stop(None)
