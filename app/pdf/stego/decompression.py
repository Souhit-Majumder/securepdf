"""
Bounded Flate decompression module for PDF content streams.
Enforces strict output memory ceilings, handles unconsumed input tails,
and validates trailing data against standard PDF stream whitespace delimiters.
"""
from __future__ import annotations

import zlib
from typing import List


class DecompressionError(Exception):
    """Base exception for PDF stream decompression errors."""
    pass


class CorruptedStreamError(DecompressionError):
    """Raised when a stream is truncated, has invalid checksums, or unexpected trailing data."""
    pass


class OutputLimitExceededError(DecompressionError):
    """Raised when decompressed output exceeds the configured maximum byte limit."""
    pass


def safe_flate_decompress(
    raw_bytes: bytes,
    max_output_bytes: int = 5 * 1024 * 1024,
    chunk_size: int = 65536,
) -> bytes:
    """
    Decompresses Flate-encoded (RFC 1950) stream bytes with strictly bounded memory allocations.

    - Returns b"" if raw_bytes is empty (ordinary empty/non-text PDF content stream).
    - Enforces max_output_bytes ceiling at every chunk to prevent memory exhaustion / zip-bombs.
    - Properly consumes decompressor.unconsumed_tail across chunk boundaries.
    - Strips and validates trailing bytes after zlib EOF per ISO 32000-1 §7.3.8 (allowing only PDF whitespace).
    """
    if not raw_bytes:
        return b""
    if max_output_bytes < 0:
        raise ValueError("max_output_bytes must be non-negative")

    # wbits=15: Standard zlib stream with Adler-32 checksum verification (RFC 1950)
    decompressor = zlib.decompressobj(15)
    output: List[bytes] = []
    total = 0
    input_offset = 0
    input_len = len(raw_bytes)

    while not decompressor.eof:
        # Prioritize unconsumed tail from previous chunk hitting the output budget
        if decompressor.unconsumed_tail:
            chunk = decompressor.unconsumed_tail
        elif input_offset < input_len:
            chunk = raw_bytes[input_offset : input_offset + chunk_size]
            input_offset += len(chunk)
        else:
            raise CorruptedStreamError("Flate stream truncated before zlib EOF or checksum")

        remaining_budget = max_output_bytes - total
        # Cap decompressed chunk output to remaining budget + 1 to detect overflow cleanly
        max_chunk = min(chunk_size, remaining_budget + 1)

        try:
            decompressed = decompressor.decompress(chunk, max_chunk)
        except zlib.error as e:
            raise CorruptedStreamError(f"Malformed Flate stream: {e}") from e

        if decompressed:
            total += len(decompressed)
            if total > max_output_bytes:
                raise OutputLimitExceededError(
                    f"Stream exceeded output limit of {max_output_bytes} bytes"
                )
            output.append(decompressed)
        elif not decompressor.eof and not decompressor.unconsumed_tail and input_offset >= input_len:
            raise CorruptedStreamError("Decompression stalled before reaching EOF")

    # Validate all remaining data after EOF (unused_data + remaining raw input)
    trailing = decompressor.unused_data + raw_bytes[input_offset:]
    # ISO 32000-1 §7.3.8: Permit only standard PDF stream whitespace delimiters
    if trailing.strip(b"\r\n\t \x0c"):
        raise CorruptedStreamError("Unexpected non-whitespace trailing data after compressed stream")

    return b"".join(output)
