"""Command-line entrypoint for the Lab 3 blockchain node (``lab3-node``).

Starts a full IPv8 node with both the registration overlay and the blockchain
overlay, optionally registers the group with the Lab 3 server, then blocks
until interrupted.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from .constants import DEFAULT_BLOCKCHAIN_COMMUNITY_ID_HEX
from .registration import register_blockchain
from .service import build_node

logger = logging.getLogger(__name__)


async def run(args: argparse.Namespace) -> None:
    """Build and start the node, optionally register, then run forever."""
    node = await build_node(
        key_file=args.pem,
        team_config_path=args.team_config,
        community_id_hex=args.community_id_hex,
        ipv8_port=args.ipv8_port,
    )

    teammate_count = len(
        node.blockchain_overlay.target_pubkeys  # type: ignore[union-attr]
    )
    logger.info(
        "Node started: pubkey=%s community=%s teammates=%d",
        node.local_pubkey_hex[:32],
        args.community_id_hex,
        teammate_count,
    )

    if args.register:
        result = await register_blockchain(
            node.registration_overlay,
            args.group_id,
            bytes.fromhex(args.community_id_hex),
        )
        logger.info("Registration result: %s", result)

    try:
        # Block indefinitely until a KeyboardInterrupt or OS signal.
        await asyncio.Event().wait()
    finally:
        await node.ipv8.stop()


def main() -> int:
    """Parse arguments and run the Lab 3 blockchain node."""
    parser = argparse.ArgumentParser(
        prog="lab3-node",
        description="Lab 3 blockchain node — registers and participates in consensus",
    )
    parser.add_argument(
        "--pem",
        default="lab1_identity.pem",
        help="Path to the local PEM key file (default: lab1_identity.pem)",
    )
    parser.add_argument(
        "--group-id",
        default=None,
        help="Group identifier for registration (required with --register)",
    )
    parser.add_argument(
        "--team-config",
        default="lab2_team.json",
        help="Path to the team JSON config (default: lab2_team.json)",
    )
    parser.add_argument(
        "--community-id-hex",
        default=DEFAULT_BLOCKCHAIN_COMMUNITY_ID_HEX,
        help="Hex-encoded blockchain community id",
    )
    parser.add_argument(
        "--ipv8-port",
        type=int,
        default=None,
        help="UDP port for IPv8 (default: IPv8 picks one)",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Register this group's blockchain community with the Lab 3 server",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG-level logging",
    )

    args = parser.parse_args()
    if args.register and not args.group_id:
        parser.error("--group-id is required when --register is set")
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
