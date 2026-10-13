"""
Tests for experimental steganographic watermark embedding and extraction:
round-trip recovery, capacity checks, text preservation, rendering integrity,
and un-watermarked baseline false-positive verification.
"""
import secrets
from pathlib import Path
import fitz
import pytest

from experimental.config import DEFAULT_KERNING_SHIFT
from experimental.crypto_adapter import (
    generate_watermark_payload,
    get_or_create_experimental_key,
)
from experimental.embed import (
    InsufficientCapacityError,
    StegoEmbeddingError,
    count_document_word_gaps,
    embed_watermark,
)
from experimental.extract import extract_watermark
from experimental.payload import WatermarkPayload


def _create_sample_pdf(path: Path, num_words: int = 1000) -> None:
    """Helper to generate a clean synthetic multi-page PDF with known word count."""
    doc = fitz.open()
    words = [
        "securepdf", "forensic", "cryptographic", "analysis", "watermarking",
        "authentication", "integrity", "document", "recipient", "verification",
        "steganography", "protocol", "carrier", "redundancy", "distribution",
    ]
    
    words_per_page = 300
    words_remaining = num_words
    
    while words_remaining > 0:
        page = doc.new_page(width=595, height=842)  # A4
        chunk_size = min(words_remaining, words_per_page)
        text_lines = []
        cur_line = []
        for i in range(chunk_size):
            cur_line.append(words[i % len(words)])
            if len(cur_line) >= 10:
                text_lines.append(" ".join(cur_line))
                cur_line = []
        if cur_line:
            text_lines.append(" ".join(cur_line))
        
        full_text = "\n".join(text_lines)
        page.insert_text((50, 60), full_text, fontsize=11, fontname="helv")
        words_remaining -= chunk_size
        
    doc.save(str(path))
    doc.close()


def test_count_document_word_gaps(tmp_path):
    pdf_path = tmp_path / "test_count.pdf"
    _create_sample_pdf(pdf_path, num_words=200)

    doc = fitz.open(str(pdf_path))
    total_gaps, gaps_per_page = count_document_word_gaps(doc)
    doc.close()

    assert total_gaps > 180  # ~199 gaps for 200 words
    assert len(gaps_per_page) == 1


def test_embed_insufficient_capacity(tmp_path):
    pdf_path = tmp_path / "tiny.pdf"
    out_path = tmp_path / "tiny_wm.pdf"
    key = secrets.token_bytes(32)

    # Short document with only 30 words (~29 gaps, far below the ~664 bits needed)
    _create_sample_pdf(pdf_path, num_words=30)
    payload = generate_watermark_payload("DOC-01", "STU-01", key)

    with pytest.raises(InsufficientCapacityError) as exc_info:
        embed_watermark(pdf_path, out_path, payload)

    assert exc_info.value.required_bits > exc_info.value.available_bits
    assert not out_path.exists()


def test_embed_rejects_in_place_overwrite(tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    _create_sample_pdf(pdf_path, num_words=800)
    key = secrets.token_bytes(32)
    payload = generate_watermark_payload("DOC-01", "STU-01", key)

    with pytest.raises(StegoEmbeddingError, match="Never overwrite source PDF in place"):
        embed_watermark(pdf_path, pdf_path, payload)


def test_round_trip_embedding_and_extraction(tmp_path):
    pdf_path = tmp_path / "source.pdf"
    out_path = tmp_path / "watermarked.pdf"
    key = secrets.token_bytes(32)

    _create_sample_pdf(pdf_path, num_words=900)
    payload = generate_watermark_payload("DOC-EXP-2026", "STU-SEC-42", key)

    # 1. Embed
    embed_res = embed_watermark(pdf_path, out_path, payload, shift=DEFAULT_KERNING_SHIFT)
    assert embed_res.total_bits_embedded == payload.total_bits
    assert embed_res.text_preserved is True
    assert embed_res.pages_used >= 1
    assert out_path.exists()

    # Verify exact text content preservation
    d_orig = fitz.open(str(pdf_path))
    d_wm = fitz.open(str(out_path))
    assert [p.get_text() for p in d_orig] == [p.get_text() for p in d_wm]
    d_orig.close()
    d_wm.close()

    # 2. Extract with correct key
    ext_res = extract_watermark(out_path, key)
    assert ext_res.status == "AUTHENTICATED"
    assert ext_res.document_uid == "DOC-EXP-2026"
    assert ext_res.recipient_uid == "STU-SEC-42"
    assert ext_res.hmac_valid is True
    assert ext_res.method_used == "stream_parsing"
    assert ext_res.payload is not None
    assert ext_res.payload.nonce == payload.nonce

    # 3. Extract with incorrect key -> INVALID_AUTHENTICATION
    wrong_key = secrets.token_bytes(32)
    ext_wrong = extract_watermark(out_path, wrong_key)
    assert ext_wrong.status == "INVALID_AUTHENTICATION"
    assert ext_wrong.hmac_valid is False
    assert ext_wrong.document_uid == "DOC-EXP-2026"
    assert ext_wrong.recipient_uid == "STU-SEC-42"


def test_extract_on_unwatermarked_baseline(tmp_path):
    pdf_path = tmp_path / "plain.pdf"
    _create_sample_pdf(pdf_path, num_words=800)
    key = secrets.token_bytes(32)

    ext_res = extract_watermark(pdf_path, key)
    assert ext_res.status == "NO_WATERMARK"
    assert ext_res.payload is None
    assert ext_res.hmac_valid is False
    assert ext_res.document_uid is None
    assert ext_res.recipient_uid is None
