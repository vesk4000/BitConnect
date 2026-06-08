"""Blockchain overlay for Lab 3.

This overlay answers server queries against the local BlockchainState, and
ingests / re-gossips signed transactions and mined blocks received from
teammates.

Trust boundaries
----------------
* Server messages (SubmitTransaction, GetChainHeight, GetBlock) are accepted
  only from a peer whose public key matches *server_public_key*.
* Peer-gossip messages (PeerTransaction, PeerBlock, status/request/response)
  are accepted only from peers in *target_pubkeys* (teammate filter).
* Block payloads are additionally validated by :func:`block_from_response_fields`
  which re-derives and compares both block_hash and txs_hash before the block
  reaches BlockchainState.
"""

from __future__ import annotations

import logging

from ipv8.lazy_community import lazy_wrapper
from ipv8.peer import Peer

from .block import Block
from .chain import BLOCK_UNKNOWN_PARENT, BlockchainState
from .codec import block_from_response_fields, block_to_response_fields
from .constants import DEFAULT_BLOCKCHAIN_COMMUNITY_ID_HEX, LAB3_SERVER_PUBLIC_KEY_HEX
from .ipv8_base import Lab3Community
from .protocol import (
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
    SubmitTransactionPayload,
    SubmitTransactionResponsePayload,
)
from .transaction import Transaction, transaction_hash

logger = logging.getLogger(__name__)


