"""
Regression tests for stream parsing tokenizer robustness in embed.py and extract.py.
Verifies that strings containing delimiters, brackets, and escaped characters
do not stall the tokenizer in infinite loops.
"""
import time
import pytest
from experimental.extract import _extract_bits_from_stream
from experimental.embed import _parse_and_embed_page_stream


def test_tokenizer_handles_isolated_delimiters_and_literal_brackets():
    """
    Verifies that literal strings containing brackets outside TJ arrays:
    e.g., '([Zie. 2018 n. 15411 sez. SU - ud. 29-01-2019 ] ) Tj'
    do not cause an infinite parsing loop, and that TJ arrays with modulated
    word spaces are correctly extracted.
    """
    stream = (
        b"BT /F1 12 Tf 100 700 Td "
        b"([Zie. 2018 n. 15411 sez. SU - ud. 29-01-2019 ] ) Tj "
        b"[(Hello) -20 ( ) (World)] TJ "
        b"ET"
    )

    t0 = time.time()
    bits = _extract_bits_from_stream(stream)
    elapsed = time.time() - t0

    # Must complete almost instantaneously (well under 0.2s)
    assert elapsed < 0.2
    # The TJ operator contains one gap with -20 shift (<= -10 threshold -> bit 1)
    assert bits == "1"


def test_embed_parser_handles_isolated_delimiters():
    """Verifies that embed stream modification parser advances monotonically without stalls."""
    stream = (
        b"BT /F1 12 Tf "
        b"([Bracketed String]) Tj "
        b"[(First Second)] TJ "
        b"ET"
    )
    t0 = time.time()
    # Embed bit 0 into the inter-word gap with bit_offset=0
    mod_stream, bits_used = _parse_and_embed_page_stream(stream, "0", 0, shift=15)
    elapsed = time.time() - t0

    assert elapsed < 0.2
    assert bits_used == 1
    assert b" 0 ( ) " in mod_stream or b" 15 ( ) " in mod_stream
