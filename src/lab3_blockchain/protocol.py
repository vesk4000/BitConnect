"""IPv8 VariablePayload definitions for the Lab 3 blockchain wire protocol."""

from __future__ import annotations

from ipv8.messaging.lazy_payload import VariablePayload, vp_compile

from .ids import (
    BLOCK_RESPONSE,
    CHAIN_HEIGHT_RESPONSE,
    GET_BLOCK,
    GET_CHAIN_HEIGHT,
    PEER_BLOCK,
    PEER_BLOCK_REQUEST,
    PEER_BLOCK_RESPONSE,
    PEER_STATUS_REQUEST,
    PEER_STATUS_RESPONSE,
    PEER_TX,
    REGISTER_BLOCKCHAIN,
    REGISTER_RESPONSE,
    SUBMIT_TX,
    SUBMIT_TX_RESPONSE,
)

# ---------------------------------------------------------------------------
# Registration community payloads
# ---------------------------------------------------------------------------


@vp_compile
class RegisterBlockchainPayload(VariablePayload):
    """Register a group's blockchain community with the Lab 3 server."""

    msg_id = REGISTER_BLOCKCHAIN
    format_list = ["varlenHutf8", "varlenH"]
    names = ["group_id", "community_id"]


@vp_compile
class RegisterResponsePayload(VariablePayload):
    """Server response to a blockchain registration request."""

    msg_id = REGISTER_RESPONSE
    format_list = ["?", "varlenHutf8"]
    names = ["success", "message"]


# ---------------------------------------------------------------------------
# Server (blockchain community) payloads
# ---------------------------------------------------------------------------


@vp_compile
class SubmitTransactionPayload(VariablePayload):
    """Submit a signed transaction to the blockchain server."""

    msg_id = SUBMIT_TX
    format_list = ["varlenH", "varlenH", "q", "varlenH"]
    names = ["sender_key", "data", "timestamp", "signature"]


@vp_compile
class SubmitTransactionResponsePayload(VariablePayload):
    """Server response after a transaction submission."""

    msg_id = SUBMIT_TX_RESPONSE
    format_list = ["?", "varlenH", "varlenHutf8"]
    names = ["success", "tx_hash", "message"]


@vp_compile
class GetChainHeightPayload(VariablePayload):
    """Request the current chain height from the server."""

    msg_id = GET_CHAIN_HEIGHT
    format_list = ["q"]
    names = ["request_id"]


@vp_compile
class ChainHeightResponsePayload(VariablePayload):
    """Server response containing the current chain height and tip hash."""

    msg_id = CHAIN_HEIGHT_RESPONSE
    format_list = ["q", "q", "varlenH"]
    names = ["request_id", "height", "tip_hash"]


@vp_compile
class GetBlockPayload(VariablePayload):
    """Request a block at a specific height from the server."""

    msg_id = GET_BLOCK
    format_list = ["q"]
    names = ["height"]


@vp_compile
class BlockResponsePayload(VariablePayload):
    """Server response carrying all fields needed to reconstruct a block."""

    msg_id = BLOCK_RESPONSE
    format_list = ["q", "varlenH", "varlenH", "q", "q", "q", "varlenH", "varlenH"]
    names = [
        "height",
        "prev_hash",
        "txs_hash",
        "timestamp",
        "difficulty",
        "nonce",
        "block_hash",
        "tx_hashes",
    ]


# ---------------------------------------------------------------------------
# Peer gossip payloads
# ---------------------------------------------------------------------------


@vp_compile
class PeerTransactionPayload(VariablePayload):
    """Gossip a signed transaction to a peer."""

    msg_id = PEER_TX
    format_list = ["varlenH", "varlenH", "q", "varlenH"]
    names = ["sender_key", "data", "timestamp", "signature"]


@vp_compile
class PeerBlockPayload(VariablePayload):
    """Gossip a block to a peer."""

    msg_id = PEER_BLOCK
    format_list = ["q", "varlenH", "varlenH", "q", "q", "q", "varlenH", "varlenH"]
    names = [
        "height",
        "prev_hash",
        "txs_hash",
        "timestamp",
        "difficulty",
        "nonce",
        "block_hash",
        "tx_hashes",
    ]


@vp_compile
class PeerStatusRequestPayload(VariablePayload):
    """Request a peer's current chain status."""

    msg_id = PEER_STATUS_REQUEST
    format_list = ["q"]
    names = ["request_id"]


@vp_compile
class PeerStatusResponsePayload(VariablePayload):
    """Peer response with its current chain height and tip hash."""

    msg_id = PEER_STATUS_RESPONSE
    format_list = ["q", "q", "varlenH"]
    names = ["request_id", "height", "tip_hash"]


@vp_compile
class PeerBlockRequestPayload(VariablePayload):
    """Request a block at a specific height from a peer."""

    msg_id = PEER_BLOCK_REQUEST
    format_list = ["q"]
    names = ["height"]


@vp_compile
class PeerBlockResponsePayload(VariablePayload):
    """Peer response carrying all fields needed to reconstruct a block."""

    msg_id = PEER_BLOCK_RESPONSE
    format_list = ["q", "varlenH", "varlenH", "q", "q", "q", "varlenH", "varlenH"]
    names = [
        "height",
        "prev_hash",
        "txs_hash",
        "timestamp",
        "difficulty",
        "nonce",
        "block_hash",
        "tx_hashes",
    ]
