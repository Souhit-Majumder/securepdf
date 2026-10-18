"""
Layer 3 Steganographic Embedder for SecurePDF.
Encodes bits into PDF content streams by modulating inter-word TJ kerning numbers.
"""
from __future__ import annotations

import logging
from typing import List, Tuple
import fitz

from app.pdf.stego.crypto import derive_layer3_subkey, generate_layer3_tag
from app.pdf.stego.framing import StegoPayload

logger = logging.getLogger(__name__)

# Standard kerning shift for bit '1': -20 displacement. Bit '0': 0 displacement.
KERNING_SHIFT_BIT_1 = -20


def count_available_word_gaps(doc: fitz.Document) -> int:
    """Counts eligible inter-word spacing opportunities across document pages."""
    total_gaps = 0
    for page in doc:
        try:
            words = page.get_text("words")
            if len(words) > 1:
                total_gaps += len(words) - 1
        except Exception:
            pass
    return total_gaps


def _parse_and_embed_page_stream(
    stream: bytes,
    bits_to_embed: str,
    bit_offset: int,
    shift: int = KERNING_SHIFT_BIT_1,
    collector: Optional[Any] = None,
    page_index: int = 0,
    stream_xref: int = 0,
) -> Tuple[bytes, int]:
    """
    Parses a PDF content stream, locates TJ arrays, and inserts kerning displacement for bits.
    Returns (modified_stream, next_bit_offset).
    """
    i = 0
    n = len(stream)
    out = bytearray()
    bit_idx = bit_offset
    total_bits = len(bits_to_embed)

    while i < n:
        b = stream[i:i + 1]

        # Whitespace
        if b in b" \t\r\n\x00\x0c":
            out.extend(b)
            i += 1

        # Comment
        elif b == b"%":
            c_start = i
            while i < n and stream[i:i + 1] not in b"\r\n":
                i += 1
            out.extend(stream[c_start:i])

        # Literal String outside array
        elif b == b"(":
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
            out.extend(stream[s_start:i])

        # Hex string outside array
        elif b == b"<":
            if stream[i:i + 2] == b"<<":
                out.extend(b"<<")
                i += 2
            else:
                h_start = i
                i += 1
                while i < n and stream[i:i + 1] != b">":
                    i += 1
                if i < n:
                    i += 1
                out.extend(stream[h_start:i])

        # Array [ ... ] containing TJ text
        elif b == b"[":
            out.extend(b"[")
            i += 1

            while i < n and stream[i:i + 1] != b"]":
                while i < n and stream[i:i + 1] in b" \t\r\n\x00\x0c":
                    out.extend(stream[i:i + 1])
                    i += 1
                if i >= n or stream[i:i + 1] == b"]":
                    break

                sb = stream[i:i + 1]

                # String literal ( ... ) inside array
                if sb == b"(":
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
                    parts = inner.split(b" ")

                    if len(parts) > 1:
                        for p_idx, part in enumerate(parts):
                            if part:
                                out.extend(b"(" + part + b")")
                            if p_idx < len(parts) - 1:
                                if collector is not None:
                                    collector.record_word_gap(page_index=page_index)
                                if bit_idx < total_bits:
                                    bit_val = bits_to_embed[bit_idx]
                                    bit_idx += 1
                                    k = shift if bit_val == "1" else 0
                                else:
                                    bit_val = "0"
                                    k = 0
                                if collector is not None:
                                    collector.record_modulation(
                                        page_index=page_index,
                                        content_stream_xref=stream_xref,
                                        gap_index=bit_idx - 1,
                                        content_stream_offset=len(out),
                                        preceding_word=part.decode("latin-1", errors="replace"),
                                        displacement=k,
                                        bit_value=bit_val,
                                        source="RUNTIME_CAPTURE",
                                    )
                                out.extend(f" {k} ( ) ".encode("ascii"))
                    else:
                        out.extend(raw_str)

                # Hex string inside array
                elif sb == b"<":
                    h_start = i
                    i += 1
                    while i < n and stream[i:i + 1] != b">":
                        i += 1
                    if i < n:
                        i += 1
                    out.extend(stream[h_start:i])

                # Delimiter
                elif sb in b"()<>[]":
                    out.extend(sb)
                    i += 1

                # Number or token inside array
                else:
                    t_start = i
                    while i < n and stream[i:i + 1] not in b" \t\r\n\x00\x0c[]()<>":
                        i += 1
                    if i == t_start:
                        i += 1
                    out.extend(stream[t_start:i])

            if i < n and stream[i:i + 1] == b"]":
                out.extend(b"]")
                i += 1
        else:
            out.extend(b)
            i += 1

    return bytes(out), bit_idx


def embed_layer3(
    doc: fitz.Document,
    document_uid: str,
    recipient_uid: str,
    nonce: bytes,
    master_key: bytes,
    collector: Optional[Any] = None,
) -> bool:
    """
    Constructs authenticated Layer 3 payload and embeds it into PDF TJ operators.
    If document capacity is insufficient, logs a warning and returns False (graceful fallback).
    """
    required_bits = StegoPayload.calculate_required_bits(document_uid, recipient_uid)
    available_bits = count_available_word_gaps(doc)

    if available_bits < required_bits:
        logger.warning(
            "Document word gap capacity (%d) insufficient for Layer 3 (%d bits); skipping Layer 3.",
            available_bits,
            required_bits,
        )
        if collector is not None:
            collector.record_layer3_result(
                status="NOT_FOUND",
                details={"error": "insufficient_capacity", "required_bits": required_bits, "available_bits": available_bits},
            )
        return False

    subkey = derive_layer3_subkey(master_key)
    hmac_tag = generate_layer3_tag(subkey, document_uid, recipient_uid, nonce)

    payload = StegoPayload(
        document_uid=document_uid,
        recipient_uid=recipient_uid,
        nonce=nonce,
        hmac_tag=hmac_tag,
    )

    bits_to_embed = payload.to_bits()
    bit_offset = 0

    for page in doc:
        if bit_offset >= len(bits_to_embed):
            break
        try:
            page.clean_contents()
            c_xrefs = page.get_contents()
            if not c_xrefs:
                continue

            primary_xref = c_xrefs[0]
            stream = doc.xref_stream(primary_xref)
            new_stream, new_offset = _parse_and_embed_page_stream(
                stream,
                bits_to_embed,
                bit_offset,
                collector=collector,
                page_index=page.number,
                stream_xref=primary_xref,
            )

            if new_offset > bit_offset:
                doc.update_stream(primary_xref, new_stream)
                bit_offset = new_offset
        except Exception as e:
            logger.warning("Failed embedding Layer 3 into page content stream: %s", e)
            if collector is not None:
                collector.record_layer3_result(status="ERROR", details={"error": str(e)})
            return False

    success = bit_offset >= len(bits_to_embed)
    if collector is not None:
        collector.record_layer3_result(
            status="VALID" if success else "NOT_FOUND",
            signature_token=hmac_tag,
            nonce_token=nonce,
            details={"document_uid": document_uid, "recipient_uid": recipient_uid},
        )
    return success
