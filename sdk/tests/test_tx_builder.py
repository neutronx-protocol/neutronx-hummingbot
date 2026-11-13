from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from neutronx_sdk import FeePolicy, OrderRequest, Side, TxBuilder, UnorderedNonce, Wallet
from neutronx_sdk.orders import (
    batch_cancel_orders_msg,
    cancel_order_msg,
    cancel_short_term_order_msg,
    place_order_msg,
    place_short_term_order_msg,
)
from neutronx_sdk.proto import new, parse, unpack_any
from neutronx_sdk.tx.builder import UNORDERED_NONCE_SLOTS, UNORDERED_TX_TTL_NS


def _order(client_id: int, side: Side, price: str, quantity: str) -> OrderRequest:
    return OrderRequest(
        pair="BTC/USDC",
        side=side,
        price=Decimal(price),
        quantity=Decimal(quantity),
        leverage=Decimal(3),
        client_id=client_id,
    )


@pytest.fixture
def own(golden: dict[str, Any]) -> Wallet:
    return Wallet.from_hex(golden["key_hex"])


@pytest.fixture
def agent(golden: dict[str, Any], own: Wallet) -> Wallet:
    return Wallet.agent(golden["agent_key_hex"], account=own.address, key_id=5)


def test_regular_tx_matches_production_signer(golden: dict[str, Any], own: Wallet) -> None:
    builder = TxBuilder(own, golden["chain_id"])
    tx = builder.regular(
        [
            place_order_msg(own.address, _order(7, Side.BUY, "65000.5", "0.001")),
            cancel_order_msg(own.address, 42, "BTC/USDC"),
        ],
        account_number=12,
        sequence=34,
        gas_limit=400_000,
        fee=FeePolicy("untx").coins(400_000),
    )
    assert tx.tx_bytes.hex() == golden["regular"]


def test_regular_tx_with_gas_price_matches_production_signer(
    golden: dict[str, Any], own: Wallet
) -> None:
    builder = TxBuilder(own, golden["chain_id"])
    fee = FeePolicy("untx", gas_price=Decimal("0.025"))
    tx = builder.regular(
        [batch_cancel_orders_msg(own.address, [1, 2, 3])],
        account_number=12,
        sequence=35,
        gas_limit=300_000,
        fee=fee.coins(300_000),
    )
    assert fee.amount(300_000) == 7500
    assert tx.tx_bytes.hex() == golden["regular_fee"]


def test_short_term_tx_matches_production_signer(golden: dict[str, Any], own: Wallet) -> None:
    builder = TxBuilder(own, golden["chain_id"])
    tx = builder.short_term(
        [
            place_short_term_order_msg(
                own.address, _order(11, Side.BUY, "64999", "0.002"), 1_000_020
            ),
            place_short_term_order_msg(
                own.address, _order(12, Side.SELL, "65001", "0.002"), 1_000_020
            ),
            cancel_short_term_order_msg(own.address, 9, "BTC/USDC", 1_000_015),
        ],
        account_number=12,
        sequence=34,
    )
    assert tx.tx_bytes.hex() == golden["short_term"]


def test_agent_regular_tx_matches_production_signer(
    golden: dict[str, Any], own: Wallet, agent: Wallet
) -> None:
    builder = TxBuilder(agent, golden["chain_id"])
    tx = builder.regular(
        [batch_cancel_orders_msg(own.address, [1, 2, 3])],
        account_number=12,
        sequence=99,
        gas_limit=300_000,
        fee=FeePolicy("untx").coins(300_000),
        unordered_timeout_ns=1_762_000_060_000_000_123,
    )
    assert tx.tx_bytes.hex() == golden["agent_regular"]


def test_agent_short_term_tx_matches_production_signer(
    golden: dict[str, Any], own: Wallet, agent: Wallet
) -> None:
    builder = TxBuilder(agent, golden["chain_id"])
    tx = builder.short_term(
        [
            place_short_term_order_msg(
                own.address, _order(13, Side.SELL, "65010.25", "0.003"), 1_000_020
            )
        ],
        account_number=12,
        sequence=77,
    )
    assert tx.tx_bytes.hex() == golden["agent_short_term"]


