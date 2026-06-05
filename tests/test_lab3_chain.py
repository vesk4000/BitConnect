from lab3_blockchain.block import block_hash, txs_hash
from lab3_blockchain import chain
from lab3_blockchain.chain import GENESIS_BLOCK, GENESIS_HASH, ZERO_HASH


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
