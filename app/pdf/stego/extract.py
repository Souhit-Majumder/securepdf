"""
Bitstream extraction and candidate decoding from PDF content streams.
"""
from __future__ import annotations

from typing import Optional
from app.pdf.stego.framing import CandidateParseResult, parse_stego_bitstream

MIN_KERNING_THRESHOLD = -10


def extract_bits_from_stream(stream: bytes, threshold: int = MIN_KERNING_THRESHOLD) -> str:
    """
    Parses content stream for TJ arrays and extracts bits from inter-word kerning numbers.
    Any kerning number preceding an explicit space `( )` is checked:
    If num <= threshold (e.g. -10): bit '1', else bit '0'.
    """
    bits = []
    i = 0
    n = len(stream)

    while i < n:
        b = stream[i:i + 1]

        # Whitespace
        if b in b" \t\r\n\x00\x0c":
            i += 1

        # Comment
        elif b == b"%":
            while i < n and stream[i:i + 1] not in b"\r\n":
                i += 1

        # Literal String outside array: skip atomically
        elif b == b"(":
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

        # Hex string or dictionary outside array
        elif b == b"<":
            if stream[i:i + 2] == b"<<":
                i += 2
            else:
                i += 1
                while i < n and stream[i:i + 1] != b">":
                    i += 1
                if i < n:
                    i += 1

        # Array [ ... ] containing TJ text and kerning numbers
        elif b == b"[":
            i += 1
            last_number: Optional[int] = None

            while i < n and stream[i:i + 1] != b"]":
                while i < n and stream[i:i + 1] in b" \t\r\n\x00\x0c":
                    i += 1
                if i >= n or stream[i:i + 1] == b"]":
                    break

                sb = stream[i:i + 1]

                # String literal ( ... )
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

                    # If this is an inter-word space `( )`, evaluate preceding kerning number
                    if inner == b" ":
                        if last_number is not None:
                            bits.append("1" if last_number <= threshold else "0")
                        else:
                            bits.append("0")
                    last_number = None

                # Hex string < ... >
                elif sb == b"<":
                    i += 1
                    while i < n and stream[i:i + 1] != b">":
                        i += 1
                    if i < n:
                        i += 1
                    last_number = None

                # Isolated delimiter inside array
                elif sb in b"()<>[]":
                    i += 1
                    last_number = None

                # Number or token
                else:
                    t_start = i
                    while i < n and stream[i:i + 1] not in b" \t\r\n\x00\x0c[]()<>":
                        i += 1
                    if i == t_start:
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


def find_and_decode_stego_bits(bits: str) -> CandidateParseResult:
    """Wrapper that searches bitstream for preamble and verifies CRC-32."""
    return parse_stego_bitstream(bits)
