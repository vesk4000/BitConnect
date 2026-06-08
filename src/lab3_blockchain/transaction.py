"""Transaction primitives for the Lab 3 blockchain."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .validation import UINT64_MAX, validate_bytes, validate_uint64


@dataclass(frozen=True)
class Transaction:
    """Transaction submitted by the Lab 3 server or gossiped by a peer."""

    sender_key: bytes
    data: bytes
    timestamp: int
    signature: bytes

    def __post_init__(self) -> None:
        validate_timestamp(self.timestamp)
        validate_bytes("sender_key", self.sender_key)
        validate_bytes("data", self.data)
        validate_bytes("signature", self.signature)


def validate_timestamp(timestamp: int) -> None:
    """Validate that a timestamp can be encoded as uint64 big-endian."""

    validate_uint64("timestamp", timestamp)


def timestamp_bytes(timestamp: int) -> bytes:
    """Return the Lab 3 8-byte unsigned big-endian timestamp encoding."""

    validate_timestamp(timestamp)
    return timestamp.to_bytes(8, byteorder="big", signed=False)


def transaction_preimage(transaction: Transaction) -> bytes:
    """Return the exact byte layout used for Lab 3 transaction hashes."""

    return (
        transaction.sender_key
        + transaction.data
        + timestamp_bytes(transaction.timestamp)
        + transaction.signature
    )


def transaction_signature_message(transaction: Transaction) -> bytes:
    """Return the exact byte layout signed by Lab 3 transaction senders."""

    return (
        transaction.sender_key
        + transaction.data
        + timestamp_bytes(transaction.timestamp)
    )


def transaction_hash(transaction: Transaction) -> bytes:
    """Compute SHA256(sender_key || data || timestamp_8byte_be || signature)."""

    return sha256(transaction_preimage(transaction)).digest()


def verify_transaction_signature(transaction: Transaction) -> bool:
    """Verify the transaction signature against the embedded IPv8 public key."""

    from lab1_pow_ipv8.libsodium_bootstrap import ensure_libsodium

    ensure_libsodium()

    from ipv8.keyvault.crypto import default_eccrypto

    try:
        public_key = default_eccrypto.key_from_public_bin(transaction.sender_key)
        return bool(
            default_eccrypto.is_valid_signature(
                public_key,
                transaction_signature_message(transaction),
                transaction.signature,
            )
        )
    except Exception:
        return False
