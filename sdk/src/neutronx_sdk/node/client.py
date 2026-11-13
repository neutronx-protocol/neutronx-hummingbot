from __future__ import annotations

from types import TracebackType

import grpc

from neutronx_sdk.network import Network
from neutronx_sdk.node.queries import (
    AgentKeysQueries,
    AuthQueries,
    BankQueries,
    NodeQueries,
    OracleQueries,
    OrderbookQueries,
    PerpsQueries,
)
from neutronx_sdk.node.rpc import DEFAULT_TIMEOUT, RpcClient, create_channel
from neutronx_sdk.node.tx_service import TxService


class NodeClient:
    __slots__ = (
        "_owns_channel",
        "_rpc",
        "agentkeys",
        "auth",
        "bank",
        "network",
        "node",
        "oracle",
        "orderbook",
        "perps",
        "tx",
    )

    def __init__(
        self,
        network: Network,
        *,
        channel: grpc.aio.Channel | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.network = network
        self._owns_channel = channel is None
        resolved = channel or create_channel(network.grpc_endpoint, secure=network.secure)
        self._rpc = RpcClient(resolved, timeout)
        self.auth = AuthQueries(self._rpc)
        self.bank = BankQueries(self._rpc)
        self.node = NodeQueries(self._rpc)
        self.orderbook = OrderbookQueries(self._rpc)
        self.perps = PerpsQueries(self._rpc)
        self.oracle = OracleQueries(self._rpc)
        self.agentkeys = AgentKeysQueries(self._rpc)
        self.tx = TxService(self._rpc)

    @property
    def rpc(self) -> RpcClient:
        return self._rpc

    async def close(self) -> None:
        if self._owns_channel:
            await self._rpc.channel.close()

    async def __aenter__(self) -> NodeClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
