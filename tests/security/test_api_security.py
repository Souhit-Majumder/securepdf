import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database.database import init_db
import os
import fitz

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield

@pytest.fixture
def test_pdf_content(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Security Test PDF")
    
    pdf_path = tmp_path / "sec_test.pdf"
    doc.save(str(pdf_path))
    doc.close()
    
    with open(str(pdf_path), "rb") as f:
        yield f.read()

def test_api_security_malformed_upload():
    # Provide a text file disguised as PDF
    response = client.post(
        "/documents/",
        files={"file": ("fake.pdf", b"This is not a PDF file", "application/pdf")}
    )
    assert response.status_code == 400
    assert "Invalid PDF file format" in response.json()["detail"]

def test_api_security_oversized_upload():
    # We will mock an oversized file by sending chunks?
    # TestClient doesn't easily let us stream huge files without memory exhaustion,
    # but we can send a 21MB bytes object if memory permits, or just skip full execution
    # if it's too large for the test runner. Let's send exactly 20.1 MB
    huge_content = b"%PDF-1.4" + (b"0" * (20 * 1024 * 1024 + 100))
    response = client.post(
        "/documents/",
        files={"file": ("huge.pdf", huge_content, "application/pdf")}
    )
    assert response.status_code == 413
    assert "File too large" in response.json()["detail"]

def test_api_security_sql_injection():
    # Test injection strings in student creation
    injection_uid = "' OR 1=1 --"
    response = client.post(
        "/students/",
        json={"name": "Evil", "student_uid": injection_uid}
    )
    # The API should just treat it as a literal string (status 200) 
    # and the DB parameterized query will safely insert it.
    assert response.status_code == 200
    assert response.json()["student_uid"] == injection_uid

def test_api_security_path_traversal(test_pdf_content):
    # Setup document
    res_doc = client.post(
        "/documents/",
        files={"file": ("dist_test.pdf", test_pdf_content, "application/pdf")}
    )
    doc_uid = res_doc.json()["document_uid"]
    
    # Path traversal student
    traversal_uid = "../../../etc/passwd"
    client.post("/students/", json={"name": "Hacker", "student_uid": traversal_uid})
    
    res_dist = client.post(
        f"/documents/{doc_uid}/distribute",
        json={"student_uid": traversal_uid}
    )
    assert res_dist.status_code == 200
    # It shouldn't crash with a FileNotFoundError because of the path sanitization we added.
    
def test_api_security_attribution_disclosure(test_pdf_content):
    # This tests the unauthenticated behavior of /verify
    # Currently it's public. We document this in the threat model.
    res_ver = client.post(
        "/verify/",
        files={"file": ("original.pdf", test_pdf_content, "application/pdf")}
    )
    # Returns 200 NOT_FOUND, which means an attacker can probe documents.
    assert res_ver.status_code == 200
    assert res_ver.json()["status"] == "NOT_FOUND"

def test_api_security_missing_fields():
    # Missing student_uid
    response = client.post("/students/", json={"name": "Incomplete"})
    assert response.status_code == 422 # FastAPI validation error
