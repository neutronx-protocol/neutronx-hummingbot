from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

from google.protobuf.message import Message

from neutronx_sdk.models import Coin, OrderbookParams
from neutronx_sdk.proto import new, pack_any
from neutronx_sdk.tx.gas import SHORT_TERM_DEFAULT_GAS_LIMIT, SHORT_TERM_MAX_GAS_LIMIT
from neutronx_sdk.wallet import Wallet

SIGN_MODE_DIRECT = 1
NANOS_PER_SECOND = 1_000_000_000
UNORDERED_TX_TTL_NS = 60 * NANOS_PER_SECOND
UNORDERED_NONCE_SLOTS = 1000
NODE_MIN_GAS_PRICE = Decimal("0.001")


@dataclass(frozen=True)
class FeePolicy:
    denom: str
    gas_price: Decimal = Decimal(0)
    flat_amount: int = 0

    def amount(self, gas_limit: int) -> int:
        if gas_limit <= 0:
            return 0
        if self.gas_price > 0:
            return int(
                (Decimal(gas_limit) * self.gas_price).to_integral_value(rounding=ROUND_CEILING)
            )
        return max(0, self.flat_amount)

    def coins(self, gas_limit: int) -> tuple[Coin, ...]:
        return (Coin(denom=self.denom, amount=self.amount(gas_limit)),)

    @classmethod
    def for_trading(
        cls,
        params: OrderbookParams,
        margin_denom: str,
        node_min_gas_price: Decimal = NODE_MIN_GAS_PRICE,
    ) -> FeePolicy:
        return cls(denom=margin_denom, gas_price=max(params.min_gas_price, node_min_gas_price))


@dataclass(frozen=True)
class SignedTx:
    tx_bytes: bytes

    @property
    def tx_hash(self) -> str:
        return hashlib.sha256(self.tx_bytes).hexdigest().upper()


class UnorderedNonce:
    __slots__ = ("_last", "_slot", "_ttl_ns")

    def __init__(self, slot: int | None = None, ttl_ns: int = UNORDERED_TX_TTL_NS) -> None:
        if ttl_ns <= 0:
            raise ValueError(f"ttl must be positive, got {ttl_ns}")
        self._slot = (
            secrets.randbelow(UNORDERED_NONCE_SLOTS)
            if slot is None
            else slot % UNORDERED_NONCE_SLOTS
        )
        self._ttl_ns = ttl_ns
        self._last = 0

    @property
    def slot(self) -> int:
        return self._slot

    def next(self, chain_time_ns: int) -> int:
        base = chain_time_ns + self._ttl_ns
        timeout = base - base % UNORDERED_NONCE_SLOTS + self._slot
        if timeout <= self._last:
            timeout = self._last + UNORDERED_NONCE_SLOTS
        self._last = timeout
        return timeout


class TxBuilder:
    __slots__ = ("_chain_id", "_wallet")

    def __init__(self, wallet: Wallet, chain_id: str) -> None:
        if not chain_id:
            raise ValueError("chain_id is required")
        self._wallet = wallet
        self._chain_id = chain_id

    @property
    def wallet(self) -> Wallet:
        return self._wallet

    @property
    def chain_id(self) -> str:
        return self._chain_id

    def short_term(
        self,
        msgs: Sequence[Message],
        *,
        account_number: int,
        sequence: int,
        gas_limit: int = SHORT_TERM_DEFAULT_GAS_LIMIT,
    ) -> SignedTx:
        if not 0 < gas_limit <= SHORT_TERM_MAX_GAS_LIMIT:
            raise ValueError(
                f"short-term gas limit must be in (0, {SHORT_TERM_MAX_GAS_LIMIT}], got {gas_limit}"
            )
        return self.build(
            msgs,
            account_number=account_number,
            sequence=0 if self._wallet.is_agent else sequence,
            gas_limit=gas_limit,
        )

    def regular(
        self,
        msgs: Sequence[Message],
        *,
        account_number: int,
        sequence: int,
        gas_limit: int,
        fee: Sequence[Coin],
        unordered_timeout_ns: int = 0,
    ) -> SignedTx:
        if self._wallet.is_agent:
            if unordered_timeout_ns <= 0:
                raise ValueError("an agent key signs regular txs unordered")
            sequence = 0
        return self.build(
            msgs,
            account_number=account_number,
            sequence=sequence,
            gas_limit=gas_limit,
            fee=fee,
            unordered_timeout_ns=unordered_timeout_ns,
        )

    def build(
        self,
        msgs: Sequence[Message],
        *,
        account_number: int,
        sequence: int,
        gas_limit: int,
        fee: Sequence[Coin] = (),
        memo: str = "",
        timeout_height: int = 0,
        unordered_timeout_ns: int = 0,
    ) -> SignedTx:
        if not msgs:
            raise ValueError("a tx carries at least one message")
        if gas_limit <= 0:
            raise ValueError(f"gas limit must be positive, got {gas_limit}")
        body_bytes = self._body(
            msgs, memo, timeout_height, unordered_timeout_ns
        ).SerializeToString()
        auth_info_bytes = self._auth_info(sequence, fee, gas_limit).SerializeToString()
        sign_doc = new(
            "cosmos.tx.v1beta1.SignDoc",
            body_bytes=body_bytes,
            auth_info_bytes=auth_info_bytes,
            chain_id=self._chain_id,
            account_number=account_number,
        )
        signature = self._wallet.sign(sign_doc.SerializeToString())
        tx_raw = new(
            "cosmos.tx.v1beta1.TxRaw",
            body_bytes=body_bytes,
            auth_info_bytes=auth_info_bytes,
            signatures=[signature],
        )
        return SignedTx(tx_bytes=tx_raw.SerializeToString())

    def _body(
        self,
        msgs: Sequence[Message],
        memo: str,
        timeout_height: int,
        unordered_timeout_ns: int,
    ) -> Any:
        body = new(
            "cosmos.tx.v1beta1.TxBody",
            messages=[pack_any(msg) for msg in msgs],
            memo=memo,
            timeout_height=timeout_height,
        )
        if self._wallet.is_agent:
            extension = new("neutronx.agentkeys.v1.TxExtension", key_id=self._wallet.agent_key_id)
            body.non_critical_extension_options.append(pack_any(extension))
        if unordered_timeout_ns:
            seconds, nanos = divmod(unordered_timeout_ns, NANOS_PER_SECOND)
            body.unordered = True
            body.timeout_timestamp.seconds = seconds
            body.timeout_timestamp.nanos = nanos
        return body

    def _auth_info(self, sequence: int, fee: Sequence[Coin], gas_limit: int) -> Any:
        public_key = new("cosmos.crypto.secp256k1.PubKey", key=self._wallet.public_key.compressed)
        signer_info = new(
            "cosmos.tx.v1beta1.SignerInfo",
            public_key=pack_any(public_key),
            mode_info=new(
                "cosmos.tx.v1beta1.ModeInfo",
                single=new("cosmos.tx.v1beta1.ModeInfo.Single", mode=SIGN_MODE_DIRECT),
            ),
            sequence=sequence,
        )
        fee_message = new(
            "cosmos.tx.v1beta1.Fee",
            amount=[
                new("cosmos.base.v1beta1.Coin", denom=c.denom, amount=str(c.amount)) for c in fee
            ],
            gas_limit=gas_limit,
        )
        return new("cosmos.tx.v1beta1.AuthInfo", signer_infos=[signer_info], fee=fee_message)
