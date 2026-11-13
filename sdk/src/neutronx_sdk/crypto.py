from __future__ import annotations

import hashlib
import hmac
from typing import Any, cast

import bech32
import coincurve
from coincurve import ecdsa as coincurve_ecdsa
from Crypto.Hash import RIPEMD160
from mnemonic import Mnemonic

DEFAULT_HD_PATH = "m/44'/118'/0'/0/0"
HARDENED_OFFSET = 0x80000000
SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
PRIVATE_KEY_LENGTH = 32
SIGNATURE_LENGTH = 64
_MASTER_KEY_SALT = b"Bitcoin seed"
_ECDSA: Any = coincurve_ecdsa


class PublicKey:
    __slots__ = ("_compressed",)

    def __init__(self, compressed: bytes) -> None:
        self._compressed = coincurve.PublicKey(compressed).format(compressed=True)

    @property
    def compressed(self) -> bytes:
        return self._compressed

    def address(self, prefix: str) -> str:
        sha = hashlib.sha256(self._compressed).digest()
        return encode_address(prefix, RIPEMD160.new(sha).digest())

    def verify(self, signature: bytes, message: bytes) -> bool:
        if len(signature) != SIGNATURE_LENGTH:
            return False
        try:
            der = cast(bytes, _ECDSA.cdata_to_der(_ECDSA.deserialize_compact(signature)))
        except ValueError:
            return False
        return bool(coincurve.PublicKey(self._compressed).verify(der, message))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PublicKey) and other._compressed == self._compressed

    def __hash__(self) -> int:
        return hash(self._compressed)

    def __repr__(self) -> str:
        return f"PublicKey({self._compressed.hex()})"


class PrivateKey:
    __slots__ = ("_key",)

    def __init__(self, secret: bytes) -> None:
        if len(secret) != PRIVATE_KEY_LENGTH:
            raise ValueError(f"private key must be {PRIVATE_KEY_LENGTH} bytes")
        self._key = coincurve.PrivateKey(secret)

    @classmethod
    def from_hex(cls, hex_key: str) -> PrivateKey:
        return cls(bytes.fromhex(hex_key.strip().removeprefix("0x")))

    @classmethod
    def from_mnemonic(
        cls,
        words: str,
        hd_path: str = DEFAULT_HD_PATH,
        passphrase: str = "",
    ) -> PrivateKey:
        normalized = " ".join(words.split())
        mnemonic = Mnemonic("english")
        if not mnemonic.check(normalized):
            raise ValueError("invalid mnemonic")
        seed = Mnemonic.to_seed(normalized, passphrase=passphrase)
        return cls(derive_bip32(seed, parse_hd_path(hd_path)))

    @property
    def public_key(self) -> PublicKey:
        return PublicKey(self._key.public_key.format(compressed=True))

    def sign(self, message: bytes) -> bytes:
        digest = hashlib.sha256(message).digest()
        signer: Any = self._key
        return cast(bytes, signer.sign_recoverable(digest, hasher=None))[:SIGNATURE_LENGTH]

    def __repr__(self) -> str:
        return f"PrivateKey(public_key={self.public_key.compressed.hex()})"


def parse_hd_path(path: str) -> list[int]:
    segments = path.split("/")
    if segments[0] != "m":
        raise ValueError(f"invalid HD path: {path}")
    indices: list[int] = []
    for segment in segments[1:]:
        hardened = segment.endswith("'")
        digits = segment[:-1] if hardened else segment
        if not digits.isdigit():
            raise ValueError(f"invalid HD path: {path}")
        index = int(digits)
        if index >= HARDENED_OFFSET:
            raise ValueError(f"invalid HD path: {path}")
        indices.append(index | HARDENED_OFFSET if hardened else index)
    return indices


def derive_bip32(seed: bytes, path: list[int]) -> bytes:
    output = hmac.new(_MASTER_KEY_SALT, seed, hashlib.sha512).digest()
    key, chain_code = output[:32], output[32:]
    _check_scalar(int.from_bytes(key, "big"))
    for index in path:
        if index >= HARDENED_OFFSET:
            data = b"\x00" + key + index.to_bytes(4, "big")
        else:
            data = coincurve.PrivateKey(key).public_key.format(compressed=True) + index.to_bytes(
                4, "big"
            )
        output = hmac.new(chain_code, data, hashlib.sha512).digest()
        tweak = int.from_bytes(output[:32], "big")
        if tweak >= SECP256K1_ORDER:
            raise ValueError("derived key is invalid")
        child = (tweak + int.from_bytes(key, "big")) % SECP256K1_ORDER
        _check_scalar(child)
        key, chain_code = child.to_bytes(32, "big"), output[32:]
    return key


def encode_address(prefix: str, data: bytes) -> str:
    words = bech32.convertbits(data, 8, 5, True)
    if words is None:
        raise ValueError("bech32 conversion failed")
    return bech32.bech32_encode(prefix, words)


def decode_address(address: str, prefix: str) -> bytes:
    hrp, words = cast("tuple[str | None, list[int] | None]", bech32.bech32_decode(address))
    if hrp != prefix or words is None:
        raise ValueError(f"not a {prefix} address: {address!r}")
    data = bech32.convertbits(words, 5, 8, False)
    if data is None:
        raise ValueError(f"not a {prefix} address: {address!r}")
    return bytes(data)


def is_address(address: str, prefix: str) -> bool:
    try:
        decode_address(address, prefix)
    except ValueError:
        return False
    return True


def _check_scalar(value: int) -> None:
    if not 0 < value < SECP256K1_ORDER:
        raise ValueError("derived key is invalid")
