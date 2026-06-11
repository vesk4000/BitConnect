"""Trust boundary codec: convert between Block objects and wire-payload fields.

This module is the single re-verification point for peer-supplied block data
before it reaches BlockchainState.  Every field is validated structurally
(lengths, ranges) and cryptographically (block_hash and txs_hash are
recomputed and compared against the transmitted values) so that no
adversarial payload can inject a bad block through a type-confusion or
hash-mismatch bug.
"""

from __future__ import annotations

from .block import (
    HASH_SIZE,
    Block,
    block_hash as compute_block_hash,
    txs_hash as compute_txs_hash,
)


def split_tx_hashes(blob: bytes) -> tuple[bytes, ...]:
    """Split a concatenated blob of 32-byte hashes into a tuple.

    Args:
        blob: raw bytes, length must be a multiple of HASH_SIZE (32).

    Returns:
        A tuple of 32-byte hash chunks, or ``()`` for an empty blob.

    Raises:
        ValueError: if ``len(blob) % 32 != 0``.
    """
    if blob == b"":
        return ()
    if len(blob) % HASH_SIZE != 0:
        raise ValueError(
            f"tx_hashes blob length {len(blob)} is not a multiple of {HASH_SIZE}"
        )
    return tuple(blob[i : i + HASH_SIZE] for i in range(0, len(blob), HASH_SIZE))


def join_tx_hashes(tx_hashes: tuple[bytes, ...]) -> bytes:
    """Concatenate a tuple of 32-byte hashes into a single blob.

    This is the inverse of :func:`split_tx_hashes` for valid input.
    """
    return b"".join(tx_hashes)


def block_to_response_fields(block: Block) -> dict:
    """Serialise a Block to a dict matching BlockResponsePayload field names.

    All derived fields (``txs_hash``, ``block_hash``, and the flat
    ``tx_hashes`` blob) are computed fresh from the block, so the returned
    dict is always internally consistent.
    """
    return {
        "height": block.height,
        "prev_hash": block.prev_hash,
        "txs_hash": compute_txs_hash(block.tx_hashes),
        "timestamp": block.timestamp,
        "difficulty": block.difficulty,
        "nonce": block.nonce,
        "block_hash": compute_block_hash(block),
        "tx_hashes": join_tx_hashes(block.tx_hashes),
    }


def block_from_response_fields(
    *,
    height: int,
    prev_hash: bytes,
    txs_hash: bytes,
    timestamp: int,
    difficulty: int,
    nonce: int,
    block_hash: bytes,
    tx_hashes: bytes,
) -> Block | None:
    """Reconstruct and cryptographically verify a Block from payload fields.

    Both the ``block_hash`` and ``txs_hash`` fields transmitted by the peer
    are re-derived from the raw data and compared; any mismatch returns None.
    This prevents forged hashes from bypassing BlockchainState validation.

    Args:
        height: block height integer.
        prev_hash: 32-byte previous block hash.
        txs_hash: 32-byte commitment to all transactions (peer-supplied).
        timestamp: uint64 timestamp.
        difficulty: uint32 proof-of-work difficulty.
        nonce: uint64 mining nonce.
        block_hash: 32-byte block hash (peer-supplied, will be verified).
        tx_hashes: concatenated 32-byte transaction hashes blob.

    Returns:
        A validated :class:`Block`, or ``None`` on any structural or
        cryptographic failure.
    """
    # Alias the peer-supplied hash fields so names don't shadow the imported
    # functions after we reconstruct the block.
    supplied_block_hash: bytes = block_hash
    supplied_txs_hash: bytes = txs_hash

    try:
        tx_hashes_tuple = split_tx_hashes(tx_hashes)
        block = Block(
            height=height,
            prev_hash=prev_hash,
            tx_hashes=tx_hashes_tuple,
            timestamp=timestamp,
            difficulty=difficulty,
            nonce=nonce,
        )
    except (ValueError, TypeError):
        # Bad lengths, out-of-range ints, or non-tuple tx_hashes all land here.
        return None

    # Re-derive both hashes and compare against the peer-supplied values.
    # A mismatch means either corruption or a deliberate forgery attempt.
    if compute_block_hash(block) != supplied_block_hash:
        return None
    if compute_txs_hash(tx_hashes_tuple) != supplied_txs_hash:
        return None

    return block
