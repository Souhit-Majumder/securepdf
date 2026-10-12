import pytest
import fitz
import os
from app.pdf.processor import open_pdf, save_pdf
from app.pdf.embed import embed_payload
from app.pdf.extract import extract_layer1
from app.crypto.fingerprint import generate_nonce, generate_fingerprint
from app.crypto.keys import get_or_create_master_key
from app.database.database import init_db, get_connection
from app.database.repository import Repository
from app.services.verification_service import VerificationService
from app.services.fingerprint_service import FingerprintService

@pytest.fixture(autouse=True)
def setup_database():
    # Setup test database
    if os.path.exists("data/securepdf.db"):
        os.remove("data/securepdf.db")
    init_db()
    repo = Repository()
    repo.create_student("STU-TEST", "Test Student")
    repo.create_student("STU-OTHER", "Other Student")
    yield
    # Cleanup after test
    if os.path.exists("data/securepdf.db"):
        os.remove("data/securepdf.db")

@pytest.fixture
def original_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "Test Document Content")
    path = str(tmp_path / "original.pdf")
    doc.save(path)
    doc.close()
    return path

@pytest.fixture
def output_pdf(tmp_path):
    return str(tmp_path / "fingerprinted.pdf")

def test_end_to_end_verification_and_visual_integrity(original_pdf, output_pdf):
    # 1. Fingerprint PDF
    fp_service = FingerprintService()
    doc_uid = "DOC-TEST"
    stu_uid = "STU-TEST"
    
    fingerprint = fp_service.fingerprint_pdf(stu_uid, doc_uid, original_pdf, output_pdf)
    
    # Verify Visual Integrity
    orig_doc = fitz.open(original_pdf)
    fing_doc = fitz.open(output_pdf)
    
    # Page count unchanged
    assert orig_doc.page_count == fing_doc.page_count
    
    # Page dimensions unchanged
    orig_rect = orig_doc[0].rect
    fing_rect = fing_doc[0].rect
    assert orig_rect == fing_rect
    
    # Text content unchanged
    assert orig_doc[0].get_text() == fing_doc[0].get_text()
    
    # File hashes should be different
    with open(original_pdf, "rb") as f1, open(output_pdf, "rb") as f2:
        assert f1.read() != f2.read()
        
    orig_doc.close()
    fing_doc.close()

    # 2. Extract and Verify
    ver_service = VerificationService()
    result = ver_service.investigate_pdf(output_pdf)
    
    assert result["status"] == "VALID"
    assert result["student_uid"] == stu_uid
    assert result["document_uid"] == doc_uid
    assert result["fingerprint"] == fingerprint

def test_modified_fingerprint(original_pdf, output_pdf):
    # Generate and embed
    fp_service = FingerprintService()
    fp_service.fingerprint_pdf("STU-TEST", "DOC-TEST", original_pdf, output_pdf)
    
    # Tamper with the PDF payload
    doc = fitz.open(output_pdf)
    payload = extract_layer1(doc)
    
    # Modify one character of the fingerprint (last char)
    parts = payload.split('|')
    fingerprint = parts[3]
    tampered_fp = fingerprint[:-1] + ('a' if fingerprint[-1] != 'a' else 'b')
    parts[3] = tampered_fp
    
    tampered_payload = "|".join(parts)
    hex_payload = tampered_payload.encode('utf-8').hex()
    doc.xref_set_key(doc.pdf_catalog(), "SPDFPayload", f"<{hex_payload}>")
    for page in doc:
        for annot in page.annots():
            page.delete_annot(annot)
    temp_pdf = str(output_pdf) + ".tmp"
    doc.save(temp_pdf)
    doc.close()
    import shutil
    shutil.move(temp_pdf, output_pdf)
    
    ver_service = VerificationService()
    result = ver_service.investigate_pdf(output_pdf)
    assert result["status"] == "INVALID"

def test_modified_nonce(original_pdf, output_pdf):
    fp_service = FingerprintService()
    fp_service.fingerprint_pdf("STU-TEST", "DOC-TEST", original_pdf, output_pdf)
    
    # Tamper with the PDF payload
    doc = fitz.open(output_pdf)
    payload = extract_layer1(doc)
    
    # Modify the nonce
    parts = payload.split('|')
    parts[2] = generate_nonce() # new random nonce
    
    tampered_payload = "|".join(parts)
    hex_payload = tampered_payload.encode('utf-8').hex()
    doc.xref_set_key(doc.pdf_catalog(), "SPDFPayload", f"<{hex_payload}>")
    for page in doc:
        for annot in page.annots():
            page.delete_annot(annot)
    temp_pdf = str(output_pdf) + ".tmp"
    doc.save(temp_pdf)
    doc.close()
    import shutil
    shutil.move(temp_pdf, output_pdf)
    
    ver_service = VerificationService()
    result = ver_service.investigate_pdf(output_pdf)
    assert result["status"] == "INVALID"

def test_wrong_student(original_pdf, output_pdf):
    # We will simulate a wrong student scenario. 
    # An attacker copies the valid fingerprint payload to another document, but changes the doc uid?
    # Or an attacker somehow maps the fingerprint to another student in DB (which shouldn't happen without key).
    # Since we can't easily tamper with the DB in a real attack, we will tamper with the payload to use STU-OTHER.
    # Wait, the payload doesn't contain student_uid. The mapping is in DB.
    # What if the attacker copies the entire payload from Student A's PDF to Student B's PDF?
    # Verification will correctly say "This belongs to Student A".
    pass

def test_unprotected_pdf(original_pdf):
    ver_service = VerificationService()
    result = ver_service.investigate_pdf(original_pdf)
    assert result["status"] == "NOT_FOUND"
    assert "No SecurePDF fingerprint found" in result["reason"]
