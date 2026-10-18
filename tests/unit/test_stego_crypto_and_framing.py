import pytest

from app.pdf.stego.crypto import (
    derive_layer3_subkey,
    build_canonical_stego_message,
    generate_layer3_tag,
    verify_layer3_tag,
)
from app.pdf.stego.framing import (
    StegoPayload,
    StegoFramingError,
    parse_stego_bitstream,
)


def test_crypto_vector_1_zero_key():
    master_key = b"\x00" * 32
    doc_uid = "DOC-TEST-001"
    rec_uid = "REC-TEST-001"
    nonce = bytes.fromhex("0123456789abcdef0123456789abcdef")

    subkey = derive_layer3_subkey(master_key)
    assert subkey.hex() == "ad015a68897c443380e845461ce228ed40a6b4873e6ecb8af74232db6ef235dd"

    canonical_msg = build_canonical_stego_message(doc_uid, rec_uid, nonce)
    assert canonical_msg == b"SPDF-STEGO-V1|DOC-TEST-001|REC-TEST-001|0123456789abcdef0123456789abcdef"

    tag = generate_layer3_tag(subkey, doc_uid, rec_uid, nonce)
    assert tag.hex() == "fe181b51ec24e029ec966e4bf7f64aa6f60ceb3962af1ada563d5d17a9fa06c0"

    assert verify_layer3_tag(subkey, doc_uid, rec_uid, nonce, tag) is True
    # Tampered tag fails
    bad_tag = bytes.fromhex("00" * 32)
    assert verify_layer3_tag(subkey, doc_uid, rec_uid, nonce, bad_tag) is False


def test_crypto_vector_2_sequential_key():
    master_key = bytes(range(32))
    doc_uid = "DOC-PROD-2026-X"
    rec_uid = "STU-SEC-9988-Y"
    nonce = bytes.fromhex("fedcba9876543210fedcba9876543210")

    subkey = derive_layer3_subkey(master_key)
    assert subkey.hex() == "e2c8d3b148cc96434eae7ae64b39dd2e9d923938b4ab5a072dab4bf0bce2d17f"

    canonical_msg = build_canonical_stego_message(doc_uid, rec_uid, nonce)
    assert canonical_msg == b"SPDF-STEGO-V1|DOC-PROD-2026-X|STU-SEC-9988-Y|fedcba9876543210fedcba9876543210"

    tag = generate_layer3_tag(subkey, doc_uid, rec_uid, nonce)
    assert tag.hex() == "c37008e0c7e86284b958befd438dd5647f0511d9e7b527af6ff4e0213cdb8d8e"

    assert verify_layer3_tag(subkey, doc_uid, rec_uid, nonce, tag) is True


def test_framing_round_trip():
    nonce = b"\x01" * 16
    tag = b"\x02" * 32
    payload = StegoPayload(
        document_uid="DOC-123",
        recipient_uid="STU-456",
        nonce=nonce,
        hmac_tag=tag,
    )

    data = payload.to_bytes()
    assert data.startswith(b"SPDF")

    recovered = StegoPayload.from_bytes(data)
    assert recovered.document_uid == "DOC-123"
    assert recovered.recipient_uid == "STU-456"
    assert recovered.nonce == nonce
    assert recovered.hmac_tag == tag


def test_framing_capacity_calculation():
    # 59 fixed + 7 ("DOC-123") + 7 ("STU-456") = 73 bytes = 584 bits
    req = StegoPayload.calculate_required_bits("DOC-123", "STU-456")
    assert req == 73 * 8
    assert req == 584


def test_bitstream_scanner():
    nonce = b"\x05" * 16
    tag = b"\x06" * 32
    payload = StegoPayload(
        document_uid="DOC-TEST",
        recipient_uid="STU-TEST",
        nonce=nonce,
        hmac_tag=tag,
    )
    bits = payload.to_bits()

    # Prepend and append random noise bits
    noisy_bits = "0011010101" + bits + "111000111"
    parsed = parse_stego_bitstream(noisy_bits)

    assert parsed.frame_detected is True
    assert parsed.crc_valid is True
    assert parsed.payload is not None
    assert parsed.payload.document_uid == "DOC-TEST"
    assert parsed.payload.recipient_uid == "STU-TEST"


def test_framing_crc_tamper_fails():
    nonce = b"\x07" * 16
    tag = b"\x08" * 32
    payload = StegoPayload(
        document_uid="DOC-X",
        recipient_uid="STU-Y",
        nonce=nonce,
        hmac_tag=tag,
    )
    data = bytearray(payload.to_bytes())
    # Corrupt last CRC byte
    data[-1] ^= 0xFF

    with pytest.raises(StegoFramingError, match="CRC-32 mismatch"):
        StegoPayload.from_bytes(bytes(data))
