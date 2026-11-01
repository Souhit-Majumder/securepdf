import io
import os
import pymupdf
import pytest
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database.database import init_db, get_connection
from app.database.repository import Repository
from app.config import config
from starlette.background import BackgroundTask
from app.api.routes.distribution import (
    _ACTIVE_BATCH_GENERATIONS,
    _ACTIVE_DOWNLOADS,
    _DOWNLOAD_LOCK,
    DownloadReleaseGuard,
    run_expired_batch_pdfs_cleanup,
)

@pytest.fixture
def client(tmp_path, monkeypatch):
    test_data = tmp_path / "data"
    test_db = test_data / "test_download.db"
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
    with _DOWNLOAD_LOCK:
        _ACTIVE_DOWNLOADS.clear()
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

def _upload_test_document(client: TestClient, title: str = "Confidential_Report.pdf"):
    pdf_bytes = _create_valid_pdf_bytes()
    res = client.post(
        "/documents/",
        files={"file": (title, io.BytesIO(pdf_bytes), "application/pdf")},
        data={"title": title}
    )
    assert res.status_code == 201
    return res.json()["document_uid"]

def test_token_creation_and_expiry_timestamps(client):
    _register_and_login(client, "alice@test.com", "alice_uploader")
    doc_uid = _upload_test_document(client, "ExamPaper.pdf")

    # Create batch with 600s expiry
    create_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 600,
            "recipients": [
                {"name": "Student One", "student_uid": "STU-TOKEN-01"},
                {"name": "Student Two", "student_uid": "STU-TOKEN-02"}
            ]
        }
    )
    assert create_res.status_code == 201
    batch_uid = create_res.json()["batch_uid"]

    # Generate PDFs synchronously
    gen_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert gen_res.status_code == 200
    assert gen_res.json()["status"] == "COMPLETED"

    # Inspect SQLite database directly
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM distribution_batch_recipients WHERE batch_id = (SELECT id FROM distribution_batches WHERE batch_uid = ?)", (batch_uid,))
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 2
    for row in rows:
        assert row["status"] == "GENERATED"
        assert row["download_token"] is not None
        assert len(row["download_token"]) >= 32
        assert row["generated_at"] is not None
        assert row["expires_at"] is not None

        gen_dt = datetime.fromisoformat(row["generated_at"].replace("Z", "+00:00"))
        exp_dt = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        delta_seconds = int((exp_dt - gen_dt).total_seconds())
        assert delta_seconds == 600

