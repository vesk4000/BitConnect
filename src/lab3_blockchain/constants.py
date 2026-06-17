"""Lab 3 blockchain well-known constants shared across all communities."""

from __future__ import annotations

REGISTRATION_COMMUNITY_ID_HEX = "4c616233426c6f636b636861696e323032365057"
LAB3_SERVER_PUBLIC_KEY_HEX = "4c69624e61434c504b3ae3fc099fb56ca3b5e1de9a1c843387f2acdbb78b1bd4350ffde518068a0d246344b10d0d8c355fd0d76873e7d7f7838f3715e025af08f791324495e083331ce6"
DEFAULT_BLOCKCHAIN_COMMUNITY_ID_HEX = "417263616e756d4c616233436861696e32303236"
# PoW difficulty in leading zero bits. Chosen so a single block takes ~1-3s to
# mine on a typical laptop: fast enough for a snappy demo, slow enough that two
# nodes rarely produce blocks at the same height simultaneously (which keeps
# fork resolution - and therefore consensus - clean).
DEFAULT_DIFFICULTY = 19

# Number of blocks that must bury the server's test transaction before we treat
# it as final (matches the spec's "Required confirmations | 3").
REQUIRED_CONFIRMATIONS = 3
