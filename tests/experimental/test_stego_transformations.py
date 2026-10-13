"""
Tests for experimental steganographic watermark survivability across transformations:
benign re-saving, metadata alteration, margin cropping, appended text,
page reordering disruption, and carrier elimination via rasterization.
"""
import secrets
from pathlib import Path
import fitz
import pytest

from experimental.crypto_adapter import generate_watermark_payload
from experimental.embed import embed_watermark
from experimental.extract import extract_watermark


def _build_test_document(path: Path) -> None:
    doc = fitz.open()
    sample_text = (
        "SecurePDF forensic watermarking prototype evaluates character positioning "
        "and font operator transformations across real-world document distribution workflows. "
        "Each page contains sufficient text volume to reliably host full 256-bit authentication tags "
        "without truncating security margins or relying on insecure shortcuts. "
    ) * 5
    for _ in range(5):
        p = doc.new_page(width=595, height=842)
        p.insert_textbox(fitz.Rect(50, 60, 545, 780), sample_text, fontsize=10, fontname="helv")
    doc.save(str(path))
    doc.close()


@pytest.fixture
def watermarked_pdf(tmp_path):
    src = tmp_path / "original.pdf"
    wm = tmp_path / "watermarked.pdf"
    key = secrets.token_bytes(32)

    _build_test_document(src)
    payload = generate_watermark_payload("DOC-TRANS-01", "STU-BOB", key)
    embed_watermark(src, wm, payload)
    return wm, key


def test_transformation_benign_resave(tmp_path, watermarked_pdf):
    wm_path, key = watermarked_pdf
    resaved = tmp_path / "resaved.pdf"

    d = fitz.open(str(wm_path))
    d.save(str(resaved), garbage=3, deflate=True)
    d.close()

    ext = extract_watermark(resaved, key)
    assert ext.status == "AUTHENTICATED"
    assert ext.hmac_valid is True
    assert ext.document_uid == "DOC-TRANS-01"
    assert ext.recipient_uid == "STU-BOB"


def test_transformation_metadata_modification(tmp_path, watermarked_pdf):
    wm_path, key = watermarked_pdf
    meta_pdf = tmp_path / "metadata_mod.pdf"

    d = fitz.open(str(wm_path))
    m = d.metadata or {}
    m["title"] = "Modified Research Syllabus"
    m["author"] = "Unknown Adversary"
    d.set_metadata(m)
    d.save(str(meta_pdf))
    d.close()

    ext = extract_watermark(meta_pdf, key)
    assert ext.status == "AUTHENTICATED"
    assert ext.hmac_valid is True
    assert ext.document_uid == "DOC-TRANS-01"


def test_transformation_appended_text(tmp_path, watermarked_pdf):
    wm_path, key = watermarked_pdf
    appended_pdf = tmp_path / "appended.pdf"

    d = fitz.open(str(wm_path))
    d[0].insert_text((50, 30), "NOTICE: CONFIDENTIAL FILE", fontsize=12, color=(1, 0, 0))
    d.save(str(appended_pdf))
    d.close()

    ext = extract_watermark(appended_pdf, key)
    assert ext.status == "AUTHENTICATED"
    assert ext.hmac_valid is True


def test_transformation_margin_cropping(tmp_path, watermarked_pdf):
    wm_path, key = watermarked_pdf
    cropped_pdf = tmp_path / "cropped.pdf"

    d = fitz.open(str(wm_path))
    for p in d:
        r = p.rect
        p.set_cropbox(fitz.Rect(r.x0 + 15, r.y0 + 15, r.x1 - 15, r.y1 - 15))
    d.save(str(cropped_pdf))
    d.close()

    ext = extract_watermark(cropped_pdf, key)
    assert ext.status == "AUTHENTICATED"
    assert ext.hmac_valid is True


def test_transformation_page_reordering_disruption(tmp_path, watermarked_pdf):
    wm_path, key = watermarked_pdf
    reordered_pdf = tmp_path / "reordered.pdf"

    d = fitz.open(str(wm_path))
    # Reverse the 3 pages: [2, 1, 0]
    d.select(list(reversed(range(d.page_count))))
    d.save(str(reordered_pdf))
    d.close()

    ext = extract_watermark(reordered_pdf, key)
    # The payload is distributed across pages sequentially, so reversing pages breaks the sequence
    assert ext.status in ("NO_WATERMARK", "CRC_ERROR", "INVALID_AUTHENTICATION")
    assert ext.hmac_valid is False


def test_transformation_rasterization_destroys_carrier(tmp_path, watermarked_pdf):
    wm_path, key = watermarked_pdf
    raster_pdf = tmp_path / "rasterized.pdf"

    # Simulate rasterization / print-scan: convert vector pages to PNG images
    d = fitz.open(str(wm_path))
    doc_raster = fitz.open()
    for p in d:
        pix = p.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        new_page = doc_raster.new_page(width=p.rect.width, height=p.rect.height)
        new_page.insert_image(new_page.rect, stream=img_bytes)
    d.close()
    doc_raster.save(str(raster_pdf))
    doc_raster.close()

    # Vector text TJ stream is gone, so extraction should fail cleanly
    ext = extract_watermark(raster_pdf, key)
    assert ext.status == "NO_WATERMARK"
    assert ext.hmac_valid is False
    assert ext.payload is None
