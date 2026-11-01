import io
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database.database import init_db
from app.config import config

@pytest.fixture
def client(tmp_path, monkeypatch):
    test_data = tmp_path / "data"
    test_db = test_data / "test_batches.db"
    test_docs = test_data / "documents"
    test_output = test_data / "output"
    test_data.mkdir(parents=True, exist_ok=True)
    test_docs.mkdir(parents=True, exist_ok=True)
    test_output.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SECUREPDF_DATA_DIR", str(test_data))
    monkeypatch.setenv("SECUREPDF_DB_PATH", str(test_db))
    monkeypatch.setenv("SECUREPDF_DOCUMENTS_DIR", str(test_docs))
    monkeypatch.setenv("SECUREPDF_OUTPUT_DIR", str(test_output))

    init_db(test_db)
    return TestClient(app)

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

def _upload_test_document(client: TestClient, title: str = "TestDoc.pdf"):
    fake_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
    res = client.post(
        "/documents/",
        files={"file": (title, io.BytesIO(fake_pdf), "application/pdf")},
        data={"title": title}
    )
    assert res.status_code == 201
    return res.json()["document_uid"]

def test_create_batch_success_default_expiry(client):
    _register_and_login(client, "alice@test.com", "alice_batch")
    doc_uid = _upload_test_document(client)

    payload = {
        "recipients": [
            {"name": "Student One", "student_uid": "STU-001"},
            {"name": "Student Two", "student_uid": "STU-002"}
        ]
    }
    res = client.post(f"/documents/{doc_uid}/batches", json=payload)
    assert res.status_code == 201
    data = res.json()

    assert data["batch_uid"].startswith("batch_")
    assert data["document_uid"] == doc_uid
    assert data["total_recipients"] == 2
    assert data["expiry_duration_seconds"] == 120  # 2 minutes default testing
    assert data["status"] == "PENDING"
    assert len(data["recipients"]) == 2

    r0 = data["recipients"][0]
    assert r0["recipient_name"] == "Student One"
    assert r0["recipient_identifier"] == "STU-001"
    assert r0["status"] == "PENDING"
    assert r0["generated_at"] is None
    assert r0["expires_at"] is None

def test_create_batch_custom_expiry_options(client):
    _register_and_login(client, "carol@test.com", "carol_batch")
    doc_uid = _upload_test_document(client)

    for dur in [30, 900, 3600, 86400, 604800, 2592000]:
        res = client.post(
            f"/documents/{doc_uid}/batches",
            json={
                "expiry_duration_seconds": dur,
                "recipients": [{"name": f"Student {dur}", "student_uid": f"STU-{dur}"}]
            }
        )
        assert res.status_code == 201
        assert res.json()["expiry_duration_seconds"] == dur

def test_create_batch_invalid_expiry_rejected(client):
    _register_and_login(client, "dave@test.com", "dave_batch")
    doc_uid = _upload_test_document(client)

    # Below 30s
    res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 10,
            "recipients": [{"name": "Student", "student_uid": "STU-INV"}]
        }
    )
    assert res.status_code == 422

    # Above 30 days
    res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 3000000,
            "recipients": [{"name": "Student", "student_uid": "STU-INV"}]
        }
    )
    assert res.status_code == 422

def test_create_batch_duplicate_recipient_rejected(client):
    _register_and_login(client, "eve@test.com", "eve_batch")
    doc_uid = _upload_test_document(client)

    payload = {
        "recipients": [
            {"name": "First Instance", "student_uid": "DUP-001"},
            {"name": "Second Instance", "student_uid": "DUP-001"}
        ]
    }
    res = client.post(f"/documents/{doc_uid}/batches", json=payload)
    assert res.status_code == 422
    assert "Duplicate recipient identifier in batch" in res.text

def test_create_batch_missing_fields_rejected(client):
    _register_and_login(client, "frank@test.com", "frank_batch")
    doc_uid = _upload_test_document(client)

    # Empty recipients
    res = client.post(f"/documents/{doc_uid}/batches", json={"recipients": []})
    assert res.status_code == 422

    # Empty name
    res = client.post(
        f"/documents/{doc_uid}/batches",
        json={"recipients": [{"name": "   ", "student_uid": "ID-1"}]}
    )
    assert res.status_code == 422

def test_create_batch_unauthenticated(client):
    res = client.post(
        "/documents/any-uid/batches",
        json={"recipients": [{"name": "Student", "student_uid": "STU-1"}]}
    )
    assert res.status_code == 401

def test_create_batch_unowned_document_forbidden(client):
    # User 1 uploads doc
    _register_and_login(client, "owner@test.com", "owner_batch")
    doc_uid = _upload_test_document(client)

    # User 2 logs in
    _register_and_login(client, "attacker@test.com", "attacker_batch")
    res = client.post(
        f"/documents/{doc_uid}/batches",
        json={"recipients": [{"name": "Student", "student_uid": "STU-1"}]}
    )
    assert res.status_code == 403

def test_recipient_identity_safety_no_overwrite(client):
    # User A creates batch with STU-SHARED named "Alice Smith"
    _register_and_login(client, "usera@test.com", "user_a")
    doc_a = _upload_test_document(client, "DocA.pdf")
    res_a = client.post(
        f"/documents/{doc_a}/batches",
        json={"recipients": [{"name": "Alice Smith", "student_uid": "STU-SHARED"}]}
    )
    assert res_a.status_code == 201
    batch_a_uid = res_a.json()["batch_uid"]

    # User B creates batch with SAME student_uid "STU-SHARED" but named "Bob Jones"
    _register_and_login(client, "userb@test.com", "user_b")
    doc_b = _upload_test_document(client, "DocB.pdf")
    res_b = client.post(
        f"/documents/{doc_b}/batches",
        json={"recipients": [{"name": "Bob Jones", "student_uid": "STU-SHARED"}]}
    )
    assert res_b.status_code == 201
    batch_b_uid = res_b.json()["batch_uid"]

    # Inspect User B's batch
    get_b = client.get(f"/documents/batches/{batch_b_uid}")
    assert get_b.status_code == 200
    assert get_b.json()["recipients"][0]["recipient_name"] == "Bob Jones"
    assert get_b.json()["recipients"][0]["recipient_identifier"] == "STU-SHARED"

    # User B cannot inspect User A's batch (403)
    get_forbidden = client.get(f"/documents/batches/{batch_a_uid}")
    assert get_forbidden.status_code == 403

    # Switch back to User A, confirm User A's recipient was NOT overwritten
    _register_and_login(client, "usera@test.com", "user_a")
    get_a = client.get(f"/documents/batches/{batch_a_uid}")
    assert get_a.status_code == 200
    assert get_a.json()["recipients"][0]["recipient_name"] == "Alice Smith"
    assert get_a.json()["recipients"][0]["recipient_identifier"] == "STU-SHARED"

def test_get_batch_status_owner_access_control(client):
    _register_and_login(client, "user1@test.com", "user1_batch")
    doc_uid = _upload_test_document(client)
    res = client.post(
        f"/documents/{doc_uid}/batches",
        json={"recipients": [{"name": "Recipient", "student_uid": "R-1"}]}
    )
    batch_uid = res.json()["batch_uid"]

    # Owner can get batch
    get_res = client.get(f"/documents/batches/{batch_uid}")
    assert get_res.status_code == 200
    assert get_res.json()["batch_uid"] == batch_uid

    # Non-existent batch
    assert client.get("/documents/batches/nonexistent_batch").status_code == 404
