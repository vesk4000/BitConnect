"""Tests for Lab 3 blockchain wire protocol payloads and message-id constants."""

from __future__ import annotations

import pytest
from ipv8.messaging.serialization import default_serializer

from lab3_blockchain.ids import (
    BLOCK_RESPONSE,
    CHAIN_HEIGHT_RESPONSE,
    GET_BLOCK,
    GET_CHAIN_HEIGHT,
    PEER_BLOCK,
    PEER_BLOCK_REQUEST,
    PEER_BLOCK_RESPONSE,
    PEER_MESSAGE_IDS,
    PEER_STATUS_REQUEST,
    PEER_STATUS_RESPONSE,
    PEER_TX,
    REGISTER_BLOCKCHAIN,
    REGISTER_RESPONSE,
    SERVER_MESSAGE_IDS,
    SUBMIT_TX,
    SUBMIT_TX_RESPONSE,
)
from lab3_blockchain.protocol import (
    BlockResponsePayload,
    ChainHeightResponsePayload,
    GetBlockPayload,
    GetChainHeightPayload,
    PeerBlockPayload,
    PeerBlockRequestPayload,
    PeerBlockResponsePayload,
    PeerStatusRequestPayload,
    PeerStatusResponsePayload,
    PeerTransactionPayload,
    RegisterBlockchainPayload,
    RegisterResponsePayload,
    SubmitTransactionPayload,
    SubmitTransactionResponsePayload,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ZERO_HASH = b"\x00" * 32
HASH_A = b"a" * 32
HASH_B = b"b" * 32


def round_trip(payload_class, payload):
    """Serialize then deserialize a payload and return the unpacked instance."""
    packed = default_serializer.pack_serializable(payload)
    obj, _ = default_serializer.unpack_serializable(payload_class, packed)
    return obj


# ---------------------------------------------------------------------------
# Registration community
# ---------------------------------------------------------------------------


def test_register_blockchain_payload_msg_id():
    assert RegisterBlockchainPayload.msg_id == REGISTER_BLOCKCHAIN == 1


def test_register_blockchain_payload_round_trip():
    payload = RegisterBlockchainPayload(
        group_id="group42", community_id=b"\xde\xad\xbe\xef"
    )
    obj = round_trip(RegisterBlockchainPayload, payload)
    assert obj.group_id == "group42"
    assert obj.community_id == b"\xde\xad\xbe\xef"


def test_register_response_payload_msg_id():
    assert RegisterResponsePayload.msg_id == REGISTER_RESPONSE == 2


def test_register_response_payload_round_trip_success():
    payload = RegisterResponsePayload(success=True, message="OK")
    obj = round_trip(RegisterResponsePayload, payload)
    assert obj.success is True
    assert obj.message == "OK"


def test_register_response_payload_round_trip_failure():
    payload = RegisterResponsePayload(success=False, message="already registered")
    obj = round_trip(RegisterResponsePayload, payload)
    assert obj.success is False
    assert obj.message == "already registered"


# ---------------------------------------------------------------------------
# Server (blockchain community) payloads
# ---------------------------------------------------------------------------


def test_submit_transaction_payload_msg_id():
    assert SubmitTransactionPayload.msg_id == SUBMIT_TX == 1


def test_submit_transaction_payload_round_trip():
    payload = SubmitTransactionPayload(
        sender_key=b"\x01" * 74,
        data=b"hello world",
        timestamp=1_700_000_000,
        signature=b"\x02" * 64,
    )
    obj = round_trip(SubmitTransactionPayload, payload)
    assert obj.sender_key == b"\x01" * 74
    assert obj.data == b"hello world"
    assert obj.timestamp == 1_700_000_000
    assert obj.signature == b"\x02" * 64


def test_submit_transaction_response_payload_msg_id():
    assert SubmitTransactionResponsePayload.msg_id == SUBMIT_TX_RESPONSE == 2


def test_submit_transaction_response_payload_round_trip():
    payload = SubmitTransactionResponsePayload(
        success=True,
        tx_hash=HASH_A,
        message="accepted",
    )
    obj = round_trip(SubmitTransactionResponsePayload, payload)
    assert obj.success is True
    assert obj.tx_hash == HASH_A
    assert obj.message == "accepted"


def test_get_chain_height_payload_msg_id():
    assert GetChainHeightPayload.msg_id == GET_CHAIN_HEIGHT == 3


def test_get_chain_height_payload_round_trip():
    payload = GetChainHeightPayload(request_id=42)
    obj = round_trip(GetChainHeightPayload, payload)
    assert obj.request_id == 42


def test_chain_height_response_payload_msg_id():
    assert ChainHeightResponsePayload.msg_id == CHAIN_HEIGHT_RESPONSE == 4


def test_chain_height_response_payload_round_trip():
    payload = ChainHeightResponsePayload(request_id=7, height=100, tip_hash=ZERO_HASH)
    obj = round_trip(ChainHeightResponsePayload, payload)
    assert obj.request_id == 7
    assert obj.height == 100
    assert obj.tip_hash == ZERO_HASH


def test_get_block_payload_msg_id():
    assert GetBlockPayload.msg_id == GET_BLOCK == 5


def test_get_block_payload_round_trip():
    payload = GetBlockPayload(height=55)
    obj = round_trip(GetBlockPayload, payload)
    assert obj.height == 55


def test_block_response_payload_msg_id():
    assert BlockResponsePayload.msg_id == BLOCK_RESPONSE == 6


def test_block_response_payload_round_trip_empty_tx_hashes():
    """A block with no transactions should encode tx_hashes as b''."""
    payload = BlockResponsePayload(
        height=1,
        prev_hash=ZERO_HASH,
        txs_hash=HASH_A,
        timestamp=1_000,
        difficulty=4,
        nonce=999,
        block_hash=HASH_B,
        tx_hashes=b"",
    )
    obj = round_trip(BlockResponsePayload, payload)
    assert obj.height == 1
    assert obj.prev_hash == ZERO_HASH
    assert obj.txs_hash == HASH_A
    assert obj.timestamp == 1_000
    assert obj.difficulty == 4
    assert obj.nonce == 999
    assert obj.block_hash == HASH_B
    assert obj.tx_hashes == b""


def test_block_response_payload_round_trip_two_tx_hashes():
    """Two concatenated 32-byte hashes should survive the round-trip intact."""
    two_hashes = HASH_A + HASH_B
    payload = BlockResponsePayload(
        height=2,
        prev_hash=HASH_A,
        txs_hash=HASH_B,
        timestamp=2_000,
        difficulty=0,
        nonce=0,
        block_hash=ZERO_HASH,
        tx_hashes=two_hashes,
    )
    obj = round_trip(BlockResponsePayload, payload)
    assert obj.tx_hashes == two_hashes


# ---------------------------------------------------------------------------
# Peer gossip payloads
# ---------------------------------------------------------------------------


def test_peer_transaction_payload_msg_id():
    assert PeerTransactionPayload.msg_id == PEER_TX == 200


def test_peer_transaction_payload_round_trip():
    payload = PeerTransactionPayload(
        sender_key=b"\xaa" * 74,
        data=b"peer data",
        timestamp=9_999,
        signature=b"\xbb" * 64,
    )
    obj = round_trip(PeerTransactionPayload, payload)
    assert obj.sender_key == b"\xaa" * 74
    assert obj.data == b"peer data"
    assert obj.timestamp == 9_999
    assert obj.signature == b"\xbb" * 64


def test_peer_block_payload_msg_id():
    assert PeerBlockPayload.msg_id == PEER_BLOCK == 201


def test_peer_block_payload_round_trip():
    payload = PeerBlockPayload(
        height=10,
        prev_hash=HASH_A,
        txs_hash=HASH_B,
        timestamp=5_000,
        difficulty=2,
        nonce=77,
        block_hash=ZERO_HASH,
        tx_hashes=b"",
    )
    obj = round_trip(PeerBlockPayload, payload)
    assert obj.height == 10
    assert obj.prev_hash == HASH_A
    assert obj.txs_hash == HASH_B
    assert obj.timestamp == 5_000
    assert obj.difficulty == 2
    assert obj.nonce == 77
    assert obj.block_hash == ZERO_HASH
    assert obj.tx_hashes == b""


def test_peer_status_request_payload_msg_id():
    assert PeerStatusRequestPayload.msg_id == PEER_STATUS_REQUEST == 202


def test_peer_status_request_payload_round_trip():
    payload = PeerStatusRequestPayload(request_id=123)
    obj = round_trip(PeerStatusRequestPayload, payload)
    assert obj.request_id == 123


def test_peer_status_response_payload_msg_id():
    assert PeerStatusResponsePayload.msg_id == PEER_STATUS_RESPONSE == 203


def test_peer_status_response_payload_round_trip():
    payload = PeerStatusResponsePayload(request_id=1, height=50, tip_hash=HASH_A)
    obj = round_trip(PeerStatusResponsePayload, payload)
    assert obj.request_id == 1
    assert obj.height == 50
    assert obj.tip_hash == HASH_A


def test_peer_block_request_payload_msg_id():
    assert PeerBlockRequestPayload.msg_id == PEER_BLOCK_REQUEST == 204


def test_peer_block_request_payload_round_trip():
    payload = PeerBlockRequestPayload(height=33)
    obj = round_trip(PeerBlockRequestPayload, payload)
    assert obj.height == 33


def test_peer_block_response_payload_msg_id():
    assert PeerBlockResponsePayload.msg_id == PEER_BLOCK_RESPONSE == 205


def test_peer_block_response_payload_round_trip():
    two_hashes = HASH_A + HASH_B
    payload = PeerBlockResponsePayload(
        height=5,
        prev_hash=ZERO_HASH,
        txs_hash=HASH_A,
        timestamp=3_000,
        difficulty=1,
        nonce=42,
        block_hash=HASH_B,
        tx_hashes=two_hashes,
    )
    obj = round_trip(PeerBlockResponsePayload, payload)
    assert obj.height == 5
    assert obj.tx_hashes == two_hashes


# ---------------------------------------------------------------------------
# ID set invariants
# ---------------------------------------------------------------------------


def test_server_message_ids_are_one_through_six():
    assert SERVER_MESSAGE_IDS == frozenset({1, 2, 3, 4, 5, 6})
    assert all(1 <= i <= 6 for i in SERVER_MESSAGE_IDS)


def test_peer_message_ids_are_all_at_least_200():
    assert all(i >= 200 for i in PEER_MESSAGE_IDS)


def test_server_and_peer_message_ids_are_disjoint():
    assert SERVER_MESSAGE_IDS.isdisjoint(PEER_MESSAGE_IDS)
