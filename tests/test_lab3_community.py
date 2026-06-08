"""Tests for the Lab 3 blockchain community overlay.

Tests cover:
1. Server height query (GetChainHeight → ChainHeightResponse)
2. SubmitTransaction success + bad-signature rejection
3. Block gossip between teammates
4. Catch-up via status request/response/block-request cycle
5. Orphan block triggers parent request then converges
6. Server-filter: non-server peers cannot trigger server path
"""

from __future__ import annotations

import types
import unittest

from ipv8.community import CommunitySettings
from ipv8.keyvault.crypto import default_eccrypto
from ipv8.lazy_community import lazy_wrapper
from ipv8.peer import Peer
from ipv8.test.base import TestBase
from ipv8.test.mocking.ipv8 import MockIPv8

from lab1_pow_ipv8.libsodium_bootstrap import ensure_libsodium
from lab3_blockchain.block import block_hash
from lab3_blockchain.chain import GENESIS_HASH
from lab3_blockchain.codec import block_to_response_fields
from lab3_blockchain.community import build_blockchain_community
from lab3_blockchain.protocol import (
    ChainHeightResponsePayload,
    GetChainHeightPayload,
    PeerBlockPayload,
    SubmitTransactionPayload,
    SubmitTransactionResponsePayload,
)
from lab3_blockchain.transaction import Transaction, transaction_signature_message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signed_transaction(data: bytes, timestamp: int) -> Transaction:
    """Create a correctly signed Transaction using a fresh curve25519 key."""
    ensure_libsodium()
    private_key = default_eccrypto.generate_key("curve25519")
    public_key_bin = private_key.pub().key_to_bin()
    unsigned = Transaction(
        sender_key=public_key_bin,
        data=data,
        timestamp=timestamp,
        signature=b"",
    )
    sig = default_eccrypto.create_signature(
        private_key,
        transaction_signature_message(unsigned),
    )
    return Transaction(
        sender_key=public_key_bin,
        data=data,
        timestamp=timestamp,
        signature=sig,
    )


def _mine_block(height: int, prev_hash: bytes):  # type: ignore[return]
    """Mine a difficulty-0 block at *height* on top of *prev_hash*."""
    from lab3_blockchain.block import mine_block_candidate

    return mine_block_candidate(
        height=height,
        prev_hash=prev_hash,
        tx_hashes=(),
        timestamp=1_000_000 + height,
        difficulty=0,
        max_nonce=0,
    )


