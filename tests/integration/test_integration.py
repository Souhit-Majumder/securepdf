import pytest
import fitz
import os
from app.pdf.processor import open_pdf
from app.pdf.embed import embed_payload
from app.database.database import init_db
from app.database.repository import Repository
from app.services.verification_service import VerificationService
from app.services.fingerprint_service import FingerprintService

@pytest.fixture(autouse=True)
def setup_database():
    if os.path.exists("data/securepdf.db"):
        os.remove("data/securepdf.db")
    init_db()
    repo = Repository()
    repo.create_student("STU-TEST", "Alice")
    yield
    if os.path.exists("data/securepdf.db"):
        os.remove("data/securepdf.db")

@pytest.fixture
def original_pdf(tmp_path):
    path = str(tmp_path / "original.pdf")
    doc = fitz.open()
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 50), "Page 1")
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 50), "Page 2")
    doc.save(path)
    doc.close()
    return path

@pytest.fixture
def fingerprinted_pdf(original_pdf, tmp_path):
    output_path = str(tmp_path / "fingerprinted.pdf")
    fp_service = FingerprintService()
    fp_service.fingerprint_pdf("STU-TEST", "DOC-TEST", original_pdf, output_path)
    return output_path

def test_normal_generation(fingerprinted_pdf):
    ver = VerificationService()
    result = ver.investigate_pdf(fingerprinted_pdf)
    
    assert result["status"] == "VALID"
    assert result["student_uid"] == "STU-TEST"
    assert "Layer 1" in result["authenticated_layers"]
    assert "Layer 2" in result["authenticated_layers"]

def test_layer1_independence(fingerprinted_pdf, tmp_path):
    # Remove Layer 2 (annotations) -> Layer 1 should still authenticate
    path = str(tmp_path / "no_l2.pdf")
    doc = fitz.open(fingerprinted_pdf)
    for page in doc:
        for annot in page.annots():
            page.delete_annot(annot)
    doc.save(path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(path)
    assert result["status"] == "VALID"
    assert result["authenticated_layers"] == ["Layer 1"]

def test_layer2_independence(fingerprinted_pdf, tmp_path):
    # Remove Layer 1 (Catalog) -> Layer 2 should still authenticate
    path = str(tmp_path / "no_l1.pdf")
    doc = fitz.open(fingerprinted_pdf)
    doc.xref_set_key(doc.pdf_catalog(), "SPDFPayload", "null")
    doc.save(path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(path)
    assert result["status"] == "VALID"
    assert result["authenticated_layers"] == ["Layer 2"]

def test_conflict_fail_closed(fingerprinted_pdf, original_pdf, tmp_path):
    # Make Layer 1 authenticate as Fingerprint A, Layer 2 as Fingerprint B
    path = str(tmp_path / "conflict.pdf")
    
    # Generate a second student & PDF to get a different valid fingerprint
    repo = Repository()
    repo.create_student("STU-OTHER", "Bob")
    fp_service = FingerprintService()
    other_pdf = str(tmp_path / "other.pdf")
    fp_service.fingerprint_pdf("STU-OTHER", "DOC-OTHER", original_pdf, other_pdf)
    
    # Now extract L1 from fingerprinted_pdf and overwrite L1 in other_pdf
    from app.pdf.extract import extract_layer1
    doc_orig = fitz.open(fingerprinted_pdf)
    l1_payload = extract_layer1(doc_orig)
    doc_orig.close()
    
    doc_conflict = fitz.open(other_pdf)
    hex_payload = l1_payload.encode('utf-8').hex()
    doc_conflict.xref_set_key(doc_conflict.pdf_catalog(), "SPDFPayload", f"<{hex_payload}>")
    doc_conflict.save(path)
    doc_conflict.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(path)
    assert result["status"] == "SECURITY_CONFLICT"
    assert "different identities" in result["reason"]

def test_tampering_layer1(fingerprinted_pdf, tmp_path):
    # Modify Layer 1 -> Layer 2 still authenticates
    path = str(tmp_path / "tamper_l1.pdf")
    doc = fitz.open(fingerprinted_pdf)
    doc.xref_set_key(doc.pdf_catalog(), "SPDFPayload", "<535044462d56317c>") # Junk hex
    doc.save(path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(path)
    assert result["status"] == "VALID"
    assert result["authenticated_layers"] == ["Layer 2"]

def test_tampering_both(fingerprinted_pdf, tmp_path):
    path = str(tmp_path / "tamper_both.pdf")
    doc = fitz.open(fingerprinted_pdf)
    doc.xref_set_key(doc.pdf_catalog(), "SPDFPayload", "<535044462d56317c>")
    
    for page in doc:
        for annot in page.annots():
            info = annot.info
            info["content"] = "TAMPERED"
            annot.set_info(info)
            annot.update()
            
    doc.save(path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(path)
    assert result["status"] == "INVALID"

def test_structural_page_extraction(fingerprinted_pdf, tmp_path):
    path = str(tmp_path / "extract.pdf")
    doc_src = fitz.open(fingerprinted_pdf)
    doc_dest = fitz.open()
    doc_dest.insert_pdf(doc_src, from_page=0, to_page=0)
    doc_dest.save(path)
    doc_src.close()
    doc_dest.close()
    
    # Layer 1 is lost during extraction, Layer 2 survives!
    ver = VerificationService()
    result = ver.investigate_pdf(path)
    assert result["status"] == "VALID"
    assert result["authenticated_layers"] == ["Layer 2"]

def test_structural_page_reordering(fingerprinted_pdf, tmp_path):
    path = str(tmp_path / "reorder.pdf")
    doc = fitz.open(fingerprinted_pdf)
    doc.select([1, 0])
    doc.save(path)
    doc.close()
    
    # Layer 1 is lost during selection, Layer 2 survives!
    ver = VerificationService()
    result = ver.investigate_pdf(path)
    assert result["status"] == "VALID"
    assert result["authenticated_layers"] == ["Layer 2"]
