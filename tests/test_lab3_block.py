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
