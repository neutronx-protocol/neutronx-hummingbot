from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import ROUND_CEILING, Decimal

from google.protobuf.message import Message

from neutronx_sdk.exceptions import ChainTxError, TxFailure
from neutronx_sdk.node.client import NodeClient
from neutronx_sdk.node.clock import ChainClock
from neutronx_sdk.node.sequence import AccountSequence, SigningSlot
from neutronx_sdk.node.tx_service import DEFAULT_CONFIRM_TIMEOUT, DEFAULT_POLL_INTERVAL, TxResult
from neutronx_sdk.tx.builder import FeePolicy, SignedTx, TxBuilder, UnorderedNonce
from neutronx_sdk.tx.gas import SHORT_TERM_DEFAULT_GAS_LIMIT, tx_prefill_gas_floor
from neutronx_sdk.wallet import Wallet

SEQUENCE_RETRY_LIMIT = 2
SIGNER_BUDGET_RETRY_LIMIT = 4
SIGNER_BUDGET_WAIT_STEP = 0.05
SIGNER_BUDGET_WAIT_STEPS = 40
SIGNER_BUDGET_HEIGHT_POLL_EVERY = 10
GAS_ADJUSTMENT = Decimal("1.3")


class TxSender:
    __slots__ = (
        "_builder",
        "_client",
        "_clock",
        "_committed_height",
        "_confirm_timeout",
        "_fee",
        "_lock",
        "_nonce",
        "_poll_interval",
        "_sequence",
        "_wallet",
    )

    def __init__(
        self,
        client: NodeClient,
        wallet: Wallet,
        *,
        fee: FeePolicy,
        nonce: UnorderedNonce | None = None,
        clock: ChainClock | None = None,
        confirm_timeout: float = DEFAULT_CONFIRM_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._client = client
        self._wallet = wallet
        self._builder = TxBuilder(wallet, client.network.chain_id)
        self._sequence = AccountSequence(client.auth, wallet.address, agent=wallet.is_agent)
        self._fee = fee
        self._nonce = nonce or UnorderedNonce()
        self._clock = clock or ChainClock(client.node)
        self._confirm_timeout = confirm_timeout
        self._poll_interval = poll_interval
        self._lock = asyncio.Lock()
        self._committed_height = 0

    @property
    def wallet(self) -> Wallet:
        return self._wallet

    @property
    def sequence(self) -> AccountSequence:
        return self._sequence

    @property
    def clock(self) -> ChainClock:
        return self._clock

    @property
    def fee(self) -> FeePolicy:
        return self._fee

    @fee.setter
    def fee(self, fee: FeePolicy) -> None:
        self._fee = fee

    @property
    def committed_height(self) -> int:
        return self._committed_height

    async def estimate_gas(self, msgs: Sequence[Message], *, ceiling: int) -> int:
        slot = await self._sequence.current()
        tx = await self._regular_tx(msgs, slot, ceiling)
        gas_used = await self._client.tx.simulate(tx)
        estimate = int(
            (Decimal(gas_used) * GAS_ADJUSTMENT).to_integral_value(rounding=ROUND_CEILING)
        )
        return min(ceiling, max(estimate, tx_prefill_gas_floor(msgs)))

    async def send(self, msgs: Sequence[Message], *, gas_limit: int) -> TxResult:
        attempt = 0
        while True:
            try:
                check_hash = await self._broadcast_regular(msgs, gas_limit)
            except ChainTxError as err:
                self._note_height(err.height)
                self._sequence.mark_stale()
                if err.failure is TxFailure.SEQUENCE_MISMATCH and attempt < SEQUENCE_RETRY_LIMIT:
                    attempt += 1
                    continue
                raise
            return await self._confirm(check_hash)

    async def send_short_term(
        self,
        msgs: Sequence[Message],
        *,
        gas_limit: int = SHORT_TERM_DEFAULT_GAS_LIMIT,
    ) -> TxResult:
        sequence_attempt = 0
        budget_attempt = 0
        while True:
            slot = await self._sequence.current()
            tx = self._builder.short_term(
                msgs,
                account_number=slot.account_number,
                sequence=slot.sequence,
                gas_limit=gas_limit,
            )
            try:
                check = await self._client.tx.broadcast_sync(tx)
                return await self._confirm(check.tx_hash)
            except ChainTxError as err:
                self._note_height(err.height)
                failure = err.failure
                if (
                    failure is TxFailure.SEQUENCE_MISMATCH
                    and sequence_attempt < SEQUENCE_RETRY_LIMIT
                ):
                    sequence_attempt += 1
                    self._sequence.mark_stale()
                    continue
                if (
                    failure is TxFailure.SIGNER_BUDGET
                    and budget_attempt < SIGNER_BUDGET_RETRY_LIMIT
                ):
                    budget_attempt += 1
                    await self._wait_past(err.queued_height)
                    continue
                raise

    async def _broadcast_regular(self, msgs: Sequence[Message], gas_limit: int) -> str:
        if self._wallet.is_agent:
            slot = await self._sequence.current()
            tx = await self._regular_tx(msgs, slot, gas_limit)
            return (await self._client.tx.broadcast_sync(tx)).tx_hash
        async with self._lock:
            slot = await self._sequence.reserve()
            tx = await self._regular_tx(msgs, slot, gas_limit)
            return (await self._client.tx.broadcast_sync(tx)).tx_hash

    async def _regular_tx(
        self, msgs: Sequence[Message], slot: SigningSlot, gas_limit: int
    ) -> SignedTx:
        timeout_ns = self._nonce.next(await self._clock.now_ns()) if self._wallet.is_agent else 0
        return self._builder.regular(
            msgs,
            account_number=slot.account_number,
            sequence=slot.sequence,
            gas_limit=gas_limit,
            fee=self._fee.coins(gas_limit),
            unordered_timeout_ns=timeout_ns,
        )

    async def _confirm(self, tx_hash: str) -> TxResult:
        try:
            result = await self._client.tx.wait_for_tx(
                tx_hash, timeout=self._confirm_timeout, poll_interval=self._poll_interval
            )
        except ChainTxError as err:
            self._note_height(err.height)
            raise
        self._note_height(result.height)
        return result

    async def _wait_past(self, queued: int | None) -> None:
        target = queued if queued is not None else self._committed_height + 1
        for step in range(SIGNER_BUDGET_WAIT_STEPS):
            if self._committed_height >= target:
                return
            if step % SIGNER_BUDGET_HEIGHT_POLL_EVERY == 0:
                self._note_height(await self._clock.height(max_age=0))
                if self._committed_height >= target:
                    return
            await asyncio.sleep(SIGNER_BUDGET_WAIT_STEP)

    def _note_height(self, height: int) -> None:
        self._committed_height = max(self._committed_height, height)
