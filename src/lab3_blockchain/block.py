"""Block primitives for the Lab 3 blockchain."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from hashlib import sha256

from .validation import (
    UINT32_MAX,
    UINT64_MAX,
    validate_bytes,
    validate_uint32,
    validate_uint64,
)

HASH_SIZE = 32
HEADER_SIZE = 84
HEADER_FORMAT = ">32s32sQIQ"


@dataclass(frozen=True)
class Block:
    """A Lab 3 block without a stored hash field."""

    height: int
    prev_hash: bytes
    tx_hashes: tuple[bytes, ...]
    timestamp: int
    difficulty: int
    nonce: int

    def __post_init__(self) -> None:
        validate_height(self.height)
        validate_hash_bytes("prev_hash", self.prev_hash)
        if not isinstance(self.tx_hashes, tuple):
            raise TypeError("tx_hashes must be a tuple")
        validate_tx_hashes(self.tx_hashes)
        validate_uint64("timestamp", self.timestamp)
        validate_uint32("difficulty", self.difficulty)
        validate_uint64("nonce", self.nonce)


def txs_hash(tx_hashes: tuple[bytes, ...]) -> bytes:
    """Compute SHA256(tx_hash_1 || ... || tx_hash_n)."""

    validate_tx_hashes(tx_hashes)
    return sha256(b"".join(tx_hashes)).digest()


def pack_header(
    prev_hash: bytes,
    txs_hash_value: bytes,
    timestamp: int,
    difficulty: int,
    nonce: int,
) -> bytes:
    """Pack the exact 84-byte Lab 3 block header."""

    validate_hash_bytes("prev_hash", prev_hash)
    validate_hash_bytes("txs_hash", txs_hash_value)
    validate_uint64("timestamp", timestamp)
    validate_uint32("difficulty", difficulty)
    validate_uint64("nonce", nonce)

    header = struct.pack(
        HEADER_FORMAT,
        prev_hash,
        txs_hash_value,
        timestamp,
        difficulty,
        nonce,
    )
    if len(header) != HEADER_SIZE:
        raise AssertionError(f"Lab 3 header must be {HEADER_SIZE} bytes")
    return header


def block_header(block: Block) -> bytes:
    """Return the exact header bytes used for this block's hash."""

    return pack_header(
        block.prev_hash,
        txs_hash(block.tx_hashes),
        block.timestamp,
        block.difficulty,
        block.nonce,
    )


def block_hash(block: Block) -> bytes:
    """Compute SHA256 over the block's 84-byte header."""

    return sha256(block_header(block)).digest()


def leading_zero_bits(digest: bytes) -> int:
    """Count leading zero bits in a byte string."""

    validate_bytes("digest", digest)
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        return bits + (8 - byte.bit_length())
    return bits


def has_valid_pow(block: Block) -> bool:
    """Return True when the block hash satisfies its declared difficulty."""

    return leading_zero_bits(block_hash(block)) >= block.difficulty


def mine_block_candidate(
    *,
    height: int,
    prev_hash: bytes,
    tx_hashes: tuple[bytes, ...],
    timestamp: int,
    difficulty: int,
    start_nonce: int = 0,
    max_nonce: int = UINT64_MAX,
) -> Block:
    """Search nonce range for a block satisfying the declared difficulty."""

    validate_height(height)
    validate_hash_bytes("prev_hash", prev_hash)
    validate_tx_hashes(tx_hashes)
    validate_uint64("timestamp", timestamp)
    validate_uint32("difficulty", difficulty)
    validate_uint64("start_nonce", start_nonce)
    validate_uint64("max_nonce", max_nonce)
    if start_nonce > max_nonce:
        raise ValueError("start_nonce must be <= max_nonce")

    body_hash = txs_hash(tx_hashes)
    for nonce in range(start_nonce, max_nonce + 1):
        digest = sha256(
            pack_header(prev_hash, body_hash, timestamp, difficulty, nonce)
        ).digest()
        if leading_zero_bits(digest) >= difficulty:
            return Block(
                height=height,
                prev_hash=prev_hash,
                tx_hashes=tx_hashes,
                timestamp=timestamp,
                difficulty=difficulty,
                nonce=nonce,
            )

    raise RuntimeError("No valid nonce found in provided search range")


def validate_height(height: int) -> None:
    if not isinstance(height, int) or isinstance(height, bool):
        raise TypeError("height must be an integer")
    if height < 0:
        raise ValueError("height must be non-negative")


def validate_tx_hashes(tx_hashes: tuple[bytes, ...]) -> None:
    if not isinstance(tx_hashes, tuple):
        raise TypeError("tx_hashes must be a tuple")
    for index, tx_hash in enumerate(tx_hashes):
        validate_hash_bytes(f"tx_hashes[{index}]", tx_hash)


def validate_hash_bytes(field_name: str, value: bytes) -> None:
    validate_bytes(field_name, value)
    if len(value) != HASH_SIZE:
        raise ValueError(f"{field_name} must be {HASH_SIZE} bytes")
