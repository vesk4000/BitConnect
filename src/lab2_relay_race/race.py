"""Relay race orchestration for Lab 2."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from lab1_pow_ipv8.libsodium_bootstrap import ensure_libsodium

ensure_libsodium()

from ipv8.configuration import (
    ConfigBuilder,
    Strategy,
    WalkerDefinition,
    default_bootstrap_defs,
)
from ipv8_service import IPv8

from .community import Challenge, RoundResult, build_lab2_community
from .ids import (
    UDP_ACK,
    UDP_BATON_PASS,
    UDP_GROUP_READY,
    UDP_NONCE_BROADCAST,
    UDP_SIGNATURE_REPLY,
)
from .keyutil import (
    extract_public_key_hex,
    load_private_key,
    sign_bytes,
    verify_signature,
)
from .team import TeamConfig, TeamMember
from .udp_prep import PeerEndpoint, get_primary_outbound_ip
from .udp_protocol import (
    body_bytes,
    body_int,
    body_str,
    build_ack_body,
    build_baton_pass_body,
    build_group_ready_body,
    build_nonce_broadcast_body,
    build_signature_reply_body,
)
from .udp_runtime import SignedUdpNode

LOGGER = logging.getLogger("lab2_race")


@dataclass(frozen=True)
class RaceSettings:
    key_file: str
    udp_port: int
    team_config: TeamConfig
    manual_peers: dict[str, PeerEndpoint] | None = None
    discovery_timeout: float = 300.0
    server_peer_timeout: float = 30.0
    registration_timeout: float = 30.0
    group_ready_timeout: float = 30.0
    request_retry_interval: float = 0.35
    signature_retry_interval: float = 0.25
    baton_timeout: float = 2.0
    round_timeout: float = 10.0
    walk_peers: int = 200
    walk_timeout: float = 3.0


@dataclass(frozen=True)
class RaceOutcome:
    group_id: str
    local_role: str
    final_result: RoundResult | None


def build_ordered_signature_list(
    team_config: TeamConfig,
    signatures_by_pubkey: dict[str, bytes],
) -> list[bytes]:
    missing = [
        member.name
        for member in team_config.members
        if member.pubkey_hex not in signatures_by_pubkey
    ]
    if missing:
        raise ValueError(f"Missing signatures from: {', '.join(missing)}")
    return [signatures_by_pubkey[member.pubkey_hex] for member in team_config.members]


async def run_relay_race(settings: RaceSettings) -> RaceOutcome:
    ensure_libsodium()
    local_pubkey = extract_public_key_hex(settings.key_file)
    private_key = load_private_key(settings.key_file)
    team = settings.team_config
    local_member = team.local_member(local_pubkey)
    teammate_members = team.teammates(local_pubkey)
    teammate_pubkeys = [member.pubkey_hex for member in teammate_members]

    udp_node = SignedUdpNode(
        local_private_key=private_key,
        local_pubkey_hex=local_pubkey,
        allowed_pubkeys=team.pubkey_set,
    )
    await udp_node.start(settings.udp_port)

    Lab2Community = build_lab2_community()
    builder = ConfigBuilder().clear_keys().clear_overlays()
    builder.add_key("lab2", "curve25519", settings.key_file)
    builder.add_overlay(
        "Lab2Community",
        "lab2",
        [
            WalkerDefinition(
                Strategy.RandomWalk,
                settings.walk_peers,
                {"timeout": settings.walk_timeout},
            )
        ],
        default_bootstrap_defs,
        {},
        [("started",)],
    )
    ipv8 = IPv8(builder.finalize(), extra_communities={"Lab2Community": Lab2Community})
    await ipv8.start()

    try:
        overlay = next(o for o in ipv8.overlays if isinstance(o, Lab2Community))
        overlay.set_local_endpoint(get_primary_outbound_ip(), settings.udp_port)
        overlay.set_target_pubkeys(
            [bytes.fromhex(pubkey) for pubkey in teammate_pubkeys]
        )

        if settings.manual_peers is None:
            peer_map = await _discover_team_endpoints(
                overlay,
                teammate_members,
                settings.discovery_timeout,
            )
        else:
            peer_map = _select_manual_team_endpoints(
                settings.manual_peers,
                teammate_members,
            )
        udp_node.set_peers(peer_map)

        server_peer = await overlay.wait_for_server_peer(settings.server_peer_timeout)
        if server_peer is None:
            raise TimeoutError("Lab 2 server peer was not discovered")

        runner = _RelayRaceSession(
            settings=settings,
            local_member=local_member,
            private_key=private_key,
            overlay=overlay,
            server_peer=server_peer,
            udp_node=udp_node,
        )
        return await runner.run()
    finally:
        await udp_node.stop()
        await ipv8.stop()


async def _discover_team_endpoints(
    overlay,
    teammate_members: list[TeamMember],
    timeout: float,
) -> dict[str, PeerEndpoint]:
    target_pubkeys = [member.pubkey for member in teammate_members]
    LOGGER.info("Discovering %d teammate UDP endpoint(s)", len(target_pubkeys))
    endpoints = await overlay.wait_for_endpoints(target_pubkeys, timeout=timeout)
    missing = [
        member.name for member in teammate_members if member.pubkey not in endpoints
    ]
    if missing:
        raise TimeoutError(f"Missing teammate endpoint(s): {', '.join(missing)}")

    peers: dict[str, PeerEndpoint] = {}
    for member in teammate_members:
        host, port = endpoints[member.pubkey]
        peers[member.pubkey_hex] = PeerEndpoint(member.pubkey_hex, host, port)
        LOGGER.info(
            "Discovered Node %s (%s) at %s:%s", member.role, member.name, host, port
        )
    return peers


def _select_manual_team_endpoints(
    manual_peers: dict[str, PeerEndpoint],
    teammate_members: list[TeamMember],
) -> dict[str, PeerEndpoint]:
    missing = [
        member.name
        for member in teammate_members
        if member.pubkey_hex not in manual_peers
    ]
    if missing:
        raise ValueError(f"Missing manual teammate endpoint(s): {', '.join(missing)}")

    peer_map = {
        member.pubkey_hex: manual_peers[member.pubkey_hex]
        for member in teammate_members
    }
    for member in teammate_members:
        peer = peer_map[member.pubkey_hex]
        LOGGER.info(
            "Using manual endpoint for Node %s (%s): %s:%s",
            member.role,
            member.name,
            peer.host,
            peer.port,
        )
    return peer_map


class _RelayRaceSession:
    def __init__(
        self,
        *,
        settings: RaceSettings,
        local_member: TeamMember,
        private_key,
        overlay,
        server_peer,
        udp_node: SignedUdpNode,
    ) -> None:
        self.settings = settings
        self.team = settings.team_config
        self.local_member = local_member
        self.private_key = private_key
        self.overlay = overlay
        self.server_peer = server_peer
        self.udp = udp_node
        self.group_id: str | None = None
        self.signed_rounds: dict[int, tuple[bytes, bytes]] = {}
        self.local_round = {"A": 1, "B": 2, "C": 3}[self.local_member.role]
        self.prefetched_challenges: dict[int, Challenge] = {}
        self.result_tasks: dict[int, asyncio.Task[RoundResult | None]] = {}

    async def run(self) -> RaceOutcome:
        if self.local_member.role == "A":
            group_id = await self._register_group()
            await self._send_group_ready(group_id)
        else:
            group_id = await self._wait_for_group_ready()
        self.group_id = group_id

        final_result: RoundResult | None = None
        for round_number in range(1, 4):
            leader = self.team.submitter_for_round(round_number)
            if leader.pubkey_hex == self.local_member.pubkey_hex:
                if round_number > 1:
                    await self._wait_for_baton_or_fallback(round_number)
                result = await self._lead_round(round_number)
                if result is not None:
                    final_result = result
            else:
                await self._follow_round(round_number)

        if final_result is None and self.local_round in self.result_tasks:
            final_result = await self.result_tasks[self.local_round]

        return RaceOutcome(
            group_id=group_id,
            local_role=self.local_member.role,
            final_result=final_result,
        )

    async def _register_group(self) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.registration_timeout
        while loop.time() < deadline:
            self.overlay.send_group_register(
                self.server_peer,
                self.team.registration_pubkey_bytes,
            )
            result = await self.overlay.wait_for_registration_result(
                self.settings.request_retry_interval
            )
            if result is None:
                continue
            LOGGER.info("Registration response: %s", result.message)
            if result.success:
                return result.group_id
            raise RuntimeError(result.message)
        raise TimeoutError("Timed out registering Lab 2 group")

    async def _send_group_ready(self, group_id: str) -> None:
        missing = {
            member.pubkey_hex
            for member in self.team.teammates(self.local_member.pubkey_hex)
        }
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.group_ready_timeout
        while missing and loop.time() < deadline:
            for pubkey_hex in list(missing):
                self.udp.send(
                    pubkey_hex, UDP_GROUP_READY, build_group_ready_body(group_id)
                )
            message = await self.udp.wait_for(
                lambda msg: (
                    msg.message_id == UDP_ACK
                    and msg.sender_pubkey_hex in missing
                    and body_int(msg.body, "ack_message_id") == UDP_GROUP_READY
                ),
                timeout=self.settings.request_retry_interval,
            )
            if message is not None:
                missing.discard(message.sender_pubkey_hex)
        if missing:
            raise TimeoutError("Timed out waiting for GroupReady ACKs")

    async def _wait_for_group_ready(self) -> str:
        node_a = self.team.members[0]
        message = await self.udp.wait_for(
            lambda msg: (
                msg.message_id == UDP_GROUP_READY
                and msg.sender_pubkey_hex == node_a.pubkey_hex
            ),
            timeout=self.settings.group_ready_timeout,
        )
        if message is None:
            raise TimeoutError("Timed out waiting for GroupReady from Node A")
        group_id = body_str(message.body, "group_id")
        self.udp.send(
            node_a.pubkey_hex,
            UDP_ACK,
            build_ack_body(UDP_GROUP_READY),
        )
        LOGGER.info("Group ready: %s", group_id)
        return group_id

    async def _follow_round(self, round_number: int) -> None:
        leader = self.team.submitter_for_round(round_number)
        while True:
            message = await self.udp.receive(timeout=self.settings.round_timeout)
            if message is None:
                raise TimeoutError(f"Timed out waiting for round {round_number} nonce")
            if self._handle_common_message(message):
                continue
            if (
                message.message_id == UDP_NONCE_BROADCAST
                and message.sender_pubkey_hex == leader.pubkey_hex
                and body_int(message.body, "round_number") == round_number
            ):
                self._reply_to_nonce_broadcast(message)
                return

    async def _wait_for_baton_or_fallback(self, expected_round: int) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.baton_timeout
        while loop.time() < deadline:
            message = await self.udp.receive(timeout=max(0.0, deadline - loop.time()))
            if message is None:
                break
            if message.message_id == UDP_GROUP_READY and self._handle_common_message(
                message
            ):
                continue
            if message.message_id == UDP_NONCE_BROADCAST:
                self._reply_to_nonce_broadcast(message)
                continue
            if self._ack_expected_baton(message, expected_round):
                return

        LOGGER.warning("Baton missing for round %d; polling server", expected_round)
        challenge = await self._fallback_until_baton_or_challenge(expected_round)
        if challenge is not None:
            self.prefetched_challenges[expected_round] = challenge

    async def _lead_round(self, round_number: int) -> RoundResult | None:
        challenge = await self._request_challenge_until(round_number)
        local_signature = sign_bytes(self.private_key, challenge.nonce)
        signatures = {self.local_member.pubkey_hex: local_signature}
        missing = {
            member.pubkey_hex
            for member in self.team.members
            if member.pubkey_hex != self.local_member.pubkey_hex
        }
        nonce_body = build_nonce_broadcast_body(round_number, challenge.nonce)

        while missing:
            for pubkey_hex in list(missing):
                self.udp.send(pubkey_hex, UDP_NONCE_BROADCAST, nonce_body)
            message = await self.udp.receive(
                timeout=self.settings.signature_retry_interval
            )
            if message is None:
                continue
            if self._handle_common_message(message):
                continue
            if (
                message.message_id == UDP_SIGNATURE_REPLY
                and message.sender_pubkey_hex in missing
                and body_int(message.body, "round_number") == round_number
            ):
                signature = body_bytes(message.body, "signature_hex")
                if verify_signature(
                    message.sender_pubkey_hex,
                    challenge.nonce,
                    signature,
                ):
                    signatures[message.sender_pubkey_hex] = signature
                    missing.remove(message.sender_pubkey_hex)
                else:
                    LOGGER.warning(
                        "Ignoring invalid nonce signature from %s",
                        message.sender_pubkey_hex[:16],
                    )
            elif message.message_id == UDP_NONCE_BROADCAST:
                self._reply_to_nonce_broadcast(message)

        ordered = build_ordered_signature_list(self.team, signatures)
        result_task = asyncio.create_task(
            self._submit_bundle_until_result(round_number, ordered)
        )
        self.result_tasks[round_number] = result_task

        if round_number < 3:
            next_member = self.team.submitter_for_round(round_number + 1)
            await self._send_baton(next_member.pubkey_hex, round_number + 1)
            return None

        return await result_task

    async def _send_baton(self, target_pubkey_hex: str, next_round_number: int) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.baton_timeout
        body = build_baton_pass_body(next_round_number, self._group_id)
        while loop.time() < deadline:
            self.udp.send(target_pubkey_hex, UDP_BATON_PASS, body)
            message = await self.udp.wait_for(
                lambda msg: (
                    msg.message_id == UDP_ACK
                    and msg.sender_pubkey_hex == target_pubkey_hex
                    and body_int(msg.body, "ack_message_id") == UDP_BATON_PASS
                    and body_int(msg.body, "round_number") == next_round_number
                ),
                timeout=self.settings.signature_retry_interval,
            )
            if message is not None:
                return
        LOGGER.warning("No ACK for BatonPass to %s", target_pubkey_hex[:16])

    async def _request_challenge_until(self, expected_round: int) -> Challenge:
        cached = self.prefetched_challenges.pop(expected_round, None)
        if cached is not None:
            return cached

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.round_timeout
        while loop.time() < deadline:
            self.overlay.send_challenge_request(self.server_peer, self._group_id)
            challenge = await self.overlay.wait_for_challenge(
                self.settings.request_retry_interval
            )
            if challenge is None:
                continue
            if challenge.round_number == expected_round:
                LOGGER.info(
                    "Received round %d challenge; deadline %.3f",
                    challenge.round_number,
                    challenge.deadline,
                )
                return challenge
            LOGGER.info(
                "Server returned round %d while waiting for round %d",
                challenge.round_number,
                expected_round,
            )
        raise TimeoutError(f"Timed out waiting for round {expected_round} challenge")

    async def _fallback_until_baton_or_challenge(
        self, expected_round: int
    ) -> Challenge | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.round_timeout
        while loop.time() < deadline:
            self.overlay.send_challenge_request(self.server_peer, self._group_id)
            retry_deadline = min(
                deadline,
                loop.time() + self.settings.request_retry_interval,
            )
            while loop.time() < retry_deadline:
                challenge = await self.overlay.wait_for_challenge(0.05)
                if challenge is not None:
                    if challenge.round_number == expected_round:
                        LOGGER.info(
                            "Fallback received round %d challenge; deadline %.3f",
                            challenge.round_number,
                            challenge.deadline,
                        )
                        return challenge
                    LOGGER.info(
                        "Fallback saw round %d while waiting for round %d",
                        challenge.round_number,
                        expected_round,
                    )

                message = await self.udp.receive(timeout=0.01)
                if message is None:
                    continue
                if self._ack_expected_baton(message, expected_round):
                    return None
                if message.message_id == UDP_NONCE_BROADCAST:
                    self._reply_to_nonce_broadcast(message)
                else:
                    self._handle_common_message(message)
        raise TimeoutError(f"Timed out waiting for round {expected_round} fallback")

    async def _submit_bundle_until_result(
        self,
        round_number: int,
        ordered_signatures: list[bytes],
    ) -> RoundResult | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.round_timeout
        while loop.time() < deadline:
            self.overlay.send_signature_bundle(
                self.server_peer,
                self._group_id,
                round_number,
                ordered_signatures,
            )
            result = await self.overlay.wait_for_round_result(
                self.settings.request_retry_interval
            )
            if result is None:
                continue
            if result.round_number != round_number:
                LOGGER.info(
                    "Ignoring result for round %d while waiting for round %d: %s",
                    result.round_number,
                    round_number,
                    result.message,
                )
                continue
            if _looks_like_duplicate_success(result, round_number):
                inferred = RoundResult(
                    success=True,
                    round_number=result.round_number,
                    rounds_completed=result.rounds_completed,
                    message=(
                        result.message
                        + " (previous bundle likely accepted; success response lost)"
                    ),
                )
                LOGGER.info("Round result: %s", inferred.message)
                return inferred
            LOGGER.info("Round result: %s", result.message)
            return result

        LOGGER.warning("No round %d result before timeout", round_number)
        return None

    def _reply_to_nonce_broadcast(self, message) -> None:
        round_number = body_int(message.body, "round_number")
        leader = self.team.submitter_for_round(round_number)
        if message.sender_pubkey_hex != leader.pubkey_hex:
            return
        nonce = body_bytes(message.body, "nonce_hex")
        cached = self.signed_rounds.get(round_number)
        if cached is None or cached[0] != nonce:
            signature = sign_bytes(self.private_key, nonce)
            self.signed_rounds[round_number] = (nonce, signature)
        else:
            signature = cached[1]
        self.udp.send(
            leader.pubkey_hex,
            UDP_SIGNATURE_REPLY,
            build_signature_reply_body(round_number, signature),
        )

    def _ack_expected_baton(self, message, expected_round: int) -> bool:
        if message.message_id != UDP_BATON_PASS:
            return False
        previous_leader = self.team.submitter_for_round(expected_round - 1)
        if (
            message.sender_pubkey_hex != previous_leader.pubkey_hex
            or body_int(message.body, "next_round_number") != expected_round
        ):
            return False
        self.udp.send(
            previous_leader.pubkey_hex,
            UDP_ACK,
            build_ack_body(UDP_BATON_PASS, expected_round),
        )
        return True

    def _handle_common_message(self, message) -> bool:
        node_a = self.team.members[0]
        if (
            message.message_id == UDP_GROUP_READY
            and message.sender_pubkey_hex == node_a.pubkey_hex
        ):
            self.group_id = body_str(message.body, "group_id")
            self.udp.send(node_a.pubkey_hex, UDP_ACK, build_ack_body(UDP_GROUP_READY))
            return True

        if self.local_round > 1 and message.message_id == UDP_BATON_PASS:
            if self._ack_expected_baton(message, self.local_round):
                return True

        return False

    @property
    def _group_id(self) -> str:
        if self.group_id is None:
            raise RuntimeError("Group is not ready")
        return self.group_id


def _looks_like_duplicate_success(result: RoundResult, round_number: int) -> bool:
    return (
        not result.success
        and result.rounds_completed >= round_number
        and "no active challenge" in result.message.lower()
    )
