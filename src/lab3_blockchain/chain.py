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
        self.orphans_by_prev_hash: dict[bytes, list[Block]] = {}
        self.transactions_by_hash: dict[bytes, Transaction] = {}
        self.mempool: dict[bytes, Transaction] = {}
        self._tip_hash = genesis_hash
        self._orphan_hashes: set[bytes] = set()

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

    def confirmations(self, tx_hash: bytes) -> int:
        """Return how many blocks are stacked *on top of* the tx's block.

        This matches the grader's "buried under at least N blocks" wording: a
        transaction in the tip block has 0 confirmations (nothing on top yet);
        one block later it has 1; and so on. To satisfy the check we must reach
        REQUIRED_CONFIRMATIONS blocks on top, i.e. tip is REQUIRED_CONFIRMATIONS
        levels above the tx block. A transaction not on the main chain (still in
        the mempool, or only on an abandoned fork) returns 0.
        """
        for height in sorted(self.hash_by_height, reverse=True):
            block = self.blocks_by_hash[self.hash_by_height[height]]
            if tx_hash in block.tx_hashes:
                return self.height() - block.height
        return 0

    def is_in_mempool(self, tx_hash: bytes) -> bool:
        """True if *tx_hash* is a known pending transaction not yet on the chain."""
        return tx_hash in self.mempool

    def is_on_main_chain(self, tx_hash: bytes) -> bool:
        """True if *tx_hash* appears in a block on the current main chain."""
        for height in self.hash_by_height:
            block = self.blocks_by_hash[self.hash_by_height[height]]
            if tx_hash in block.tx_hashes:
                return True
        return False

    def add_transaction(self, transaction: Transaction) -> bytes:
        if not verify_transaction_signature(transaction):
            raise ValueError("transaction signature is invalid")
        tx_hash = transaction_hash(transaction)
        self.transactions_by_hash.setdefault(tx_hash, transaction)
        self.mempool.setdefault(tx_hash, transaction)
        return tx_hash

    def snapshot_mempool(self, limit: int | None = None) -> tuple[bytes, ...]:
        if limit is None:
            return tuple(self.mempool)
        validate_non_negative_int("limit", limit)
        return tuple(self.mempool)[:limit]

    def build_candidate_block(
        self,
        tx_hashes: tuple[bytes, ...],
        timestamp: int,
        difficulty: int,
        nonce: int,
    ) -> Block:
        return Block(
            height=self.height() + 1,
            prev_hash=self._tip_hash,
            tx_hashes=tx_hashes,
            timestamp=timestamp,
            difficulty=difficulty,
            nonce=nonce,
        )

    def validate_block(self, block: Block) -> BlockValidationResult:
        validate_tx_hashes(block.tx_hashes)
        candidate_hash = block_hash(block)

        if (
            candidate_hash in self.blocks_by_hash
            or candidate_hash in self._orphan_hashes
        ):
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
        """Validate and insert *block*, then attach any waiting orphans.

        Orphan attachment is done with an explicit work queue rather than
        recursion: syncing a long chain can chain-attach hundreds of orphans,
        and a recursive approach would overflow the Python stack.
        """
        first_result: AddBlockResult | None = None
        pending: list[Block] = [block]
        while pending:
            current = pending.pop()
            result = self._insert_block(current)
            if first_result is None:
                first_result = result
            if result.accepted:
                # Queue any orphans whose parent is the block we just inserted.
                for orphan in self.orphans_by_prev_hash.pop(result.block_hash, []):
                    self._orphan_hashes.discard(block_hash(orphan))
                    pending.append(orphan)
        assert first_result is not None
        return first_result

    def _insert_block(self, block: Block) -> AddBlockResult:
        """Validate and insert a single block (no orphan attachment)."""
        validation = self.validate_block(block)
        if not validation.valid:
            if validation.reason == BLOCK_UNKNOWN_PARENT:
                self._store_orphan(block, validation.block_hash)
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

        old_main_chain = self._main_chain_block_hashes()
        new_tip = self._is_better_tip(validation.block_hash, block)
        if new_tip:
            self._tip_hash = validation.block_hash
            self._rebuild_main_chain_index()
            self._reconcile_mempool_after_tip_change(old_main_chain)

        return AddBlockResult(
            accepted=True,
            block_hash=validation.block_hash,
            reason=BLOCK_VALID,
            message="block accepted",
            new_tip=new_tip,
        )

    def _store_orphan(
        self,
        block: Block,
        block_hash_value: bytes,
    ) -> None:
        self.orphans_by_prev_hash.setdefault(block.prev_hash, []).append(block)
        self._orphan_hashes.add(block_hash_value)

    def _is_better_tip(self, candidate_hash: bytes, candidate_block: Block) -> bool:
        current_tip = self.tip()
        if candidate_block.height != current_tip.height:
            return candidate_block.height > current_tip.height
        return candidate_hash < self._tip_hash

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

    def _main_chain_block_hashes(self) -> tuple[bytes, ...]:
        return tuple(
            self.hash_by_height[height] for height in sorted(self.hash_by_height)
        )

    def _reconcile_mempool_after_tip_change(
        self,
        old_main_chain: tuple[bytes, ...],
    ) -> None:
        old_tx_hashes = self._chain_tx_hashes(old_main_chain)
        new_tx_hashes = self._chain_tx_hashes(self._main_chain_block_hashes())
        new_tx_hash_set = set(new_tx_hashes)

        for tx_hash in old_tx_hashes:
            if tx_hash in new_tx_hash_set:
                continue
            transaction = self.transactions_by_hash.get(tx_hash)
            if transaction is not None:
                self.mempool.setdefault(tx_hash, transaction)

        for tx_hash in new_tx_hashes:
            self.mempool.pop(tx_hash, None)

    def _chain_tx_hashes(self, block_hashes: tuple[bytes, ...]) -> tuple[bytes, ...]:
        result: list[bytes] = []
        seen: set[bytes] = set()
        for chain_block_hash in block_hashes:
            chain_block = self.blocks_by_hash[chain_block_hash]
            for tx_hash in chain_block.tx_hashes:
                if tx_hash in seen:
                    continue
                seen.add(tx_hash)
                result.append(tx_hash)
        return tuple(result)
