from hashlib import sha256
import struct

import pytest

from lab3_blockchain import block
from lab3_blockchain.block import (
    HASH_SIZE,
    HEADER_SIZE,
    UINT32_MAX,
    UINT64_MAX,
    Block,
    block_hash,
    block_header,
    has_valid_pow,
    leading_zero_bits,
    mine_block_candidate,
    pack_header,
    txs_hash,
)


def test_lab3_block_module_imports():
    assert block is not None


def test_empty_txs_hash_is_sha256_empty_bytes():
    assert txs_hash(()) == sha256(b"").digest()
    assert txs_hash(()) != b"\x00" * HASH_SIZE


def test_txs_hash_concatenates_transaction_hashes_in_order():
    tx_a = b"a" * HASH_SIZE
    tx_b = b"b" * HASH_SIZE

    assert txs_hash((tx_a, tx_b)) == sha256(tx_a + tx_b).digest()
    assert txs_hash((tx_b, tx_a)) == sha256(tx_b + tx_a).digest()


def test_pack_header_matches_exact_lab3_struct_layout():
    prev_hash = b"p" * HASH_SIZE
    body_hash = b"t" * HASH_SIZE
    timestamp = 0x0102030405060708
    difficulty = 0x0A0B0C0D
    nonce = 0x1112131415161718

    header = pack_header(prev_hash, body_hash, timestamp, difficulty, nonce)

    assert len(header) == HEADER_SIZE
    assert header == struct.pack(
        ">32s32sQIQ",
        prev_hash,
        body_hash,
        timestamp,
        difficulty,
        nonce,
    )
    assert header[0:32] == prev_hash
    assert header[32:64] == body_hash
    assert header[64:72] == bytes.fromhex("0102030405060708")
    assert header[72:76] == bytes.fromhex("0a0b0c0d")
    assert header[76:84] == bytes.fromhex("1112131415161718")


def test_block_header_uses_body_commitment_from_tx_hashes():
    tx_a = b"a" * HASH_SIZE
    tx_b = b"b" * HASH_SIZE
    block_obj = Block(
        height=1,
        prev_hash=b"p" * HASH_SIZE,
        tx_hashes=(tx_a, tx_b),
        timestamp=42,
        difficulty=7,
        nonce=99,
    )

    assert block_header(block_obj) == pack_header(
        b"p" * HASH_SIZE,
        sha256(tx_a + tx_b).digest(),
        42,
        7,
        99,
    )


def test_block_hash_is_sha256_of_packed_header():
    block_obj = Block(
        height=1,
        prev_hash=b"p" * HASH_SIZE,
        tx_hashes=(b"a" * HASH_SIZE,),
        timestamp=42,
        difficulty=1,
        nonce=123,
    )

    assert block_hash(block_obj) == sha256(block_header(block_obj)).digest()


def test_leading_zero_bits_counts_correctly():
    assert leading_zero_bits(bytes.fromhex("0000000f")) == 28
    assert leading_zero_bits(bytes.fromhex("00000010")) == 27
    assert leading_zero_bits(bytes.fromhex("00ff")) == 8
    assert leading_zero_bits(b"") == 0


def test_difficulty_zero_always_satisfies_pow():
    block_obj = Block(
        height=1,
        prev_hash=b"p" * HASH_SIZE,
        tx_hashes=(),
        timestamp=42,
        difficulty=0,
        nonce=0,
    )

    assert has_valid_pow(block_obj)


def test_has_valid_pow_recomputes_block_hash_against_declared_difficulty():
    mined = mine_block_candidate(
        height=1,
        prev_hash=b"p" * HASH_SIZE,
        tx_hashes=(),
        timestamp=42,
        difficulty=8,
        max_nonce=10_000,
    )
    mined_bits = leading_zero_bits(block_hash(mined))
    too_difficult = Block(
        height=mined.height,
        prev_hash=mined.prev_hash,
        tx_hashes=mined.tx_hashes,
        timestamp=mined.timestamp,
        difficulty=mined_bits + 1,
        nonce=mined.nonce,
    )

    assert mined_bits >= 8
    assert has_valid_pow(mined)
    assert not has_valid_pow(too_difficult)


def test_bad_nonce_fails_when_hash_is_recomputed():
    for nonce in range(100):
        block_obj = Block(
            height=1,
            prev_hash=b"p" * HASH_SIZE,
            tx_hashes=(),
            timestamp=42,
            difficulty=8,
            nonce=nonce,
        )
        if not has_valid_pow(block_obj):
            return

    pytest.fail("expected at least one invalid nonce in first 100 candidates")


def test_mine_block_candidate_returns_valid_block():
    mined = mine_block_candidate(
        height=1,
        prev_hash=b"p" * HASH_SIZE,
        tx_hashes=(b"a" * HASH_SIZE,),
        timestamp=42,
        difficulty=4,
        max_nonce=1_000,
    )

    assert mined.height == 1
    assert mined.prev_hash == b"p" * HASH_SIZE
    assert mined.tx_hashes == (b"a" * HASH_SIZE,)
    assert mined.timestamp == 42
    assert mined.difficulty == 4
    assert has_valid_pow(mined)


def test_mine_block_candidate_rejects_exhausted_nonce_range():
    with pytest.raises(RuntimeError):
        mine_block_candidate(
            height=1,
            prev_hash=b"p" * HASH_SIZE,
            tx_hashes=(),
            timestamp=42,
            difficulty=256,
            max_nonce=3,
        )


def test_mine_block_candidate_rejects_reversed_nonce_range():
    with pytest.raises(ValueError, match="start_nonce"):
        mine_block_candidate(
            height=1,
            prev_hash=b"p" * HASH_SIZE,
            tx_hashes=(),
            timestamp=42,
            difficulty=0,
            start_nonce=2,
            max_nonce=1,
        )


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("prev_hash", b"short"),
        ("tx_hashes", (b"short",)),
        ("timestamp", -1),
        ("timestamp", UINT64_MAX + 1),
        ("difficulty", -1),
        ("difficulty", UINT32_MAX + 1),
        ("nonce", -1),
        ("nonce", UINT64_MAX + 1),
        ("height", -1),
    ],
)
def test_block_rejects_invalid_fields(field_name, value):
    kwargs = {
        "height": 1,
        "prev_hash": b"p" * HASH_SIZE,
        "tx_hashes": (b"a" * HASH_SIZE,),
        "timestamp": 42,
        "difficulty": 1,
        "nonce": 123,
    }
    kwargs[field_name] = value

    with pytest.raises((TypeError, ValueError)):
        Block(**kwargs)


def test_block_rejects_non_tuple_tx_hashes():
    with pytest.raises(TypeError, match="tx_hashes"):
        Block(
            height=1,
            prev_hash=b"p" * HASH_SIZE,
            tx_hashes=[b"a" * HASH_SIZE],  # type: ignore[arg-type]
            timestamp=42,
            difficulty=1,
            nonce=123,
        )
