"""Async signed UDP transport for the Lab 2 relay race."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Any

from .ids import (
    UDP_ACK,
    UDP_BATON_PASS,
    UDP_GROUP_READY,
    UDP_NONCE_BROADCAST,
    UDP_SERVER_HINT,
    UDP_SIGNATURE_REPLY,
)
from .udp_prep import PeerEndpoint
from .udp_protocol import (
    DuplicateMessageError,
    SignedUdpCodec,
    SignedUdpMessage,
    UdpProtocolError,
)

LOGGER = logging.getLogger("lab2_udp_runtime")


class SignedUdpNode:
    """Small asyncio datagram wrapper around SignedUdpCodec."""

    def __init__(
        self,
        *,
        local_private_key,
        local_pubkey_hex: str,
        allowed_pubkeys: set[str],
        peers: Mapping[str, PeerEndpoint] | None = None,
    ) -> None:
        self.local_pubkey_hex = local_pubkey_hex
        self.codec = SignedUdpCodec(
            local_private_key=local_private_key,
            local_pubkey_hex=local_pubkey_hex,
            allowed_pubkeys=allowed_pubkeys,
        )
        self.peers: dict[str, PeerEndpoint] = dict(peers or {})
        self.transport: asyncio.DatagramTransport | None = None
        self._queue: asyncio.Queue[SignedUdpMessage] = asyncio.Queue()
        self._backlog: list[SignedUdpMessage] = []
        self._ignored_message_ids: set[int] = set()
        self._sequence = 0

    async def start(self, port: int) -> None:
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: _DatagramProtocol(self),
            local_addr=("0.0.0.0", port),
        )
        LOGGER.info("Signed UDP listener started on port %s", port)

    async def stop(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None

    def set_peers(self, peers: Mapping[str, PeerEndpoint]) -> None:
        self.peers = dict(peers)

    def ignore_message_id(self, message_id: int) -> None:
        self._ignored_message_ids.add(message_id)

    def send(self, pubkey_hex: str, message_id: int, body: Mapping[str, Any]) -> None:
        if self.transport is None:
            raise RuntimeError("Signed UDP listener is not started")
        peer = self.peers[pubkey_hex]
        self._sequence += 1
        datagram = self.codec.encode(message_id, self._sequence, body)
        LOGGER.debug(
            "Signed UDP send %s seq=%d to ...%s @ %s:%d",
            _message_name(message_id),
            self._sequence,
            pubkey_hex[-16:],
            peer.host,
            peer.port,
        )
        self.transport.sendto(datagram, (peer.host, peer.port))

    def broadcast(
        self, pubkeys: list[str], message_id: int, body: Mapping[str, Any]
    ) -> None:
        for pubkey_hex in pubkeys:
            self.send(pubkey_hex, message_id, body)

    async def receive(self, timeout: float | None = None) -> SignedUdpMessage | None:
        if self._backlog:
            return self._backlog.pop(0)
        try:
            if timeout is None:
                return await self._queue.get()
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def wait_for(
        self,
        predicate: Callable[[SignedUdpMessage], bool],
        timeout: float,
    ) -> SignedUdpMessage | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            for index, message in enumerate(self._backlog):
                if predicate(message):
                    return self._backlog.pop(index)

            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                message = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            if predicate(message):
                return message
            self._backlog.append(message)

    def _on_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            message = self.codec.decode(data)
        except DuplicateMessageError:
            LOGGER.debug("Dropping duplicate signed UDP datagram from %s:%d", *addr)
            return
        except UdpProtocolError as exc:
            LOGGER.debug(
                "Dropping invalid signed UDP datagram from %s:%d: %s",
                addr[0],
                addr[1],
                exc,
            )
            return
        LOGGER.debug(
            "Signed UDP recv %s seq=%d from ...%s @ %s:%d",
            _message_name(message.message_id),
            message.sequence,
            message.sender_pubkey_hex[-16:],
            addr[0],
            addr[1],
        )
        self._learn_peer_endpoint(message.sender_pubkey_hex, addr)
        if message.message_id in self._ignored_message_ids:
            LOGGER.debug(
                "Ignoring signed UDP %s after endpoint learning",
                _message_name(message.message_id),
            )
            return
        self._queue.put_nowait(message)

    def _learn_peer_endpoint(self, pubkey_hex: str, addr: tuple[str, int]) -> None:
        current = self.peers.get(pubkey_hex)
        if current is None:
            return
        host, port = addr
        if current.host == host and current.port == port:
            return
        LOGGER.info(
            "Updated signed UDP endpoint for ...%s from %s:%d to %s:%d",
            pubkey_hex[-16:],
            current.host,
            current.port,
            host,
            port,
        )
        self.peers[pubkey_hex] = PeerEndpoint(pubkey_hex, host, port)


class _DatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, node: SignedUdpNode) -> None:
        self.node = node

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.node._on_datagram(data, addr)

    def connection_lost(self, exc: Exception | None) -> None:
        if exc is not None:
            LOGGER.warning("Signed UDP connection lost: %s", exc)


def _message_name(message_id: int) -> str:
    names = {
        UDP_GROUP_READY: "GroupReady",
        UDP_NONCE_BROADCAST: "NonceBroadcast",
        UDP_SIGNATURE_REPLY: "SignatureReply",
        UDP_BATON_PASS: "BatonPass",
        UDP_ACK: "Ack",
        UDP_SERVER_HINT: "ServerHint",
    }
    return names.get(message_id, str(message_id))
