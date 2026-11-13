from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from neutronx_sdk.models import ChainStatus
from neutronx_sdk.node.queries import NodeQueries

DEFAULT_MAX_AGE = 10.0


class ChainClock:
    __slots__ = ("_fetched_at", "_lock", "_monotonic", "_node", "_offset_ns", "_status", "_time_ns")

    def __init__(
        self,
        node: NodeQueries,
        *,
        time_ns: Callable[[], int] = time.time_ns,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._node = node
        self._time_ns = time_ns
        self._monotonic = monotonic
        self._status: ChainStatus | None = None
        self._fetched_at = 0.0
        self._offset_ns = 0
        self._lock = asyncio.Lock()

    @property
    def status(self) -> ChainStatus | None:
        return self._status

    async def refresh(self) -> ChainStatus:
        async with self._lock:
            status = await self._node.status()
            local_ns = self._time_ns()
            self._status = status
            self._fetched_at = self._monotonic()
            self._offset_ns = int(status.block_time.timestamp() * 1_000_000_000) - local_ns
            return status

    async def current(self, max_age: float = DEFAULT_MAX_AGE) -> ChainStatus:
        if self._status is None or self._monotonic() - self._fetched_at > max_age:
            return await self.refresh()
        return self._status

    async def now_ns(self, max_age: float = DEFAULT_MAX_AGE) -> int:
        await self.current(max_age)
        return self._time_ns() + self._offset_ns

    async def height(self, max_age: float = DEFAULT_MAX_AGE) -> int:
        return (await self.current(max_age)).height
