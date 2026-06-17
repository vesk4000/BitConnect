"""Command-line entrypoint for the Lab 3 blockchain node (``lab3-node``).

Starts a full IPv8 node with both the registration overlay and the blockchain
overlay, optionally registers the group with the Lab 3 server, then blocks
until interrupted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from .constants import DEFAULT_BLOCKCHAIN_COMMUNITY_ID_HEX
from .discovery import DEFAULT_BOOTSTRAP_CONFIG
from .registration import register_blockchain
from .service import build_node

logger = logging.getLogger(__name__)


class _JunkPacketFilter(logging.Filter):
    """Drop IPv8's noisy ``PacketDecodingError`` tracebacks.

    The public IPv8 network is full of nodes running old/incompatible protocol
    versions. Their introduction packets fail signature verification, and IPv8
    logs every one as an ERROR with a full traceback. These are expected and
    harmless - we simply cannot (and should not) verify foreign signatures - so
    we filter out only these specific records while leaving every other log
    intact. Valid packets are unaffected: this only suppresses records whose
    message is the packet-handling exception carrying an invalid signature.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "Exception occurred while handling packet" in msg and (
            "invalid signature" in msg or "PacketDecodingError" in msg
        ):
            return False
        return True


async def run(args: argparse.Namespace) -> None:
    """Build and start the node, optionally register, then run forever."""
    node = await build_node(
        key_file=args.pem,
        team_config_path=args.team_config,
        community_id_hex=args.community_id_hex,
        ipv8_port=args.ipv8_port,
        bootstrap_config=args.bootstrap_config,
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
    parser.add_argument(
        "--bootstrap-config",
        default=DEFAULT_BOOTSTRAP_CONFIG,
        help="Path to JSON list of bootstrap seed addresses "
        "(default: the bootstrap_servers.json shipped in the package)",
    )

    args = parser.parse_args()
    # Fall back to the recovered group_id file if --group-id was not given.
    if args.register and not args.group_id:
        try:
            saved = json.loads(Path("lab2_group_id.json").read_text(encoding="utf-8"))
            args.group_id = str(saved["group_id"])
        except (OSError, KeyError, json.JSONDecodeError):
            parser.error(
                "--group-id is required when --register is set "
                "(or run: uv run python -m lab3_blockchain.recover_group_id)"
            )
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Suppress the expected flood of foreign invalid-signature packet errors.
    _junk_filter = _JunkPacketFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(_junk_filter)

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
