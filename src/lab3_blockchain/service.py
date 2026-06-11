"""IPv8 wiring for both Lab 3 overlays.

Builds a single IPv8 instance that hosts both the RegistrationCommunity and
the BlockchainCommunity, wires up the shared BlockchainState, and returns a
Lab3Node dataclass that the CLI and tests can interact with.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ipv8.configuration import (
    ConfigBuilder,
    Strategy,
    WalkerDefinition,
    default_bootstrap_defs,
)
from ipv8_service import IPv8

from lab1_pow_ipv8.libsodium_bootstrap import ensure_libsodium
from lab2_relay_race.keyutil import extract_public_key_hex
from lab2_relay_race.team import load_team_config

from .chain import BlockchainState
from .community import build_blockchain_community
from .constants import DEFAULT_BLOCKCHAIN_COMMUNITY_ID_HEX
from .registration import build_registration_community

logger = logging.getLogger(__name__)


@dataclass
class Lab3Node:
    """Container for a running Lab 3 IPv8 node and its overlays."""

    ipv8: IPv8
    registration_overlay: object
    blockchain_overlay: object
    state: BlockchainState
    local_pubkey_hex: str


async def build_node(
    *,
    key_file: str,
    team_config_path: str,
    community_id_hex: str = DEFAULT_BLOCKCHAIN_COMMUNITY_ID_HEX,
    ipv8_port: int | None = None,
) -> Lab3Node:
    """Construct and start a full Lab 3 IPv8 node.

    Loads the identity key from *key_file*, discovers teammates from
    *team_config_path*, and starts two IPv8 overlays: one for blockchain
    registration and one for blockchain consensus.

    Args:
        key_file: Path to the PEM file holding the local curve25519 key.
        team_config_path: Path to the JSON team configuration file.
        community_id_hex: Hex-encoded community id for the blockchain overlay.
        ipv8_port: UDP port for IPv8; if None, IPv8 picks a default.

    Returns:
        A :class:`Lab3Node` with both overlays started and the shared
        :class:`BlockchainState` injected into the blockchain overlay.
    """
    ensure_libsodium()

    local_pubkey_hex = extract_public_key_hex(key_file)
    team = load_team_config(team_config_path)
    teammates = team.teammates(local_pubkey_hex)
    # TeamMember.pubkey returns the raw bytes of the serialised public key.
    teammate_keys: set[bytes] = {m.pubkey for m in teammates}

    RegistrationCommunity = build_registration_community()
    BlockchainCommunity = build_blockchain_community(community_id_hex)

    builder = ConfigBuilder().clear_keys().clear_overlays()
    if ipv8_port is not None:
        builder.set_port(ipv8_port)
    builder.add_key("lab3", "curve25519", key_file)
    builder.add_overlay(
        "Lab3RegistrationCommunity",
        "lab3",
        [WalkerDefinition(Strategy.RandomWalk, 20, {"timeout": 3.0})],
        default_bootstrap_defs,
        {},
        [],
    )
    builder.add_overlay(
        "Lab3BlockchainCommunity",
        "lab3",
        [WalkerDefinition(Strategy.RandomWalk, 20, {"timeout": 3.0})],
        default_bootstrap_defs,
        {},
        [],
    )

    ipv8 = IPv8(
        builder.finalize(),
        extra_communities={
            "Lab3RegistrationCommunity": RegistrationCommunity,
            "Lab3BlockchainCommunity": BlockchainCommunity,
        },
    )
    await ipv8.start()

    registration_overlay = next(
        o for o in ipv8.overlays if isinstance(o, RegistrationCommunity)
    )
    blockchain_overlay = next(
        o for o in ipv8.overlays if isinstance(o, BlockchainCommunity)
    )

    state = BlockchainState()
    blockchain_overlay.set_state(state)
    blockchain_overlay.set_target_pubkeys(teammate_keys)
    # server_public_key is already set inside BlockchainCommunity.__init__.

    logger.info(
        "Lab3Node started: pubkey=%s community=%s teammates=%d",
        local_pubkey_hex[:16],
        community_id_hex,
        len(teammates),
    )

    # Part C will add node.start_mining()/start_catchup() as register_task
    # loops here.

    return Lab3Node(
        ipv8=ipv8,
        registration_overlay=registration_overlay,
        blockchain_overlay=blockchain_overlay,
        state=state,
        local_pubkey_hex=local_pubkey_hex,
    )
