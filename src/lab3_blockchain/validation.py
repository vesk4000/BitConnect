"""Shared validation helpers for Lab 3 blockchain primitives."""

from __future__ import annotations

UINT32_MAX = (1 << 32) - 1
UINT64_MAX = (1 << 64) - 1


def validate_bytes(field_name: str, value: bytes) -> None:
    if not isinstance(value, bytes):
        raise TypeError(f"{field_name} must be bytes")


def validate_uint32(field_name: str, value: int) -> None:
    validate_unsigned_int(field_name, value, UINT32_MAX, 32)


def validate_uint64(field_name: str, value: int) -> None:
    validate_unsigned_int(field_name, value, UINT64_MAX, 64)


def validate_non_negative_int(field_name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def validate_unsigned_int(
    field_name: str,
    value: int,
    max_value: int,
    bits: int,
) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0 or value > max_value:
        raise ValueError(f"{field_name} must fit in unsigned {bits} bits")
