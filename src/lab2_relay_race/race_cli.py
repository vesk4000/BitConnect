"""CLI entrypoint for the Lab 2 relay race."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .keyutil import extract_public_key_hex
from .race import RaceSettings, run_relay_race
from .team import TeamConfig, load_team_config
from .udp_prep import PeerEndpoint


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lab 2: Relay race client")
    parser.add_argument(
        "--pem",
        default="lab1_identity.pem",
        help="PEM file path for your IPv8 private key",
    )
    parser.add_argument(
        "--team-config",
        default="lab2_team.json",
        help="Lab 2 team config with explicit A/B/C role order",
    )
    parser.add_argument(
        "--udp-port",
        type=int,
        required=True,
        help="Local UDP port for teammate relay traffic",
    )
    parser.add_argument(
        "--discovery-timeout",
        type=float,
        default=300.0,
        help="Seconds to wait for teammate endpoint discovery",
    )
    parser.add_argument(
        "--server-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for Lab 2 server discovery",
    )
    parser.add_argument(
        "--peer",
        action="append",
        default=[],
        help=(
            "Manual teammate endpoint as ROLE=host:port, e.g. B=127.0.0.1:5001. "
            "Repeat for the other two roles to bypass teammate IPv8 discovery."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def parse_manual_peers(
    peer_args: list[str],
    team_config: TeamConfig,
    local_pubkey_hex: str,
) -> dict[str, PeerEndpoint] | None:
    if not peer_args:
        return None

    members_by_role = {member.role: member for member in team_config.members}
    local_member = team_config.local_member(local_pubkey_hex)
    peers: dict[str, PeerEndpoint] = {}

    for item in peer_args:
        if "=" not in item:
            raise ValueError("--peer must be in ROLE=host:port form")
        role, endpoint = item.split("=", 1)
        role = role.strip().upper()
        if role not in members_by_role:
            raise ValueError(f"Unknown Lab 2 role in --peer: {role}")
        if ":" not in endpoint:
            raise ValueError(f"--peer endpoint must be host:port, got {endpoint!r}")
        host, port_text = endpoint.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError(f"Invalid port in --peer {item!r}") from exc
        if not host or port <= 0 or port > 65535:
            raise ValueError(f"Invalid endpoint in --peer {item!r}")

        member = members_by_role[role]
        if member.pubkey_hex == local_member.pubkey_hex:
            continue
        if member.pubkey_hex in peers:
            raise ValueError(f"Duplicate --peer endpoint for role {role}")
        peers[member.pubkey_hex] = PeerEndpoint(member.pubkey_hex, host, port)

    missing = [
        member.role
        for member in team_config.teammates(local_pubkey_hex)
        if member.pubkey_hex not in peers
    ]
    if missing:
        raise ValueError(
            "Missing --peer endpoint(s) for teammate role(s): " + ", ".join(missing)
        )
    return peers


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.getLogger("ipv8.community").setLevel(logging.CRITICAL)

    try:
        team_config = load_team_config(args.team_config)
        local_pubkey = extract_public_key_hex(args.pem)
        manual_peers = parse_manual_peers(args.peer, team_config, local_pubkey)
        outcome = asyncio.run(
            run_relay_race(
                RaceSettings(
                    key_file=args.pem,
                    udp_port=args.udp_port,
                    team_config=team_config,
                    manual_peers=manual_peers,
                    discovery_timeout=args.discovery_timeout,
                    server_peer_timeout=args.server_timeout,
                )
            )
        )
    except KeyboardInterrupt:
        print("Interrupted by user", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if outcome.final_result is None:
        print(
            f"[lab2] Node {outcome.local_role}: submitted round, no result before timeout"
        )
        return 0
    status = "ACCEPTED" if outcome.final_result.success else "REJECTED"
    print(f"[lab2] Node {outcome.local_role}: {status}: {outcome.final_result.message}")
    return 0 if outcome.final_result.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
