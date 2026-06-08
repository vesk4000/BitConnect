"""Tests for the Lab 3 registration community and register_blockchain helper.

Two-node setup: node 0 acts as the client, node 1 acts as the "server"
(we override node 0's server_public_key to point at node 1 so the filter
logic is exercised).
"""

from __future__ import annotations

import asyncio
import types
import unittest

from ipv8.community import CommunitySettings
from ipv8.lazy_community import lazy_wrapper
from ipv8.peer import Peer
from ipv8.test.base import TestBase
from ipv8.test.mocking.ipv8 import MockIPv8

from lab3_blockchain.protocol import RegisterBlockchainPayload, RegisterResponsePayload
from lab3_blockchain.registration import (
    RegistrationResult,
    build_registration_community,
    register_blockchain,
)


class TestRegistration(TestBase):
    """Registration community: send/receive and server-filter tests."""

    def setUp(self) -> None:
        super().setUp()
        self.initialize(build_registration_community(), 2)
        # Make packet handling non-fragile so unknown-curve guards don't crash.
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
    # Helpers
    # ------------------------------------------------------------------

    def _install_server_responder(
        self, server_node_idx: int, success: bool, message: str
    ) -> None:
        """Add a simple responder on *server_node_idx* for RegisterBlockchainPayload.

        The @lazy_wrapper decorator produces a function with signature
        ``(self, source_address, data)``; when added to decode_map via
        add_message_handler it is called as ``handler(source_address, data)``.
        Binding it to the overlay with ``types.MethodType`` restores the
        ``self`` argument so the wrapper can call ``self.serializer``.
        """
        overlay = self.overlay(server_node_idx)

        @lazy_wrapper(RegisterBlockchainPayload)
        def responder(
            _self: object, peer: Peer, payload: RegisterBlockchainPayload
        ) -> None:
            overlay.ez_send(peer, RegisterResponsePayload(success, message))

        # Bind the decorated function to the overlay so `self` (the Community
        # instance) is passed correctly when the decode_map invokes it.
        bound_responder = types.MethodType(responder, overlay)
        overlay.add_message_handler(RegisterBlockchainPayload, bound_responder)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    async def test_successful_registration(self) -> None:
        """A matching server key produces a success result."""
        # node 0 = client, node 1 = server
        self.overlay(0).set_server_public_key(self.key_bin(1))
        self._install_server_responder(1, True, "ok")

        # Launch register_blockchain as a background task while we pump messages.
        reg_task = asyncio.ensure_future(
            register_blockchain(
                self.overlay(0),
                "group-A",
                b"\x01" * 20,
                server_timeout=5.0,
                response_timeout=2.0,
                retries=1,
            )
        )
        # Pump messages until the task completes.
        for _ in range(20):
            await self.deliver_messages(timeout=0.1)
            if reg_task.done():
                break

        result: RegistrationResult | None = await reg_task
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "ok")

    async def test_wrong_server_key_returns_none(self) -> None:
        """When server_public_key doesn't match the responder node, result is None."""
        # Point node 0 at a fake key — responses from node 1 will be filtered.
        fake_key = b"\xff" * len(self.key_bin(1))
        self.overlay(0).set_server_public_key(fake_key)
        self._install_server_responder(1, True, "ok")

        reg_task = asyncio.ensure_future(
            register_blockchain(
                self.overlay(0),
                "group-B",
                b"\x02" * 20,
                server_timeout=0.5,  # no server with that key → times out fast
                response_timeout=0.3,
                retries=0,
            )
        )
        for _ in range(15):
            await self.deliver_messages(timeout=0.1)
            if reg_task.done():
                break

        result = await reg_task
        self.assertIsNone(result)

    async def test_failure_response_is_propagated(self) -> None:
        """A server-reported failure is surfaced as success=False."""
        self.overlay(0).set_server_public_key(self.key_bin(1))
        self._install_server_responder(1, False, "duplicate group")

        reg_task = asyncio.ensure_future(
            register_blockchain(
                self.overlay(0),
                "group-C",
                b"\x03" * 20,
                server_timeout=5.0,
                response_timeout=2.0,
                retries=0,
            )
        )
        for _ in range(20):
            await self.deliver_messages(timeout=0.1)
            if reg_task.done():
                break

        result = await reg_task
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertEqual(result.message, "duplicate group")


if __name__ == "__main__":
    unittest.main()
