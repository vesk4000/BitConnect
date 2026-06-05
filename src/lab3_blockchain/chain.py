"""Consensus state for the Lab 3 blockchain."""

from __future__ import annotations

from dataclasses import dataclass

from .transaction import (
    Transaction,
    transaction_hash,
    verify_transaction_signature,
)
from .block import Block, block_hash, has_valid_pow, validate_tx_hashes
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

BLOCK_VALID = "valid"
BLOCK_DUPLICATE = "duplicate"
BLOCK_BAD_POW = "bad_pow"
BLOCK_UNKNOWN_PARENT = "unknown_parent"
BLOCK_BAD_HEIGHT = "bad_height"


@dataclass(frozen=True)
class BlockValidationResult:
    valid: bool
    block_hash: bytes
    reason: str
    message: str


@dataclass(frozen=True)
class AddBlockResult:
    accepted: bool
    block_hash: bytes
    reason: str
    message: str
    new_tip: bool


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

    def validate_block(self, block: Block) -> BlockValidationResult:
        validate_tx_hashes(block.tx_hashes)
        candidate_hash = block_hash(block)

        if candidate_hash in self.blocks_by_hash:
            return BlockValidationResult(
                valid=False,
                block_hash=candidate_hash,
                reason=BLOCK_DUPLICATE,
                message="block is already stored",
            )

        if not has_valid_pow(block):
            return BlockValidationResult(
                valid=False,
                block_hash=candidate_hash,
                reason=BLOCK_BAD_POW,
                message="block hash does not satisfy declared difficulty",
            )

        parent = self.blocks_by_hash.get(block.prev_hash)
        if parent is None:
            return BlockValidationResult(
                valid=False,
                block_hash=candidate_hash,
                reason=BLOCK_UNKNOWN_PARENT,
                message="block parent is unknown",
            )

        expected_height = parent.height + 1
        if block.height != expected_height:
            return BlockValidationResult(
                valid=False,
                block_hash=candidate_hash,
                reason=BLOCK_BAD_HEIGHT,
                message=f"block height must be {expected_height}",
            )

        return BlockValidationResult(
            valid=True,
            block_hash=candidate_hash,
            reason=BLOCK_VALID,
            message="block is valid",
        )

    def add_block(self, block: Block) -> AddBlockResult:
        validation = self.validate_block(block)
        if not validation.valid:
            return AddBlockResult(
                accepted=False,
                block_hash=validation.block_hash,
                reason=validation.reason,
                message=validation.message,
                new_tip=False,
            )

        self.blocks_by_hash[validation.block_hash] = block
        self.children_by_hash.setdefault(block.prev_hash, set()).add(
            validation.block_hash
        )
        self.children_by_hash.setdefault(validation.block_hash, set())

        new_tip = block.height > self.height()
        if new_tip:
            self._tip_hash = validation.block_hash
            self._rebuild_main_chain_index()
            self._remove_mempool_transactions(block.tx_hashes)

        return AddBlockResult(
            accepted=True,
            block_hash=validation.block_hash,
            reason=BLOCK_VALID,
            message="block accepted",
            new_tip=new_tip,
        )

    def _rebuild_main_chain_index(self) -> None:
        main_chain: dict[int, bytes] = {}
        cursor_hash = self._tip_hash
        while True:
            cursor_block = self.blocks_by_hash[cursor_hash]
            main_chain[cursor_block.height] = cursor_hash
            if cursor_block.height == 0:
                break
            cursor_hash = cursor_block.prev_hash
        self.hash_by_height = main_chain

    def _remove_mempool_transactions(self, tx_hashes: tuple[bytes, ...]) -> None:
        for tx_hash in tx_hashes:
            self.mempool.pop(tx_hash, None)
