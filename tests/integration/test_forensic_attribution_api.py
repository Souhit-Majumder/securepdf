import io
import os
import pymupdf
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.database.database import init_db
from app.config import config
from app.api.routes.distribution import _ACTIVE_BATCH_GENERATIONS, _ACTIVE_DOWNLOADS, _DOWNLOAD_LOCK
from app.database.repository import Repository
from app.api.dependencies import _rate_limiter

FORENSIC_TEST_KEY = "test_forensic_audit_key_secret_2026"

@pytest.fixture
def test_setup(tmp_path, monkeypatch):
    test_data = tmp_path / "data"
    test_db = test_data / "test_attribution.db"
    test_docs = test_data / "documents"
    test_output = test_data / "output"
    test_data.mkdir(parents=True, exist_ok=True)
    test_docs.mkdir(parents=True, exist_ok=True)
    test_output.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SECUREPDF_DATA_DIR", str(test_data))
    monkeypatch.setenv("SECUREPDF_DB_PATH", str(test_db))
    monkeypatch.setenv("SECUREPDF_DOCUMENTS_DIR", str(test_docs))
    monkeypatch.setenv("SECUREPDF_OUTPUT_DIR", str(test_output))
    monkeypatch.setenv("SECUREPDF_FORENSIC_KEY", FORENSIC_TEST_KEY)

    init_db(test_db)
    _ACTIVE_BATCH_GENERATIONS.clear()
    with _DOWNLOAD_LOCK:
        _ACTIVE_DOWNLOADS.clear()
    Repository._ACTIVE_CLAIMS.clear()
    _rate_limiter.reset_for_ip("testclient")
    _rate_limiter.reset_for_ip("127.0.0.1")

    client = TestClient(app)
    return client

def _create_pdf_bytes():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), "SecurePDF Phase 4 Forensic Investigation Document")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes

def _register_and_login(client: TestClient, email: str, username: str, password: str = "P@ssw0rd123!"):
    client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": password}
    )
    res = client.post(
        "/api/auth/login",
        json={"identifier": username, "password": password}
    )
    assert res.status_code == 200
    return res

def _upload_doc(client: TestClient, title: str = "AttributionTest.pdf"):
    pdf_bytes = _create_pdf_bytes()
    res = client.post(
        "/documents/",
        files={"file": (title, io.BytesIO(pdf_bytes), "application/pdf")},
        data={"title": title}
    )
    assert res.status_code == 201
    return res.json()["document_uid"]

def test_batch_recipient_attribution_with_owner_session(test_setup):
    client = test_setup
    _register_and_login(client, "owner@univ.edu", "prof_owner")
    doc_uid = _upload_doc(client, "Exam2026.pdf")

    # Create batch
    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 600,
            "recipients": [
                {"name": "Alice Montgomery", "student_uid": "STU-ALICE-2026"},
                {"name": "Bob Vance", "student_uid": "STU-BOB-2026"}
            ]
        }
    )
    assert batch_res.status_code == 201
    batch_uid = batch_res.json()["batch_uid"]

    # Generate watermarked recipient PDFs
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    # Read Alice's generated PDF from disk
    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    repo = Repository()
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    recipients = repo.get_batch_recipients(batch.id)
    alice_rec = next(r for r in recipients if r.recipient_identifier == "STU-ALICE-2026")
    alice_pdf_bytes = (batch_dir / f"rec_{alice_rec.id}.pdf").read_bytes()

    # Owner verifies Alice's watermarked PDF using their authenticated session + audit key
    verify_res = client.post(
        "/api/inspection/verify",
        files={"file": ("leaked_exam.pdf", io.BytesIO(alice_pdf_bytes), "application/pdf")},
        headers={"X-SecurePDF-Audit-Key": FORENSIC_TEST_KEY}
    )
    assert verify_res.status_code == 200
    data = verify_res.json()

    assert data["verification_status"] == "VALID"
    assert data["document_uid"] == doc_uid
    # Recipient attribution correctly resolved for document owner!
    assert data["recipient_name"] == "Alice Montgomery"
    assert data["recipient_identifier"] == "STU-ALICE-2026"

    # Data minimization: no secret leakage
    assert "nonce" not in data
    assert "fingerprint" not in data
    assert "download_token" not in data
    assert "master_key" not in data