def _add_capture_handler(overlay, payload_class: type, captured: list) -> None:
    """Register a @lazy_wrapper handler on *overlay* that appends decoded payloads.

    The @lazy_wrapper decorator produces a function ``wrapper(self, addr, data)``.
    When registered via add_message_handler the decode_map calls it as
    ``handler(addr, data)``; binding with types.MethodType restores ``self``
    so the Community serializer is available for decoding.
    """

    @lazy_wrapper(payload_class)
    def _handler(_self: object, peer: Peer, payload: object) -> None:
        captured.append(payload)

    overlay.add_message_handler(payload_class, types.MethodType(_handler, overlay))


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestBlockchainCommunity(TestBase):
    """Functional tests for BlockchainCommunity message handling."""

    def setUp(self) -> None:
        super().setUp()
        self.initialize(build_blockchain_community(), 2)
        # Allow the overlay class to operate in production mode so that our
        # custom _verify_signature override is exercised without crashing the
        # test on unsupported-curve packets from IPv8 internals.
        self.production_overlay_classes.append(self.overlay_class)

    def create_node(
        self,
        settings: CommunitySettings | None = None,
        create_dht: bool = False,
        enable_statistics: bool = False,
    ) -> MockIPv8:
        # Use curve25519 so key generation doesn't hit UnsupportedAlgorithm
        # (the default "low" curve sect233k1 is rejected by modern cryptography).
        return MockIPv8(
            "curve25519", self.overlay_class, settings, create_dht, enable_statistics
        )

    # ------------------------------------------------------------------
    # 1. Server height query
    # ------------------------------------------------------------------

    async def test_server_height_query(self) -> None:
        """node 0 (server) sends GetChainHeight; node 1 replies with height=0."""
        # node 0 acts as the server for node 1.
        self.overlay(1).set_server_public_key(self.key_bin(0))

        captured: list[ChainHeightResponsePayload] = []
        _add_capture_handler(self.overlay(0), ChainHeightResponsePayload, captured)

        # node 0 sends the height request to node 1 (simulating server querying client).
        self.overlay(0).ez_send(self.peer(1), GetChainHeightPayload(request_id=42))
        await self.deliver_messages()

        self.assertEqual(len(captured), 1)
        resp = captured[0]
        self.assertEqual(int(resp.request_id), 42)
        self.assertEqual(int(resp.height), 0)
        self.assertEqual(bytes(resp.tip_hash), self.overlay(1).state.tip_hash)

    # ------------------------------------------------------------------
    # 2. SubmitTransaction – success + bad signature
    # ------------------------------------------------------------------

    async def test_submit_transaction_success(self) -> None:
        """A valid transaction from the server lands in the mempool."""
        # node 0 = server, node 1 = blockchain overlay under test.
        self.overlay(1).set_server_public_key(self.key_bin(0))

        captured: list[SubmitTransactionResponsePayload] = []
        _add_capture_handler(
            self.overlay(0), SubmitTransactionResponsePayload, captured
        )

        tx = _signed_transaction(b"hello", 1)
        self.overlay(0).ez_send(
            self.peer(1),
            SubmitTransactionPayload(
                tx.sender_key, tx.data, tx.timestamp, tx.signature
            ),
        )
        await self.deliver_messages()

        self.assertEqual(len(captured), 1)
        resp = captured[0]
        self.assertTrue(bool(resp.success))
        # The returned hash must appear in the mempool.
        self.assertIn(bytes(resp.tx_hash), self.overlay(1).state.mempool)

    async def test_submit_transaction_bad_signature_rejected(self) -> None:
        """An invalid signature receives success=False; mempool remains empty."""
        self.overlay(1).set_server_public_key(self.key_bin(0))

        captured: list[SubmitTransactionResponsePayload] = []
        _add_capture_handler(
            self.overlay(0), SubmitTransactionResponsePayload, captured
        )

        tx = _signed_transaction(b"tampered", 1)
        # Send with mismatched data so the signature check fails.
        self.overlay(0).ez_send(
            self.peer(1),
            SubmitTransactionPayload(
                tx.sender_key, b"different data", tx.timestamp, tx.signature
            ),
        )
        await self.deliver_messages()

        self.assertEqual(len(captured), 1)
        resp = captured[0]
        self.assertFalse(bool(resp.success))
        self.assertEqual(len(self.overlay(1).state.mempool), 0)

    # ------------------------------------------------------------------
    # 3. Block gossip
    # ------------------------------------------------------------------

    async def test_block_gossip_propagates_to_peer(self) -> None:
        """A block added to node 0 and gossiped reaches node 1."""
        # Both nodes are teammates of each other.
        self.overlay(0).set_target_pubkeys({self.key_bin(1)})
        self.overlay(1).set_target_pubkeys({self.key_bin(0)})

        block = _mine_block(1, GENESIS_HASH)
        self.overlay(0).state.add_block(block)
        self.overlay(0).gossip_block(block)

        await self.deliver_messages()
        await self.deliver_messages()

        self.assertEqual(self.overlay(1).state.height(), 1)
        self.assertEqual(self.overlay(1).state.tip_hash, block_hash(block))

    # ------------------------------------------------------------------
    # 4. Catch-up via status request
    # ------------------------------------------------------------------

    async def test_catchup_via_status_request(self) -> None:
        """node 1 catches up to a 3-block chain on node 0 via status exchange."""
        self.overlay(0).set_target_pubkeys({self.key_bin(1)})
        self.overlay(1).set_target_pubkeys({self.key_bin(0)})

        # Give node 0 a 3-block lead.
        prev = GENESIS_HASH
        for h in range(1, 4):
            blk = _mine_block(h, prev)
            self.overlay(0).state.add_block(blk)
            prev = block_hash(blk)

        self.assertEqual(self.overlay(0).state.height(), 3)
        self.assertEqual(self.overlay(1).state.height(), 0)

        # node 1 broadcasts a status request.
        # Round 1: status request → status response (node 0 tells node 1 its height).
        # Round 2: node 1 issues block requests for h=1,2,3.
        # Round 3: block responses arrive at node 1.
        self.overlay(1).broadcast_status_request(request_id=1)

        for _ in range(6):
            await self.deliver_messages()

        self.assertEqual(self.overlay(1).state.height(), 3)
        self.assertEqual(self.overlay(1).state.tip_hash, self.overlay(0).state.tip_hash)

    # ------------------------------------------------------------------
    # 5. Orphan triggers parent request then converges
    # ------------------------------------------------------------------

    async def test_orphan_triggers_parent_request_and_converges(self) -> None:
        """Delivering child before parent causes node 1 to request the parent."""
        self.overlay(0).set_target_pubkeys({self.key_bin(1)})
        self.overlay(1).set_target_pubkeys({self.key_bin(0)})

        # Build two chained blocks on node 0.
        parent = _mine_block(1, GENESIS_HASH)
        parent_hash = block_hash(parent)
        child = _mine_block(2, parent_hash)

        self.overlay(0).state.add_block(parent)
        self.overlay(0).state.add_block(child)

        # Deliver ONLY the child to node 1; it becomes an orphan and node 1
        # emits PeerBlockRequestPayload(1) back to node 0.
        self.overlay(0).ez_send(
            self.peer(1),
            PeerBlockPayload(**block_to_response_fields(child)),
        )

        # Round 1: child arrives → orphan stored → block request(1) sent.
        await self.deliver_messages()
        # Round 2: parent response arrives at node 1 → orphan attaches.
        await self.deliver_messages()
        # Round 3: any cascade gossip settles.
        await self.deliver_messages()

        self.assertEqual(self.overlay(1).state.height(), 2)
        self.assertEqual(self.overlay(1).state.tip_hash, block_hash(child))

    # ------------------------------------------------------------------
    # 6. Server-filter: non-server peer cannot trigger server path
    # ------------------------------------------------------------------

    async def test_teammate_cannot_trigger_server_path(self) -> None:
        """GetChainHeight from a non-server peer is silently dropped."""
        # Point node 1's server key at a non-existent peer, not node 0.
        fake_server_key = b"\x00" * len(self.key_bin(0))
        self.overlay(1).set_server_public_key(fake_server_key)

        captured: list = []
        _add_capture_handler(self.overlay(0), ChainHeightResponsePayload, captured)

        # node 0 is NOT the registered server; the request should be ignored.
        self.overlay(0).ez_send(self.peer(1), GetChainHeightPayload(request_id=99))
        await self.deliver_messages()

        self.assertEqual(len(captured), 0)


if __name__ == "__main__":
    unittest.main()
