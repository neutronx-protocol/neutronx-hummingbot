from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import grpc

from neutronx_sdk.exceptions import ChainTxError, TxConfirmationTimeoutError
from neutronx_sdk.node.rpc import RpcClient
from neutronx_sdk.tx.builder import SignedTx
from neutronx_sdk.tx.responses import decode_tx_msg_data

TX_SERVICE = "cosmos.tx.v1beta1.Service"
BROADCAST_MODE_SYNC = 2
DEFAULT_BROADCAST_TIMEOUT = 15.0
DEFAULT_CONFIRM_TIMEOUT = 30.0
DEFAULT_POLL_INTERVAL = 0.5
DEFAULT_GET_TX_TIMEOUT = 5.0


@dataclass(frozen=True)
class TxEvent:
    type: str
    attributes: dict[str, str]


@dataclass(frozen=True)
class TxResult:
    tx_hash: str
    height: int
    gas_used: int
    gas_wanted: int
    raw_log: str
    events: tuple[TxEvent, ...]
    msg_responses: tuple[bytes, ...]


@dataclass(frozen=True)
class CheckTxResult:
    tx_hash: str
    gas_wanted: int


class TxService:
    __slots__ = ("_rpc",)

    def __init__(self, rpc: RpcClient) -> None:
        self._rpc = rpc

    async def broadcast_sync(
        self,
        tx: SignedTx,
        *,
        timeout: float = DEFAULT_BROADCAST_TIMEOUT,
    ) -> CheckTxResult:
        response = await self._rpc.call(
            TX_SERVICE,
            "BroadcastTx",
            tx_bytes=tx.tx_bytes,
            mode=BROADCAST_MODE_SYNC,
            timeout=timeout,
        )
        tx_response = response.tx_response
        tx_hash = str(tx_response.txhash) or tx.tx_hash
        if int(tx_response.code) != 0:
            raise ChainTxError(
                int(tx_response.code),
                str(tx_response.raw_log),
                tx_hash=tx_hash,
                height=int(tx_response.height),
                check_tx=True,
            )
        return CheckTxResult(tx_hash=tx_hash, gas_wanted=int(tx_response.gas_wanted))

    async def get_tx(
        self, tx_hash: str, *, timeout: float = DEFAULT_GET_TX_TIMEOUT
    ) -> TxResult | None:
        try:
            response = await self._rpc.call(TX_SERVICE, "GetTx", hash=tx_hash, timeout=timeout)
        except grpc.aio.AioRpcError as err:
            if err.code() == grpc.StatusCode.NOT_FOUND:
                return None
            raise
        tx_response = response.tx_response
        if int(tx_response.height) <= 0 and int(tx_response.code) == 0:
            return None
        if int(tx_response.code) != 0:
            raise ChainTxError(
                int(tx_response.code),
                str(tx_response.raw_log),
                tx_hash=tx_hash,
                height=int(tx_response.height),
                check_tx=False,
            )
        return _tx_result(tx_hash, tx_response)

    async def wait_for_tx(
        self,
        tx_hash: str,
        *,
        timeout: float = DEFAULT_CONFIRM_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> TxResult:
        deadline = time.monotonic() + timeout
        while True:
            result = await self.get_tx(tx_hash)
            if result is not None:
                return result
            if time.monotonic() + poll_interval > deadline:
                raise TxConfirmationTimeoutError(tx_hash, timeout)
            await asyncio.sleep(poll_interval)

    async def broadcast(
        self,
        tx: SignedTx,
        *,
        confirm_timeout: float = DEFAULT_CONFIRM_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> TxResult:
        check = await self.broadcast_sync(tx)
        return await self.wait_for_tx(
            check.tx_hash, timeout=confirm_timeout, poll_interval=poll_interval
        )

    async def simulate(self, tx: SignedTx) -> int:
        response = await self._rpc.call(TX_SERVICE, "Simulate", tx_bytes=tx.tx_bytes)
        return int(response.gas_info.gas_used)


def _tx_result(tx_hash: str, tx_response: Any) -> TxResult:
    return TxResult(
        tx_hash=tx_hash,
        height=int(tx_response.height),
        gas_used=int(tx_response.gas_used),
        gas_wanted=int(tx_response.gas_wanted),
        raw_log=str(tx_response.raw_log),
        events=tuple(
            TxEvent(
                type=str(event.type),
                attributes={str(a.key): str(a.value) for a in event.attributes},
            )
            for event in tx_response.events
        ),
        msg_responses=tuple(decode_tx_msg_data(str(tx_response.data))),
    )
