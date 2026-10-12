import pytest
import sqlite3
import os
from app.database.database import init_db
from app.database.repository import Repository

@pytest.fixture(autouse=True)
def setup_database():
    if os.path.exists("data/securepdf.db"):
        os.remove("data/securepdf.db")
    init_db()
    repo = Repository()
    repo.create_student("STU-TEST", "Alice")
    repo.get_or_create_document("DOC-TEST", "original.pdf")
    yield
    if os.path.exists("data/securepdf.db"):
        os.remove("data/securepdf.db")

def test_fingerprint_unique_document_nonce():
    repo = Repository()
    
    student = repo.get_student_by_uid("STU-TEST")
    document = repo.get_or_create_document("DOC-TEST", "original.pdf")
    
    # 1. First insertion succeeds
    fp1 = repo.create_fingerprint(document.id, student.id, "NONCE1", "FINGERPRINT_A")
    assert fp1 is not None
    assert fp1.nonce == "NONCE1"
    
    # 2. Second identical (document, nonce) insertion fails safely
    # SQLite will raise IntegrityError which is caught by create_fingerprint, returning existing.
    fp2 = repo.create_fingerprint(document.id, student.id, "NONCE1", "FINGERPRINT_B")
    assert fp2.id == fp1.id
    assert fp2.fingerprint == "FINGERPRINT_A"

def test_fingerprint_uniqueness_behavior():
    repo = Repository()
    student = repo.get_student_by_uid("STU-TEST")
    doc1 = repo.get_or_create_document("DOC-1", "doc1.pdf")
    doc2 = repo.get_or_create_document("DOC-2", "doc2.pdf")
    
    # 1. First insertion succeeds
    fp1 = repo.create_fingerprint(doc1.id, student.id, "NONCE-A", "HEX-1")
    assert fp1.fingerprint == "HEX-1"
    
    # 2. Same document + different nonce succeeds
    fp2 = repo.create_fingerprint(doc1.id, student.id, "NONCE-B", "HEX-2")
    assert fp2.fingerprint == "HEX-2"
    
    # 3. Different document + same nonce succeeds
    fp3 = repo.create_fingerprint(doc2.id, student.id, "NONCE-A", "HEX-3")
    assert fp3.fingerprint == "HEX-3"
    
    # 4. Same document + same nonce fails safely (returns existing record)
    fp4 = repo.create_fingerprint(doc1.id, student.id, "NONCE-A", "HEX-4")
    # It catches the IntegrityError and returns the original fp1 because (doc1, NONCE-A) exists
    assert fp4.id == fp1.id
    assert fp4.fingerprint == "HEX-1"  # Returns the original, doesn't overwrite