def build_blockchain_community(
    community_id_hex: str = DEFAULT_BLOCKCHAIN_COMMUNITY_ID_HEX,
) -> type:
    """Return a BlockchainCommunity class for the given hex community id.

    The factory pattern allows callers (and tests) to create communities with
    different community ids without altering module-level state.
    """

    class BlockchainCommunity(Lab3Community):
        """IPv8 overlay implementing the Lab 3 reactive blockchain consensus."""

        community_id = bytes.fromhex(community_id_hex)

        def __init__(self, settings) -> None:
            super().__init__(settings)
            self.set_server_public_key(bytes.fromhex(LAB3_SERVER_PUBLIC_KEY_HEX))
            self.state: BlockchainState = BlockchainState()

            # Server-path handlers
            self.add_message_handler(
                SubmitTransactionPayload, self.on_submit_transaction
            )
            self.add_message_handler(GetChainHeightPayload, self.on_get_chain_height)
            self.add_message_handler(GetBlockPayload, self.on_get_block)

            # Peer-gossip handlers
            self.add_message_handler(PeerTransactionPayload, self.on_peer_transaction)
            self.add_message_handler(PeerBlockPayload, self.on_peer_block)
            self.add_message_handler(
                PeerStatusRequestPayload, self.on_peer_status_request
            )
            self.add_message_handler(
                PeerStatusResponsePayload, self.on_peer_status_response
            )
            self.add_message_handler(
                PeerBlockRequestPayload, self.on_peer_block_request
            )
            self.add_message_handler(
                PeerBlockResponsePayload, self.on_peer_block_response
            )

        def set_state(self, state: BlockchainState) -> None:
            """Replace the local BlockchainState (used by tests and service wiring)."""
            self.state = state

        # ------------------------------------------------------------------
        # Server-path handlers
        # ------------------------------------------------------------------

        @lazy_wrapper(SubmitTransactionPayload)
        def on_submit_transaction(
            self, peer: Peer, payload: SubmitTransactionPayload
        ) -> None:
            """Accept a signed transaction from the server and gossip it to teammates."""
            if not self._is_server(peer):
                return
            tx = Transaction(
                sender_key=bytes(payload.sender_key),
                data=bytes(payload.data),
                timestamp=int(payload.timestamp),
                signature=bytes(payload.signature),
            )
            try:
                tx_hash = self.state.add_transaction(tx)
            except ValueError:
                self.ez_send(
                    peer,
                    SubmitTransactionResponsePayload(False, b"", "invalid signature"),
                )
                return
            self.ez_send(
                peer,
                SubmitTransactionResponsePayload(True, tx_hash, "accepted"),
            )
            self.gossip_transaction(tx)

        @lazy_wrapper(GetChainHeightPayload)
        def on_get_chain_height(
            self, peer: Peer, payload: GetChainHeightPayload
        ) -> None:
            """Return current chain height and tip hash to the server."""
            if not self._is_server(peer):
                return
            self.ez_send(
                peer,
                ChainHeightResponsePayload(
                    int(payload.request_id),
                    self.state.height(),
                    self.state.tip_hash,
                ),
            )

        @lazy_wrapper(GetBlockPayload)
        def on_get_block(self, peer: Peer, payload: GetBlockPayload) -> None:
            """Serve a block at a given height to the server (no-op if missing)."""
            if not self._is_server(peer):
                return
            block = self.state.get_block_by_height(int(payload.height))
            if block is None:
                return
            self.ez_send(peer, BlockResponsePayload(**block_to_response_fields(block)))

        # ------------------------------------------------------------------
        # Peer-gossip handlers
        # ------------------------------------------------------------------

        @lazy_wrapper(PeerTransactionPayload)
        def on_peer_transaction(
            self, peer: Peer, payload: PeerTransactionPayload
        ) -> None:
            """Ingest a gossiped transaction and re-gossip it if not already known."""
            if not self._is_teammate(peer):
                return
            tx = Transaction(
                sender_key=bytes(payload.sender_key),
                data=bytes(payload.data),
                timestamp=int(payload.timestamp),
                signature=bytes(payload.signature),
            )
            # Check novelty before add so we don't re-gossip duplicates.
            already_known = transaction_hash(tx) in self.state.transactions_by_hash
            try:
                self.state.add_transaction(tx)
            except ValueError:
                # Invalid signature — drop silently.
                return
            if not already_known:
                self.gossip_transaction(tx, exclude=peer.public_key.key_to_bin())

        def _ingest_block(self, peer: Peer, payload) -> None:
            """Shared logic for PeerBlockPayload and PeerBlockResponsePayload.

            Validates the block through the codec trust boundary, adds it to
            local state, and either re-gossips it (if accepted) or requests the
            missing parent (if the block is an orphan).
            """
            block = block_from_response_fields(
                height=int(payload.height),
                prev_hash=bytes(payload.prev_hash),
                txs_hash=bytes(payload.txs_hash),
                timestamp=int(payload.timestamp),
                difficulty=int(payload.difficulty),
                nonce=int(payload.nonce),
                block_hash=bytes(payload.block_hash),
                tx_hashes=bytes(payload.tx_hashes),
            )
            if block is None:
                # Codec detected a hash mismatch or structural error — discard.
                logger.debug("Dropping block payload that failed codec validation")
                return
            result = self.state.add_block(block)
            if result.accepted:
                self.gossip_block(block, exclude=peer.public_key.key_to_bin())
            elif result.reason == BLOCK_UNKNOWN_PARENT and block.height > 0:
                # Ask the sender for the missing ancestor so we can reconnect
                # this orphan to the main chain.
                try:
                    self.ez_send(peer, PeerBlockRequestPayload(block.height - 1))
                except Exception as exc:
                    logger.debug("Failed to send parent request: %s", exc)

        @lazy_wrapper(PeerBlockPayload)
        def on_peer_block(self, peer: Peer, payload: PeerBlockPayload) -> None:
            """Ingest a gossiped block from a teammate."""
            if not self._is_teammate(peer):
                return
            self._ingest_block(peer, payload)

        @lazy_wrapper(PeerBlockResponsePayload)
        def on_peer_block_response(
            self, peer: Peer, payload: PeerBlockResponsePayload
        ) -> None:
            """Ingest a block received in response to a PeerBlockRequestPayload."""
            if not self._is_teammate(peer):
                return
            self._ingest_block(peer, payload)

        @lazy_wrapper(PeerStatusRequestPayload)
        def on_peer_status_request(
            self, peer: Peer, payload: PeerStatusRequestPayload
        ) -> None:
            """Reply with our current chain height and tip hash."""
            if not self._is_teammate(peer):
                return
            self.ez_send(
                peer,
                PeerStatusResponsePayload(
                    int(payload.request_id),
                    self.state.height(),
                    self.state.tip_hash,
                ),
            )

        @lazy_wrapper(PeerStatusResponsePayload)
        def on_peer_status_response(
            self, peer: Peer, payload: PeerStatusResponsePayload
        ) -> None:
            """If the peer is ahead, request all blocks we are missing."""
            if not self._is_teammate(peer):
                return
            peer_height = int(payload.height)
            local_height = self.state.height()
            if peer_height > local_height:
                for h in range(local_height + 1, peer_height + 1):
                    try:
                        self.ez_send(peer, PeerBlockRequestPayload(h))
                    except Exception as exc:
                        logger.debug(
                            "Failed to send block request for height %d: %s", h, exc
                        )

        @lazy_wrapper(PeerBlockRequestPayload)
        def on_peer_block_request(
            self, peer: Peer, payload: PeerBlockRequestPayload
        ) -> None:
            """Serve a requested block back to the teammate (no-op if missing)."""
            if not self._is_teammate(peer):
                return
            block = self.state.get_block_by_height(int(payload.height))
            if block is None:
                return
            try:
                self.ez_send(
                    peer,
                    PeerBlockResponsePayload(**block_to_response_fields(block)),
                )
            except Exception as exc:
                logger.debug("Failed to send block response: %s", exc)

        # ------------------------------------------------------------------
        # Gossip helpers
        # ------------------------------------------------------------------

        def gossip_transaction(
            self, tx: Transaction, exclude: bytes | None = None
        ) -> None:
            """Broadcast a transaction to all teammates (optionally skipping *exclude*)."""
            payload = PeerTransactionPayload(
                tx.sender_key, tx.data, tx.timestamp, tx.signature
            )
            for peer in self._peers_for_targets(exclude):
                try:
                    self.ez_send(peer, payload)
                except Exception as exc:
                    logger.debug("gossip_transaction send failed: %s", exc)

        def gossip_block(self, block: Block, exclude: bytes | None = None) -> None:
            """Broadcast a block to all teammates (optionally skipping *exclude*)."""
            payload = PeerBlockPayload(**block_to_response_fields(block))
            for peer in self._peers_for_targets(exclude):
                try:
                    self.ez_send(peer, payload)
                except Exception as exc:
                    logger.debug("gossip_block send failed: %s", exc)

        def broadcast_status_request(self, request_id: int) -> None:
            """Send a PeerStatusRequestPayload to every known teammate.

            Used by Part C's catch-up loop to discover whether any teammate
            has a longer chain.
            """
            payload = PeerStatusRequestPayload(request_id)
            for peer in self._peers_for_targets():
                try:
                    self.ez_send(peer, payload)
                except Exception as exc:
                    logger.debug("broadcast_status_request send failed: %s", exc)

    return BlockchainCommunity
