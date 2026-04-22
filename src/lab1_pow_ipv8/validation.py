"""Validation helpers for email, URL, and nonce constraints."""

from __future__ import annotations

import unicodedata

from .constants import MAX_NONCE


def canonicalize_email(email: str) -> str:
    """
    Canonicalize email for identity binding (NFC, stripped, lowercased).
    """
    return unicodedata.normalize("NFC", email).strip().lower()


def validate_email(email: str) -> None:
    if not email:
        raise ValueError("Email must be non-empty")
    if "\n" in email or "\r" in email:
        raise ValueError("Email must not contain newline characters")
    email_bytes = email.encode("utf-8")
    if len(email_bytes) > 254:
        raise ValueError("Email must be at most 254 UTF-8 bytes")
    if "@" not in email or email.count("@") != 1:
        raise ValueError("Email must be a well-formed address")

    local, domain = email.rsplit("@", 1)
    if not local or not domain:
        raise ValueError("Email must contain a local part and a domain")
    if domain not in {"tudelft.nl", "student.tudelft.nl"}:
        raise ValueError(
            "Email domain must be either @tudelft.nl or @student.tudelft.nl"
        )


def validate_github_url(github_url: str) -> None:
    if not github_url:
        raise ValueError("GitHub URL must be non-empty")
    if any(ch.isspace() for ch in github_url):
        raise ValueError("GitHub URL must not contain whitespace")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in github_url):
        raise ValueError("GitHub URL must not contain control characters")
    url_bytes = github_url.encode("utf-8")
    if len(url_bytes) > 512:
        raise ValueError("GitHub URL must be at most 512 UTF-8 bytes")


def validate_nonce(nonce: int) -> None:
    if not isinstance(nonce, int):
        raise ValueError("Nonce must be an integer")
    if nonce < 0 or nonce > MAX_NONCE:
        raise ValueError("Nonce must be between 0 and 2^63 - 1")
