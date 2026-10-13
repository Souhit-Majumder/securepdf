"""
Cryptographic adapter for experimental watermarking.
Generates and authenticates full 256-bit HMAC-SHA256 signatures under an isolated experimental master key.
"""
from __future__ import annotations

import hmac
import os
import secrets
from hashlib import sha256
from pathlib import Path
from typing import Optional, Tuple

from experimental.config import DEFAULT_KEY_PATH, WORKING_DIR
from experimental.payload import WatermarkPayload


def get_or_create_experimental_key(key_path: Optional[Path] = None) -> bytes:
    """Retrieves or securely creates an isolated 256-bit experimental master key."""
    target_path = key_path if key_path is not None else DEFAULT_KEY_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists():
        with open(target_path, "rb") as f:
            key = f.read()
            if len(key) >= 32:
                return key[:32]

    # Generate 32 bytes (256 bits) of cryptographic entropy
    key = secrets.token_bytes(32)
    with open(target_path, "wb") as f:
        f.write(key)
    return key


def build_canonical_stego_message(doc_uid: str, recipient_uid: str, nonce: bytes) -> bytes:
    """Constructs unambiguous canonical message for HMAC-SHA256 signature."""
    return f"SPDF-STEGO-V1|{doc_uid}|{recipient_uid}|{nonce.hex()}".encode("utf-8")


def generate_watermark_payload(
    doc_uid: str,
    recipient_uid: str,
    key: bytes,
    nonce: Optional[bytes] = None,
) -> WatermarkPayload:
    """Generates an authenticated WatermarkPayload with full 256-bit HMAC-SHA256."""
    actual_nonce = nonce if nonce is not None else secrets.token_bytes(16)
    msg = build_canonical_stego_message(doc_uid, recipient_uid, actual_nonce)
    tag = hmac.new(key, msg, digestmod=sha256).digest()

    return WatermarkPayload(
        document_uid=doc_uid,
        recipient_uid=recipient_uid,
        nonce=actual_nonce,
        hmac_tag=tag,
    )


def verify_watermark_payload(payload: WatermarkPayload, key: bytes) -> Tuple[bool, str]:
    """
    Verifies the HMAC-SHA256 signature of a recovered payload.
    Returns (is_valid, reason).
    """
    expected_msg = build_canonical_stego_message(payload.document_uid, payload.recipient_uid, payload.nonce)
    expected_tag = hmac.new(key, expected_msg, digestmod=sha256).digest()

    if hmac.compare_digest(payload.hmac_tag, expected_tag):
        return True, "Valid HMAC-SHA256 authentication."
    return False, "HMAC-SHA256 mismatch (tampered payload or incorrect master key)."
