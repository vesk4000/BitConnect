from hashlib import sha256

import pytest
from ipv8.keyvault.crypto import default_eccrypto

from lab1_pow_ipv8.libsodium_bootstrap import ensure_libsodium
from lab3_blockchain import transaction
from lab3_blockchain.transaction import (
    UINT64_MAX,
    Transaction,
    timestamp_bytes,
    transaction_hash,
    transaction_preimage,
    transaction_signature_message,
    verify_transaction_signature,
)


def test_lab3_transaction_module_imports():
    assert transaction is not None


def test_timestamp_bytes_are_unsigned_big_endian():
    assert timestamp_bytes(0) == b"\x00" * 8
    assert timestamp_bytes(1) == b"\x00" * 7 + b"\x01"
    assert timestamp_bytes(0x0102030405060708) == bytes.fromhex("0102030405060708")
    assert timestamp_bytes(UINT64_MAX) == b"\xff" * 8


def test_transaction_preimage_matches_lab3_layout():
    tx = Transaction(
        sender_key=b"sender",
        data=b"payload",
        timestamp=42,
        signature=b"signature",
    )

    assert transaction_preimage(tx) == (
        b"sender" + b"payload" + (42).to_bytes(8, "big") + b"signature"
    )


def test_transaction_hash_matches_sha256_of_preimage():
    tx = Transaction(
        sender_key=b"sender",
        data=b"payload",
        timestamp=123456,
        signature=b"signature",
    )

    assert transaction_hash(tx) == sha256(transaction_preimage(tx)).digest()


def test_transaction_signature_message_excludes_signature():
    tx = Transaction(
        sender_key=b"sender",
        data=b"payload",
        timestamp=42,
        signature=b"signature",
    )

    assert transaction_signature_message(tx) == (
        b"sender" + b"payload" + (42).to_bytes(8, "big")
    )


@pytest.mark.parametrize("timestamp", [-1, UINT64_MAX + 1])
def test_timestamp_rejects_values_outside_uint64(timestamp):
    with pytest.raises(ValueError):
        timestamp_bytes(timestamp)


@pytest.mark.parametrize("timestamp", [1.5, "123", True])
def test_timestamp_rejects_non_integer_values(timestamp):
    with pytest.raises(TypeError):
        timestamp_bytes(timestamp)


def test_transaction_rejects_non_bytes_fields():
    with pytest.raises(TypeError, match="sender_key"):
        Transaction(
            sender_key="sender",  # type: ignore[arg-type]
            data=b"payload",
            timestamp=0,
            signature=b"signature",
        )


def test_verify_transaction_signature_accepts_ipv8_signature():
    private_key, public_key = _generate_key_pair()
    tx = _signed_transaction(private_key, public_key, b"payload", 42)

    assert verify_transaction_signature(tx)


@pytest.mark.parametrize(
    "field_name,replacement",
    [
        ("data", b"tampered"),
        ("timestamp", 43),
        ("signature", b"\x00" * 64),
    ],
)
def test_verify_transaction_signature_rejects_tampering(field_name, replacement):
    private_key, public_key = _generate_key_pair()
    tx = _signed_transaction(private_key, public_key, b"payload", 42)
    tampered = Transaction(
        sender_key=tx.sender_key,
        data=replacement if field_name == "data" else tx.data,
        timestamp=replacement if field_name == "timestamp" else tx.timestamp,
        signature=replacement if field_name == "signature" else tx.signature,
    )

    assert not verify_transaction_signature(tampered)


def test_verify_transaction_signature_rejects_invalid_public_key():
    tx = Transaction(
        sender_key=b"not an ipv8 public key",
        data=b"payload",
        timestamp=42,
        signature=b"signature",
    )

    assert not verify_transaction_signature(tx)


def _generate_key_pair():
    ensure_libsodium()
    private_key = default_eccrypto.generate_key("curve25519")
    return private_key, private_key.pub().key_to_bin()


def _signed_transaction(
    private_key,
    public_key: bytes,
    data: bytes,
    timestamp: int,
) -> Transaction:
    unsigned = Transaction(
        sender_key=public_key,
        data=data,
        timestamp=timestamp,
        signature=b"",
    )
    signature = default_eccrypto.create_signature(
        private_key,
        transaction_signature_message(unsigned),
    )
    return Transaction(
        sender_key=public_key,
        data=data,
        timestamp=timestamp,
        signature=signature,
    )
