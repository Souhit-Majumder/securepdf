"""
Cryptographic subkey derivation and HMAC verification for Layer 3 steganographic carrier.
Domain separation label: b"SecurePDF-Layer3-Subkey-v1"
Canonical message: SPDF-STEGO-V1|{doc_uid}|{recipient_uid}|{nonce.hex()}
"""
from __future__ import annotations

import hashlib
import hmac


LAYER3_DOMAIN_LABEL = b"SecurePDF-Layer3-Subkey-v1"


def derive_layer3_subkey(master_key: bytes) -> bytes:
    """Derives an isolated 256-bit subkey for Layer 3 from the production master key."""
    return hmac.new(master_key, LAYER3_DOMAIN_LABEL, hashlib.sha256).digest()


def build_canonical_stego_message(doc_uid: str, recipient_uid: str, nonce: bytes) -> bytes:
    """Constructs the canonical byte message for Layer 3 HMAC authentication."""
    return f"SPDF-STEGO-V1|{doc_uid}|{recipient_uid}|{nonce.hex()}".encode("utf-8")


def generate_layer3_tag(subkey: bytes, doc_uid: str, recipient_uid: str, nonce: bytes) -> bytes:
    """Generates a 32-byte (256-bit) HMAC-SHA256 authentication tag."""
    msg = build_canonical_stego_message(doc_uid, recipient_uid, nonce)
    return hmac.new(subkey, msg, hashlib.sha256).digest()


def verify_layer3_tag(subkey: bytes, doc_uid: str, recipient_uid: str, nonce: bytes, expected_tag: bytes) -> bool:
    """Performs constant-time verification of the Layer 3 HMAC tag."""
    computed_tag = generate_layer3_tag(subkey, doc_uid, recipient_uid, nonce)
    return hmac.compare_digest(computed_tag, expected_tag)
