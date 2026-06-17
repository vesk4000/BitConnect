"""Seed-based peer discovery for Lab 3.

The public IPv8 bootstrap servers (Tribler/Dispersy) are frequently offline,
so we cannot rely on IPv8's built-in bootstrapping to find the Lab 3 server or
our teammates. Instead we keep a configurable list of *seed addresses* and
periodically ``walk_to`` each of them.

Crucially, we do **not** register these as IPv8 "formal" bootstrappers
(``BootstrapperDefinition``). Doing so causes IPv8 to blacklist them, hiding
them from ``get_peers()``. By walking to them ourselves, every node we reach -
the server and our teammates alike - becomes a normal verified peer that we
then filter purely by public key / community. This keeps the design uniform:
the professor's server is just one entry in the seed list; in principle any
working bootstrap server in our community would introduce us to the rest.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from dataclasses import dataclass
from pathlib import Path

from ipv8.messaging.interfaces.udp.endpoint import UDPv4Address

logger = logging.getLogger(__name__)

# Ships inside the package so it works from any working directory.
DEFAULT_BOOTSTRAP_CONFIG = str(Path(__file__).with_name("bootstrap_servers.json"))


@dataclass(frozen=True)
class SeedAddress:
    """A bootstrap seed we walk to. *host* may be a domain or an IP."""

    host: str
    port: int


def load_seed_addresses(
    config_path: str = DEFAULT_BOOTSTRAP_CONFIG,
) -> list[SeedAddress]:
    """Load seed addresses from the JSON config file.

    Returns an empty list (with a warning) if the file is missing or malformed,
    so a node can still run - it just won't discover anyone until seeds exist.
    """
    path = Path(config_path)
    if not path.is_file():
        logger.warning(
            "Bootstrap config %s not found; no seed addresses loaded", config_path
        )
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = raw["bootstrap_servers"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read bootstrap config %s: %s", config_path, exc)
        return []

    seeds: list[SeedAddress] = []
    for entry in entries:
        try:
            seeds.append(SeedAddress(str(entry["host"]), int(entry["port"])))
        except (KeyError, TypeError, ValueError):
            logger.warning("Skipping malformed bootstrap entry: %r", entry)
    logger.info("Loaded %d bootstrap seed address(es) from %s", len(seeds), config_path)
    return seeds


def resolve_seeds(seeds: list[SeedAddress]) -> list[UDPv4Address]:
    """Resolve seed hostnames to UDPv4 addresses, skipping ones that fail.

    Dead/unresolvable seeds (e.g. defunct Tribler DNS) are simply dropped -
    they would never respond to a walk anyway.
    """
    resolved: list[UDPv4Address] = []
    seen: set[tuple[str, int]] = set()
    for seed in seeds:
        try:
            ip = socket.gethostbyname(seed.host)
        except OSError as exc:
            logger.debug("Could not resolve seed %s:%d (%s)", seed.host, seed.port, exc)
            continue
        key = (ip, seed.port)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(UDPv4Address(ip, seed.port))
    # DEBUG, not INFO: this runs on every re-resolve round and is pure noise
    # once discovery has settled.
    logger.debug("Resolved %d/%d seed address(es)", len(resolved), len(seeds))
    return resolved


async def seed_walk_loop(
    overlays: list,
    seeds: list[SeedAddress],
    *,
    interval: float = 5.0,
    reresolve_every: int = 12,
) -> None:
    """Periodically walk every overlay to seed addresses and cross-pollinate peers.

    Runs forever. Each round:

    1. Walk every overlay to every resolved seed address (so the server, which
       lives in the registration community, introduces our nodes to each other).
    2. Cross-pollinate: collect the addresses of every peer discovered in *any*
       overlay and walk to them in *every* overlay. Because all overlays on a
       node share the same UDP port, an address learned in the registration
       community can be reached in the blockchain community too. This bridges
       teammates into the blockchain overlay (where blocks are gossiped) without
       requiring the server to join that overlay.

    Re-resolves DNS periodically so seeds that were down at startup can still be
    picked up later.

    Args:
        overlays: IPv8 community overlays to drive discovery on.
        seeds: Seed addresses (domains/IPs + ports) to walk to.
        interval: Seconds between walk rounds.
        reresolve_every: Re-resolve DNS every N rounds.
    """
    if not seeds:
        logger.warning("seed_walk_loop: no seeds configured; discovery disabled")
        return

    resolved = resolve_seeds(seeds)
    round_no = 0
    while True:
        if round_no % reresolve_every == 0 and round_no > 0:
            resolved = resolve_seeds(seeds) or resolved

        # 1. Walk to seed addresses on every overlay.
        for overlay in overlays:
            for addr in resolved:
                try:
                    overlay.walk_to(addr)
                except Exception as exc:  # noqa: BLE001 - never let discovery die
                    logger.debug("walk_to seed %s failed: %s", addr, exc)

        # 2. Cross-pollinate discovered peer addresses across all overlays.
        discovered: set = set()
        for overlay in overlays:
            for peer in overlay.get_peers():
                discovered.add(peer.address)
        for overlay in overlays:
            for addr in discovered:
                try:
                    overlay.walk_to(addr)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("walk_to peer %s failed: %s", addr, exc)

        round_no += 1
        await asyncio.sleep(interval)
