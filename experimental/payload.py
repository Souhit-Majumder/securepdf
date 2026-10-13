"""
Payload encoding, decoding, serialization, and framing for the experimental watermarking prototype.
Encodes full 256-bit HMAC-SHA256 tags without truncation, with CRC-32 integrity validation.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Optional

from experimental.config import STEGO_VERSION, SYNC_PREAMBLE, SYNC_PREAMBLE_BITS


class StegoPayloadError(Exception):
    """Raised when payload serialization, framing, or deserialization fails."""
    pass


class InsufficientCapacityError(StegoPayloadError):
    """Raised when the document cannot accommodate the full payload."""
    def __init__(self, required_bits: int, available_bits: int):
        super().__init__(
            f"Document capacity insufficient: requires {required_bits} word gaps, "
            f"but document only has {available_bits} word gaps "
            f"(deficit: {required_bits - available_bits} bits)."
        )
        self.required_bits = required_bits
        self.available_bits = available_bits


@dataclass(frozen=True)
class FrameDecodeResult:
    frame_detected: bool
    frame_offset: Optional[int]
    payload: Optional[WatermarkPayload]
    crc_valid: bool
    payload_decoded: bool
    candidate_bits: Optional[str]
    error_message: Optional[str]


@dataclass(frozen=True)
class WatermarkPayload:
    document_uid: str
    recipient_uid: str
    nonce: bytes             # 16 bytes
    hmac_tag: bytes          # 32 bytes (full untruncated HMAC-SHA256)
    version: int = STEGO_VERSION

    def __post_init__(self):
        if len(self.nonce) != 16:
            raise StegoPayloadError(f"Nonce must be exactly 16 bytes, got {len(self.nonce)}")
        if len(self.hmac_tag) != 32:
            raise StegoPayloadError(f"HMAC tag must be exactly 32 bytes (full SHA-256), got {len(self.hmac_tag)}")
        if not self.document_uid or len(self.document_uid.encode("utf-8")) > 255:
            raise StegoPayloadError(f"Invalid document_uid length: {len(self.document_uid)}")
        if not self.recipient_uid or len(self.recipient_uid.encode("utf-8")) > 255:
            raise StegoPayloadError(f"Invalid recipient_uid length: {len(self.recipient_uid)}")

    def to_bytes(self) -> bytes:
        """
        Serializes payload to binary format:
        [SYNC 4B][VERSION 1B][DOC_LEN 1B][DOC_BYTES][REC_LEN 1B][REC_BYTES][NONCE 16B][HMAC 32B][CRC32 4B]
        """
        doc_b = self.document_uid.encode("utf-8")
        rec_b = self.recipient_uid.encode("utf-8")

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
        """Serializes payload to bitstring '010101...'."""
        b = self.to_bytes()
        return "".join(f"{byte:08b}" for byte in b)

    @property
    def total_bits(self) -> int:
        return len(self.to_bytes()) * 8

    @classmethod
    def calculate_required_bits(cls, document_uid: str, recipient_uid: str) -> int:
        """Calculates exact number of bits/word gaps required for given identifiers."""
        doc_len = len(document_uid.encode("utf-8"))
        rec_len = len(recipient_uid.encode("utf-8"))
        # 4 (sync) + 1 (ver) + 1 (doc_len) + doc_len + 1 (rec_len) + rec_len + 16 (nonce) + 32 (hmac) + 4 (crc)
        total_bytes = 4 + 1 + 1 + doc_len + 1 + rec_len + 16 + 32 + 4
        return total_bytes * 8

    @classmethod
    def from_bytes(cls, data: bytes) -> WatermarkPayload:
        """Deserializes payload from raw bytes, verifying sync preamble and CRC-32."""
        if len(data) < len(SYNC_PREAMBLE) + 1 + 1 + 1 + 16 + 32 + 4:
            raise StegoPayloadError(f"Data too short ({len(data)} bytes) for valid payload")

        if not data.startswith(SYNC_PREAMBLE):
            raise StegoPayloadError("Data does not begin with sync preamble")

        payload_and_crc = data[len(SYNC_PREAMBLE):]
        if len(payload_and_crc) < 4:
            raise StegoPayloadError("Missing CRC-32")

        body = payload_and_crc[:-4]
        expected_crc = struct.unpack(">I", payload_and_crc[-4:])[0]
        actual_crc = zlib.crc32(body) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise StegoPayloadError(f"CRC-32 mismatch: expected 0x{expected_crc:08X}, computed 0x{actual_crc:08X}")

        offset = 0
        version, doc_len = struct.unpack(">BB", body[offset:offset + 2])
        offset += 2

        if version != STEGO_VERSION:
            raise StegoPayloadError(f"Unsupported stego version: {version}")

        if offset + doc_len > len(body):
            raise StegoPayloadError("Truncated document UID")
        doc_uid = body[offset:offset + doc_len].decode("utf-8")
        offset += doc_len

        rec_len = body[offset]
        offset += 1
        if offset + rec_len > len(body):
            raise StegoPayloadError("Truncated recipient UID")
        rec_uid = body[offset:offset + rec_len].decode("utf-8")
        offset += rec_len

        if offset + 16 + 32 > len(body):
            raise StegoPayloadError("Truncated nonce or HMAC")
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

    @classmethod
    def find_and_decode_detailed(cls, bits: str) -> FrameDecodeResult:
        """
        Scans a bit sequence, searches for sync preamble, and evaluates decoding stages:
        preamble detection, CRC-32 validation, and payload field parsing.
        """
        sync_bits = SYNC_PREAMBLE_BITS
        idx = bits.find(sync_bits)
        if idx == -1:
            return FrameDecodeResult(
                frame_detected=False,
                frame_offset=None,
                payload=None,
                crc_valid=False,
                payload_decoded=False,
                candidate_bits=None,
                error_message="Sync preamble 'SPDF' not found in bitstream",
            )

        start = 0
        saw_preamble = False
        first_preamble_idx = None

        while True:
            idx = bits.find(sync_bits, start)
            if idx == -1:
                break

            if first_preamble_idx is None:
                first_preamble_idx = idx
            saw_preamble = True

            candidate_bits = bits[idx:]
            min_bits = (len(SYNC_PREAMBLE) + 1 + 1 + 1 + 16 + 32 + 4) * 8
            if len(candidate_bits) < min_bits:
                start = idx + 1
                continue

            num_bytes = len(candidate_bits) // 8
            byte_arr = bytearray()
            for b_i in range(num_bytes):
                chunk = candidate_bits[b_i * 8:(b_i + 1) * 8]
                byte_arr.append(int(chunk, 2))

            for candidate_len in range(len(SYNC_PREAMBLE) + 60, num_bytes + 1):
                raw_chunk = bytes(byte_arr[:candidate_len])
                if len(raw_chunk) >= len(SYNC_PREAMBLE) + 4:
                    body = raw_chunk[len(SYNC_PREAMBLE):-4]
                    expected_crc = struct.unpack(">I", raw_chunk[-4:])[0]
                    actual_crc = zlib.crc32(body) & 0xFFFFFFFF
                    if actual_crc == expected_crc:
                        try:
                            payload = cls.from_bytes(raw_chunk)
                            return FrameDecodeResult(
                                frame_detected=True,
                                frame_offset=idx,
                                payload=payload,
                                crc_valid=True,
                                payload_decoded=True,
                                candidate_bits=candidate_bits[:payload.total_bits],
                                error_message=None,
                            )
                        except StegoPayloadError as err:
                            return FrameDecodeResult(
                                frame_detected=True,
                                frame_offset=idx,
                                payload=None,
                                crc_valid=True,
                                payload_decoded=False,
                                candidate_bits=candidate_bits[:candidate_len * 8],
                                error_message=f"CRC valid but body parsing failed: {err}",
                            )

            start = idx + 1

        return FrameDecodeResult(
            frame_detected=saw_preamble,
            frame_offset=first_preamble_idx,
            payload=None,
            crc_valid=False,
            payload_decoded=False,
            candidate_bits=bits[first_preamble_idx:] if first_preamble_idx is not None else None,
            error_message="Sync preamble detected, but CRC-32 validation failed on all candidate lengths",
        )

    @classmethod
    def find_and_decode_from_bits(cls, bits: str) -> Optional[WatermarkPayload]:
        """Convenience method returning decoded payload or None."""
        return cls.find_and_decode_detailed(bits).payload
