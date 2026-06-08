"""Tests for the Lab 3 blockchain codec trust-boundary module."""

from __future__ import annotations

import pytest

from lab3_blockchain.block import HASH_SIZE, block_hash, mine_block_candidate, txs_hash
from lab3_blockchain.codec import (
    block_from_response_fields,
    block_to_response_fields,
    join_tx_hashes,
    split_tx_hashes,
)

HASH_A = b"a" * HASH_SIZE
HASH_B = b"b" * HASH_SIZE
ZERO_HASH = b"\x00" * HASH_SIZE


# ---------------------------------------------------------------------------
# split_tx_hashes
# ---------------------------------------------------------------------------


def test_split_tx_hashes_empty_blob_returns_empty_tuple():
    assert split_tx_hashes(b"") == ()


def test_split_tx_hashes_one_hash():
    result = split_tx_hashes(HASH_A)
    assert result == (HASH_A,)


def test_split_tx_hashes_two_hashes():
    blob = HASH_A + HASH_B
    result = split_tx_hashes(blob)
    assert result == (HASH_A, HASH_B)


def test_split_tx_hashes_non_multiple_raises_value_error():
    with pytest.raises(ValueError):
        split_tx_hashes(b"\x00" * 31)


def test_split_tx_hashes_non_multiple_one_byte_raises():
    with pytest.raises(ValueError):
        split_tx_hashes(b"\x01")


def test_split_tx_hashes_non_multiple_33_bytes_raises():
    with pytest.raises(ValueError):
        split_tx_hashes(b"\x00" * 33)


# ---------------------------------------------------------------------------
# join_tx_hashes
# ---------------------------------------------------------------------------


def test_join_tx_hashes_empty_tuple_returns_empty_bytes():
    assert join_tx_hashes(()) == b""


def test_join_tx_hashes_two_hashes():
    assert join_tx_hashes((HASH_A, HASH_B)) == HASH_A + HASH_B


def test_join_is_inverse_of_split_for_single_hash():
    blob = HASH_A
    assert join_tx_hashes(split_tx_hashes(blob)) == blob


def test_join_is_inverse_of_split_for_two_hashes():
    blob = HASH_A + HASH_B
    assert join_tx_hashes(split_tx_hashes(blob)) == blob


def test_split_is_inverse_of_join_for_single_hash():
    tup = (HASH_A,)
    assert split_tx_hashes(join_tx_hashes(tup)) == tup


def test_split_is_inverse_of_join_for_two_hashes():
    tup = (HASH_A, HASH_B)
    assert split_tx_hashes(join_tx_hashes(tup)) == tup


# ---------------------------------------------------------------------------
# block_to_response_fields / block_from_response_fields round-trip
# ---------------------------------------------------------------------------


def _mine_test_block():
    """Mine a minimal block with difficulty=0 for deterministic testing."""
    return mine_block_candidate(
        height=1,
        prev_hash=ZERO_HASH,
        tx_hashes=(HASH_A, HASH_B),
        timestamp=100,
        difficulty=0,
        max_nonce=0,
    )


def test_block_to_response_fields_keys_match_payload_names():
    block = _mine_test_block()
    fields = block_to_response_fields(block)
    expected_keys = {
        "height",
        "prev_hash",
        "txs_hash",
        "timestamp",
        "difficulty",
        "nonce",
        "block_hash",
        "tx_hashes",
    }
    assert set(fields.keys()) == expected_keys


def test_block_to_response_fields_computes_correct_hashes():
    block = _mine_test_block()
    fields = block_to_response_fields(block)

    assert fields["block_hash"] == block_hash(block)
    assert fields["txs_hash"] == txs_hash(block.tx_hashes)
    assert fields["tx_hashes"] == join_tx_hashes(block.tx_hashes)


def test_block_round_trip_returns_equal_block():
    block = _mine_test_block()
    fields = block_to_response_fields(block)
    recovered = block_from_response_fields(**fields)

    assert recovered is not None
    assert recovered == block


def test_block_round_trip_recovered_has_matching_block_hash():
    block = _mine_test_block()
    fields = block_to_response_fields(block)
    recovered = block_from_response_fields(**fields)

    assert recovered is not None
    assert block_hash(recovered) == fields["block_hash"]


# ---------------------------------------------------------------------------
# block_from_response_fields tamper cases — all must return None
# ---------------------------------------------------------------------------


def test_block_from_response_fields_returns_none_for_corrupted_block_hash():
    block = _mine_test_block()
    fields = block_to_response_fields(block)
    # Flip one byte in the transmitted block_hash.
    bad_hash = bytes([fields["block_hash"][0] ^ 0xFF]) + fields["block_hash"][1:]
    fields["block_hash"] = bad_hash

    assert block_from_response_fields(**fields) is None


def test_block_from_response_fields_returns_none_for_corrupted_txs_hash():
    block = _mine_test_block()
    fields = block_to_response_fields(block)
    # Corrupt the txs_hash while keeping block_hash intact —
    # block_hash won't change (it does NOT cover txs_hash directly as a
    # field; however the codec must still verify the txs_hash field).
    bad_txs = bytes([fields["txs_hash"][0] ^ 0xFF]) + fields["txs_hash"][1:]
    fields["txs_hash"] = bad_txs

    assert block_from_response_fields(**fields) is None


def test_block_from_response_fields_returns_none_for_tx_hashes_wrong_length():
    block = _mine_test_block()
    fields = block_to_response_fields(block)
    # A blob that is not divisible by 32 cannot be split.
    fields["tx_hashes"] = b"\x00" * 31

    assert block_from_response_fields(**fields) is None


def test_block_from_response_fields_returns_none_for_tx_hashes_content_mismatch():
    """tx_hashes blob has a valid length but different content than txs_hash."""
    block = _mine_test_block()
    fields = block_to_response_fields(block)
    # Replace tx_hashes with a different valid-length blob; the recomputed
    # txs_hash will differ from the transmitted txs_hash field.
    fields["tx_hashes"] = b"\xff" * HASH_SIZE

    assert block_from_response_fields(**fields) is None


def test_block_from_response_fields_returns_none_for_out_of_range_height():
    block = _mine_test_block()
    fields = block_to_response_fields(block)
    fields["height"] = -1  # Block.__post_init__ rejects negative heights

    assert block_from_response_fields(**fields) is None


def test_block_from_response_fields_returns_none_for_wrong_prev_hash_length():
    block = _mine_test_block()
    fields = block_to_response_fields(block)
    fields["prev_hash"] = b"\x00" * 31  # too short

    assert block_from_response_fields(**fields) is None
