import pytest
from ipv8.keyvault.crypto import default_eccrypto

from lab1_pow_ipv8.libsodium_bootstrap import ensure_libsodium
from lab3_blockchain.block import Block, block_hash, mine_block_candidate, txs_hash
from lab3_blockchain import chain
from lab3_blockchain.chain import (
    BLOCK_BAD_HEIGHT,
    BLOCK_BAD_POW,
    BLOCK_DUPLICATE,
    BLOCK_UNKNOWN_PARENT,
    BLOCK_VALID,
    GENESIS_BLOCK,
    GENESIS_HASH,
    ZERO_HASH,
    BlockchainState,
)
from lab3_blockchain.transaction import (
    Transaction,
    transaction_hash,
    transaction_signature_message,
)


def test_lab3_chain_module_imports():
    assert chain is not None


def test_genesis_block_uses_shared_lab3_convention():
    assert GENESIS_BLOCK.height == 0
    assert GENESIS_BLOCK.prev_hash == ZERO_HASH
    assert GENESIS_BLOCK.tx_hashes == ()
    assert GENESIS_BLOCK.timestamp == 0
    assert GENESIS_BLOCK.difficulty == 0
    assert GENESIS_BLOCK.nonce == 0
    assert txs_hash(GENESIS_BLOCK.tx_hashes) == txs_hash(())


def test_genesis_hash_is_deterministic():
    assert GENESIS_HASH == block_hash(GENESIS_BLOCK)
    assert GENESIS_HASH == block_hash(
        type(GENESIS_BLOCK)(
            height=0,
            prev_hash=b"\x00" * 32,
            tx_hashes=(),
            timestamp=0,
            difficulty=0,
            nonce=0,
        )
    )


def test_new_chain_state_contains_only_genesis():
    state = BlockchainState()

    assert state.tip_hash == GENESIS_HASH
    assert state.height() == 0
    assert state.tip() == GENESIS_BLOCK
    assert state.get_block_by_height(0) == GENESIS_BLOCK
    assert state.get_block_by_height(1) is None
    assert state.get_block_by_hash(GENESIS_HASH) == GENESIS_BLOCK
    assert state.get_block_by_hash(b"x" * 32) is None
    assert state.blocks_by_hash == {GENESIS_HASH: GENESIS_BLOCK}
    assert state.hash_by_height == {0: GENESIS_HASH}
    assert state.children_by_hash == {GENESIS_HASH: set()}
    assert state.mempool == {}


def test_add_transaction_verifies_signature_and_returns_hash():
    state = BlockchainState()
    tx = _signed_transaction(b"payload", 42)

    tx_hash = state.add_transaction(tx)

    assert tx_hash == transaction_hash(tx)
    assert state.mempool == {tx_hash: tx}
    assert state.snapshot_mempool() == (tx_hash,)


def test_add_transaction_deduplicates_by_transaction_hash():
    state = BlockchainState()
    tx = _signed_transaction(b"payload", 42)

    first_hash = state.add_transaction(tx)
    second_hash = state.add_transaction(tx)

    assert first_hash == second_hash
    assert len(state.mempool) == 1
    assert state.snapshot_mempool() == (first_hash,)


def test_add_transaction_rejects_invalid_signature():
    state = BlockchainState()
    tx = _signed_transaction(b"payload", 42)
    tampered = Transaction(
        sender_key=tx.sender_key,
        data=b"tampered",
        timestamp=tx.timestamp,
        signature=tx.signature,
    )

    with pytest.raises(ValueError, match="signature"):
        state.add_transaction(tampered)
    assert state.mempool == {}


def test_snapshot_mempool_preserves_insertion_order_and_limit():
    state = BlockchainState()
    tx1 = _signed_transaction(b"payload-1", 42)
    tx2 = _signed_transaction(b"payload-2", 43)
    tx1_hash = state.add_transaction(tx1)
    tx2_hash = state.add_transaction(tx2)

    assert state.snapshot_mempool() == (tx1_hash, tx2_hash)
    assert state.snapshot_mempool(limit=1) == (tx1_hash,)
    assert state.snapshot_mempool(limit=0) == ()


