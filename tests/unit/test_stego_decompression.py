import zlib
import pytest

from app.pdf.stego.decompression import (
    safe_flate_decompress,
    CorruptedStreamError,
    OutputLimitExceededError,
)


def test_safe_flate_decompress_valid_stream():
    data = b"Hello, SecurePDF bounded decompression world!" * 20
    compressed = zlib.compress(data)
    result = safe_flate_decompress(compressed)
    assert result == data


def test_safe_flate_decompress_empty_input():
    # Empty input returns b"" cleanly for blank/empty PDF content streams
    assert safe_flate_decompress(b"") == b""


def test_safe_flate_decompress_negative_limit():
    with pytest.raises(ValueError, match="non-negative"):
        safe_flate_decompress(b"some data", max_output_bytes=-1)


def test_safe_flate_decompress_exact_limit():
    data = b"A" * 100
    compressed = zlib.compress(data)
    result = safe_flate_decompress(compressed, max_output_bytes=100)
    assert result == data


def test_safe_flate_decompress_oversized_limit():
    data = b"A" * 101
    compressed = zlib.compress(data)
    with pytest.raises(OutputLimitExceededError):
        safe_flate_decompress(compressed, max_output_bytes=100)


def test_safe_flate_decompress_small_chunks_unconsumed_tail():
    data = b"Testing unconsumed_tail handling across multiple chunks." * 10
    compressed = zlib.compress(data)
    # Use small chunk size (16 bytes) to force unconsumed_tail loops
    result = safe_flate_decompress(compressed, chunk_size=16)
    assert result == data


def test_safe_flate_decompress_corrupted_adler32():
    data = b"Checksum corruption test." * 5
    compressed = zlib.compress(data)
    corrupted = compressed[:-2] + b"\xff\xff"
    with pytest.raises(CorruptedStreamError):
        safe_flate_decompress(corrupted)


def test_safe_flate_decompress_truncated_stream():
    data = b"Truncation test data that has sufficient length." * 10
    compressed = zlib.compress(data)
    truncated = compressed[:10]
    with pytest.raises(CorruptedStreamError):
        safe_flate_decompress(truncated)


def test_safe_flate_decompress_trailing_pdf_whitespace():
    data = b"Testing trailing PDF whitespace delimiters."
    compressed = zlib.compress(data)
    # PDF stream delimiter whitespace: \r\n \t \x0c
    with_whitespace = compressed + b"\r\n   \t\x0c"
    result = safe_flate_decompress(with_whitespace)
    assert result == data


def test_safe_flate_decompress_trailing_garbage_rejected():
    data = b"Testing trailing non-whitespace rejection."
    compressed = zlib.compress(data)
    with_garbage = compressed + b"EXTRA_GARBAGE"
    with pytest.raises(CorruptedStreamError):
        safe_flate_decompress(with_garbage)


def test_safe_flate_decompress_concatenated_streams_rejected():
    data = b"Concatenated stream test."
    compressed = zlib.compress(data)
    concatenated = compressed + compressed
    with pytest.raises(CorruptedStreamError):
        safe_flate_decompress(concatenated)
