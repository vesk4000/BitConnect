"""IPv8 client overlay and submit flow for Lab 1."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, cast

from ipv8.community import Community, CommunitySettings
from ipv8.configuration import (
    ConfigBuilder,
    Strategy,
    WalkerDefinition,
    default_bootstrap_defs,
)
from ipv8.lazy_community import lazy_wrapper
from ipv8.peer import Peer
from ipv8_service import IPv8

from .constants import COMMUNITY_ID_HEX, SERVER_PUBLIC_KEY_HEX
from .protocol import SubmissionPayload, SubmissionResponsePayload
from .validation import validate_email, validate_github_url, validate_nonce


LOGGER = logging.getLogger("lab1_pow_ipv8")


@dataclass(frozen=True)
class SubmissionResult:
    success: bool
    message: str


class LabPowCommunity(Community):
    community_id = bytes.fromhex(COMMUNITY_ID_HEX)
    server_public_key = bytes.fromhex(SERVER_PUBLIC_KEY_HEX)

    def __init__(
        self,
        settings: CommunitySettings,
        email: str,
        github_url: str,
        nonce: int,
    ) -> None:
        super().__init__(settings)
        self.add_message_handler(SubmissionResponsePayload, self.on_response)

        self.email = email
        self.github_url = github_url
        self.nonce = nonce

        self._submit_started = False
        self._response: SubmissionResult | None = None
        self._response_event = asyncio.Event()

    def started(self) -> None:
        async def submit_when_found() -> None:
            if self._response_event.is_set():
                self.cancel_pending_task("submit_when_found")
                return

            server_peer = self.find_server_peer()
            if server_peer is None:
                LOGGER.info("No matching server peer discovered yet; retrying...")
                return

            if not self._submit_started:
                self._submit_started = True
                LOGGER.info("Discovered server peer, submitting PoW...")
                self.ez_send(
                    server_peer,
                    SubmissionPayload(self.email, self.github_url, self.nonce),
                )

        self.register_task(
            "submit_when_found",
            submit_when_found,
            interval=2.0,
            delay=0.1,
        )

    def find_server_peer(self) -> Peer | None:
        for peer in self.get_peers():
            if peer.public_key.key_to_bin() == self.server_public_key:
                return peer
        return None

    @lazy_wrapper(SubmissionResponsePayload)
    def on_response(self, peer: Peer, payload: SubmissionResponsePayload) -> None:
        if peer.public_key.key_to_bin() != self.server_public_key:
            LOGGER.warning(
                "Ignoring response from non-server peer: %s",
                peer.public_key.key_to_bin().hex(),
            )
            return

        payload_obj = cast(Any, payload)
        self._response = SubmissionResult(
            success=bool(payload_obj.success),
            message=str(payload_obj.message),
        )
        self._response_event.set()
        self.cancel_pending_task("submit_when_found")

    async def wait_for_response(self, timeout_seconds: float) -> SubmissionResult | None:
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=timeout_seconds)
        except TimeoutError:
            return None
        return self._response


async def submit_pow(
    email: str,
    github_url: str,
    nonce: int,
    key_file: str,
    timeout_seconds: float = 60.0,
) -> SubmissionResult:
    validate_email(email)
    validate_github_url(github_url)
    validate_nonce(nonce)

    builder = ConfigBuilder().clear_keys().clear_overlays()
    builder.add_key("lab1", "curve25519", key_file)
    builder.add_overlay(
        "LabPowCommunity",
        "lab1",
        [WalkerDefinition(Strategy.RandomWalk, 30, {"timeout": 3.0})],
        default_bootstrap_defs,
        {"email": email, "github_url": github_url, "nonce": nonce},
        [("started",)],
    )

    ipv8 = IPv8(builder.finalize(), extra_communities={"LabPowCommunity": LabPowCommunity})
    await ipv8.start()

    try:
        overlay = next(o for o in ipv8.overlays if isinstance(o, LabPowCommunity))
        result = await overlay.wait_for_response(timeout_seconds)
        if result is None:
            raise TimeoutError(
                "No authenticated response from server before timeout. "
                "Make sure server peer was discovered and submission was signed."
            )
        return result
    finally:
        await ipv8.stop()
