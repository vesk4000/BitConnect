from __future__ import annotations

import asyncio

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
