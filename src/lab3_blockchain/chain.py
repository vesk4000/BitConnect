"""Consensus state for the Lab 3 blockchain."""

from __future__ import annotations

from .block import Block, block_hash

ZERO_HASH = b"\x00" * 32

GENESIS_BLOCK = Block(
    height=0,
    prev_hash=ZERO_HASH,
    tx_hashes=(),
    timestamp=0,
    difficulty=0,
    nonce=0,
)
GENESIS_HASH = block_hash(GENESIS_BLOCK)
