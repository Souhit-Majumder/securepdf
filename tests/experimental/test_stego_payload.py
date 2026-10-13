"""
Tests for experimental steganographic watermark payload serialization, framing,
sync detection, CRC-32 validation, and capacity calculations.
"""
import secrets
import pytest

from experimental.config import STEGO_VERSION, SYNC_PREAMBLE, SYNC_PREAMBLE_BITS
from experimental.payload import (
    InsufficientCapacityError,
    StegoPayloadError,
    WatermarkPayload,
)


def test_payload_creation_valid():
    doc_uid = "DOC-TEST-001"
    rec_uid = "STU-ALICE-123"
    nonce = secrets.token_bytes(16)
    hmac_tag = secrets.token_bytes(32)  # Full 256-bit tag

    payload = WatermarkPayload(
        document_uid=doc_uid,
        recipient_uid=rec_uid,
        nonce=nonce,
        hmac_tag=hmac_tag,
    )

    assert payload.document_uid == doc_uid
    assert payload.recipient_uid == rec_uid
    assert payload.nonce == nonce
    assert payload.hmac_tag == hmac_tag
    assert payload.version == STEGO_VERSION
    assert len(payload.hmac_tag) == 32
    assert len(payload.nonce) == 16


def test_payload_invalid_nonce_or_hmac():
    doc_uid = "DOC-001"
    rec_uid = "STU-001"

    # Nonce too short
    with pytest.raises(StegoPayloadError, match="Nonce must be exactly 16 bytes"):
        WatermarkPayload(doc_uid, rec_uid, b"short_nonce", secrets.token_bytes(32))

    # HMAC truncated (e.g. 8 bytes / 64 bits instead of 32 bytes / 256 bits)
    with pytest.raises(StegoPayloadError, match="HMAC tag must be exactly 32 bytes"):
        WatermarkPayload(doc_uid, rec_uid, secrets.token_bytes(16), b"truncated_tag_64b")


def test_payload_serialization_round_trip():
    doc_uid = "DOC-MATH-101"
    rec_uid = "STU-BOB-999"
    nonce = secrets.token_bytes(16)
    hmac_tag = secrets.token_bytes(32)

    payload = WatermarkPayload(doc_uid, rec_uid, nonce, hmac_tag)
    raw_bytes = payload.to_bytes()

    assert raw_bytes.startswith(SYNC_PREAMBLE)
    recovered = WatermarkPayload.from_bytes(raw_bytes)

    assert recovered.document_uid == doc_uid
    assert recovered.recipient_uid == rec_uid
    assert recovered.nonce == nonce
    assert recovered.hmac_tag == hmac_tag
    assert recovered.version == payload.version


def test_payload_crc32_tamper_detection():
    payload = WatermarkPayload("DOC-01", "STU-01", secrets.token_bytes(16), secrets.token_bytes(32))
    raw = bytearray(payload.to_bytes())

    # Mutate a byte in the body (after the 4-byte sync preamble, before the 4-byte CRC)
    raw[8] ^= 0xFF

    with pytest.raises(StegoPayloadError, match="CRC-32 mismatch"):
        WatermarkPayload.from_bytes(bytes(raw))


def test_payload_sync_preamble_missing():
    payload = WatermarkPayload("DOC-01", "STU-01", secrets.token_bytes(16), secrets.token_bytes(32))
    raw = bytearray(payload.to_bytes())
    raw[:4] = b"NOPE"

    with pytest.raises(StegoPayloadError, match="Data does not begin with sync preamble"):
        WatermarkPayload.from_bytes(bytes(raw))


def test_calculate_required_bits():
    doc_uid = "DOC-01"
    rec_uid = "STU-01"
    payload = WatermarkPayload(doc_uid, rec_uid, secrets.token_bytes(16), secrets.token_bytes(32))

    expected_bits = payload.total_bits
    calc_bits = WatermarkPayload.calculate_required_bits(doc_uid, rec_uid)

    assert calc_bits == expected_bits
    assert calc_bits == len(payload.to_bits())


def test_insufficient_capacity_error():
    err = InsufficientCapacityError(required_bits=664, available_bits=200)
    assert err.required_bits == 664
    assert err.available_bits == 200
    assert "deficit: 464 bits" in str(err)


def test_find_and_decode_from_bits_with_noise():
    doc_uid = "DOC-SYLLABUS-2026"
    rec_uid = "STU-RESEARCHER-01"
    payload = WatermarkPayload(doc_uid, rec_uid, secrets.token_bytes(16), secrets.token_bytes(32))
    payload_bits = payload.to_bits()

    # Prepend and append arbitrary noise bits
    prefix_noise = "0100110011010101" * 5
    suffix_noise = "1110001010101010" * 5
    noisy_stream = prefix_noise + payload_bits + suffix_noise

    recovered = WatermarkPayload.find_and_decode_from_bits(noisy_stream)
    assert recovered is not None
    assert recovered.document_uid == doc_uid
    assert recovered.recipient_uid == rec_uid
    assert recovered.nonce == payload.nonce
    assert recovered.hmac_tag == payload.hmac_tag


def test_find_and_decode_from_bits_not_found():
    random_bits = "0101010011001101" * 20
    recovered = WatermarkPayload.find_and_decode_from_bits(random_bits)
    assert recovered is None
