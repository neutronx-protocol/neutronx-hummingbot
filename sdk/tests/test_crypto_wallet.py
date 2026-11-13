from __future__ import annotations

from typing import Any

import pytest

from neutronx_sdk import PrivateKey, Wallet
from neutronx_sdk.crypto import (
    SECP256K1_ORDER,
    decode_address,
    encode_address,
    is_address,
    parse_hd_path,
)


def test_mnemonic_derives_production_address(golden: dict[str, Any]) -> None:
    wallet = Wallet.from_mnemonic(golden["mnemonic"])
    assert wallet.address == golden["mnemonic_address"]
    assert wallet.public_key.compressed.hex() == golden["mnemonic_pubkey"]


def test_mnemonic_whitespace_is_normalized(golden: dict[str, Any]) -> None:
    spaced = "  " + golden["mnemonic"].replace(" ", "   ") + "\n"
    assert Wallet.from_mnemonic(spaced).address == golden["mnemonic_address"]


def test_hex_key_derives_production_address(golden: dict[str, Any]) -> None:
    wallet = Wallet.from_hex("0x" + golden["key_hex"])
    assert wallet.address == golden["account"]
    assert wallet.public_key.compressed.hex() == golden["pubkey"]


def test_invalid_mnemonic_is_refused() -> None:
    with pytest.raises(ValueError, match="invalid mnemonic"):
        Wallet.from_mnemonic("abandon " * 11 + "abandon")


def test_signature_is_low_s_and_deterministic(golden: dict[str, Any]) -> None:
    key = PrivateKey.from_hex(golden["key_hex"])
    first = key.sign(b"payload")
    assert first == key.sign(b"payload")
    assert len(first) == 64
    assert int.from_bytes(first[32:], "big") <= SECP256K1_ORDER // 2
    assert key.public_key.verify(first, b"payload")


def test_agent_wallet_trades_as_the_account(golden: dict[str, Any]) -> None:
    agent = Wallet.agent(golden["agent_key_hex"], account=golden["account"], key_id=5)
    assert agent.address == golden["account"]
    assert agent.key_address != golden["account"]
    assert agent.public_key.compressed.hex() == golden["agent_pubkey"]
    assert agent.is_agent
    assert agent.agent_key_id == 5
    assert "agent_key_id=5" in repr(agent)


def test_agent_wallet_refuses_own_key_and_bad_account(golden: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="own key"):
        Wallet.agent(golden["key_hex"], account=golden["account"], key_id=1)
    with pytest.raises(ValueError, match="not a neutronx address"):
        Wallet.agent(golden["agent_key_hex"], account="cosmos1xyz", key_id=1)
    with pytest.raises(ValueError, match="positive"):
        Wallet.agent(golden["agent_key_hex"], account=golden["account"], key_id=0)


def test_wallet_refuses_foreign_account_for_own_key(golden: dict[str, Any]) -> None:
    key = PrivateKey.from_hex(golden["agent_key_hex"])
    with pytest.raises(ValueError, match="different address"):
        Wallet(key, account=golden["account"])


def test_repr_never_shows_the_secret(golden: dict[str, Any]) -> None:
    key = PrivateKey.from_hex(golden["key_hex"])
    assert golden["key_hex"] not in repr(key)
    assert golden["key_hex"] not in repr(Wallet(key))


def test_private_key_length_is_checked() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        PrivateKey(b"\x01" * 31)


def test_address_round_trip(golden: dict[str, Any]) -> None:
    data = decode_address(golden["account"], "neutronx")
    assert len(data) == 20
    assert encode_address("neutronx", data) == golden["account"]
    assert is_address(golden["account"], "neutronx")
    assert not is_address(golden["account"], "cosmos")
    assert not is_address("neutronx1invalid", "neutronx")


@pytest.mark.parametrize("path", ["44'/118'/0'/0/0", "m/44'/x/0", "m/2147483648", "m/-1"])
def test_bad_hd_paths_are_refused(path: str) -> None:
    with pytest.raises(ValueError, match="invalid HD path"):
        parse_hd_path(path)


def test_hd_path_parsing() -> None:
    assert parse_hd_path("m/44'/118'/0'/0/7") == [
        44 | 0x80000000,
        118 | 0x80000000,
        0x80000000,
        0,
        7,
    ]