def test_cross_user_verification_denied(test_setup):
    client_a = test_setup
    _register_and_login(client_a, "user_a@univ.edu", "user_a")
    doc_uid_a = _upload_doc(client_a, "UserA_Document.pdf")

    batch_res = client_a.post(
        f"/documents/{doc_uid_a}/batches",
        json={
            "expiry_duration_seconds": 300,
            "recipients": [{"name": "Charlie Chaplin", "student_uid": "STU-CHARLIE"}]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    client_a.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    repo = Repository()
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    recipients = repo.get_batch_recipients(batch.id)
    pdf_bytes = (batch_dir / f"rec_{recipients[0].id}.pdf").read_bytes()

    # User B logs in
    client_b = TestClient(app)
    _register_and_login(client_b, "user_b@univ.edu", "user_b")

    # User B attempts to verify User A's document
    res = client_b.post(
        "/api/inspection/verify",
        files={"file": ("stolen.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers={"X-SecurePDF-Audit-Key": FORENSIC_TEST_KEY}
    )
    assert res.status_code == 403
    assert "Access denied: You do not own the document carrier in this file" in res.json()["detail"]

def test_audit_key_only_redacts_recipient_pii(test_setup):
    client_owner = test_setup
    _register_and_login(client_owner, "prof@college.edu", "prof_math")
    doc_uid = _upload_doc(client_owner, "CalculusExam.pdf")

    batch_res = client_owner.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "recipients": [{"name": "Diana Prince", "student_uid": "STU-DIANA"}]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    client_owner.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    repo = Repository()
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    recipients = repo.get_batch_recipients(batch.id)
    pdf_bytes = (batch_dir / f"rec_{recipients[0].id}.pdf").read_bytes()

    # External auditor client without user session cookie
    auditor_client = TestClient(app)
    res = auditor_client.post(
        "/api/inspection/verify",
        files={"file": ("audited.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers={"X-SecurePDF-Audit-Key": FORENSIC_TEST_KEY}
    )
    assert res.status_code == 200
    data = res.json()

    assert data["verification_status"] == "VALID"
    assert data["document_uid"] == doc_uid
    # Recipient PII MUST be strictly redacted for audit-key-only caller
    assert data["recipient_name"] is None
    assert data["recipient_identifier"] is None
    # Pseudonymized subject_ref is provided
    assert data["subject_ref"] is not None

def test_legacy_distribution_attribution_fallback(test_setup):
    """
    Asserts that an authentic legacy fingerprint without a batch-recipient
    association remains cryptographically VALID, but recipient attribution
    is not reported (recipient_name and recipient_identifier are None).
    """
    client = test_setup
    _register_and_login(client, "legacy@univ.edu", "legacy_user")
    doc_uid = _upload_doc(client, "OldLecture.pdf")

    # Phase 1 student creation and single distribution
    client.post("/students/", json={"name": "Legacy Student", "student_uid": "STU-LEGACY-01"})
    dist_res = client.post(f"/documents/{doc_uid}/distribute", json={"student_uid": "STU-LEGACY-01"})
    assert dist_res.status_code == 200
    legacy_pdf_bytes = dist_res.content

    # Document owner verifies legacy distribution PDF
    verify_res = client.post(
        "/api/inspection/verify",
        files={"file": ("legacy.pdf", io.BytesIO(legacy_pdf_bytes), "application/pdf")},
        headers={"X-SecurePDF-Audit-Key": FORENSIC_TEST_KEY}
    )
    assert verify_res.status_code == 200
    data = verify_res.json()

    # Must remain cryptographically VALID
    assert data["verification_status"] == "VALID"
    assert data["document_uid"] == doc_uid
    # Recipient PII must remain unattributed because no batch recipient record exists
    assert data["recipient_name"] is None
    assert data["recipient_identifier"] is None

def test_tampered_or_unwatermarked_pdf(test_setup):
    client = test_setup
    plain_pdf_bytes = _create_pdf_bytes()

    res = client.post(
        "/api/inspection/verify",
        files={"file": ("plain.pdf", io.BytesIO(plain_pdf_bytes), "application/pdf")},
        headers={"X-SecurePDF-Audit-Key": FORENSIC_TEST_KEY}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "NOT_FOUND"
    assert data["recipient_name"] is None
    assert data["recipient_identifier"] is None
