from __future__ import annotations

from neutronx_sdk.crypto import DEFAULT_HD_PATH, PrivateKey, PublicKey, decode_address
from neutronx_sdk.network import BECH32_PREFIX


class Wallet:
    __slots__ = ("_address", "_agent_key_id", "_key", "_key_address")

    def __init__(
        self,
        key: PrivateKey,
        *,
        prefix: str = BECH32_PREFIX,
        account: str | None = None,
        agent_key_id: int = 0,
    ) -> None:
        if agent_key_id < 0:
            raise ValueError(f"agent key id must not be negative, got {agent_key_id}")
        key_address = key.public_key.address(prefix)
        if agent_key_id:
            if account is None:
                raise ValueError("an agent key signs for an account address")
            decode_address(account, prefix)
            if account == key_address:
                raise ValueError("an agent key cannot be the account's own key")
            address = account
        else:
            if account is not None and account != key_address:
                raise ValueError("the account's own key derives a different address")
            address = key_address
        self._key = key
        self._key_address = key_address
        self._address = address
        self._agent_key_id = agent_key_id

    @classmethod
    def from_mnemonic(
        cls,
        words: str,
        *,
        prefix: str = BECH32_PREFIX,
        hd_path: str = DEFAULT_HD_PATH,
        passphrase: str = "",
    ) -> Wallet:
        return cls(PrivateKey.from_mnemonic(words, hd_path, passphrase), prefix=prefix)

    @classmethod
    def from_hex(cls, hex_key: str, *, prefix: str = BECH32_PREFIX) -> Wallet:
        return cls(PrivateKey.from_hex(hex_key), prefix=prefix)

    @classmethod
    def agent(
        cls,
        key: PrivateKey | str,
        *,
        account: str,
        key_id: int,
        prefix: str = BECH32_PREFIX,
    ) -> Wallet:
        if key_id <= 0:
            raise ValueError(f"agent key id must be positive, got {key_id}")
        private_key = PrivateKey.from_hex(key) if isinstance(key, str) else key
        return cls(private_key, prefix=prefix, account=account, agent_key_id=key_id)

    @property
    def address(self) -> str:
        return self._address

    @property
    def key_address(self) -> str:
        return self._key_address

    @property
    def public_key(self) -> PublicKey:
        return self._key.public_key

    @property
    def agent_key_id(self) -> int:
        return self._agent_key_id

    @property
    def is_agent(self) -> bool:
        return self._agent_key_id > 0

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)

    def __repr__(self) -> str:
        if self._agent_key_id:
            return f"Wallet(address={self._address}, agent_key_id={self._agent_key_id})"
        return f"Wallet(address={self._address})"
