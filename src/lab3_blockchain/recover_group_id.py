"""Recover the Lab 2 group_id needed for Lab 3 registration.

The Lab 2 server assigns each 3-member team a ``group_id`` and returns it on
registration. Re-registering the same trio is idempotent: the server replies
``"Group already registered"`` and echoes back the *same* group_id. We exploit
that here to recover the id without re-running the full relay race.

This reuses the existing Lab 2 community (``build_lab2_community``) and its
``send_group_register`` / ``wait_for_registration_result`` methods. Because the
public IPv8 bootstrap servers are dead, we ``walk_to`` the known Lab 2 server
address directly instead of relying on discovery.

Run with:  uv run python -m lab3_blockchain.recover_group_id --pem <key.pem>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition
from ipv8.messaging.interfaces.udp.endpoint import UDPv4Address
from ipv8_service import IPv8

from lab1_pow_ipv8.libsodium_bootstrap import ensure_libsodium
from lab2_relay_race.community import build_lab2_community
from lab2_relay_race.team import load_team_config

LOGGER = logging.getLogger(__name__)

# Lab 2 server (same host as Lab 3, but the Lab 2 service is on port 8091).
LAB2_SERVER_HOST = "64.130.52.136"
LAB2_SERVER_PORT = 8091

GROUP_ID_FILE = "lab2_group_id.json"


async def recover_group_id(
    *,
    key_file: str,
    team_config_path: str,
    server_host: str = LAB2_SERVER_HOST,
    server_port: int = LAB2_SERVER_PORT,
    timeout: float = 60.0,
) -> str:
    """Register the team with the Lab 2 server and return the group_id."""
    ensure_libsodium()
    team = load_team_config(team_config_path)
    member_keys = team.registration_pubkey_bytes  # ordered A, B, C

    Lab2Community = build_lab2_community()
    builder = ConfigBuilder().clear_keys().clear_overlays()
    builder.add_key("lab2", "curve25519", key_file)
    builder.add_overlay(
        "Lab2Community",
        "lab2",
        [WalkerDefinition(Strategy.RandomWalk, 20, {"timeout": 3.0})],
        [],  # no formal bootstrappers; we walk to the server directly
        {},
        [],
    )
    ipv8 = IPv8(builder.finalize(), extra_communities={"Lab2Community": Lab2Community})
    await ipv8.start()
    try:
        overlay = next(o for o in ipv8.overlays if isinstance(o, Lab2Community))
        server_addr = UDPv4Address(server_host, server_port)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        LOGGER.info("Walking to Lab 2 server at %s:%d ...", server_host, server_port)
        while loop.time() < deadline:
            overlay.walk_to(server_addr)
            server_peer = overlay.find_server_peer()
            if server_peer is None:
                await asyncio.sleep(1.0)
                continue

            LOGGER.info("Discovered Lab 2 server; sending group registration")
            overlay.send_group_register(server_peer, member_keys)
            result = await overlay.wait_for_registration_result(3.0)
            if result is None:
                continue  # retry: resend registration
            if not result.success:
                raise RuntimeError(f"Registration rejected: {result.message}")
            LOGGER.info("Server response: %s", result.message)
            return result.group_id

        raise TimeoutError("Timed out recovering group_id from Lab 2 server")
    finally:
        await ipv8.stop()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="recover-group-id",
        description="Recover the Lab 2 group_id by re-registering the team",
    )
    parser.add_argument("--pem", default="lab1_identity.pem", help="Local PEM key file")
    parser.add_argument(
        "--team-config", default="lab2_team.json", help="Path to team JSON config"
    )
    parser.add_argument(
        "--out", default=GROUP_ID_FILE, help="Where to save the recovered group_id"
    )
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # The dead public bootstrap network floods logs with invalid-signature errors.
    logging.getLogger("Lab2Community").setLevel(logging.CRITICAL)

    try:
        group_id = asyncio.run(
            recover_group_id(key_file=args.pem, team_config_path=args.team_config)
        )
    except (RuntimeError, TimeoutError) as exc:
        print(f"ERROR: {exc}")
        return 1

    Path(args.out).write_text(
        json.dumps({"group_id": group_id}, indent=2), encoding="utf-8"
    )
    print("\n" + "=" * 60)
    print(f"  Recovered group_id: {group_id}")
    print(f"  Saved to: {args.out}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
