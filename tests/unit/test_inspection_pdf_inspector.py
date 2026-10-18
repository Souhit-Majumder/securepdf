"""
Unit tests for SecurePDF Read-Only Structural Inspector (Stage 3).
"""
import hashlib
from pathlib import Path
import fitz
import pytest

from app.inspection.pdf_inspector import PdfStructuralInspector
from app.inspection.models import AuthorizationContext
from app.pdf.embed import embed_payload
from app.pdf.processor import save_pdf


@pytest.fixture
def sample_pdf_path(tmp_path):
    """Generates a multi-page test PDF with ample word gap capacity (>1000 gaps)."""
    path = str(tmp_path / "sample_text.pdf")
    doc = fitz.open()
    for _ in range(10):
        page = doc.new_page(width=595, height=842)
        for line_idx in range(15):
            page.insert_text(
                (50, 50 + line_idx * 30),
                "SecurePDF document verification forensic integrity carrier text sample.",
            )
    doc.save(path)
    doc.close()
    return path


def test_source_document_immutability(sample_pdf_path):
    """Verifies that inspecting a PDF never mutates the file on disk."""
    orig_hash = hashlib.sha256(Path(sample_pdf_path).read_bytes()).hexdigest()

    inspector = PdfStructuralInspector()
    report = inspector.inspect_pdf(sample_pdf_path)

    post_hash = hashlib.sha256(Path(sample_pdf_path).read_bytes()).hexdigest()
    assert orig_hash == post_hash, "Source PDF file on disk was modified by read-only inspector!"
    assert report.telemetry_source == "READ_ONLY_INSPECTION"


def test_open_document_immutability(sample_pdf_path):
    """Verifies that inspecting an open fitz.Document never mutates it or marks it dirty."""
    doc = fitz.open(sample_pdf_path)
    orig_page_count = doc.page_count

    inspector = PdfStructuralInspector()
    report = inspector.inspect_pdf(doc)

    assert doc.page_count == orig_page_count
    assert not doc.is_dirty, "Document was dirtied by read-only inspector!"
    doc.close()


