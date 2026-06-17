"""IPv8 wiring for both Lab 3 overlays.

Builds a single IPv8 instance that hosts both the RegistrationCommunity and
the BlockchainCommunity, wires up the shared BlockchainState, and returns a
Lab3Node dataclass that the CLI and tests can interact with.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

from ipv8.configuration import (
    ConfigBuilder,
    Strategy,
    WalkerDefinition,
)
from ipv8_service import IPv8

from lab1_pow_ipv8.libsodium_bootstrap import ensure_libsodium
from lab2_relay_race.keyutil import extract_public_key_hex
from lab2_relay_race.team import load_team_config
from lab2_relay_race.udp_prep import get_primary_outbound_ip

from .block import block_hash, mine_block_candidate
from .chain import BlockchainState
from .community import build_blockchain_community
from .constants import (
    DEFAULT_BLOCKCHAIN_COMMUNITY_ID_HEX,
    DEFAULT_DIFFICULTY,
    REQUIRED_CONFIRMATIONS,
)
from .discovery import DEFAULT_BOOTSTRAP_CONFIG, load_seed_addresses, seed_walk_loop
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
    _mining_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _catchup_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _discovery_task: asyncio.Task | None = field(default=None, init=False, repr=False)


def _has_pending_work(node: Lab3Node) -> bool:
    """True if there is any transaction that still needs mining/confirming.

    We mine only when there is work to do (option ii: idle until the server's
    test transaction arrives). "Work" means some known transaction is either:

    * still in the mempool (not yet in a block), or
    * already in a block but buried under fewer than REQUIRED_CONFIRMATIONS
      blocks (needs more confirmation blocks on top).

    Once every known transaction is buried >= REQUIRED_CONFIRMATIONS deep, there
    is nothing left to do and the miner goes idle.
    """
    if node.state.mempool:
        return True
    for tx_hash in node.state.transactions_by_hash:
        # A tx on the main chain needs REQUIRED_CONFIRMATIONS blocks stacked on
        # top of it. confirmations() counts blocks above the tx block, so the
        # tx block itself is 0 and we keep mining until it reaches the target.
        if node.state.is_on_main_chain(tx_hash):
            if node.state.confirmations(tx_hash) < REQUIRED_CONFIRMATIONS:
                return True
    return False


async def _mine_one_block(node: Lab3Node) -> bool:
    """Mine a single block on the current tip, off the event loop.

    Returns True if a block was found, accepted and gossiped. The blocking PoW
    search runs in a thread-pool executor so status/catch-up handlers stay
    responsive. We abort early if the tip changes (a teammate's block arrived),
    so we never waste time extending a stale tip.
    """
    BATCH = 200_000
    MAX_NONCE = 2**64 - 1
    loop = asyncio.get_event_loop()

    tip_at_start = node.state.tip_hash
    tx_hashes = node.state.snapshot_mempool()
    candidate = node.state.build_candidate_block(
        tx_hashes=tx_hashes,
        timestamp=int(time.time()),
        difficulty=DEFAULT_DIFFICULTY,
        nonce=0,
    )

    # Start the nonce search at a random offset so that three nodes building an
    # identical candidate (same tip, same per-second timestamp, same mempool)
    # don't all converge on the exact same block. They still converge on one
    # chain via fork-choice, but this reduces redundant simultaneous wins.
    start_nonce = random.randrange(0, 2**32)
    while start_nonce <= MAX_NONCE:
        if node.state.tip_hash != tip_at_start:
            return False  # tip moved; rebuild candidate on the new tip
        end_nonce = min(start_nonce + BATCH, MAX_NONCE)
        try:
            block = await loop.run_in_executor(
                None,
                lambda s=start_nonce, e=end_nonce: mine_block_candidate(
                    height=candidate.height,
                    prev_hash=candidate.prev_hash,
                    tx_hashes=candidate.tx_hashes,
                    timestamp=candidate.timestamp,
                    difficulty=candidate.difficulty,
                    start_nonce=s,
                    max_nonce=e,
                ),
            )
        except RuntimeError:
            start_nonce = end_nonce + 1
            await asyncio.sleep(0)  # yield between batches
            continue

        result = node.state.add_block(block)
        if result.accepted:
            became_tip = node.state.tip_hash == result.block_hash
            logger.info(
                "MINED block #%d %s (%d tx) | %s | height=%d tip=%s",
                block.height,
                result.block_hash.hex()[:8],
                len(block.tx_hashes),
                "new tip" if became_tip else "side branch",
                node.state.height(),
                node.state.tip_hash.hex()[:12],
            )
            node.blockchain_overlay.gossip_block(block)
            return True
        logger.warning("Mined block rejected by own state: %s", result.reason)
        return False

    return False


async def _mining_loop(node: Lab3Node) -> None:
    """Mine on demand: idle until a transaction needs work, then confirm it.

    Per our group convention (option ii), nodes do NOT mine empty blocks while
    waiting. They sit idle at genesis until the server submits its test
    transaction. Once a transaction is pending, every node races to mine it in
    and then stacks confirmation blocks until it is buried
    REQUIRED_CONFIRMATIONS deep, after which mining goes idle again. This keeps
    the chain minimal (genesis -> tx block -> 3 confirmations) and trivially
    consistent across all three nodes.
    """
    logger.info("Mining loop started (idle until a transaction arrives)")
    announced_idle = False
    while True:
        if not _has_pending_work(node):
            if not announced_idle:
                logger.info(
                    "No pending transactions - mining idle at height %d",
                    node.state.height(),
                )
                announced_idle = True
            await asyncio.sleep(0.5)
            continue

        announced_idle = False
        try:
            await _mine_one_block(node)
        except Exception as exc:  # noqa: BLE001 - keep the miner alive
            logger.error("Error during mining: %s", exc, exc_info=True)
            await asyncio.sleep(0.5)


async def _catchup_loop(node: Lab3Node) -> None:
    """Every second, reconcile chain state with teammates.

    Also emits a one-line chain summary whenever our tip changes, giving a clean
    timeline of how the chain grew and converged without per-second spam.
    """
    logger.info("Catch-up loop started")
    request_id = 0
    last_tip = None
    while True:
        try:
            await asyncio.sleep(1.0)
            request_id += 1
            if node.state.tip_hash != last_tip:
                logger.info(
                    "CHAIN height=%d tip=%s | %s",
                    node.state.height(),
                    node.state.tip_hash.hex()[:12],
                    node.blockchain_overlay._chain_summary(),
                )
                last_tip = node.state.tip_hash
            node.blockchain_overlay.broadcast_status_request(request_id)
        except Exception as e:
            logger.error("Error in catch-up loop: %s", e, exc_info=True)


async def build_node(
    *,
    key_file: str,
    team_config_path: str,
    community_id_hex: str = DEFAULT_BLOCKCHAIN_COMMUNITY_ID_HEX,
    ipv8_port: int | None = None,
    bootstrap_config: str = DEFAULT_BOOTSTRAP_CONFIG,
    discovery_timeout: float = 120.0,
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
    # NOTE: empty bootstrapper list ([]) on purpose. We do not use IPv8's formal
    # bootstrappers (which blacklist their addresses and hide them from
    # get_peers); instead we walk_to seed addresses ourselves via seed_walk_loop,
    # so the server and teammates are all discovered as normal peers and filtered
    # by public key.
    builder.add_overlay(
        "Lab3RegistrationCommunity",
        "lab3",
        [WalkerDefinition(Strategy.RandomWalk, 20, {"timeout": 3.0})],
        [],
        {},
        [],
    )
    builder.add_overlay(
        "Lab3BlockchainCommunity",
        "lab3",
        [WalkerDefinition(Strategy.RandomWalk, 20, {"timeout": 3.0})],
        [],
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

    # Set local endpoint for peer discovery (required for IPv8 to find us)
    if ipv8_port:
        local_ip = get_primary_outbound_ip()
        blockchain_overlay.set_local_endpoint(local_ip, ipv8_port)
        logger.info("Local endpoint set to %s:%d", local_ip, ipv8_port)

    logger.info(
        "Lab3Node started: pubkey=%s community=%s teammates=%d",
        local_pubkey_hex[:16],
        community_id_hex,
        len(teammates),
    )

    node = Lab3Node(
        ipv8=ipv8,
        registration_overlay=registration_overlay,
        blockchain_overlay=blockchain_overlay,
        state=state,
        local_pubkey_hex=local_pubkey_hex,
    )

    # Start seed-based discovery: periodically walk to bootstrap seed addresses
    # on BOTH overlays. The server introduces our nodes to each other, and the
    # server itself becomes a normal verified peer (filtered by pubkey later).
    seeds = load_seed_addresses(bootstrap_config)
    node._discovery_task = asyncio.create_task(
        seed_walk_loop([registration_overlay, blockchain_overlay], seeds)
    )

    # Wait for all teammates to be discovered (in the blockchain community)
    # before starting consensus. This is a hard prerequisite: there is no point
    # mining or running catch-up until our peers are actually reachable.
    logger.info("Waiting for peer discovery (timeout=%.0fs)...", discovery_timeout)
    if not await blockchain_overlay.wait_for_teammate_peers(timeout=discovery_timeout):
        logger.error(
            "Peer discovery timed out: not all teammates found. "
            "Mining/catch-up will NOT start. Check connectivity / bootstrap config."
        )
        return node

    logger.info("All teammates discovered - starting mining and catch-up loops")
    node._mining_task = asyncio.create_task(_mining_loop(node))
    node._catchup_task = asyncio.create_task(_catchup_loop(node))
    return node
