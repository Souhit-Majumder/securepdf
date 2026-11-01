import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database.database import init_db
import os
import fitz

import uuid

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    # Authenticate client with session cookie
    uid = uuid.uuid4().hex[:8]
    client.post("/api/auth/register", json={
        "email": f"test_api_{uid}@example.com",
        "username": f"user_api_{uid}",
        "password": "Password123!"
    })
    yield

@pytest.fixture
def test_pdf_content(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "API Test PDF")
    
    pdf_path = tmp_path / "api_test.pdf"
    doc.save(str(pdf_path))
    doc.close()
    
    with open(str(pdf_path), "rb") as f:
        yield f.read()

def test_api_upload_document(test_pdf_content):
    response = client.post(
        "/documents/",
        files={"file": ("test.pdf", test_pdf_content, "application/pdf")},
        data={"title": "Test Document"}
    )
    assert response.status_code in (200, 201)
    data = response.json()
    assert "document_uid" in data
    assert data["original_filename"] == "Test Document"

def test_api_upload_invalid_file():
    response = client.post(
        "/documents/",
        files={"file": ("test.txt", b"Hello world", "text/plain")},
        data={"title": "Text file"}
    )
    assert response.status_code == 400
    assert "Only PDF files are allowed" in response.json()["detail"]

def test_api_create_student():
    response = client.post(
        "/students/",
        json={"name": "API Student", "student_uid": "API-STU-001"}
    )
    assert response.status_code in (200, 201)
    data = response.json()
    assert data["name"] == "API Student"
    assert data["student_uid"] == "API-STU-001"

def test_api_distribute_and_verify(test_pdf_content):
    # 1. Upload doc
    res_doc = client.post(
        "/documents/",
        files={"file": ("dist_test.pdf", test_pdf_content, "application/pdf")}
    )
    doc_uid = res_doc.json()["document_uid"]
    
    # 2. Add student
    client.post(
        "/students/",
        json={"name": "Bob", "student_uid": "API-BOB-001"}
    )
    
    # 3. Distribute
    res_dist = client.post(
        f"/documents/{doc_uid}/distribute",
        json={"student_uid": "API-BOB-001"}
    )
    assert res_dist.status_code == 200
    assert res_dist.headers["content-type"] == "application/pdf"
    
    personalized_pdf_content = res_dist.content
    
    # 4. Verify
    res_ver = client.post(
        "/verify/",
        files={"file": ("leaked.pdf", personalized_pdf_content, "application/pdf")}
    )
    assert res_ver.status_code == 200
    data = res_ver.json()
    assert data["status"] == "VALID"
    assert data["student_uid"] == "API-BOB-001"
    assert data["student_name"] == "Bob"
    assert data["document_uid"] == doc_uid
    assert "Layer 1" in data["authenticated_layers"]
    assert "Layer 2" in data["authenticated_layers"]

def test_api_verify_invalid_pdf():
    # Provide a txt file instead of pdf
    response = client.post(
        "/verify/",
        files={"file": ("leaked.txt", b"not a pdf", "text/plain")}
    )
    assert response.status_code == 400
    assert "Only PDF files are allowed" in response.json()["detail"]

def test_api_verify_no_payload(test_pdf_content):
    # An original PDF with no payload
    response = client.post(
        "/verify/",
        files={"file": ("original.pdf", test_pdf_content, "application/pdf")}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "NOT_FOUND"

def test_api_oversized_file():
    # 21 MB dummy file starting with %PDF
    oversized = b"%PDF-1.4" + (b"0" * (21 * 1024 * 1024))
    response = client.post(
        "/documents/",
        files={"file": ("huge.pdf", oversized, "application/pdf")}
    )
    assert response.status_code == 413
    assert "File too large" in response.json()["detail"]
