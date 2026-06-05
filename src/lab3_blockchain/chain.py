"""Consensus state for the Lab 3 blockchain."""

from __future__ import annotations

from .transaction import (
    Transaction,
    transaction_hash,
    verify_transaction_signature,
)
from .block import Block, block_hash
from .validation import validate_non_negative_int

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


class BlockchainState:
    """Mutable local blockchain state rooted at the deterministic genesis block."""

    def __init__(self, genesis_block: Block = GENESIS_BLOCK) -> None:
        genesis_hash = block_hash(genesis_block)
        self.blocks_by_hash: dict[bytes, Block] = {genesis_hash: genesis_block}
        self.hash_by_height: dict[int, bytes] = {genesis_block.height: genesis_hash}
        self.children_by_hash: dict[bytes, set[bytes]] = {genesis_hash: set()}
        self.mempool: dict[bytes, Transaction] = {}
        self._tip_hash = genesis_hash

    @property
    def tip_hash(self) -> bytes:
        return self._tip_hash

    def height(self) -> int:
        return self.tip().height

    def tip(self) -> Block:
        return self.blocks_by_hash[self._tip_hash]

    def get_block_by_height(self, height: int) -> Block | None:
        block_hash_at_height = self.hash_by_height.get(height)
        if block_hash_at_height is None:
            return None
        return self.blocks_by_hash[block_hash_at_height]

    def get_block_by_hash(self, hash_: bytes) -> Block | None:
        return self.blocks_by_hash.get(hash_)

    def add_transaction(self, transaction: Transaction) -> bytes:
        if not verify_transaction_signature(transaction):
            raise ValueError("transaction signature is invalid")
        tx_hash = transaction_hash(transaction)
        self.mempool.setdefault(tx_hash, transaction)
        return tx_hash

    def snapshot_mempool(self, limit: int | None = None) -> tuple[bytes, ...]:
        if limit is None:
            return tuple(self.mempool)
        validate_non_negative_int("limit", limit)
        return tuple(self.mempool)[:limit]