def test_signature_verifies_over_sign_doc(golden: dict[str, Any], own: Wallet) -> None:
    tx = TxBuilder(own, golden["chain_id"]).short_term(
        [cancel_short_term_order_msg(own.address, 9, "BTC/USDC", 1_000_015)],
        account_number=12,
        sequence=34,
    )
    raw = parse("cosmos.tx.v1beta1.TxRaw", tx.tx_bytes)
    sign_doc = new(
        "cosmos.tx.v1beta1.SignDoc",
        body_bytes=raw.body_bytes,
        auth_info_bytes=raw.auth_info_bytes,
        chain_id=golden["chain_id"],
        account_number=12,
    )
    assert own.public_key.verify(bytes(raw.signatures[0]), sign_doc.SerializeToString())
    assert not own.public_key.verify(bytes(raw.signatures[0]), b"other")


def test_agent_body_carries_extension_and_unordered_timeout(own: Wallet, agent: Wallet) -> None:
    tx = TxBuilder(agent, "neutronx-1").regular(
        [batch_cancel_orders_msg(own.address, [1])],
        account_number=1,
        sequence=5,
        gas_limit=200_000,
        fee=(),
        unordered_timeout_ns=3_000_000_007,
    )
    raw = parse("cosmos.tx.v1beta1.TxRaw", tx.tx_bytes)
    body = parse("cosmos.tx.v1beta1.TxBody", raw.body_bytes)
    auth = parse("cosmos.tx.v1beta1.AuthInfo", raw.auth_info_bytes)
    extension = unpack_any(
        body.non_critical_extension_options[0], "neutronx.agentkeys.v1.TxExtension"
    )
    assert extension.key_id == 5
    assert body.unordered
    assert (body.timeout_timestamp.seconds, body.timeout_timestamp.nanos) == (3, 7)
    assert auth.signer_infos[0].sequence == 0


def test_agent_regular_tx_requires_unordered_timeout(own: Wallet, agent: Wallet) -> None:
    with pytest.raises(ValueError, match="unordered"):
        TxBuilder(agent, "neutronx-1").regular(
            [batch_cancel_orders_msg(own.address, [1])],
            account_number=1,
            sequence=0,
            gas_limit=200_000,
            fee=(),
        )


def test_tx_hash_is_uppercase_sha256(own: Wallet) -> None:
    tx = TxBuilder(own, "neutronx-1").short_term(
        [cancel_short_term_order_msg(own.address, 1, "BTC/USDC", 10)],
        account_number=1,
        sequence=1,
    )
    assert len(tx.tx_hash) == 64
    assert tx.tx_hash == tx.tx_hash.upper()


@pytest.mark.parametrize("gas_limit", [0, 10_000_001])
def test_short_term_gas_limit_bounds(own: Wallet, gas_limit: int) -> None:
    with pytest.raises(ValueError, match="gas limit"):
        TxBuilder(own, "neutronx-1").short_term(
            [cancel_short_term_order_msg(own.address, 1, "BTC/USDC", 10)],
            account_number=1,
            sequence=1,
            gas_limit=gas_limit,
        )


def test_empty_tx_is_refused(own: Wallet) -> None:
    with pytest.raises(ValueError, match="at least one message"):
        TxBuilder(own, "neutronx-1").build([], account_number=1, sequence=1, gas_limit=1)


def test_unordered_nonce_ends_in_slot_and_strictly_increases() -> None:
    nonce = UnorderedNonce(slot=42)
    first = nonce.next(1_000_000_000_000)
    second = nonce.next(1_000_000_000_000)
    third = nonce.next(999_000_000_000)
    assert first % UNORDERED_NONCE_SLOTS == 42
    assert first >= 1_000_000_000_000 + UNORDERED_TX_TTL_NS - UNORDERED_NONCE_SLOTS
    assert second == first + UNORDERED_NONCE_SLOTS
    assert third == second + UNORDERED_NONCE_SLOTS


def test_fee_policy_flat_amount_and_zero_gas() -> None:
    assert FeePolicy("untx", flat_amount=500).amount(100_000) == 500
    assert FeePolicy("untx", gas_price=Decimal("0.1")).amount(0) == 0
    assert FeePolicy("untx", gas_price=Decimal("0.0000001")).amount(3) == 1
