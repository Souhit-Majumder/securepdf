"""
Tests for experimental cryptographic adapter: isolated key generation,
canonical message framing, full HMAC-SHA256 signature and constant-time verification.
"""
import secrets
import pytest

from experimental.crypto_adapter import (
    build_canonical_stego_message,
    generate_watermark_payload,
    get_or_create_experimental_key,
    verify_watermark_payload,
)
from experimental.payload import WatermarkPayload


def test_get_or_create_experimental_key(tmp_path):
    key_file = tmp_path / "test_exp.key"
    assert not key_file.exists()

    key1 = get_or_create_experimental_key(key_file)
    assert len(key1) == 32
    assert key_file.exists()

    # Re-reading should return identical key
    key2 = get_or_create_experimental_key(key_file)
    assert key1 == key2


def test_build_canonical_stego_message():
    nonce = bytes.fromhex("0123456789abcdef0123456789abcdef")
    msg = build_canonical_stego_message("DOC-001", "STU-ALICE", nonce)
    expected = b"SPDF-STEGO-V1|DOC-001|STU-ALICE|0123456789abcdef0123456789abcdef"
    assert msg == expected


def test_generate_and_verify_watermark_payload():
    key = secrets.token_bytes(32)
    doc_uid = "DOC-RESEARCH-2026"
    rec_uid = "STU-MAJOR-007"

    payload = generate_watermark_payload(doc_uid, rec_uid, key)
    assert len(payload.hmac_tag) == 32
    assert len(payload.nonce) == 16

    is_valid, reason = verify_watermark_payload(payload, key)
    assert is_valid is True
    assert "Valid HMAC-SHA256" in reason


def test_verify_fails_with_wrong_key():
    key_alice = secrets.token_bytes(32)
    key_mallory = secrets.token_bytes(32)

    payload = generate_watermark_payload("DOC-1", "STU-1", key_alice)
    is_valid, reason = verify_watermark_payload(payload, key_mallory)

    assert is_valid is False
    assert "mismatch" in reason


def test_verify_fails_when_recipient_tampered():
    key = secrets.token_bytes(32)
    payload = generate_watermark_payload("DOC-1", "STU-ALICE", key)

    # Tampered payload attributing to Bob instead of Alice
    tampered_payload = WatermarkPayload(
        document_uid=payload.document_uid,
        recipient_uid="STU-BOB",
        nonce=payload.nonce,
        hmac_tag=payload.hmac_tag,
    )

    is_valid, reason = verify_watermark_payload(tampered_payload, key)
    assert is_valid is False
    assert "mismatch" in reason


def test_distinct_nonces_produce_distinct_tags():
    key = secrets.token_bytes(32)
    doc_uid = "DOC-1"
    rec_uid = "STU-ALICE"

    p1 = generate_watermark_payload(doc_uid, rec_uid, key)
    p2 = generate_watermark_payload(doc_uid, rec_uid, key)

    assert p1.nonce != p2.nonce
    assert p1.hmac_tag != p2.hmac_tag
