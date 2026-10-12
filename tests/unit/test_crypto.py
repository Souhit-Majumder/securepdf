import pytest
from Crypto.Random import get_random_bytes
from app.crypto.fingerprint import generate_nonce, generate_fingerprint
from app.crypto.integrity import verify_fingerprint

@pytest.fixture
def master_key():
    return get_random_bytes(32)

@pytest.fixture
def wrong_key():
    return get_random_bytes(32)

@pytest.fixture
def doc_uid():
    return "DOC-TEST"

@pytest.fixture
def student_uid():
    return "STU-TEST"

def test_correct_fingerprint_is_valid(master_key, doc_uid, student_uid):
    nonce = generate_nonce()
    fingerprint = generate_fingerprint(master_key, doc_uid, student_uid, nonce)
    
    assert verify_fingerprint(master_key, doc_uid, student_uid, nonce, fingerprint) == True

def test_different_nonce_produces_different_fingerprint(master_key, doc_uid, student_uid):
    nonce1 = generate_nonce()
    nonce2 = generate_nonce()
    
    fp1 = generate_fingerprint(master_key, doc_uid, student_uid, nonce1)
    fp2 = generate_fingerprint(master_key, doc_uid, student_uid, nonce2)
    
    assert nonce1 != nonce2
    assert fp1 != fp2

def test_modified_document_uid_is_invalid(master_key, doc_uid, student_uid):
    nonce = generate_nonce()
    fingerprint = generate_fingerprint(master_key, doc_uid, student_uid, nonce)
    
    # Tamper with document UID
    tampered_doc = "DOC-FORGED"
    assert verify_fingerprint(master_key, tampered_doc, student_uid, nonce, fingerprint) == False

def test_modified_student_uid_is_invalid(master_key, doc_uid, student_uid):
    nonce = generate_nonce()
    fingerprint = generate_fingerprint(master_key, doc_uid, student_uid, nonce)
    
    # Tamper with student UID
    tampered_stu = "STU-FORGED"
    assert verify_fingerprint(master_key, doc_uid, tampered_stu, nonce, fingerprint) == False

def test_modified_nonce_is_invalid(master_key, doc_uid, student_uid):
    nonce = generate_nonce()
    fingerprint = generate_fingerprint(master_key, doc_uid, student_uid, nonce)
    
    # Tamper with nonce
    tampered_nonce = generate_nonce()
    assert verify_fingerprint(master_key, doc_uid, student_uid, tampered_nonce, fingerprint) == False

def test_wrong_key_is_invalid(master_key, wrong_key, doc_uid, student_uid):
    nonce = generate_nonce()
    fingerprint = generate_fingerprint(master_key, doc_uid, student_uid, nonce)
    
    # Attempt verification with the wrong key
    assert verify_fingerprint(wrong_key, doc_uid, student_uid, nonce, fingerprint) == False