def test_plain_pdf_without_kerning(sample_pdf_path):
    """
    Plain PDFs without kerning arrays have L1, L2, and L3 reported as NOT_FOUND.
    Must NEVER report AUTHENTICATED.
    """
    inspector = PdfStructuralInspector()
    report = inspector.inspect_pdf(sample_pdf_path)

    assert report.overall_status == "NOT_FOUND"
    assert report.overall_status != "AUTHENTICATED"

    l1 = next(c for c in report.carriers if c.carrier_name == "Layer 1 (Catalog)")
    l2 = next(c for c in report.carriers if c.carrier_name == "Layer 2 (Annotations)")
    l3 = next(c for c in report.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")

    assert l1.status == "NOT_FOUND"
    assert l2.status == "NOT_FOUND"
    assert l3.status == "NOT_FOUND"
    assert l3.status != "AUTHENTICATED"


def test_ordinary_pdf_with_arbitrary_kerning_classified_as_observed_syntax(tmp_path):
    """
    PDF with arbitrary TJ kerning but no SPDF framing is classified as OBSERVED_SYNTAX.
    Must NEVER infer intentional bit values or report AUTHENTICATED.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "init")

    # Craft arbitrary kerning stream without SPDF preamble
    stream_parts = ["BT", "/F1 12 Tf", "["]
    for i in range(20):
        disp = -5 if i % 2 == 0 else 0
        stream_parts.append(f"(word{i}) {disp} ( )")
    stream_parts.extend(["] TJ", "ET"])
    stream_bytes = " ".join(stream_parts).encode("latin-1")

    c_xref = page.get_contents()[0]
    doc.update_stream(c_xref, stream_bytes)
    out_pdf = str(tmp_path / "arbitrary_kerning.pdf")
    doc.save(out_pdf)
    doc.close()

    inspector = PdfStructuralInspector()
    report = inspector.inspect_pdf(out_pdf)

    l3 = next(c for c in report.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert l3.status == "OBSERVED_SYNTAX"
    assert l3.status != "AUTHENTICATED"
    assert l3.status != "STRUCTURALLY_DECODED"
    assert report.overall_status == "OBSERVED_SYNTAX"


def test_layer1_and_layer2_structural_detection(sample_pdf_path, tmp_path):
    """PDF with Layer 1 and Layer 2 payloads is decoded structurally."""
    doc = fitz.open(sample_pdf_path)
    nonce = "1234567890abcdef1234567890abcdef"
    fp = "fedcba0987654321fedcba0987654321"

    embed_payload(doc, "DOC-L1-L2", nonce, fp, enable_stego=False)
    out_pdf = str(tmp_path / "l1_l2.pdf")
    save_pdf(doc, out_pdf)
    doc.close()

    inspector = PdfStructuralInspector()
    report = inspector.inspect_pdf(out_pdf)

    l1 = next(c for c in report.carriers if c.carrier_name == "Layer 1 (Catalog)")
    l2 = next(c for c in report.carriers if c.carrier_name == "Layer 2 (Annotations)")

    assert l1.status == "STRUCTURALLY_DECODED"
    assert l1.signature_ref is not None
    assert l1.nonce_ref is not None

    assert l2.status == "STRUCTURALLY_DECODED"
    assert l2.signature_ref is not None
    assert l2.nonce_ref is not None

    # L1 and L2 share the same signature reference
    assert report.cross_layer.signatures_match is True
    assert report.cross_layer.cross_carrier_conflict is False


def test_layer3_structural_decoding_and_no_authenticated_label(sample_pdf_path, tmp_path):
    """
    Valid Layer 3 embedding must yield STRUCTURALLY_DECODED in static inspection,
    and NEVER report AUTHENTICATED (since static inspection lacks live verification).
    """
    doc = fitz.open(sample_pdf_path)
    nonce = "1234567890abcdef1234567890abcdef"
    fp = "fedcba0987654321fedcba0987654321"
    master_key = b"\x01" * 32

    embed_payload(
        doc,
        "DOC-L3-FULL",
        nonce,
        fp,
        enable_stego=True,
        student_uid="STU-BOB-42",
        master_key=master_key,
    )
    out_pdf = str(tmp_path / "l3_full.pdf")
    save_pdf(doc, out_pdf)
    doc.close()

    inspector = PdfStructuralInspector()

    # Unprivileged inspection (PII clearance = False)
    auth_anon = AuthorizationContext(principal="auditor", has_pii_clearance=False)
    report_anon = inspector.inspect_pdf(out_pdf, auth_ctx=auth_anon)

    l3_anon = next(c for c in report_anon.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert l3_anon.status == "STRUCTURALLY_DECODED"
    assert l3_anon.status != "AUTHENTICATED"
    assert report_anon.subject.student_uid is None
    assert report_anon.subject.subject_ref.startswith("subj_anon_")

    # Privileged inspection (PII clearance = True)
    auth_priv = AuthorizationContext(principal="admin", has_pii_clearance=True)
    report_priv = inspector.inspect_pdf(out_pdf, auth_ctx=auth_priv)
    assert report_priv.subject.student_uid == "STU-BOB-42"


def test_crc_failure_classified_as_invalid(tmp_path):
    """A bitstream containing 'SPDF' sync preamble with corrupted CRC-32 yields INVALID."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "initial page stream setup")

    # Craft TJ array with 'SPDF' sync preamble bits followed by corrupted bytes
    sync_preamble_bits = "".join(f"{b:08b}" for b in b"SPDF")
    corrupt_body_bits = "0" * (60 * 8)  # invalid CRC
    fake_bits = sync_preamble_bits + corrupt_body_bits

    # Embed bits manually into a TJ array
    stream_parts = ["BT", "/F1 12 Tf", "["]
    for i, bit in enumerate(fake_bits):
        k = -20 if bit == "1" else 0
        stream_parts.append(f"(w{i}) {k} ( )")
    stream_parts.extend(["] TJ", "ET"])
    stream_bytes = " ".join(stream_parts).encode("latin-1")

    # Update content stream directly
    c_xref = page.get_contents()[0]
    doc.update_stream(c_xref, stream_bytes)

    out_pdf = str(tmp_path / "crc_corrupt.pdf")
    doc.save(out_pdf)
    doc.close()

    inspector = PdfStructuralInspector()
    report = inspector.inspect_pdf(out_pdf)

    l3 = next(c for c in report.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert l3.status == "INVALID"
    assert l3.details.get("frame_detected") is True
    assert l3.details.get("crc_valid") is False


def test_get_page_modulations_pagination_and_source_label(sample_pdf_path):
    """
    Tests get_page_modulations() pagination, offset tracking,
    and telemetry_source='STRUCTURAL_RESCAN' label.
    """
    doc = fitz.open(sample_pdf_path)
    inspector = PdfStructuralInspector()

    page_0_all = inspector.get_page_modulations(doc, page_index=0, offset=0, limit=100)
    assert len(page_0_all) > 4

    p1 = inspector.get_page_modulations(doc, page_index=0, offset=0, limit=2)
    p2 = inspector.get_page_modulations(doc, page_index=0, offset=2, limit=2)

    assert len(p1) == 2
    assert len(p2) == 2
    assert p1[0].location.gap_index == page_0_all[0].location.gap_index
    assert p1[1].location.gap_index == page_0_all[1].location.gap_index
    assert p2[0].location.gap_index == page_0_all[2].location.gap_index
    assert p2[1].location.gap_index == page_0_all[3].location.gap_index

    # All returned samples must be labeled STRUCTURAL_RESCAN
    for s in p1 + p2:
        assert s.source == "STRUCTURAL_RESCAN"
        assert s.location.content_stream_offset >= 0

    doc.close()
