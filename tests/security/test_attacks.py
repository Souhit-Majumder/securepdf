import pytest
import fitz
import os
import shutil
from app.pdf.processor import open_pdf, save_pdf
from app.pdf.embed import embed_payload
from app.database.database import init_db
from app.database.repository import Repository
from app.services.verification_service import VerificationService
from app.services.fingerprint_service import FingerprintService

@pytest.fixture(autouse=True)
def setup_database():
    init_db()
    repo = Repository()
    repo.create_student("STU-TEST", "Alice")
    yield

@pytest.fixture
def original_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "Original Document Content")
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 50), "Second Page Content")
    
    path = str(tmp_path / "original.pdf")
    doc.save(path)
    doc.close()
    return path

@pytest.fixture
def fingerprinted_pdf(original_pdf, tmp_path):
    output_path = str(tmp_path / "fingerprinted.pdf")
    fp_service = FingerprintService()
    fp_service.fingerprint_pdf("STU-TEST", "DOC-TEST", original_pdf, output_path)
    return output_path

def test_attack_pymupdf_resave(fingerprinted_pdf, tmp_path):
    """Attack: Student simply opens and resaves the PDF with PyMuPDF."""
    resaved_path = str(tmp_path / "resaved.pdf")
    doc = fitz.open(fingerprinted_pdf)
    doc.save(resaved_path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(resaved_path)
    assert result["status"] == "VALID"

def test_attack_remove_metadata(fingerprinted_pdf, tmp_path):
    """Attack: Student clears standard PDF metadata (Author, Title, etc)."""
    cleared_path = str(tmp_path / "no_meta.pdf")
    doc = fitz.open(fingerprinted_pdf)
    doc.set_metadata({})
    doc.save(cleared_path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(cleared_path)
    assert result["status"] == "VALID"

def test_attack_pdf_optimization(fingerprinted_pdf, tmp_path):
    """Attack: Student compresses/optimizes the PDF using PyMuPDF garbage collection."""
    optimized_path = str(tmp_path / "optimized.pdf")
    doc = fitz.open(fingerprinted_pdf)
    doc.save(optimized_path, garbage=4, deflate=True)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(optimized_path)
    # The /SPDFPayload is in the Catalog. Garbage collection shouldn't remove it 
    # unless it's completely unreachable. Let's measure it!
    assert result["status"] == "VALID"

def test_attack_page_reordering(fingerprinted_pdf, tmp_path):
    """Attack: Student rearranges the pages in the PDF."""
    reordered_path = str(tmp_path / "reordered.pdf")
    doc = fitz.open(fingerprinted_pdf)
    doc.set_page_labels(doc.get_page_labels()) # touch pages
    
    # Reverse page order
    doc.select([1, 0])
    doc.save(reordered_path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(reordered_path)
    # Layer 1 is stripped, but Layer 2 survives!
    assert result["status"] == "VALID"
    assert "Layer 2" in result["authenticated_layers"]

def test_attack_delete_page(fingerprinted_pdf, tmp_path):
    """Attack: Student deletes a page from the PDF."""
    deleted_path = str(tmp_path / "deleted.pdf")
    doc = fitz.open(fingerprinted_pdf)
    doc.delete_page(1)
    doc.save(deleted_path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(deleted_path)
    assert result["status"] == "VALID"

def test_attack_add_page(fingerprinted_pdf, tmp_path):
    """Attack: Student adds a page to the PDF."""
    added_path = str(tmp_path / "added.pdf")
    doc = fitz.open(fingerprinted_pdf)
    doc.new_page()
    doc.save(added_path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(added_path)
    assert result["status"] == "VALID"

def test_attack_modify_visible_text(fingerprinted_pdf, tmp_path):
    """Attack: Student redacts or adds text to the PDF."""
    modified_path = str(tmp_path / "modified_text.pdf")
    doc = fitz.open(fingerprinted_pdf)
    page = doc[0]
    page.insert_text((100, 100), "ATTACKER ADDED TEXT")
    doc.save(modified_path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(modified_path)
    # Visible content change does NOT invalidate the fingerprint because our 
    # current implementation only hashes the metadata IDs, not the file hash.
    assert result["status"] == "VALID"

def test_attack_copy_pages_to_new_pdf(fingerprinted_pdf, tmp_path):
    """Attack: Student extracts pages into a completely new PDF document."""
    copied_path = str(tmp_path / "copied.pdf")
    doc_src = fitz.open(fingerprinted_pdf)
    doc_dest = fitz.open() # brand new PDF
    doc_dest.insert_pdf(doc_src)
    doc_dest.save(copied_path)
    doc_src.close()
    doc_dest.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(copied_path)
    # Layer 1 is stripped, but Layer 2 survives!
    assert result["status"] == "VALID"
    assert "Layer 2" in result["authenticated_layers"]

def test_attack_delete_payload(fingerprinted_pdf, tmp_path):
    """Attack: Student discovers /SPDFPayload and deletes it."""
    deleted_payload_path = str(tmp_path / "deleted_payload.pdf")
    doc = fitz.open(fingerprinted_pdf)
    doc.xref_set_key(doc.pdf_catalog(), "SPDFPayload", "null")
    doc.save(deleted_payload_path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(deleted_payload_path)
    # Layer 1 is deleted, but Layer 2 survives!
    assert result["status"] == "VALID"
    assert "Layer 2" in result["authenticated_layers"]

def test_parser_robustness(original_pdf, tmp_path):
    path = str(tmp_path / "malformed.pdf")
    doc = fitz.open(original_pdf)
    # 1. Invalid L1 (not hex)
    doc.xref_set_key(doc.pdf_catalog(), "SPDFPayload", "<not_hex_string>")
    # 2. Invalid L2 (not Base64)
    from app.pdf.payload_redundancy import embed_redundant_annotations
    embed_redundant_annotations(doc[0], "SPDF1|DOC|NONCE|not_base64!@#", copies=1)
    # 3. Oversized L2 DOS attack
    # We add 150 annotations. The extractor should cap at 100.
    for i in range(150):
        annot = doc[0].add_rect_annot(fitz.Rect(0, 0, 0.1, 0.1))
        info = annot.info
        info["title"] = "SPDF_DOS"
        info["content"] = "SPDF1|DOC|NONCE|fake"
        annot.set_info(info)
        annot.update()
    doc.save(path)
    doc.close()
    
    ver = VerificationService()
    # It should not crash, but safely return INVALID or NOT_FOUND (since none authenticate)
    result = ver.investigate_pdf(path)
    assert result["status"] in ["INVALID", "NOT_FOUND"]

def test_db_side_effect_protection(original_pdf, tmp_path):
    # A fake document_uid should not create a new DB record during verification
    path = str(tmp_path / "fake_uid.pdf")
    doc = fitz.open(original_pdf)
    payload = "SPDF-V1|DOC-FAKE-123|nonce|ffff"
    hex_payload = payload.encode('utf-8').hex()
    doc.xref_set_key(doc.pdf_catalog(), "SPDFPayload", f"<{hex_payload}>")
    doc.save(path)
    doc.close()
    
    ver = VerificationService()
    result = ver.investigate_pdf(path)
    assert result["status"] in ["INVALID", "NOT_FOUND"]
    
    # Verify DB does not contain DOC-FAKE-123
    from app.database.repository import Repository
    repo = Repository()
    assert repo.get_document_by_uid("DOC-FAKE-123") is None

def test_cryptographic_wrong_student_uid_fails(fingerprinted_pdf, tmp_path):
    """
    Simulates a database compromise or logic failure where verification is attempted
    with the wrong student UID for a mathematically valid payload.
    """
    repo = Repository()
    repo.create_student("STU-ATTACKER", "Eve")
    
    from app.crypto.integrity import verify_fingerprint
    from app.crypto.keys import get_or_create_master_key
    from app.pdf.extract import extract_layer1
    
    doc = fitz.open(fingerprinted_pdf)
    payload = extract_layer1(doc)
    doc.close()
    
    _, document_uid, nonce, extracted_fingerprint = payload.split('|')
    
    master_key = get_or_create_master_key()
    
    # Try verifying with STU-ATTACKER instead of STU-TEST
    is_valid = verify_fingerprint(master_key, document_uid, "STU-ATTACKER", nonce, extracted_fingerprint)
    
    assert is_valid == False
