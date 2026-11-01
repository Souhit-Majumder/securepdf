"""
Integration tests for SecurePDF authorization, user-level data isolation,
and anti-oracle / anti-hijacking guarantees.
"""
import uuid
import pytest
from fastapi.testclient import TestClient
import fitz

from app.main import app
from app.config import config
from app.database.database import init_db
from app.database.repository import Repository
from app.api.dependencies import get_rate_limiter

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    get_rate_limiter()._requests.clear()
    yield


@pytest.fixture
def sample_pdf_bytes():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Sample authorization test PDF")
    content = doc.tobytes()
    doc.close()
    return content


def create_authenticated_user_client() -> tuple[TestClient, dict]:
    """Helper to register and return a dedicated authenticated client and user info."""
    user_client = TestClient(app)
    uid = uuid.uuid4().hex[:8]
    user_data = {
        "email": f"user_{uid}@securepdf.org",
        "username": f"user_{uid}",
        "password": "Password123!"
    }
    reg = user_client.post("/api/auth/register", json=user_data)
    assert reg.status_code == 201
    return user_client, reg.json()


def test_unauthenticated_document_upload_rejected(sample_pdf_bytes):
    unauth_client = TestClient(app)
    res = unauth_client.post(
        "/documents/",
        files={"file": ("test.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 401


def test_unauthenticated_distribution_rejected():
    unauth_client = TestClient(app)
    res = unauth_client.post(
        "/documents/any-doc-id/distribute",
        json={"student_uid": "STU-001"}
    )
    assert res.status_code == 401


def test_unauthenticated_student_registration_rejected():
    unauth_client = TestClient(app)
    res = unauth_client.post(
        "/students/",
        json={"name": "Alice", "student_uid": "STU-001"}
    )
    assert res.status_code == 401


def test_owner_can_distribute_own_document(sample_pdf_bytes):
    user_client, _ = create_authenticated_user_client()

    # 1. Upload document
    upload_res = user_client.post(
        "/documents/",
        files={"file": ("lecture.pdf", sample_pdf_bytes, "application/pdf")},
        data={"title": "Lecture 1"}
    )
    assert upload_res.status_code == 201
    doc_uid = upload_res.json()["document_uid"]

    # 2. Register student
    stu_uid = f"STU_{uuid.uuid4().hex[:6]}"
    stu_res = user_client.post(
        "/students/",
        json={"name": "Alice Student", "student_uid": stu_uid}
    )
    assert stu_res.status_code == 201

    # 3. Distribute document
    dist_res = user_client.post(
        f"/documents/{doc_uid}/distribute",
        json={"student_uid": stu_uid}
    )
    assert dist_res.status_code == 200
    assert dist_res.headers["content-type"] == "application/pdf"
    assert len(dist_res.content) > 0


def test_cross_user_distribution_forbidden(sample_pdf_bytes):
    client_a, _ = create_authenticated_user_client()
    client_b, _ = create_authenticated_user_client()

    # User A uploads document
    upload_res = client_a.post(
        "/documents/",
        files={"file": ("lecture_a.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_uid = upload_res.json()["document_uid"]

    # Register student
    stu_uid = f"STU_{uuid.uuid4().hex[:6]}"
    client_a.post("/students/", json={"name": "Student A", "student_uid": stu_uid})

    # User B attempts to distribute User A's document
    cross_dist = client_b.post(
        f"/documents/{doc_uid}/distribute",
        json={"student_uid": stu_uid}
    )
    assert cross_dist.status_code == 403
    assert "access denied" in cross_dist.json()["detail"].lower()


def test_legacy_unowned_document_distribution_forbidden(sample_pdf_bytes):
    client_user, _ = create_authenticated_user_client()
    repo = Repository()

    # Create unowned legacy document directly (user_id = None)
    legacy_uid = f"legacy_doc_{uuid.uuid4().hex[:8]}"
    repo.get_or_create_document(legacy_uid, "legacy.pdf", user_id=None)

    # Save physical dummy file
    config.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    doc_path = config.DOCUMENTS_DIR / f"{legacy_uid}.pdf"
    with open(doc_path, "wb") as f:
        f.write(sample_pdf_bytes)

    # Register student
    stu_uid = f"STU_{uuid.uuid4().hex[:6]}"
    client_user.post("/students/", json={"name": "Test Student", "student_uid": stu_uid})

    # Attempt to distribute legacy document via web API
    res = client_user.post(
        f"/documents/{legacy_uid}/distribute",
        json={"student_uid": stu_uid}
    )
    assert res.status_code == 403
    assert "access denied" in res.json()["detail"].lower()


def test_anti_hijacking_repository_protection():
    repo = Repository()
    doc_uid = f"doc_{uuid.uuid4().hex[:8]}"

    # 1. User 10 owns the document
    doc1 = repo.get_or_create_document(doc_uid, "test.pdf", user_id=10)
    assert doc1.user_id == 10

    # 2. User 20 attempts to hijack/claim the document
    with pytest.raises(ValueError, match="already owned"):
        repo.get_or_create_document(doc_uid, "test.pdf", user_id=20)

    # 3. CLI/Service call with user_id=None accesses document without modifying ownership
    doc_cli = repo.get_or_create_document(doc_uid, "test.pdf", user_id=None)
    assert doc_cli.user_id == 10


def test_duplicate_document_uid_conflict():
    repo = Repository()
    doc_uid = f"dup_{uuid.uuid4().hex[:8]}"
    repo.create_document(doc_uid, "original.pdf", user_id=1)

    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_document(doc_uid, "duplicate.pdf", user_id=2)


def test_legacy_verify_unauthenticated_rejected(sample_pdf_bytes):
    unauth_client = TestClient(app)
    res = unauth_client.post(
        "/verify/",
        files={"file": ("sample.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 401


def test_legacy_verify_with_forensic_key(sample_pdf_bytes, monkeypatch):
    test_key = "securepdf_test_forensic_key_9999"
    monkeypatch.setenv("SECUREPDF_FORENSIC_KEY", test_key)

    unauth_client = TestClient(app)
    res = unauth_client.post(
        "/verify/",
        files={"file": ("sample.pdf", sample_pdf_bytes, "application/pdf")},
        headers={"X-SecurePDF-Audit-Key": test_key}
    )
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    # Student PII must be redacted for forensic key caller
    assert data["student_uid"] is None
    assert data["student_name"] is None


def test_legacy_verify_cross_user_attribution_blocked(sample_pdf_bytes):
    client_a, _ = create_authenticated_user_client()
    client_b, _ = create_authenticated_user_client()

    # User A creates doc, student, and distributes
    up = client_a.post("/documents/", files={"file": ("a.pdf", sample_pdf_bytes, "application/pdf")})
    doc_uid = up.json()["document_uid"]

    stu_uid = f"STU_{uuid.uuid4().hex[:6]}"
    client_a.post("/students/", json={"name": "Alice Secret", "student_uid": stu_uid})

    dist = client_a.post(f"/documents/{doc_uid}/distribute", json={"student_uid": stu_uid})
    watermarked_bytes = dist.content

    # User B attempts to verify User A's distributed file
    res_b = client_b.post(
        "/verify/",
        files={"file": ("leaked.pdf", watermarked_bytes, "application/pdf")}
    )
    assert res_b.status_code == 403
    assert "access denied" in res_b.json()["detail"].lower()

    # User A verifies their own document copy
    res_a = client_a.post(
        "/verify/",
        files={"file": ("leaked.pdf", watermarked_bytes, "application/pdf")}
    )
    assert res_a.status_code == 200
    assert res_a.json()["student_uid"] == stu_uid
    assert res_a.json()["student_name"] == "Alice Secret"


def test_legacy_verify_rate_limiting(sample_pdf_bytes):
    client_user, _ = create_authenticated_user_client()

    # Perform 5 requests (within rate limit)
    for _ in range(5):
        res = client_user.post(
            "/verify/",
            files={"file": ("test.pdf", sample_pdf_bytes, "application/pdf")}
        )
        assert res.status_code in (200, 400)

    # 6th request must trigger rate limit
    res_limited = client_user.post(
        "/verify/",
        files={"file": ("test.pdf", sample_pdf_bytes, "application/pdf")}
    )
    assert res_limited.status_code == 429
    assert "Retry-After" in res_limited.headers

    from app.api.dependencies import _rate_limiter
    _rate_limiter.reset_for_ip("testclient")
    _rate_limiter.reset_for_ip("127.0.0.1")