def test_owner_batch_status_returns_download_url_without_leaking_secrets(client):
    _register_and_login(client, "owner@test.com", "owner_user")
    doc_uid = _upload_test_document(client, "ProjectBrief.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "recipients": [{"name": "Charlie Brown", "student_uid": "STU-SEC-99"}]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    # Fetch status via GET
    status_res = client.get(f"/documents/batches/{batch_uid}")
    assert status_res.status_code == 200
    data = status_res.json()

    recipient = data["recipients"][0]
    assert recipient["status"] == "GENERATED"
    assert recipient["download_url"] is not None
    assert recipient["download_url"].startswith("/documents/download/")

    # Strict privacy assertions: NO download_token field, NO filesystem paths, NO fingerprint IDs or nonces
    assert "download_token" not in recipient
    assert "fingerprint_id" not in recipient
    assert "nonce" not in recipient
    assert "file_path" not in recipient
    assert "path" not in recipient

def test_successful_public_download_with_valid_token(client):
    _register_and_login(client, "prof@test.com", "prof_user")
    doc_uid = _upload_test_document(client, "FinalExam_2026.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 180,
            "recipients": [{"name": "Dana Scully", "student_uid": "STU-PUBLIC-1"}]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    status_data = client.get(f"/documents/batches/{batch_uid}").json()
    download_url = status_data["recipients"][0]["download_url"]

    # Public download using a completely unauthenticated client (no session cookie)
    public_client = TestClient(app)
    dl_res = public_client.get(download_url)

    assert dl_res.status_code == 200
    assert dl_res.headers["content-type"] == "application/pdf"
    assert dl_res.content.startswith(b"%PDF")

    # Content-Disposition contains sanitized filename without recipient identifier or DB keys
    content_disp = dl_res.headers.get("content-disposition", "")
    assert "attachment" in content_disp
    assert "FinalExam_2026.pdf" in content_disp
    assert "STU-PUBLIC-1" not in content_disp
    assert "rec_" not in content_disp

def test_invalid_token_returns_404(client):
    res = client.get("/documents/download/nonexistent_token_1234567890")
    assert res.status_code == 404
    assert "Invalid or non-existent download token" in res.json()["detail"]

def test_expired_link_returns_410_and_deletes_pdf_while_preserving_db_records(client):
    _register_and_login(client, "uploader@test.com", "exp_uploader")
    doc_uid = _upload_test_document(client, "StrictTiming.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 30,
            "recipients": [{"name": "Fox Mulder", "student_uid": "STU-EXP-01"}]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    batch_data = client.get(f"/documents/batches/{batch_uid}").json()
    download_url = batch_data["recipients"][0]["download_url"]
    token = download_url.split("/")[-1]

    # Verify physical PDF exists on disk before expiration
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, fingerprint_id FROM distribution_batch_recipients WHERE download_token = ?", (token,))
    rec_row = cursor.fetchone()
    rec_id = rec_row["id"]
    fp_id = rec_row["fingerprint_id"]

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    pdf_path = batch_dir / f"rec_{rec_id}.pdf"
    assert pdf_path.exists()

    # Artificially set expires_at in SQLite to 10 minutes in the past
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor.execute("UPDATE distribution_batch_recipients SET expires_at = ? WHERE id = ?", (past_time, rec_id))
    conn.commit()
    conn.close()

    # Attempt download after expiration
    expired_dl_res = client.get(f"/documents/download/{token}")
    assert expired_dl_res.status_code == 410
    assert "This download link has expired" in expired_dl_res.json()["detail"]

    # Invariant: Physical file on disk MUST be deleted!
    assert not pdf_path.exists()

    # Invariant: DB records (recipient and fingerprint) MUST be strictly preserved for forensic attribution!
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status, fingerprint_id FROM distribution_batch_recipients WHERE id = ?", (rec_id,))
    preserved_rec = cursor.fetchone()
    assert preserved_rec["status"] == "EXPIRED"
    assert preserved_rec["fingerprint_id"] == fp_id

    cursor.execute("SELECT * FROM fingerprints WHERE id = ?", (fp_id,))
    preserved_fp = cursor.fetchone()
    assert preserved_fp is not None
    conn.close()

def test_periodic_cleanup_deletes_expired_pdfs_safely(client):
    _register_and_login(client, "clean@test.com", "clean_user")
    doc_uid = _upload_test_document(client, "CleanupTest.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 60,
            "recipients": [
                {"name": "Recipient Expired", "student_uid": "STU-CLEAN-EXPIRED"},
                {"name": "Recipient Active", "student_uid": "STU-CLEAN-ACTIVE"}
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, recipient_identifier FROM distribution_batch_recipients WHERE batch_id = (SELECT id FROM distribution_batches WHERE batch_uid = ?)", (batch_uid,))
    rows = cursor.fetchall()
    id_map = {r["recipient_identifier"]: r["id"] for r in rows}

    # Expire only the first recipient
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor.execute("UPDATE distribution_batch_recipients SET expires_at = ? WHERE id = ?", (past_iso, id_map["STU-CLEAN-EXPIRED"]))
    conn.commit()
    conn.close()

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    expired_pdf = batch_dir / f"rec_{id_map['STU-CLEAN-EXPIRED']}.pdf"
    active_pdf = batch_dir / f"rec_{id_map['STU-CLEAN-ACTIVE']}.pdf"

    assert expired_pdf.exists()
    assert active_pdf.exists()

    # Trigger background cleanup function directly
    repo = Repository()
    cleaned = run_expired_batch_pdfs_cleanup(repo)
    assert cleaned >= 1

    # Expired PDF deleted, active PDF preserved
    assert not expired_pdf.exists()
    assert active_pdf.exists()

def test_concurrent_download_cleanup_protection(client):
    _register_and_login(client, "concur@test.com", "concur_user")
    doc_uid = _upload_test_document(client, "ConcurTest.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 30,
            "recipients": [{"name": "Streamer", "student_uid": "STU-STREAM-1"}]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM distribution_batch_recipients WHERE batch_id = (SELECT id FROM distribution_batches WHERE batch_uid = ?)", (batch_uid,))
    rec_id = cursor.fetchone()["id"]

    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor.execute("UPDATE distribution_batch_recipients SET expires_at = ? WHERE id = ?", (past_iso, rec_id))
    conn.commit()
    conn.close()

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    pdf_path = batch_dir / f"rec_{rec_id}.pdf"
    assert pdf_path.exists()

    # Simulate an active in-flight stream using DownloadReleaseGuard
    guard = DownloadReleaseGuard(pdf_path)
    assert _ACTIVE_DOWNLOADS[pdf_path] == 1

    # Run cleanup: should NOT delete file while marked active
    repo = Repository()
    run_expired_batch_pdfs_cleanup(repo)
    assert pdf_path.exists()

    # Finish stream and remove from _ACTIVE_DOWNLOADS
    guard.release()
    assert pdf_path not in _ACTIVE_DOWNLOADS

    # Next cleanup tick deletes the file
    run_expired_batch_pdfs_cleanup(repo)
    assert not pdf_path.exists()

def test_retry_preserves_existing_valid_token_and_expiry(client):
    _register_and_login(client, "retry@test.com", "retry_user")
    doc_uid = _upload_test_document(client, "RetryPreserve.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 600,
            "recipients": [
                {"name": "Alice Keep", "student_uid": "STU-ALICE-KEEP"},
                {"name": "Bob Reger", "student_uid": "STU-BOB-REGEN"}
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    # Record initial tokens and timestamps
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, recipient_identifier, download_token, generated_at, expires_at FROM distribution_batch_recipients WHERE batch_id = (SELECT id FROM distribution_batches WHERE batch_uid = ?)", (batch_uid,))
    initial_rows = {r["recipient_identifier"]: dict(r) for r in cursor.fetchall()}
    conn.close()

    alice_initial = initial_rows["STU-ALICE-KEEP"]
    bob_initial = initial_rows["STU-BOB-REGEN"]

    # Delete Bob's PDF to trigger partial regeneration
    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    (batch_dir / f"rec_{bob_initial['id']}.pdf").unlink()

    # Run generation retry
    retry_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert retry_res.status_code == 200

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, recipient_identifier, download_token, generated_at, expires_at FROM distribution_batch_recipients WHERE batch_id = (SELECT id FROM distribution_batches WHERE batch_uid = ?)", (batch_uid,))
    post_retry_rows = {r["recipient_identifier"]: dict(r) for r in cursor.fetchall()}
    conn.close()

    alice_post = post_retry_rows["STU-ALICE-KEEP"]
    bob_post = post_retry_rows["STU-BOB-REGEN"]

    # Invariant: Alice's existing token, generated_at, and expires_at are strictly preserved!
    assert alice_post["download_token"] == alice_initial["download_token"]
    assert alice_post["generated_at"] == alice_initial["generated_at"]
    assert alice_post["expires_at"] == alice_initial["expires_at"]

    # Bob's existing token is also preserved upon missing-file regeneration
    assert bob_post["download_token"] == bob_initial["download_token"]
    assert (batch_dir / f"rec_{bob_initial['id']}.pdf").exists()

def test_owner_access_control_on_batch_status(client):
    _register_and_login(client, "owner_a@test.com", "user_a")
    doc_uid = _upload_test_document(client, "DocA.pdf")
    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={"expiry_duration_seconds": 120, "recipients": [{"name": "Student A", "student_uid": "STU-A"}]}
    )
    batch_uid = batch_res.json()["batch_uid"]

    # User B logs in
    _register_and_login(client, "owner_b@test.com", "user_b")
    forbidden_res = client.get(f"/documents/batches/{batch_uid}")
    assert forbidden_res.status_code == 403
    assert "Access denied" in forbidden_res.json()["detail"]

def test_two_simultaneous_downloads_cleanup_skips_until_both_finish(client):
    _register_and_login(client, "simul@test.com", "simul_user")
    doc_uid = _upload_test_document(client, "SimulDoc.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={"expiry_duration_seconds": 30, "recipients": [{"name": "Simul Student", "student_uid": "STU-SIMUL"}]}
    )
    batch_uid = batch_res.json()["batch_uid"]
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM distribution_batch_recipients WHERE batch_id = (SELECT id FROM distribution_batches WHERE batch_uid = ?)", (batch_uid,))
    rec_id = cursor.fetchone()["id"]

    # Mark expired in past
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor.execute("UPDATE distribution_batch_recipients SET expires_at = ? WHERE id = ?", (past_iso, rec_id))
    conn.commit()
    conn.close()

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    pdf_path = batch_dir / f"rec_{rec_id}.pdf"
    assert pdf_path.exists()

    # Stream 1 starts
    guard1 = DownloadReleaseGuard(pdf_path)
    assert _ACTIVE_DOWNLOADS[pdf_path] == 1

    # Stream 2 starts for the same file
    guard2 = DownloadReleaseGuard(pdf_path)
    assert _ACTIVE_DOWNLOADS[pdf_path] == 2

    # Stream 1 finishes
    guard1.release()
    assert _ACTIVE_DOWNLOADS[pdf_path] == 1

    # Cleanup runs while Stream 2 is still active: MUST NOT delete the file!
    repo = Repository()
    cleaned = run_expired_batch_pdfs_cleanup(repo)
    assert cleaned == 0
    assert pdf_path.exists()

    # Stream 2 finishes
    guard2.release()
    assert pdf_path not in _ACTIVE_DOWNLOADS

    # Now cleanup runs: file MUST be safely unlinked!
    cleaned = run_expired_batch_pdfs_cleanup(repo)
    assert cleaned == 1
    assert not pdf_path.exists()

@pytest.mark.anyio
async def test_client_disconnect_before_first_chunk_releases_registration(tmp_path):
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    guard = DownloadReleaseGuard(dummy_pdf)
    assert _ACTIVE_DOWNLOADS[dummy_pdf] == 1

    f = open(dummy_pdf, "rb")
    guard.attach_file(f)

    # Starlette background task attached to response
    bg = BackgroundTask(guard.release)

    # Client disconnects before generator is ever iterated:
    # Starlette executes the background task upon request finalization
    await bg()

    # Invariants: active count decremented and file handle closed!
    assert dummy_pdf not in _ACTIVE_DOWNLOADS
    assert f.closed is True

def test_generator_normal_completion_and_exception_releases_guard(tmp_path):
    dummy_pdf = tmp_path / "stream_test.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 " + b"X" * 1024)

    # Case A: Normal iteration to completion
    guard_a = DownloadReleaseGuard(dummy_pdf)
    assert _ACTIVE_DOWNLOADS[dummy_pdf] == 1
    fa = open(dummy_pdf, "rb")
    guard_a.attach_file(fa)

    def iter_normal():
        try:
            while chunk := fa.read(512):
                yield chunk
        finally:
            guard_a.release()

    chunks = list(iter_normal())
    assert len(chunks) > 0
    assert dummy_pdf not in _ACTIVE_DOWNLOADS
    assert fa.closed is True

    # Case B: Exception during iteration
    guard_b = DownloadReleaseGuard(dummy_pdf)
    assert _ACTIVE_DOWNLOADS[dummy_pdf] == 1
    fb = open(dummy_pdf, "rb")
    guard_b.attach_file(fb)

    def iter_error():
        try:
            chunk = fb.read(512)
            yield chunk
            raise RuntimeError("Client aborted stream unexpectedly")
        finally:
            guard_b.release()

    gen = iter_error()
    next(gen)
    with pytest.raises(RuntimeError):
        next(gen)

    assert dummy_pdf not in _ACTIVE_DOWNLOADS
    assert fb.closed is True

def test_duplicate_release_attempts_do_not_corrupt_reference_count(tmp_path):
    dummy_pdf = tmp_path / "duplicate_test.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 duplicate")

    guard1 = DownloadReleaseGuard(dummy_pdf)
    guard2 = DownloadReleaseGuard(dummy_pdf)
    assert _ACTIVE_DOWNLOADS[dummy_pdf] == 2

    # Guard 1 is released once
    guard1.release()
    assert _ACTIVE_DOWNLOADS[dummy_pdf] == 1

    # Simulate duplicate release attempts on guard 1 (e.g. generator finally + BackgroundTask)
    for _ in range(5):
        guard1.release()
    assert _ACTIVE_DOWNLOADS[dummy_pdf] == 1

    # Guard 2 released once
    guard2.release()
    assert dummy_pdf not in _ACTIVE_DOWNLOADS

    # Extra releases on guard 2 do not result in negative counts or exceptions
    for _ in range(5):
        guard2.release()
    assert dummy_pdf not in _ACTIVE_DOWNLOADS

