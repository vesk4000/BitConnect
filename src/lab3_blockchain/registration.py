"""Client-side registration community for the Lab 3 blockchain.

Sends a RegisterBlockchainPayload to the Lab 3 server and waits for a
RegisterResponsePayload.  The server assigns the group a stable community
slot so the grader can locate the blockchain overlay.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ipv8.lazy_community import lazy_wrapper
from ipv8.peer import Peer

from .constants import LAB3_SERVER_PUBLIC_KEY_HEX, REGISTRATION_COMMUNITY_ID_HEX
from .ipv8_base import Lab3Community
from .protocol import RegisterBlockchainPayload, RegisterResponsePayload

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegistrationResult:
    """Outcome of a single blockchain registration attempt."""

    success: bool
    message: str


def build_registration_community() -> type:
    """Return a RegistrationCommunity class bound to the Lab 3 server constants.

    The factory pattern lets tests pass the class directly to TestBase.initialize
    without hitting the module-level community_id resolution issues that arise
    when community_id references a runtime constant.
    """

    class RegistrationCommunity(Lab3Community):
        """IPv8 community that registers a group's blockchain with the Lab 3 server."""

        community_id = bytes.fromhex(REGISTRATION_COMMUNITY_ID_HEX)

        def __init__(self, settings) -> None:
            super().__init__(settings)
            self.set_server_public_key(bytes.fromhex(LAB3_SERVER_PUBLIC_KEY_HEX))
            self.add_message_handler(RegisterResponsePayload, self.on_register_response)
            self._results: asyncio.Queue[RegistrationResult] = asyncio.Queue()

        def send_register(
            self, server_peer: Peer, group_id: str, community_id: bytes
        ) -> None:
            """Send a registration request to *server_peer*."""
            self.ez_send(server_peer, RegisterBlockchainPayload(group_id, community_id))

        @lazy_wrapper(RegisterResponsePayload)
        def on_register_response(
            self, peer: Peer, payload: RegisterResponsePayload
        ) -> None:
            # Only trust responses that originate from the known server key.
            if not self._is_server(peer):
                return
            self._results.put_nowait(
                RegistrationResult(bool(payload.success), str(payload.message))
            )

        async def wait_for_result(self, timeout: float) -> RegistrationResult | None:
            """Return the next registration result or None if *timeout* elapses."""
            try:
                return await asyncio.wait_for(self._results.get(), timeout)
            except asyncio.TimeoutError:
                return None

    return RegistrationCommunity


async def register_blockchain(
    overlay,
    group_id: str,
    community_id: bytes,
    *,
    server_timeout: float = 60.0,
    response_timeout: float = 10.0,
    retries: int = 3,
) -> RegistrationResult | None:
    """Discover the server peer and register *community_id* for *group_id*.

    Waits up to *server_timeout* seconds for the server to appear in the
    overlay's peer list, then sends up to ``retries + 1`` registration
    requests, each with a *response_timeout* window.  Returns the first
    successful (or failed) server response, or None if every attempt times out.
    """
    logger.info("Waiting for Lab 3 server peer (timeout=%.1fs)...", server_timeout)
    server_peer = await overlay.wait_for_server_peer(server_timeout)
    if server_peer is None:
        logger.warning("Lab 3 server peer not found within %.1fs", server_timeout)
        return None

    for attempt in range(retries + 1):
        logger.info(
            "Sending registration attempt %d/%d for group=%r community=%s",
            attempt + 1,
            retries + 1,
            group_id,
            community_id.hex(),
        )
        overlay.send_register(server_peer, group_id, community_id)
        result = await overlay.wait_for_result(response_timeout)
        if result is not None:
            logger.info(
                "Registration result: success=%s message=%r",
                result.success,
                result.message,
            )
            return result
        logger.warning(
            "No registration response within %.1fs (attempt %d/%d)",
            response_timeout,
            attempt + 1,
            retries + 1,
        )

    logger.error("All %d registration attempts timed out", retries + 1)
    return None
