# Lab 1 – Proof of Work over IPv8

This repository contains a complete Python client for **CS4160 Lab 1**.

It can:

1. Mine a valid PoW for `(email, github_url, nonce)`
2. Join the IPv8 community for the lab
3. Discover peers and filter strictly on the server public key
4. Submit the signed payload
5. Receive and print the server response

## Project layout

- `src/lab1_pow_ipv8/pow.py` – PoW construction, validation and mining loop
- `src/lab1_pow_ipv8/validation.py` – email/url/nonce validation
- `src/lab1_pow_ipv8/protocol.py` – IPv8 message payloads (`msg_id=1` and `msg_id=2`)
- `src/lab1_pow_ipv8/client.py` – community + peer filtering + submission flow
- `src/lab1_pow_ipv8/main.py` – CLI entrypoint
- `tests/test_pow.py` – local tests for PoW correctness

## Setup

Create a virtual environment, install dependencies, and run tests.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pip install -e .
pytest -q
```

## Usage

Run the client from the project root:

```powershell
python -m lab1_pow_ipv8.main --email your.name@student.tudelft.nl --github-url https://github.com/you/bitconnect-lab1
```

### Useful flags

- `--key-file lab1_identity.pem` to persist/reuse your private key
- `--difficulty 28` (default for lab server)
- `--mine-only` mine and print nonce, but do not submit
- `--submit-only --nonce <N>` skip mining and only submit
- `--timeout 120` seconds to wait for server reply
- `--no-canonicalize-email` send/hash the email exactly as typed

## Notes and pitfalls

- Nonce encoding is 8-byte **big-endian** binary (not decimal text).
- PoW input is exactly: `email + "\n" + github_url + "\n" + nonce_u64_be`.
- The client ignores responses from peers whose public key does not match the given server key.
- Keep your `.pem` file safe: this is your identity for later labs.

## Troubleshooting

- If no server response arrives, ensure your packet is sent with IPv8 authenticated messaging (`ez_send`, as implemented).
- If you get invalid hash rejections, confirm you are hashing the exact same email/URL strings you submit.
- If dependency installation on Windows fails, ensure libsodium prerequisites for IPv8 are installed (see py-ipv8 docs).
