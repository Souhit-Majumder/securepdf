"""
Steganographic text-level watermark embedding via inter-word TJ kerning modulation.
Preserves original PDF text characters, font resources, and visual formatting.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import fitz

from experimental.config import DEFAULT_KERNING_SHIFT
from experimental.payload import InsufficientCapacityError, StegoPayloadError, WatermarkPayload


class StegoEmbeddingError(Exception):
    """Raised when watermark embedding cannot be performed safely."""
    pass


@dataclass
class EmbeddingResult:
    input_path: str
    output_path: str
    document_uid: str
    recipient_uid: str
    total_bits_embedded: int
    total_word_gaps_available: int
    kerning_shift: int
    pages_used: int
    text_preserved: bool


def _count_gaps_in_string(s: bytes) -> int:
    """Counts inter-word gaps (spaces separating non-empty chunks) in a string."""
    parts = s.split(b" ")
    # Number of spaces between words
    return max(0, len(parts) - 1)


def count_document_word_gaps(doc: fitz.Document) -> Tuple[int, List[int]]:
    """
    Counts available inter-word gaps across all pages in the document.
    Returns (total_gaps, gaps_per_page).
    """
    gaps_per_page = []
    total = 0
    for page in doc:
        # We clean contents to get normalized operators
        p_gaps = 0
        try:
            # Get words using text extraction as accurate count of word boundaries
            words = page.get_text("words")
            if len(words) > 1:
                # Count gaps between words on same or consecutive lines
                p_gaps = len(words) - 1
            else:
                p_gaps = 0
        except Exception:
            p_gaps = 0
        gaps_per_page.append(p_gaps)
        total += p_gaps
    return total, gaps_per_page


def _parse_and_embed_page_stream(
    stream: bytes,
    bits_to_embed: str,
    bit_offset: int,
    shift: int = DEFAULT_KERNING_SHIFT,
) -> Tuple[bytes, int]:
    """
    Parses a cleaned PDF content stream, locates text arrays/strings,
    and inserts inter-word TJ kerning displacement for bits.
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

        # Literal String outside array: copy verbatim
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

        # Hex string or dictionary outside array
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
                # Copy whitespace
                while i < n and stream[i:i + 1] in b" \t\r\n\x00\x0c":
                    out.extend(stream[i:i + 1])
                    i += 1
                if i >= n or stream[i:i + 1] == b"]":
                    break

                sb = stream[i:i + 1]

                # String literal ( ... ) with balanced parentheses
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
                        # Modulate inter-word spaces
                        for p_idx, part in enumerate(parts):
                            if part:
                                out.extend(b"(" + part + b")")
                            if p_idx < len(parts) - 1:
                                if bit_idx < total_bits:
                                    bit_val = bits_to_embed[bit_idx]
                                    bit_idx += 1
                                    k = shift if bit_val == "1" else 0
                                else:
                                    k = 0
                                out.extend(f" {k} ( ) ".encode("ascii"))
                    else:
                        out.extend(raw_str)

                # Hex string < ... >
                elif sb == b"<":
                    h_start = i
                    i += 1
                    while i < n and stream[i:i + 1] != b">":
                        i += 1
                    if i < n:
                        i += 1
                    out.extend(stream[h_start:i])

                # Isolated delimiter inside array: advance 1 byte
                elif sb in b"()<>[]":
                    out.extend(sb)
                    i += 1

                # Number or other token inside array
                else:
                    t_start = i
                    while i < n and stream[i:i + 1] not in b" \t\r\n\x00\x0c[]()<>":
                        i += 1
                    if i == t_start:
                        out.extend(stream[i:i + 1])
                        i += 1
                    else:
                        out.extend(stream[t_start:i])

            if i < n and stream[i:i + 1] == b"]":
                out.extend(b"]")
                i += 1

        else:
            # Copy all non-array stream bytes verbatim
            out.extend(stream[i:i + 1])
            i += 1

    return bytes(out), bit_idx


def embed_watermark(
    input_pdf_path: str | Path,
    output_pdf_path: str | Path,
    payload: WatermarkPayload,
    shift: int = DEFAULT_KERNING_SHIFT,
) -> EmbeddingResult:
    """
    Embeds an authenticated WatermarkPayload into a PDF by subtly modulating
    inter-word TJ kerning in content streams.
    Validates rendering and exact text equivalence before writing.
    """
    in_path = Path(input_pdf_path)
    out_path = Path(output_pdf_path)

    if not in_path.exists():
        raise StegoEmbeddingError(f"Input PDF not found: {in_path}")

    if in_path.resolve() == out_path.resolve():
        raise StegoEmbeddingError("Never overwrite source PDF in place")

    # Read-only open
    doc = fitz.open(str(in_path))

    # Strict header check
    with open(in_path, "rb") as f:
        header = f.read(4)
    if header != b"%PDF":
        doc.close()
        raise StegoEmbeddingError(f"Invalid PDF header: {header}")

    # Record baseline plain text for post-embedding equivalence check
    orig_text = [page.get_text() for page in doc]

    # Calculate capacity
    required_bits = payload.total_bits
    total_gaps, gaps_per_page = count_document_word_gaps(doc)

    if total_gaps < required_bits:
        doc.close()
        raise InsufficientCapacityError(required_bits=required_bits, available_bits=total_gaps)

    bits_to_embed = payload.to_bits()
    bit_offset = 0
    pages_used = 0

    out_path.parent.mkdir(parents=True, exist_ok=True)

    for page_idx, page in enumerate(doc):
        if bit_offset >= len(bits_to_embed):
            break

        # Normalize page content stream to standard PDF text operators
        try:
            page.clean_contents()
            c_xrefs = page.get_contents()
            if not c_xrefs:
                continue

            # In PyMuPDF, clean_contents consolidates into a single contents xref
            primary_xref = c_xrefs[0]
            stream = doc.xref_stream(primary_xref)

            new_stream, new_offset = _parse_and_embed_page_stream(
                stream, bits_to_embed, bit_offset, shift=shift
            )

            if new_offset > bit_offset:
                doc.update_stream(primary_xref, new_stream)
                bit_offset = new_offset
                pages_used += 1

        except Exception as err:
            doc.close()
            raise StegoEmbeddingError(f"Failed to process content stream on page {page_idx + 1}: {err}") from err

    # Save to destination
    doc.save(str(out_path), garbage=3, deflate=True)
    doc.close()

    # Post-validation on written file: Text equivalence & rendering integrity
    verify_doc = fitz.open(str(out_path))
    new_text = [page.get_text() for page in verify_doc]

    # 1. Text equivalence check
    text_preserved = (orig_text == new_text)
    if not text_preserved:
        verify_doc.close()
        if out_path.exists():
            out_path.unlink()
        raise StegoEmbeddingError(
            "Validation failed: text extraction after embedding diverged from original text."
        )

    # 2. Rendering check
    try:
        for p in verify_doc:
            _ = p.get_pixmap(dpi=72)
    except Exception as err:
        verify_doc.close()
        if out_path.exists():
            out_path.unlink()
        raise StegoEmbeddingError(f"Validation failed: rendered page produced errors: {err}") from err

    verify_doc.close()

    return EmbeddingResult(
        input_path=str(in_path),
        output_path=str(out_path),
        document_uid=payload.document_uid,
        recipient_uid=payload.recipient_uid,
        total_bits_embedded=bit_offset,
        total_word_gaps_available=total_gaps,
        kerning_shift=shift,
        pages_used=pages_used,
        text_preserved=text_preserved,
    )
