from __future__ import annotations

from collections.abc import Iterable

from neutronx_sdk.exceptions import NeutronXError
from neutronx_sdk.orders import CLIENT_ID_MAX


class ClientIdAllocator:
    __slots__ = ("_in_use", "_limit", "_next")

    def __init__(self, start: int = 1, *, limit: int = CLIENT_ID_MAX) -> None:
        if not 1 <= limit <= CLIENT_ID_MAX:
            raise ValueError(f"limit must be in [1, {CLIENT_ID_MAX}], got {limit}")
        self._limit = limit
        self._next = self._wrap(start)
        self._in_use: set[int] = set()

    @property
    def limit(self) -> int:
        return self._limit

    def seed(self, in_use: Iterable[int]) -> None:
        valid = {client_id for client_id in in_use if 1 <= client_id <= self._limit}
        self._in_use |= valid
        if valid:
            self._next = self._wrap(max(self._next, max(valid) + 1))

    def allocate(self) -> int:
        for _ in range(len(self._in_use) + 1):
            candidate = self._next
            self._next = self._wrap(candidate + 1)
            if candidate not in self._in_use:
                self._in_use.add(candidate)
                return candidate
        raise NeutronXError("client id space is exhausted")

    def release(self, client_id: int) -> None:
        self._in_use.discard(client_id)

    def __contains__(self, client_id: object) -> bool:
        return client_id in self._in_use

    def __len__(self) -> int:
        return len(self._in_use)

    def _wrap(self, value: int) -> int:
        return (value - 1) % self._limit + 1
