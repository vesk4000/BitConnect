"""Shared base community for Lab 3 blockchain overlays.

Both the registration community and the blockchain community extend this class
to gain server/teammate identity checks, peer filtering, and a hardened
signature verifier.
"""

from __future__ import annotations

import asyncio
import logging

import cryptography.exceptions
from ipv8.community import Community, CommunitySettings
from ipv8.peer import Peer

logger = logging.getLogger(__name__)


class Lab3Community(Community):
    """Base class for Lab 3 IPv8 communities.

    Subclasses must set ``community_id`` and call ``super().__init__(settings)``
    before registering their own message handlers.
    """

    # community_id is intentionally absent here; each subclass must define it.

    def __init__(self, settings: CommunitySettings) -> None:
        super().__init__(settings)
        self.server_public_key: bytes = b""
        self.target_pubkeys: set[bytes] = set()
        self.local_endpoint: tuple[str, int] | None = None

    # ------------------------------------------------------------------
    # Configuration setters
    # ------------------------------------------------------------------

    def set_server_public_key(self, key: bytes) -> None:
        """Set the binary public key of the trusted Lab 3 server."""
        self.server_public_key = key

    def set_target_pubkeys(self, keys: set[bytes]) -> None:
        """Set the binary public keys of known teammates."""
        self.target_pubkeys = keys

    def set_local_endpoint(self, host: str, port: int) -> None:
        """Set the local endpoint (host:port) for peer discovery."""
        self.local_endpoint = (host, port)
        logger.info("Local endpoint set to %s:%d", host, port)

    # ------------------------------------------------------------------
    # Identity predicates
    # ------------------------------------------------------------------

    def _is_server(self, peer: Peer) -> bool:
        """Return True iff *peer* is the authorised Lab 3 server."""
        return peer.public_key.key_to_bin() == self.server_public_key

    def _is_teammate(self, peer: Peer) -> bool:
        """Return True iff *peer* is a known teammate."""
        return peer.public_key.key_to_bin() in self.target_pubkeys

    # ------------------------------------------------------------------
    # Peer helpers
    # ------------------------------------------------------------------

    def _peers_for_targets(self, exclude: bytes | None = None) -> list[Peer]:
        """Return connected peers whose public key is in *target_pubkeys*.

        *exclude* (serialised public key bytes) is omitted from the result so
        gossip senders can skip the originating peer and avoid trivial loops.
        """
        result: list[Peer] = []
        for peer in self.get_peers():
            pk = peer.public_key.key_to_bin()
            if pk in self.target_pubkeys and pk != exclude:
                result.append(peer)
        return result

    def find_server_peer(self) -> Peer | None:
        """Return the first connected peer that matches *server_public_key*, or None."""
        for peer in self.get_peers():
            if peer.public_key.key_to_bin() == self.server_public_key:
                return peer
        return None

    async def wait_for_server_peer(self, timeout: float) -> Peer | None:
        """Poll :meth:`find_server_peer` every 100 ms until found or *timeout* elapses."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            peer = self.find_server_peer()
            if peer is not None:
                return peer
            await asyncio.sleep(0.1)
        return None

    async def wait_for_teammate_peers(self, timeout: float = 120.0) -> bool:
        """Wait until all known teammates are discovered, or timeout elapses.

        Returns True if all teammates found, False on timeout.
        Logs progress periodically.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        expected_count = len(self.target_pubkeys)

        if expected_count == 0:
            logger.warning("wait_for_teammate_peers: no target pubkeys set!")
            return True

        logger.info(
            "Waiting for %d teammate peers (timeout: %.0fs)", expected_count, timeout
        )
        logger.info("Target pubkeys: %s", [pk.hex()[:16] for pk in self.target_pubkeys])

        last_log_time = loop.time()
        while loop.time() < deadline:
            all_peers = self.get_peers()
            found_peers = list(self._peers_for_targets())
            found_count = len(found_peers)

            if found_count >= expected_count:
                logger.info("All %d teammates discovered!", found_count)
                return True

            # Log progress every 30 seconds
            if loop.time() - last_log_time >= 30:
                elapsed = loop.time() - (deadline - timeout)
                logger.info(
                    "Still waiting: %d/%d teammates discovered (%.0fs elapsed), total peers: %d",
                    found_count,
                    expected_count,
                    elapsed,
                    len(all_peers),
                )
                if all_peers:
                    for peer in all_peers[:5]:  # Show first 5 peers
                        logger.info(
                            "  - Known peer: %s",
                            peer.public_key.key_to_bin().hex()[:16],
                        )
                last_log_time = loop.time()

            await asyncio.sleep(1.0)

        logger.warning(
            "Timeout waiting for teammate peers: only %d/%d found after %.0fs",
            len(list(self._peers_for_targets())),
            expected_count,
            timeout,
        )
        logger.warning("Total peers known to IPv8: %d", len(self.get_peers()))
        return False

    # ------------------------------------------------------------------
    # Hardened signature verification
    # ------------------------------------------------------------------

    def _verify_signature(self, auth, data):  # type: ignore[override]
        """Delegate to the parent verifier, silencing UnsupportedAlgorithm.

        Peers on the public IPv8 network may advertise key curves that the
        local ``cryptography`` build cannot verify; without this guard the
        exception aborts packet handling for the entire overlay.
        """
        try:
            return super()._verify_signature(auth, data)
        except cryptography.exceptions.UnsupportedAlgorithm:
            return (False, data)
