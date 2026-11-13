from __future__ import annotations

import asyncio
from dataclasses import dataclass

from neutronx_sdk.node.queries import AuthQueries


@dataclass(frozen=True)
class SigningSlot:
    account_number: int
    sequence: int


class AccountSequence:
    __slots__ = ("_account_number", "_address", "_agent", "_auth", "_lock", "_sequence", "_stale")

    def __init__(self, auth: AuthQueries, address: str, *, agent: bool = False) -> None:
        self._auth = auth
        self._address = address
        self._agent = agent
        self._account_number: int | None = None
        self._sequence: int | None = None
        self._stale = True
        self._lock = asyncio.Lock()

    @property
    def address(self) -> str:
        return self._address

    @property
    def account_number(self) -> int | None:
        return self._account_number

    @property
    def sequence(self) -> int | None:
        return self._sequence

    async def refresh(self) -> None:
        async with self._lock:
            await self._refresh()

    async def reserve(self) -> SigningSlot:
        async with self._lock:
            account_number, sequence = await self._ready()
            if self._agent:
                return SigningSlot(account_number, 0)
            self._sequence = sequence + 1
            return SigningSlot(account_number, sequence)

    async def current(self) -> SigningSlot:
        async with self._lock:
            account_number, sequence = await self._ready()
            return SigningSlot(account_number, 0 if self._agent else sequence)

    def mark_stale(self) -> None:
        self._stale = True

    async def _ready(self) -> tuple[int, int]:
        if self._stale or self._account_number is None or self._sequence is None:
            await self._refresh()
        if self._account_number is None or self._sequence is None:
            raise RuntimeError(f"account {self._address} has no sequence")
        return self._account_number, self._sequence

    async def _refresh(self) -> None:
        account = await self._auth.account(self._address)
        self._account_number = account.account_number
        self._sequence = account.sequence
        self._stale = False
