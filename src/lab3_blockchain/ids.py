"""Message-id constants for the Lab 3 blockchain protocol communities."""

from __future__ import annotations

# Server (blockchain community) message IDs
SUBMIT_TX = 1
SUBMIT_TX_RESPONSE = 2
GET_CHAIN_HEIGHT = 3
CHAIN_HEIGHT_RESPONSE = 4
GET_BLOCK = 5
BLOCK_RESPONSE = 6

# Registration community message IDs
REGISTER_BLOCKCHAIN = 1
REGISTER_RESPONSE = 2

# Peer gossip message IDs
PEER_TX = 200
PEER_BLOCK = 201
PEER_STATUS_REQUEST = 202
PEER_STATUS_RESPONSE = 203
PEER_BLOCK_REQUEST = 204
PEER_BLOCK_RESPONSE = 205

SERVER_MESSAGE_IDS: frozenset[int] = frozenset(
    {
        SUBMIT_TX,
        SUBMIT_TX_RESPONSE,
        GET_CHAIN_HEIGHT,
        CHAIN_HEIGHT_RESPONSE,
        GET_BLOCK,
        BLOCK_RESPONSE,
    }
)
PEER_MESSAGE_IDS: frozenset[int] = frozenset(
    {
        PEER_TX,
        PEER_BLOCK,
        PEER_STATUS_REQUEST,
        PEER_STATUS_RESPONSE,
        PEER_BLOCK_REQUEST,
        PEER_BLOCK_RESPONSE,
    }
)
