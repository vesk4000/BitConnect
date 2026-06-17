# Lab 3 — Proof-of-Work Blockchain over IPv8

A three-node Proof-of-Work blockchain built on [py-ipv8](https://github.com/Tribler/py-ipv8).
Each teammate runs one `lab3-node`. The nodes discover one another and the Lab 3
server, accept a signed test transaction from the server, mine it into a block,
stack confirmation blocks on top, gossip blocks and transactions between
themselves, and converge on a single canonical chain. The server periodically
queries all three nodes and grades the chain against five checks.

This document covers **how to run** the code (locally and across three
laptops), and **how it works** — the architecture, the wire protocol, the
consensus design, and the decisions behind them.

---

## 1. How to run

### Prerequisites

This repo uses the [uv](https://docs.astral.sh/uv/) package manager:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

Then sync dependencies once from the repo root:

```bash
uv lock
uv sync
```

Each member needs their Ed25519 key from Lab 1 (a `.pem` file) and the shared
`lab2_team.json`, which lists all three members' public keys in canonical
A/B/C order (the files in `pubkeys/`).

### 1a. Run all three nodes locally (single machine)

The quickest way to test consensus end-to-end is the local runner, which
starts all three nodes as subprocesses on ports `5010/5011/5012`, prefixes
their output, and writes per-node logs to the repo root:

```bash
uv run lab3-run-local
```

- Press **Ctrl+C** to stop all nodes (the runner kills the whole process tree,
  so no node is left holding its UDP port).
- Pass a number to auto-stop after N seconds, e.g. `uv run lab3-run-local 60`.
- Logs are written to `vesk_node.log`, `miro_node.log`, `daniel_node.log`.

The runner has node A (`VESK`) register with the server automatically, loading
the group ID from `lab2_group_id.json` (see §1c). The key files and ports it
uses are defined near the bottom of
[`src/lab3_blockchain/run_lab3_nodes.py`](../src/lab3_blockchain/run_lab3_nodes.py);
edit that list to match your own key filenames.

### 1b. Run across three laptops (real network)

On each laptop, from the repo root, run a single node. Every member uses
**their own** key file but the **same** `lab2_team.json`:

```bash
# Laptop A
uv run lab3-node --pem lab1_identity.pem --ipv8-port 5010

# Laptop B
uv run lab3-node --pem miro_key.pem --ipv8-port 5011

# Laptop C
uv run lab3-node --pem daniel.pem --ipv8-port 5012
```

The `--ipv8-port` is optional (IPv8 picks one if omitted), but pinning it makes
firewall rules easier. **No IP addresses are configured anywhere** — discovery
is automatic (see §4). The nodes find each other through a shared bootstrap
seed (the Lab 3 server), so all three just need outbound UDP to the internet.

Once all three are up and have discovered each other (you'll see
`All N teammates discovered!` in each log), any **one** member registers the
group (see below). You only register from a single laptop.

### 1c. Register with the server

Registration tells the server which community to join and triggers it to submit
the test transaction. The server identifies your group by the **Lab 2
group ID**. If you saved it, pass it directly:

```bash
uv run lab3-node --pem lab1_identity.pem --ipv8-port 5010 --register --group-id <YOUR_GROUP_ID>
```

If you don't have the group ID handy, recover it from the Lab 2 server (it is
idempotent — re-registering the same trio returns the same ID) and save it to
`lab2_group_id.json`:

```bash
uv run python -m lab3_blockchain.recover_group_id --pem lab1_identity.pem
```

After that, `--register` with **no** `--group-id` auto-loads the saved ID, which
is exactly what the local runner relies on.

> **Re-registering is allowed at any time** and resets the server's retry
> counter. The pass is sticky: once the server records a pass, re-registering
> never un-does it (it just replies `already passed`).

### 1d. Lab 3 node options

| Flag | Default | Meaning |
|---|---|---|
| `--pem <path>` | `lab1_identity.pem` | Local Ed25519 key file |
| `--team-config <path>` | `lab2_team.json` | A/B/C members + public keys |
| `--community-id-hex <hex>` | `ArcanumLab3Chain2026` | Blockchain community ID |
| `--ipv8-port <int>` | auto | UDP port for IPv8 |
| `--register` | off | Register the group with the Lab 3 server |
| `--group-id <id>` | from `lab2_group_id.json` | Lab 2 group ID (needed with `--register`) |
| `--bootstrap-config <path>` | packaged `bootstrap_servers.json` | Discovery seed list |
| `--debug` | off | DEBUG-level logging |

---

## 2. What the server checks (grading)

The server grades the chain returned by your three nodes during one attempt
against five checks (from the spec):

1. **Transaction accepted** — the node receiving the server's *Submit
   Transaction* replies `success = True`.
2. **Chain integrity** — every block has a valid PoW for its declared
   `difficulty`, and each block's `prev_hash` matches its parent's `block_hash`.
3. **Body commitment** — recomputed `SHA256(tx_hash_1 || … || tx_hash_n)` over
   the test transaction's block equals that block's `txs_hash`.
4. **Confirmations** — the test transaction is **buried under at least 3
   blocks** on every node (i.e. ≥3 blocks stacked on top of its block).
5. **Consistency** — all three nodes agree on the same `block_hash` at every
   confirmed height.

One registration triggers an initial attempt plus up to **3 automatic
retries**; you pass if **any** attempt clears all five checks. You do not need a
fresh chain per attempt — a single growing, consistent chain satisfies every
attempt.

---

## 3. Chain primitives

The pure data layer has no networking and is fully unit-tested.

### Block header — [`block.py`](../src/lab3_blockchain/block.py)

A block hash is `SHA256` over an **84-byte header** packed big-endian
(`struct` format `">32s32sQIQ"`):

| Field | Bytes | Type |
|---|---|---|
| `prev_hash` | 32 | parent block hash |
| `txs_hash` | 32 | `SHA256` over the concatenated tx hashes |
| `timestamp` | 8 | uint64 big-endian |
| `difficulty` | 4 | uint32 big-endian (leading-zero-bit target) |
| `nonce` | 8 | uint64 big-endian |

- `txs_hash(tx_hashes) = SHA256(tx_hash_1 || … || tx_hash_n)`; for an empty
  block this is `SHA256(b"")`, **not** 32 zero bytes.
- PoW is satisfied when `block_hash` has at least `difficulty` leading zero
  **bits** (`leading_zero_bits` / `has_valid_pow`).
- `mine_block_candidate(...)` searches a nonce range and returns the first block
  meeting the target, or raises if the range is exhausted.

The `Block` dataclass deliberately does **not** store its hash — the hash is
always derived, so a block can never carry a hash that disagrees with its
contents.

### Transactions — [`transaction.py`](../src/lab3_blockchain/transaction.py)

- `tx_hash = SHA256(sender_key || data || timestamp_8byte_be || signature)`.
- The **signed message** is `sender_key || data || timestamp_8byte_be` (the
  signature is not part of what's signed).
- `verify_transaction_signature` checks the Ed25519 signature against the
  embedded IPv8 public key, returning `False` on any error rather than raising.

### Genesis — [`chain.py`](../src/lab3_blockchain/chain.py)

All nodes boot from a single deterministic genesis block:
`height 0, prev_hash = 32 × 0x00, tx_hashes = (), timestamp 0, difficulty 0,
nonce 0`. Because the header is fixed, every node computes the identical
`GENESIS_HASH`, which satisfies the spec's "agree on block 0" requirement for
free.

### Chain state & fork choice — [`chain.py`](../src/lab3_blockchain/chain.py)

`BlockchainState` stores a **block tree**, not just a single chain:

- `blocks_by_hash`, `children_by_hash`, and a `hash_by_height` index for the
  current main chain.
- `orphans_by_prev_hash` holds blocks whose parent hasn't arrived yet.

`add_block`:

1. Validates the block (PoW for its declared difficulty, known parent, correct
   height). Unknown-parent blocks are stored as **orphans**.
2. Inserts it into the tree and re-evaluates the tip via `_is_better_tip`.
3. **Attaches waiting orphans iteratively** using an explicit work queue —
   never recursion. (Syncing a long chain can chain-attach hundreds of orphans;
   recursion would overflow the Python stack. This was a real bug that the
   work-queue refactor fixed.)

**Fork-choice rule** (`_is_better_tip`) is deterministic:

```
higher block height wins;
on equal height, the lexicographically smaller block_hash wins.
```

Because the rule is a pure function of the block tree, any two nodes holding the
same set of blocks independently select the **same** tip — this is what makes
consensus converge (see §5).

The mempool is reconciled on every tip change
(`_reconcile_mempool_after_tip_change`): transactions that fall off an abandoned
fork return to the mempool, and transactions on the new main chain are removed.

`confirmations(tx_hash)` returns the number of blocks stacked **on top of** the
transaction's block (tx-in-tip = 0). This matches the grader's "buried under N
blocks" wording, so reaching `REQUIRED_CONFIRMATIONS = 3` means 3 blocks above
the tx block.

---

## 4. Networking & discovery

### Two overlays, one node — [`service.py`](../src/lab3_blockchain/service.py)

A single IPv8 instance hosts two communities on the same UDP port:

- **Registration community** (`Lab3RegistrationCommunity`) — talks to the
  server's registration endpoint.
- **Blockchain community** (`Lab3BlockchainCommunity`) — answers server queries
  and gossips transactions/blocks with teammates.

Both extend [`Lab3Community`](../src/lab3_blockchain/ipv8_base.py), which
provides identity predicates and peer helpers.

### Trust boundaries

Every handler filters by public key before acting:

- **Server messages** (`SubmitTransaction`, `GetChainHeight`, `GetBlock`) are
  accepted only from the peer whose key equals the published Lab 3 server key
  (`_is_server`).
- **Peer-gossip messages** are accepted only from peers listed in
  `target_pubkeys`, i.e. the teammates from `lab2_team.json` (`_is_teammate`).
- **Block payloads** additionally pass through
  [`codec.py`](../src/lab3_blockchain/codec.py), which re-derives and compares
  both `block_hash` and `txs_hash` before the block reaches `BlockchainState`.
  A forged or corrupted block is dropped at this boundary.

`Lab3Community._verify_signature` also silences `UnsupportedAlgorithm` from the
public IPv8 network (peers advertising key curves the local `cryptography`
build can't verify) so one junk packet can't abort handling for the whole
overlay.

### Discovery without live bootstrap servers — [`discovery.py`](../src/lab3_blockchain/discovery.py)

The public IPv8/Tribler bootstrap servers are effectively dead, and we
deliberately avoid hardcoding teammate IPs. The solution:

- We keep a configurable list of **seed addresses**
  ([`bootstrap_servers.json`](../src/lab3_blockchain/bootstrap_servers.json),
  shipped inside the package): the historical Tribler seeds plus the Lab 3
  server.
- We do **not** register these as IPv8 *formal* bootstrappers
  (`BootstrapperDefinition`), because IPv8 blacklists bootstrap addresses and
  hides them from `get_peers()`. Instead, `seed_walk_loop` calls `walk_to(addr)`
  ourselves, so the server and teammates all appear as **normal verified peers**
  that we then filter purely by public key.
- **Cross-pollination:** addresses discovered in *either* overlay are walked-to
  in *both*. Since both overlays share the node's UDP port, an address learned
  in the registration community is reachable in the blockchain community too.
  This is how the server (which lives in the registration community) introduces
  our three nodes to each other inside the blockchain community — without the
  server having to join that overlay.

Dead seeds are harmless: they simply never respond. Any live bootstrap server
in our community would work; the professor's server just happens to be the one
currently alive. This keeps the design portable — on a real network the three
laptops only need outbound UDP.

### Startup sequence (`build_node`)

1. Build IPv8 with both overlays (empty formal bootstrapper lists).
2. Wire the shared `BlockchainState`, teammate keys, and server key.
3. Start `seed_walk_loop` on both overlays.
4. **Block until all teammates are discovered** in the blockchain community.
   There is no point mining or running catch-up before peers are reachable —
   and registering before all three are up is a known way to waste an attempt.
5. Start the mining loop and the catch-up loop.

---

## 5. Consensus (Part C)

Two background loops drive consensus, both in
[`service.py`](../src/lab3_blockchain/service.py).

### Mining loop (`_mining_loop`, on-demand)

By group convention the nodes do **not** mine empty blocks while idle. They sit
at genesis until the server submits the test transaction. `_has_pending_work`
then reports work to do while either:

- a transaction is still in the mempool (not yet in a block), or
- a transaction is on the main chain but buried under fewer than
  `REQUIRED_CONFIRMATIONS` blocks.

For each block, `_mine_one_block` runs the blocking nonce search in a
thread-pool executor (`run_in_executor`) so status/catch-up handlers stay
responsive, and aborts early if the tip moves under it (a teammate's block
arrived). It starts the nonce search at a **random offset** so three nodes
building an identical candidate (same tip, same per-second timestamp, same
mempool) don't all mine the exact same block. Once the transaction is buried
`REQUIRED_CONFIRMATIONS` deep, mining goes idle again.

Result: a minimal, trivially consistent chain — `genesis → tx block → 3 empty
confirmation blocks` (tip at height 4).

### Catch-up loop (`_catchup_loop`) + status handlers

Every second, each node broadcasts a `PeerStatusRequest` to its teammates. On
the reply (`on_peer_status_response`), if the peer's tip hash differs from ours
at all, we request the peer's **entire main chain** (`PeerBlockRequest` for
heights `1..peer_height`). Every block received is fed into our local tree;
duplicates are ignored by hash, and missing branches fill in.

This is the key simplification: we never do a fragile, multi-round-trip
ancestor walk-back. **One status exchange pulls the peer's whole chain**, both
trees become supersets that contain each other's blocks, and the deterministic
fork-choice rule (§3) independently picks the **same** canonical tip on every
node. Trees converge regardless of fork depth.

### Why this converges

Consensus here = *same block tree + deterministic fork choice*. Catch-up's only
job is to make the trees converge; once two nodes hold the same set of blocks,
`_is_better_tip` guarantees they choose the identical tip. Forks (e.g. two nodes
mining height-1 blocks simultaneously) are resolved automatically: both blocks
end up in every tree, and the smaller-hash tie-break selects one winner
everywhere.

---

## 6. Wire protocol

Message IDs — [`ids.py`](../src/lab3_blockchain/ids.py); payloads —
[`protocol.py`](../src/lab3_blockchain/protocol.py). Server-path IDs are low
(1–6) to match the server; peer-gossip IDs are in the 200 range to avoid
clashing with the server's IDs in the shared community.

### Registration community

| ID | Payload | Direction | Fields |
|---|---|---|---|
| 1 | `RegisterBlockchain` | → server | `group_id`, `community_id` |
| 2 | `RegisterResponse` | ← server | `success`, `message` |

### Blockchain community — server path

| ID | Payload | Direction | Fields |
|---|---|---|---|
| 1 | `SubmitTransaction` | ← server | `sender_key`, `data`, `timestamp`, `signature` |
| 2 | `SubmitTransactionResponse` | → server | `success`, `tx_hash`, `message` |
| 3 | `GetChainHeight` | ← server | `request_id` |
| 4 | `ChainHeightResponse` | → server | `request_id`, `height`, `tip_hash` |
| 5 | `GetBlock` | ← server | `height` |
| 6 | `BlockResponse` | → server | full block fields |

### Blockchain community — peer gossip

| ID | Payload | Purpose |
|---|---|---|
| 200 | `PeerTransaction` | gossip a signed transaction |
| 201 | `PeerBlock` | gossip a mined block |
| 202 | `PeerStatusRequest` | "what's your tip?" (catch-up heartbeat) |
| 203 | `PeerStatusResponse` | `height`, `tip_hash` |
| 204 | `PeerBlockRequest` | "send me the block at height H" |
| 205 | `PeerBlockResponse` | full block fields |

Block payloads carry the flat `tx_hashes` blob (concatenated 32-byte hashes)
plus the derived `txs_hash` and `block_hash`; the codec re-verifies both on
receipt.

---

## 7. Logging & diagnostics

Because all three nodes can run on one machine, the logs are designed to make
consensus and server interaction observable at a glance (INFO level):

- Every **server message** logs its type, contents, our reply, and our current
  chain inline, e.g.
  `<<< SERVER GetChainHeight(req=…) | replied height=4 tip=… | chain=#0:…→#4:…`.
- **Mining**, **applied peer blocks**, and **tip changes** each log once.
- **Tip mismatches** log once per distinct divergence (deduped) rather than
  every second.
- A `CHAIN height=… tip=… | #0→#1→…` summary prints only when the tip changes,
  giving a clean timeline without per-second spam.
- Routine peer-discovery churn is at DEBUG, off by default.

The recurring junk-packet errors from the public IPv8 network are suppressed by
a logging filter in [`cli.py`](../src/lab3_blockchain/cli.py) (not by editing
the library).

---

## 8. File map

| File | Responsibility |
|---|---|
| `block.py` | Header packing, hashing, PoW, nonce search |
| `transaction.py` | Transaction hashing + Ed25519 signature verification |
| `chain.py` | Block tree, validation, fork choice, mempool, confirmations |
| `codec.py` | Trust-boundary (de)serialisation; re-verifies hashes |
| `protocol.py` / `ids.py` | IPv8 payloads and message IDs |
| `ipv8_base.py` | Shared community: identity checks, peer helpers |
| `registration.py` | Registration community + retrying `register_blockchain` |
| `community.py` | Blockchain community: all server/peer handlers, gossip |
| `service.py` | IPv8 wiring + the mining and catch-up loops (`build_node`) |
| `discovery.py` | Seed-walk discovery with cross-pollination |
| `cli.py` | `lab3-node` entry point |
| `run_lab3_nodes.py` | Local three-node runner (`lab3-run-local`) |
| `recover_group_id.py` | One-shot Lab 2 group-ID recovery |
| `constants.py` | Community IDs, server key, difficulty, confirmations |

Tests live in `tests/test_lab3_*.py` (block, chain, codec, community, protocol,
registration, transaction). Run them with `uv run pytest tests/ -q`.
