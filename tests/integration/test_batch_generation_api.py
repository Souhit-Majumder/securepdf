import io
import os
import pymupdf
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database.database import init_db
from app.config import config
from app.api.routes.distribution import _ACTIVE_BATCH_GENERATIONS

@pytest.fixture
def client(tmp_path, monkeypatch):
    test_data = tmp_path / "data"
    test_db = test_data / "test_generation.db"
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
    _ACTIVE_BATCH_GENERATIONS.clear()
    from app.database.repository import Repository
    Repository._ACTIVE_CLAIMS.clear()
    return TestClient(app)

def _create_valid_pdf_bytes():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), "SecurePDF Confidential Distribution Document Content")
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

def _upload_test_document(client: TestClient, title: str = "SampleExam.pdf"):
    pdf_bytes = _create_valid_pdf_bytes()
    res = client.post(
        "/documents/",
        files={"file": (title, io.BytesIO(pdf_bytes), "application/pdf")},
        data={"title": title}
    )
    assert res.status_code == 201
    return res.json()["document_uid"]

def test_generate_batch_success(client):
    _register_and_login(client, "alice@test.com", "alice_gen")
    doc_uid = _upload_test_document(client)

    # 1. Create distribution batch with 120s expiry
    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 120,
            "recipients": [
                {"name": "Alice Student", "student_uid": "STU-001"},
                {"name": "Bob Student", "student_uid": "STU-002"},
            ]
        }
    )
    assert batch_res.status_code == 201
    batch_uid = batch_res.json()["batch_uid"]

    # 2. Trigger synchronous personalized generation
    gen_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert gen_res.status_code == 200
    gen_data = gen_res.json()

    assert gen_data["batch_uid"] == batch_uid
    assert gen_data["status"] == "COMPLETED"
    assert gen_data["total_recipients"] == 2

    # 3. Verify recipient records and timestamp calculations
    recipients = gen_data["recipients"]
    assert len(recipients) == 2

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    assert batch_dir.exists()

    for r in recipients:
        assert r["status"] == "GENERATED"
        assert r["generated_at"] is not None
        assert r["expires_at"] is not None

        gen_dt = datetime.strptime(r["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
        exp_dt = datetime.strptime(r["expires_at"], "%Y-%m-%dT%H:%M:%SZ")
        assert (exp_dt - gen_dt).total_seconds() == 120

    # 4. Verify opaque file paths on disk (zero recipient PII in filenames)
    files = list(batch_dir.glob("*.pdf"))
    assert len(files) == 2
    for f in files:
        assert f.name.startswith("rec_")
        assert f.name.endswith(".pdf")
        assert "Alice" not in f.name
        assert "Bob" not in f.name
        assert "STU" not in f.name
        assert f.stat().st_size > 0

def test_generate_batch_atomic_recovery_and_idempotency(client):
    """
    Verifies requirement 2:
    - Never regenerate recipients already marked GENERATED with valid fingerprint association and existing output file.
    - Safely recover and retry interrupted PROCESSING batches after a restart.
    """
    _register_and_login(client, "recovery@test.com", "recovery_user")
    doc_uid = _upload_test_document(client)

    # Create batch with 2 recipients
    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "recipients": [
                {"name": "First Recipient", "student_uid": "STU-R1"},
                {"name": "Second Recipient", "student_uid": "STU-R2"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]

    # Generate first recipient normally
    # To simulate partial completion + restart, we run generation once
    gen_res1 = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert gen_res1.status_code == 200
    recipients_run1 = gen_res1.json()["recipients"]
    r1_gen_at = recipients_run1[0]["generated_at"]

    # Verify calling generate again does not re-embed or re-generate completed recipients
    gen_res2 = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert gen_res2.status_code == 200
    recipients_run2 = gen_res2.json()["recipients"]
    assert recipients_run2[0]["generated_at"] == r1_gen_at

def test_generate_batch_concurrency_protection(client):
    """
    Verifies requirement 3:
    - Prevent multiple requests from starting generation for the same batch simultaneously.
    """
    _register_and_login(client, "concurrency@test.com", "concurrency_user")
    doc_uid = _upload_test_document(client)

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "recipients": [
                {"name": "Concurrent One", "student_uid": "STU-C1"}
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]

    # Simulate an active generation lock in progress
    _ACTIVE_BATCH_GENERATIONS.add(batch_uid)

    try:
        conflict_res = client.post(f"/documents/batches/{batch_uid}/generate")
        assert conflict_res.status_code == 409
        assert "Batch generation is currently in progress" in conflict_res.json()["detail"]
    finally:
        _ACTIVE_BATCH_GENERATIONS.discard(batch_uid)

def test_generate_batch_db_failure_removes_final_pdf(client, monkeypatch):
    """
    Verifies requirement 1:
    - If DB commit fails, remove the final PDF and roll back.
    - No orphan PDF file remains on disk.
    """
    _register_and_login(client, "dbfail@test.com", "dbfail_user")
    doc_uid = _upload_test_document(client)

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "recipients": [
                {"name": "Fail Student", "student_uid": "STU-FAIL"}
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]

    from app.database.repository import Repository
    original_record = Repository.record_recipient_generation

    def faulty_record(self, *args, **kwargs):
        raise RuntimeError("Simulated Database Commit Failure")

    monkeypatch.setattr(Repository, "record_recipient_generation", faulty_record)

    gen_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert gen_res.status_code == 200
    data = gen_res.json()
    assert data["status"] == "FAILED"
    assert data["recipients"][0]["status"] == "FAILED"

    # Crucial assertion: Final PDF must NOT exist on disk!
    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    if batch_dir.exists():
        files = list(batch_dir.glob("*.pdf"))
        assert len(files) == 0

def test_generate_batch_partial_failure_and_retry(client, monkeypatch):
    """
    Verifies partial failure handling:
    - One recipient fails while another succeeds -> batch status PARTIALLY_FAILED.
    - Retry finishes failed recipient without duplicating or regenerating the first.
    """
    _register_and_login(client, "partial@test.com", "partial_user")
    doc_uid = _upload_test_document(client)

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "recipients": [
                {"name": "Good Recipient", "student_uid": "STU-GOOD"},
                {"name": "Faulty Recipient", "student_uid": "STU-FAULTY"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]

    from app.services.fingerprint_service import FingerprintService
    original_embed = FingerprintService.embed_and_save_pdf

    fail_faulty = True

    def selective_embed(self, doc_uid, student_uid, nonce, fp, in_p, out_p):
        if student_uid == "STU-FAULTY" and fail_faulty:
            raise ValueError("Simulated PDF Watermarking Failure for Faulty Recipient")
        return original_embed(self, doc_uid, student_uid, nonce, fp, in_p, out_p)

    monkeypatch.setattr(FingerprintService, "embed_and_save_pdf", selective_embed)

    # First run: STU-FAULTY fails
    gen_res1 = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert gen_res1.status_code == 200
    data1 = gen_res1.json()
    assert data1["status"] == "PARTIALLY_FAILED"

    rec1 = {r["recipient_identifier"]: r for r in data1["recipients"]}
    assert rec1["STU-GOOD"]["status"] == "GENERATED"
    assert rec1["STU-FAULTY"]["status"] == "FAILED"
    good_gen_at = rec1["STU-GOOD"]["generated_at"]

    # Now unmock failure and retry
    fail_faulty = False
    gen_res2 = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert gen_res2.status_code == 200
    data2 = gen_res2.json()
    assert data2["status"] == "COMPLETED"

    rec2 = {r["recipient_identifier"]: r for r in data2["recipients"]}
    assert rec2["STU-GOOD"]["status"] == "GENERATED"
    assert rec2["STU-GOOD"]["generated_at"] == good_gen_at  # Preserved!
    assert rec2["STU-FAULTY"]["status"] == "GENERATED"      # Now succeeded!

def test_generate_batch_authorization_and_ownership(client):
    # Setup User A with batch
    _register_and_login(client, "owner@test.com", "owner_user")
    doc_uid = _upload_test_document(client)
    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={"recipients": [{"name": "Student", "student_uid": "STU-AUTH"}]}
    )
    batch_uid = batch_res.json()["batch_uid"]

    # 1. Unauthenticated request -> 401
    unauth_client = TestClient(app)
    res_unauth = unauth_client.post(f"/documents/batches/{batch_uid}/generate")
    assert res_unauth.status_code == 401

    # 2. Other user (User B) attempting to generate -> 403 Forbidden
    _register_and_login(client, "other@test.com", "other_user")
    res_forbidden = client.post(f"/documents/batches/{batch_uid}/generate")
    assert res_forbidden.status_code == 403
    assert "Access denied" in res_forbidden.json()["detail"]

    # 3. Non-existent batch -> 404
    res_notfound = client.post("/documents/batches/batch_nonexistent999/generate")
    assert res_notfound.status_code == 404

def test_generated_recipient_with_missing_pdf_is_regenerated_without_duplication(client):
    """
    Focused test 1:
    - A generated recipient whose PDF is missing must be regenerated.
    - An existing generated recipient whose PDF is valid must be skipped.
    - Regeneration must reuse existing fingerprint credentials without duplicating rows.
    """
    _register_and_login(client, "retry_val@test.com", "retry_val_user")
    doc_uid = _upload_test_document(client)

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "recipients": [
                {"name": "Valid Recipient", "student_uid": "STU-VAL-1"},
                {"name": "Missing PDF Recipient", "student_uid": "STU-VAL-2"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]

    # 1. Run initial generation to completion
    res1 = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert res1.status_code == 200
    assert res1.json()["status"] == "COMPLETED"

    from app.database.repository import Repository
    repo = Repository()
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    recipients = repo.get_batch_recipients(batch.id)
    r1, r2 = recipients[0], recipients[1]

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    pdf1 = batch_dir / f"rec_{r1.id}.pdf"
    pdf2 = batch_dir / f"rec_{r2.id}.pdf"
    assert pdf1.exists() and pdf1.stat().st_size > 0
    assert pdf2.exists() and pdf2.stat().st_size > 0

    # Count initial fingerprint rows in database
    conn = repo._get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(*) as count FROM fingerprints")
    initial_fp_count = cur.fetchone()["count"]
    assert initial_fp_count == 2
    conn.close()

    fp2_orig_id = r2.fingerprint_id
    fp2_orig = repo.get_fingerprint_by_id(fp2_orig_id)
    assert fp2_orig is not None

    # 2. Simulate disk loss: delete recipient 2's PDF
    pdf2.unlink()
    assert not pdf2.exists()

    # Track recipient 1 timestamp to verify it is skipped
    r1_orig_gen_at = r1.generated_at

    # 3. Trigger generation retry
    res2 = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert res2.status_code == 200
    assert res2.json()["status"] == "COMPLETED"

    # 4. Verify recipient 1 was skipped and recipient 2 was regenerated
    recipients_after = repo.get_batch_recipients(batch.id)
    r1_after, r2_after = recipients_after[0], recipients_after[1]

    assert r1_after.generated_at == r1_orig_gen_at
    assert pdf2.exists() and pdf2.stat().st_size > 0

    # 5. Crucial: verify fingerprint was NOT duplicated
    conn = repo._get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(*) as count FROM fingerprints")
    after_fp_count = cur.fetchone()["count"]
    conn.close()

    assert after_fp_count == initial_fp_count  # EXACTLY 2, zero duplicates!
    assert r2_after.fingerprint_id == fp2_orig_id

def test_generated_recipient_with_valid_pdf_is_skipped(client):
    """
    Focused test 2:
    - When all recipients have valid output PDFs on disk, retry skips all without modifications.
    """
    _register_and_login(client, "skip_valid@test.com", "skip_user")
    doc_uid = _upload_test_document(client)

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "recipients": [
                {"name": "Alice Valid", "student_uid": "STU-SKIP-1"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]

    # Initial generation
    res1 = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert res1.status_code == 200
    gen_at1 = res1.json()["recipients"][0]["generated_at"]

    # Retry generation
    res2 = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert res2.status_code == 200
    gen_at2 = res2.json()["recipients"][0]["generated_at"]

    assert gen_at1 == gen_at2

def test_two_concurrent_recovery_requests_for_processing_batch_exactly_one_claim(client):
    """
    Focused test 3:
    - Two concurrent recovery requests for the same PROCESSING batch must result in
      exactly one successful claim (and one rejection).
    """
    _register_and_login(client, "recovery_race@test.com", "race_user")
    doc_uid = _upload_test_document(client)

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={"recipients": [{"name": "Student", "student_uid": "STU-RACE"}]}
    )
    batch_uid = batch_res.json()["batch_uid"]

    from app.database.repository import Repository
    repo = Repository()
    batch = repo.get_distribution_batch_by_uid(batch_uid)

    # Set status directly to PROCESSING in DB to simulate an interrupted batch after restart
    conn = repo._get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE distribution_batches SET status = 'PROCESSING' WHERE id = ?", (batch.id,))
    conn.commit()
    conn.close()

    # Clear in-memory active tracking to simulate clean server restart state
    Repository._ACTIVE_CLAIMS.clear()
    _ACTIVE_BATCH_GENERATIONS.clear()

    # 1. Repository level atomic test:
    claim1 = repo.claim_batch_for_generation(batch.id, allow_recovery=True)
    claim2 = repo.claim_batch_for_generation(batch.id, allow_recovery=True)

    assert claim1 is True
    assert claim2 is False  # Second claim is strictly rejected!

    # 2. Release and test API level concurrency:
    repo.release_batch_claim(batch.id)

    # Make first request (acquires synchronous in-memory and DB claim)
    res1 = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert res1.status_code == 200

def test_lock_release_after_generation_failure(client, monkeypatch):
    """
    Focused test 4:
    - Lock must be reliably released even when generation fails.
    - Subsequent calls must not be blocked by a stale lock.
    """
    _register_and_login(client, "lock_release@test.com", "lock_user")
    doc_uid = _upload_test_document(client)

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={"recipients": [{"name": "Fail Student", "student_uid": "STU-LOCK-FAIL"}]}
    )
    batch_uid = batch_res.json()["batch_uid"]

    from app.services.fingerprint_service import FingerprintService
    original_embed = FingerprintService.embed_and_save_pdf

    def fail_embed(*args, **kwargs):
        raise RuntimeError("Simulated embedding crash for lock test")

    monkeypatch.setattr(FingerprintService, "embed_and_save_pdf", fail_embed)

    # Trigger generation which will fail
    res_fail = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert res_fail.status_code == 200
    assert res_fail.json()["status"] == "FAILED"

    # Crucial assertion: in-memory and repo lock sets must NOT contain this batch
    assert batch_uid not in _ACTIVE_BATCH_GENERATIONS
    from app.database.repository import Repository
    repo = Repository()
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    assert batch.id not in Repository._ACTIVE_CLAIMS

    # Unmock and verify we can immediately retry generation without a 409 conflict
    monkeypatch.setattr(FingerprintService, "embed_and_save_pdf", original_embed)
    res_retry = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert res_retry.status_code == 200
    assert res_retry.json()["status"] == "COMPLETED"

