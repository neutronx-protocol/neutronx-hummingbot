from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

LEGACY_DEC_PRECISION = 18
_SCALE = Decimal(10) ** LEGACY_DEC_PRECISION
_ONE = Decimal(1)


def to_legacy_dec(value: Decimal | int | str) -> str:
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    if not number.is_finite():
        raise ValueError(f"not a finite decimal: {value!r}")
    return str(int((number * _SCALE).quantize(_ONE, rounding=ROUND_DOWN)))


def from_legacy_dec(raw: str) -> Decimal:
    text = raw.strip()
    if not text:
        return Decimal(0)
    if "." in text:
        return Decimal(text)
    return Decimal(int(text)).scaleb(-LEGACY_DEC_PRECISION)


def optional_legacy_dec(raw: str) -> Decimal | None:
    text = raw.strip()
    if not text:
        return None
    return from_legacy_dec(text)


def positive_legacy_dec(raw: str) -> Decimal | None:
    value = optional_legacy_dec(raw)
    if value is None or value <= 0:
        return None
    return value
