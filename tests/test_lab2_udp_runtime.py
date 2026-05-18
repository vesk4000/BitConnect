from __future__ import annotations

import asyncio

from ipv8.keyvault.crypto import default_eccrypto

from lab1_pow_ipv8.libsodium_bootstrap import ensure_libsodium
from lab2_relay_race.ids import UDP_GROUP_READY
from lab2_relay_race.udp_prep import PeerEndpoint
from lab2_relay_race.udp_protocol import SignedUdpCodec, build_group_ready_body
from lab2_relay_race.udp_protocol import SignedUdpMessage
from lab2_relay_race.udp_runtime import SignedUdpNode


def test_wait_for_reads_queue_when_backlog_has_non_matching_message():
    async def scenario():
        node = SignedUdpNode(
            local_private_key=None,
            local_pubkey_hex="local",
            allowed_pubkeys=set(),
        )
        non_matching = SignedUdpMessage("peer-a", 1, 1, {})
        matching = SignedUdpMessage("peer-b", 2, 1, {})
        node._backlog.append(non_matching)
        node._queue.put_nowait(matching)

        message = await node.wait_for(lambda msg: msg.message_id == 2, timeout=0.1)

        assert message == matching
        assert node._backlog == [non_matching]

    asyncio.run(scenario())


def test_valid_inbound_datagram_updates_peer_endpoint():
    ensure_libsodium()
    key = default_eccrypto.generate_key("curve25519")
    pubkey_hex = key.pub().key_to_bin().hex()
    sender = SignedUdpCodec(
        local_private_key=key,
        local_pubkey_hex=pubkey_hex,
        allowed_pubkeys={pubkey_hex},
    )
    node = SignedUdpNode(
        local_private_key=None,
        local_pubkey_hex="local",
        allowed_pubkeys={pubkey_hex},
        peers={
            pubkey_hex: PeerEndpoint(pubkey_hex, "127.0.0.1", 5001),
        },
    )

    node._on_datagram(
        sender.encode(UDP_GROUP_READY, 1, build_group_ready_body("group-1")),
        ("192.168.1.42", 5001),
    )

    assert node.peers[pubkey_hex].host == "192.168.1.42"
    assert node.peers[pubkey_hex].port == 5001


def test_ignored_inbound_datagram_still_updates_peer_endpoint():
    ensure_libsodium()
    key = default_eccrypto.generate_key("curve25519")
    pubkey_hex = key.pub().key_to_bin().hex()
    sender = SignedUdpCodec(
        local_private_key=key,
        local_pubkey_hex=pubkey_hex,
        allowed_pubkeys={pubkey_hex},
    )
    node = SignedUdpNode(
        local_private_key=None,
        local_pubkey_hex="local",
        allowed_pubkeys={pubkey_hex},
        peers={
            pubkey_hex: PeerEndpoint(pubkey_hex, "127.0.0.1", 5001),
        },
    )

    node.ignore_message_id(UDP_GROUP_READY)
    node._on_datagram(
        sender.encode(UDP_GROUP_READY, 1, build_group_ready_body("group-1")),
        ("192.168.1.42", 5001),
    )

    assert node.peers[pubkey_hex].host == "192.168.1.42"
    assert node._queue.empty()
