"""
Steganographic text-level watermark extraction and authentication.
Features primary stream-level kerning decoding and experimental geometric word-gap extraction.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import fitz

from experimental.config import MIN_KERNING_THRESHOLD
from experimental.crypto_adapter import get_or_create_experimental_key, verify_watermark_payload
from experimental.payload import StegoPayloadError, WatermarkPayload


@dataclass
class ExtractionResult:
    pdf_path: str
    status: str             # "AUTHENTICATED" | "INVALID_AUTHENTICATION" | "CRC_ERROR" | "NO_WATERMARK" | "ERROR"
    frame_detected: bool
    payload_decoded: bool
    crc_valid: bool
    hmac_valid: bool
    recipient_recovered: bool
    payload: Optional[WatermarkPayload]
    document_uid: Optional[str]
    recipient_uid: Optional[str]
    nonce_hex: Optional[str]
    bits_recovered: int
    raw_bits: str
    frame_offset: Optional[int]
    method_used: str
    reason: str


def _extract_bits_from_stream(stream: bytes, threshold: int = MIN_KERNING_THRESHOLD) -> str:
    """
    Parses content stream for TJ arrays and extracts bits from inter-word kerning numbers.
    Any kerning number preceding an explicit space `( )` is checked:
    If num <= threshold (e.g. -10): bit '1', else bit '0'.
    """
    bits = []
    i = 0
    n = len(stream)

    while i < n:
        if stream[i:i + 1] == b"[":
            i += 1
            last_number: Optional[int] = None

            while i < n and stream[i:i + 1] != b"]":
                while i < n and stream[i:i + 1] in b" \t\r\n":
                    i += 1
                if i >= n or stream[i:i + 1] == b"]":
                    break

                # String literal ( ... )
                if stream[i:i + 1] == b"(":
                    s_start = i
                    i += 1
                    depth = 1
                    while i < n and depth > 0:
                        if stream[i:i + 1] == b"\\" and i + 1 < n:
                            i += 2
                            continue
                        elif stream[i:i + 1] == b"(":
                            depth += 1
                        elif stream[i:i + 1] == b")":
                            depth -= 1
                        i += 1
                    raw_str = stream[s_start:i]
                    inner = raw_str[1:-1]

                    # If this is a space character `( )`, check preceding kerning number
                    if inner == b" ":
                        if last_number is not None:
                            bits.append("1" if last_number <= threshold else "0")
                        else:
                            bits.append("0")
                    last_number = None

                # Hex string
                elif stream[i:i + 1] == b"<":
                    i += 1
                    while i < n and stream[i:i + 1] != b">":
                        i += 1
                    if i < n:
                        i += 1
                    last_number = None

                # Number or token
                else:
                    t_start = i
                    while i < n and stream[i:i + 1] not in b" \t\r\n[]()<>":
                        i += 1
                    token = stream[t_start:i]
                    try:
                        last_number = int(token)
                    except ValueError:
                        try:
                            last_number = int(float(token))
                        except ValueError:
                            last_number = None

            if i < n and stream[i:i + 1] == b"]":
                i += 1
        else:
            i += 1

    return "".join(bits)


def _extract_bits_geometric(doc: fitz.Document) -> str:
    """
    Experimental geometric extraction: reads word bounding boxes and evaluates gap deltas.
    Uses adaptive bimodal thresholding based on the baseline natural word gap S0.
    Subject to floating-point rounding and zoom variations; treated strictly as an experimental alternative.
    """
    gaps_all = []
    for page in doc:
        words = page.get_text("words")
        if len(words) < 2:
            continue

        lines: dict[tuple[int, int], list] = {}
        for w in words:
            lines.setdefault((w[5], w[6]), []).append(w)

        for _, line_words in lines.items():
            if len(line_words) < 2:
                continue
            line_words.sort(key=lambda x: x[0])  # Sort by x0

            for j in range(len(line_words) - 1):
                gap = line_words[j + 1][0] - line_words[j][2]
                if 0.5 < gap < 30.0:
                    gaps_all.append(gap)

    if not gaps_all:
        return ""

    # Estimate natural gap S0 from 15th percentile of inter-word spacing
    sorted_gaps = sorted(gaps_all)
    p15 = sorted_gaps[int(len(sorted_gaps) * 0.15)]
    # Kerning delta is ~0.26 pt, so midpoint threshold is S0 + 0.13 pt
    thresh = p15 + 0.13

    bits = []
    for page in doc:
        words = page.get_text("words")
        if len(words) < 2:
            continue

        lines = {}
        for w in words:
            lines.setdefault((w[5], w[6]), []).append(w)

        for _, line_words in lines.items():
            if len(line_words) < 2:
                continue
            line_words.sort(key=lambda x: x[0])

            for j in range(len(line_words) - 1):
                gap = line_words[j + 1][0] - line_words[j][2]
                if 0.5 < gap < 30.0:
                    bits.append("1" if gap > thresh else "0")

    return "".join(bits)


def extract_watermark(
    pdf_path: str | Path,
    key: Optional[bytes] = None,
    use_geometric_fallback: bool = False,
) -> ExtractionResult:
    """
    Extracts and authenticates steganographic watermark from a PDF file.
    Primary: Content-stream kerning parsing.
    Secondary: Experimental geometric word-gap extraction.
    """
    path = Path(pdf_path)
    if not path.exists():
        return ExtractionResult(
            pdf_path=str(path),
            status="ERROR",
            frame_detected=False,
            payload_decoded=False,
            crc_valid=False,
            hmac_valid=False,
            recipient_recovered=False,
            payload=None,
            document_uid=None,
            recipient_uid=None,
            nonce_hex=None,
            bits_recovered=0,
            raw_bits="",
            frame_offset=None,
            method_used="none",
            reason=f"File not found: {path}",
        )

    actual_key = key if key is not None else get_or_create_experimental_key()

    try:
        doc = fitz.open(str(path))
    except Exception as err:
        return ExtractionResult(
            pdf_path=str(path),
            status="ERROR",
            frame_detected=False,
            payload_decoded=False,
            crc_valid=False,
            hmac_valid=False,
            recipient_recovered=False,
            payload=None,
            document_uid=None,
            recipient_uid=None,
            nonce_hex=None,
            bits_recovered=0,
            raw_bits="",
            frame_offset=None,
            method_used="none",
            reason=f"PDF parsing error: {err}",
        )

    # 1. Primary Track: Content-stream kerning parsing
    stream_bits_list = []
    for page in doc:
        try:
            for xref in page.get_contents():
                st = doc.xref_stream(xref)
                p_bits = _extract_bits_from_stream(st)
                if p_bits:
                    stream_bits_list.append(p_bits)
        except Exception:
            continue

    all_stream_bits = "".join(stream_bits_list)
    decode_res = WatermarkPayload.find_and_decode_detailed(all_stream_bits)

    if decode_res.payload is not None:
        doc.close()
        payload = decode_res.payload
        is_valid, reason = verify_watermark_payload(payload, actual_key)
        return ExtractionResult(
            pdf_path=str(path),
            status="AUTHENTICATED" if is_valid else "INVALID_AUTHENTICATION",
            frame_detected=True,
            payload_decoded=True,
            crc_valid=True,
            hmac_valid=is_valid,
            recipient_recovered=True,
            payload=payload,
            document_uid=payload.document_uid,
            recipient_uid=payload.recipient_uid,
            nonce_hex=payload.nonce.hex(),
            bits_recovered=len(all_stream_bits),
            raw_bits=all_stream_bits,
            frame_offset=decode_res.frame_offset,
            method_used="stream_parsing",
            reason=reason,
        )

    # If stream parsing detected a preamble but failed CRC or body parsing
    if decode_res.frame_detected:
        doc.close()
        status = "CRC_ERROR" if not decode_res.crc_valid else "CORRUPTED_PAYLOAD"
        return ExtractionResult(
            pdf_path=str(path),
            status=status,
            frame_detected=True,
            payload_decoded=False,
            crc_valid=decode_res.crc_valid,
            hmac_valid=False,
            recipient_recovered=False,
            payload=None,
            document_uid=None,
            recipient_uid=None,
            nonce_hex=None,
            bits_recovered=len(all_stream_bits),
            raw_bits=all_stream_bits,
            frame_offset=decode_res.frame_offset,
            method_used="stream_parsing",
            reason=decode_res.error_message or "Frame detected but decoding failed",
        )

    # 2. Secondary Experimental Track: Geometric word-gap extraction (if requested)
    if use_geometric_fallback:
        geom_bits = _extract_bits_geometric(doc)
        geom_decode = WatermarkPayload.find_and_decode_detailed(geom_bits)
        if geom_decode.payload is not None:
            doc.close()
            geom_payload = geom_decode.payload
            is_valid, reason = verify_watermark_payload(geom_payload, actual_key)
            return ExtractionResult(
                pdf_path=str(path),
                status="AUTHENTICATED" if is_valid else "INVALID_AUTHENTICATION",
                frame_detected=True,
                payload_decoded=True,
                crc_valid=True,
                hmac_valid=is_valid,
                recipient_recovered=True,
                payload=geom_payload,
                document_uid=geom_payload.document_uid,
                recipient_uid=geom_payload.recipient_uid,
                nonce_hex=geom_payload.nonce.hex(),
                bits_recovered=len(geom_bits),
                raw_bits=geom_bits,
                frame_offset=geom_decode.frame_offset,
                method_used="geometric_experimental",
                reason=f"{reason} (Recovered via experimental geometric fallback)",
            )

    if not doc.is_closed:
        doc.close()
    return ExtractionResult(
        pdf_path=str(path),
        status="NO_WATERMARK",
        frame_detected=False,
        payload_decoded=False,
        crc_valid=False,
        hmac_valid=False,
        recipient_recovered=False,
        payload=None,
        document_uid=None,
        recipient_uid=None,
        nonce_hex=None,
        bits_recovered=len(all_stream_bits),
        raw_bits=all_stream_bits,
        frame_offset=None,
        method_used="stream_parsing",
        reason="No valid sync preamble or valid payload found in text stream.",
    )