@pytest.mark.parametrize("limit", [-1, True, "1"])
def test_snapshot_mempool_rejects_invalid_limit(limit):
    state = BlockchainState()

    with pytest.raises((TypeError, ValueError)):
        state.snapshot_mempool(limit=limit)


def test_validate_block_accepts_valid_child_of_genesis():
    state = BlockchainState()
    block = _child_block(prev_hash=GENESIS_HASH, height=1)

    result = state.validate_block(block)

    assert result.valid
    assert result.reason == BLOCK_VALID
    assert result.block_hash == block_hash(block)


def test_add_block_appends_valid_child_of_genesis():
    state = BlockchainState()
    block = _child_block(prev_hash=GENESIS_HASH, height=1)

    result = state.add_block(block)

    assert result.accepted
    assert result.reason == BLOCK_VALID
    assert result.new_tip
    assert result.block_hash == block_hash(block)
    assert state.tip_hash == block_hash(block)
    assert state.height() == 1
    assert state.tip() == block
    assert state.get_block_by_height(1) == block
    assert state.get_block_by_hash(block_hash(block)) == block
    assert state.children_by_hash[GENESIS_HASH] == {block_hash(block)}
    assert state.children_by_hash[block_hash(block)] == set()


def test_add_block_removes_included_transactions_from_mempool():
    state = BlockchainState()
    tx = _signed_transaction(b"payload", 42)
    tx_hash = state.add_transaction(tx)
    block = _child_block(prev_hash=GENESIS_HASH, height=1, tx_hashes=(tx_hash,))

    state.add_block(block)

    assert state.mempool == {}


def test_add_block_rejects_duplicate_block():
    state = BlockchainState()
    block = _child_block(prev_hash=GENESIS_HASH, height=1)
    state.add_block(block)

    result = state.add_block(block)

    assert not result.accepted
    assert result.reason == BLOCK_DUPLICATE
    assert result.block_hash == block_hash(block)
    assert not result.new_tip


def test_add_block_rejects_unknown_parent():
    state = BlockchainState()
    block = _child_block(prev_hash=b"x" * 32, height=1)

    result = state.add_block(block)

    assert not result.accepted
    assert result.reason == BLOCK_UNKNOWN_PARENT
    assert state.height() == 0


def test_add_block_rejects_wrong_height():
    state = BlockchainState()
    block = _child_block(prev_hash=GENESIS_HASH, height=2)

    result = state.add_block(block)

    assert not result.accepted
    assert result.reason == BLOCK_BAD_HEIGHT
    assert state.height() == 0


def test_add_block_rejects_bad_pow():
    state = BlockchainState()
    block = Block(
        height=1,
        prev_hash=GENESIS_HASH,
        tx_hashes=(),
        timestamp=42,
        difficulty=257,
        nonce=0,
    )

    result = state.add_block(block)

    assert not result.accepted
    assert result.reason == BLOCK_BAD_POW
    assert state.height() == 0


def test_block_rejects_bad_transaction_hash_length_before_add():
    with pytest.raises(ValueError, match="tx_hashes"):
        Block(
            height=1,
            prev_hash=GENESIS_HASH,
            tx_hashes=(b"short",),
            timestamp=42,
            difficulty=0,
            nonce=0,
        )


def _signed_transaction(data: bytes, timestamp: int) -> Transaction:
    ensure_libsodium()
    private_key = default_eccrypto.generate_key("curve25519")
    public_key = private_key.pub().key_to_bin()
    unsigned = Transaction(
        sender_key=public_key,
        data=data,
        timestamp=timestamp,
        signature=b"",
    )
    signature = default_eccrypto.create_signature(
        private_key,
        transaction_signature_message(unsigned),
    )
    return Transaction(
        sender_key=public_key,
        data=data,
        timestamp=timestamp,
        signature=signature,
    )


def _child_block(
    *,
    prev_hash: bytes,
    height: int,
    tx_hashes: tuple[bytes, ...] = (),
) -> Block:
    return mine_block_candidate(
        height=height,
        prev_hash=prev_hash,
        tx_hashes=tx_hashes,
        timestamp=42 + height,
        difficulty=0,
        max_nonce=0,
    )
