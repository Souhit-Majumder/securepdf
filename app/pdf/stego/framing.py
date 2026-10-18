"""
Binary framing, serialization, deserialization, and CRC-32 validation for Layer 3 steganographic payloads.
Wire Format:
[SYNC 4B][VERSION 1B][DOC_LEN 1B][DOC_BYTES][REC_LEN 1B][REC_BYTES][NONCE 16B][HMAC 32B][CRC32 4B]
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Optional


SYNC_PREAMBLE = b"SPDF"
SYNC_PREAMBLE_BITS = "".join(f"{b:08b}" for b in SYNC_PREAMBLE)
STEGO_VERSION = 1


class StegoFramingError(Exception):
    """Raised when payload serialization, framing, or deserialization fails."""
    pass


@dataclass(frozen=True)
class StegoPayload:
    document_uid: str
    recipient_uid: str
    nonce: bytes             # 16 bytes
    hmac_tag: bytes          # 32 bytes (HMAC-SHA256)
    version: int = STEGO_VERSION

    def __post_init__(self):
        if len(self.nonce) != 16:
            raise StegoFramingError(f"Nonce must be exactly 16 bytes, got {len(self.nonce)}")
        if len(self.hmac_tag) != 32:
            raise StegoFramingError(f"HMAC tag must be exactly 32 bytes, got {len(self.hmac_tag)}")
        doc_b = self.document_uid.strip().encode("utf-8")
        rec_b = self.recipient_uid.strip().encode("utf-8")
        if not (1 <= len(doc_b) <= 255):
            raise StegoFramingError(f"Invalid document_uid byte length: {len(doc_b)}")
        if not (1 <= len(rec_b) <= 255):
            raise StegoFramingError(f"Invalid recipient_uid byte length: {len(rec_b)}")

    def to_bytes(self) -> bytes:
        """Serializes payload into full binary frame with sync preamble and CRC-32."""
        doc_b = self.document_uid.strip().encode("utf-8")
        rec_b = self.recipient_uid.strip().encode("utf-8")

        body = (
            struct.pack(">BB", self.version, len(doc_b))
            + doc_b
            + struct.pack(">B", len(rec_b))
            + rec_b
            + self.nonce
            + self.hmac_tag
        )

        crc = zlib.crc32(body) & 0xFFFFFFFF
        return SYNC_PREAMBLE + body + struct.pack(">I", crc)

    def to_bits(self) -> str:
        """Converts serialized binary frame to bitstring '0101...'."""
        return "".join(f"{byte:08b}" for byte in self.to_bytes())

    @property
    def total_bits(self) -> int:
        return len(self.to_bytes()) * 8

    @classmethod
    def calculate_required_bits(cls, document_uid: str, recipient_uid: str) -> int:
        """Calculates exact required bits / word gaps based on UTF-8 byte lengths."""
        doc_len = len(document_uid.strip().encode("utf-8"))
        rec_len = len(recipient_uid.strip().encode("utf-8"))
        total_bytes = 4 + 1 + 1 + doc_len + 1 + rec_len + 16 + 32 + 4  # 59 + doc + rec
        return total_bytes * 8

    @classmethod
    def from_bytes(cls, data: bytes) -> StegoPayload:
        """Deserializes raw binary frame, validating preamble, bounds, and CRC-32."""
        min_len = 4 + 1 + 1 + 1 + 16 + 32 + 4  # 59 bytes
        if len(data) < min_len:
            raise StegoFramingError(f"Data too short ({len(data)} bytes) for valid frame")

        if not data.startswith(SYNC_PREAMBLE):
            raise StegoFramingError("Data does not begin with sync preamble")

        payload_and_crc = data[len(SYNC_PREAMBLE):]
        if len(payload_and_crc) < 4:
            raise StegoFramingError("Missing CRC-32")

        body = payload_and_crc[:-4]
        expected_crc = struct.unpack(">I", payload_and_crc[-4:])[0]
        actual_crc = zlib.crc32(body) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise StegoFramingError(f"CRC-32 mismatch: expected 0x{expected_crc:08X}, got 0x{actual_crc:08X}")

        offset = 0
        version, doc_len = struct.unpack(">BB", body[offset:offset + 2])
        offset += 2

        if version != STEGO_VERSION:
            raise StegoFramingError(f"Unsupported stego version: {version}")

        if offset + doc_len > len(body):
            raise StegoFramingError("Truncated document UID")
        doc_uid = body[offset:offset + doc_len].decode("utf-8")
        offset += doc_len

        if offset >= len(body):
            raise StegoFramingError("Missing recipient length")
        rec_len = body[offset]
        offset += 1

        if offset + rec_len > len(body):
            raise StegoFramingError("Truncated recipient UID")
        rec_uid = body[offset:offset + rec_len].decode("utf-8")
        offset += rec_len

        if offset + 16 + 32 > len(body):
            raise StegoFramingError("Truncated nonce or HMAC tag")
        nonce = body[offset:offset + 16]
        offset += 16
        hmac_tag = body[offset:offset + 32]
        offset += 32

        return cls(
            document_uid=doc_uid,
            recipient_uid=rec_uid,
            nonce=nonce,
            hmac_tag=hmac_tag,
            version=version,
        )


@dataclass(frozen=True)
class CandidateParseResult:
    frame_detected: bool
    crc_valid: bool
    payload: Optional[StegoPayload]
    error: Optional[str]


def parse_stego_bitstream(bits: str) -> CandidateParseResult:
    """Scans bitstream for SYNC_PREAMBLE, recovers candidate bytes, and validates CRC-32."""
    sync_bits = SYNC_PREAMBLE_BITS
    idx = bits.find(sync_bits)
    if idx == -1:
        return CandidateParseResult(frame_detected=False, crc_valid=False, payload=None, error="No sync preamble found")

    start = 0
    saw_preamble = False

    while True:
        idx = bits.find(sync_bits, start)
        if idx == -1:
            break
        saw_preamble = True

        candidate_bits = bits[idx:]
        min_bits = 59 * 8
        if len(candidate_bits) < min_bits:
            start = idx + 1
            continue

        num_bytes = len(candidate_bits) // 8
        byte_arr = bytearray(int(candidate_bits[b_i * 8:(b_i + 1) * 8], 2) for b_i in range(num_bytes))

        # Check candidate length from headers if present
        candidate_lengths: list[int] = []
        if num_bytes >= 7 and byte_arr[4] == STEGO_VERSION:
            doc_len = byte_arr[5]
            if num_bytes >= 7 + doc_len:
                rec_len = byte_arr[6 + doc_len]
                det_len = 59 + doc_len + rec_len
                if det_len <= num_bytes:
                    candidate_lengths.append(det_len)

        # Fallback bounded scan
        for c_len in range(59, min(num_bytes, 512) + 1):
            if c_len not in candidate_lengths:
                candidate_lengths.append(c_len)

        for candidate_len in candidate_lengths:
            raw_chunk = bytes(byte_arr[:candidate_len])
            if len(raw_chunk) >= 59:
                body = raw_chunk[4:-4]
                expected_crc = struct.unpack(">I", raw_chunk[-4:])[0]
                actual_crc = zlib.crc32(body) & 0xFFFFFFFF
                if actual_crc == expected_crc:
                    try:
                        payload = StegoPayload.from_bytes(raw_chunk)
                        return CandidateParseResult(
                            frame_detected=True,
                            crc_valid=True,
                            payload=payload,
                            error=None
                        )
                    except StegoFramingError as err:
                        return CandidateParseResult(
                            frame_detected=True,
                            crc_valid=True,
                            payload=None,
                            error=f"CRC valid but body parsing failed: {err}"
                        )

        start = idx + 1

    return CandidateParseResult(
        frame_detected=saw_preamble,
        crc_valid=False,
        payload=None,
        error="Sync preamble found, but CRC-32 validation failed on all candidates"
    )
