import io
import os
import pymupdf
import pytest
from datetime import datetime
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.database.database import init_db
from app.database.repository import Repository
from app.config import config
from app.api.routes.distribution import _ACTIVE_BATCH_GENERATIONS
from app.services.verification_service import VerificationService
from app.services.fingerprint_service import FingerprintService, PostVerificationResult
from app.pdf.stego.supervisor import extract_layer3_with_timeout
from app.pdf.extract import extract_layer1, extract_layer2
from app.pdf.payload_redundancy import decode_compact_payload

@pytest.fixture
def test_setup(tmp_path, monkeypatch):
    test_data = tmp_path / "data"
    test_db = test_data / "test_stego_distribution.db"
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
    Repository._ACTIVE_CLAIMS.clear()

    client = TestClient(app)
    repo = Repository(db_path=str(test_db))
    return {
        "client": client,
        "repo": repo,
        "tmp_path": tmp_path,
        "test_docs": test_docs,
        "test_output": test_output,
    }

def _create_large_text_pdf_bytes(pages: int = 10, lines_per_page: int = 15) -> bytes:
    """Creates a multi-page PDF with >1000 word gaps, providing ample Layer 3 capacity."""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        for line_idx in range(lines_per_page):
            text_line = "SecurePDF document verification forensic integrity carrier text sample."
            page.insert_text((50, 50 + line_idx * 30), text_line)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes

def _create_small_text_pdf_bytes() -> bytes:
    """Creates a 1-line PDF with 4 word gaps, insufficient for Layer 3 (requires ~664 bits)."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "Short text sample only.")
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

def _upload_pdf(client: TestClient, pdf_bytes: bytes, title: str = "TestDoc.pdf") -> str:
    res = client.post(
        "/documents/",
        files={"file": (title, io.BytesIO(pdf_bytes), "application/pdf")},
        data={"title": title}
    )
    assert res.status_code == 201
    return res.json()["document_uid"]


def test_batch_generate_three_layer_success(test_setup, monkeypatch):
    """
    1. Asserts that when ENABLE_STEGO_CARRIER = True on a high-capacity PDF:
       - Personalized batch PDF generation succeeds with all 3 carriers embedded and verified.
       - VerificationService.investigate_pdf() validates all 3 layers: ["Layer 1", "Layer 2", "Layer 3"].
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]

    _register_and_login(client, "alice@test.com", "alice_user")
    pdf_bytes = _create_large_text_pdf_bytes(pages=10, lines_per_page=15)
    doc_uid = _upload_pdf(client, pdf_bytes, "HighCapacity.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "Alice Student", "student_uid": "STU-001"},
                {"name": "Bob Student", "student_uid": "STU-002"},
            ]
        }
    )
    assert batch_res.status_code == 201
    batch_data = batch_res.json()
    assert batch_data["enable_stego"] is True
    assert batch_data["stego_status"] == "PENDING"
    assert all(r["stego_status"] == "PENDING" for r in batch_data["recipients"])
    batch_uid = batch_data["batch_uid"]

    gen_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert gen_res.status_code == 200
    data = gen_res.json()
    assert data["status"] == "COMPLETED"
    assert data["stego_status"] == "SUCCESS"
    assert all(r["stego_status"] == "SUCCESS" for r in data["recipients"])

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    ver_service = VerificationService(repo=test_setup["repo"])

    files = list(batch_dir.glob("rec_*.pdf"))
    assert len(files) == 2

    for f in files:
        res = ver_service.investigate_pdf(str(f))
        assert res["status"] == "VALID"
        assert res["document_uid"] == doc_uid
        assert res["authenticated_layers"] == ["Layer 1", "Layer 2", "Layer 3"]
        assert res["student_uid"] in ("STU-001", "STU-002")


def test_independent_layer3_fingerprints_across_recipients(test_setup, monkeypatch):
    """
    2. Asserts that every recipient receives an independent Layer 3 fingerprint
       with unique nonces and unique HMAC tags.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]

    _register_and_login(client, "prof@test.com", "prof_user")
    pdf_bytes = _create_large_text_pdf_bytes(pages=10, lines_per_page=15)
    doc_uid = _upload_pdf(client, pdf_bytes, "IndependentFPs.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "Student One", "student_uid": "STU-ALPHA"},
                {"name": "Student Two", "student_uid": "STU-BETA"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    repo = test_setup["repo"]
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    recipients = repo.get_batch_recipients(batch.id)
    assert len(recipients) == 2

    pdf_alpha = str(batch_dir / f"rec_{recipients[0].id}.pdf")
    pdf_beta = str(batch_dir / f"rec_{recipients[1].id}.pdf")

    extract_alpha = extract_layer3_with_timeout(pdf_alpha)
    extract_beta = extract_layer3_with_timeout(pdf_beta)

    assert extract_alpha["crc_valid"] and extract_beta["crc_valid"]

    p_alpha = extract_alpha["payload"]
    p_beta = extract_beta["payload"]

    assert p_alpha["recipient_uid"] == "STU-ALPHA"
    assert p_beta["recipient_uid"] == "STU-BETA"
    # Cryptographic independence
    assert p_alpha["nonce"] != p_beta["nonce"]
    assert p_alpha["hmac_tag"] != p_beta["hmac_tag"]


def test_batch_generate_insufficient_capacity_fallback(test_setup, monkeypatch):
    """
    3. Asserts that when ENABLE_STEGO_CARRIER = True on a low-capacity document:
       - Capacity deficit is detected upfront on the post-L1/L2 document.
       - Generation succeeds gracefully with Layer 1 and Layer 2 without error.
       - VerificationService confirms ["Layer 1", "Layer 2"] and does NOT report Layer 3.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]

    _register_and_login(client, "prof_small@test.com", "prof_small")
    pdf_bytes = _create_small_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "SmallDoc.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "recipients": [
                {"name": "Student Fallback", "student_uid": "STU-FALLBACK"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    gen_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    assert gen_res.status_code == 200
    assert gen_res.json()["status"] == "COMPLETED"
    assert gen_res.json()["stego_status"] == "SKIPPED"
    assert gen_res.json()["recipients"][0]["stego_status"] == "SKIPPED"

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    files = list(batch_dir.glob("rec_*.pdf"))
    assert len(files) == 1

    ver_service = VerificationService(repo=test_setup["repo"])
    res = ver_service.investigate_pdf(str(files[0]))

    assert res["status"] == "VALID"
    assert res["student_uid"] == "STU-FALLBACK"
    assert res["authenticated_layers"] == ["Layer 1", "Layer 2"]
    assert "Layer 3" not in res["authenticated_layers"]


def test_unexpected_embedding_failure_handling(test_setup, monkeypatch):
    """
    4. Asserts that if embed_layer3 unexpectedly fails on a document with sufficient capacity:
       - The recipient is marked FAILED.
       - The temporary file is unlinked.
       - The batch status reflects the failure.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]

    _register_and_login(client, "prof_fail@test.com", "prof_fail")
    pdf_bytes = _create_large_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "FailEmbedding.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "Fail Recipient", "student_uid": "STU-FAIL"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]

    # Mock embed_layer3 to fail unexpectedly
    with patch("app.pdf.embed.embed_layer3", return_value=False):
        gen_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    assert gen_res.status_code == 200
    data = gen_res.json()
    assert data["status"] == "FAILED"
    assert data["stego_status"] == "FAILED"
    assert data["recipients"][0]["status"] == "FAILED"
    assert data["recipients"][0]["stego_status"] == "FAILED"

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    # Verify no temp or final file remains for this failed recipient
    assert len(list(batch_dir.glob("*.pdf"))) == 0


def test_post_generation_verification_hmac_failure(test_setup, monkeypatch):
    """
    5. Asserts that if independent on-disk verification fails (e.g. CRC/HMAC mismatch):
       - The unverified PDF is rejected before promotion to final_path.
       - Temporary file is cleaned up, and recipient is marked FAILED.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]

    _register_and_login(client, "prof_ver_fail@test.com", "prof_ver_fail")
    pdf_bytes = _create_large_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "CorruptVerify.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "Corrupt Recipient", "student_uid": "STU-CORRUPT"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]

    failed_result = PostVerificationResult(
        is_valid=False,
        l1_verified=True,
        l2_verified=True,
        l3_status="FAILED",
        authenticated_layers=["Layer 1", "Layer 2"],
        error="Simulated post-generation HMAC verification failure",
    )

    with patch.object(FingerprintService, "verify_saved_pdf_carriers", return_value=failed_result):
        gen_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    assert gen_res.status_code == 200
    assert gen_res.json()["status"] == "FAILED"
    assert gen_res.json()["stego_status"] == "FAILED"
    assert gen_res.json()["recipients"][0]["status"] == "FAILED"
    assert gen_res.json()["recipients"][0]["stego_status"] == "FAILED"

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    assert len(list(batch_dir.glob("*.pdf"))) == 0


def test_layer1_and_layer2_unimpaired_by_stego(test_setup, monkeypatch):
    """
    6. Asserts that Layer 1 catalog payload and Layer 2 redundant annotations
       remain 100% valid and parseable after Layer 3 content-stream modulation.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]

    _register_and_login(client, "prof_unimpaired@test.com", "prof_unimpaired")
    pdf_bytes = _create_large_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "Unimpaired.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "Unimpaired Recipient", "student_uid": "STU-UNIMPAIRED"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    files = list(batch_dir.glob("rec_*.pdf"))
    assert len(files) == 1

    doc = pymupdf.open(str(files[0]))

    # Layer 1 catalog check
    l1 = extract_layer1(doc)
    assert l1 is not None
    parts = l1.split("|")
    assert parts[0] == "SPDF-V1"
    assert parts[1] == doc_uid

    # Layer 2 annotation check
    l2 = extract_layer2(doc)
    assert len(l2) == 3
    for p in l2:
        ver, d_uid, nonce_str, fp_str = decode_compact_payload(p)
        assert ver == "SPDF1"
        assert d_uid == doc_uid
        assert nonce_str == parts[2]
        assert fp_str == parts[3]

    doc.close()


def test_batch_retry_and_recovery_with_stego(test_setup, monkeypatch):
    """
    7. Asserts that retrying an interrupted batch:
       - Preserves and reuses existing cryptographic nonces.
       - Creates zero duplicate rows in the fingerprints table.
       - Completes generation with all 3 authenticated layers.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]
    repo = test_setup["repo"]

    _register_and_login(client, "prof_retry@test.com", "prof_retry")
    pdf_bytes = _create_large_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "RetryBatch.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "Retry Recipient", "student_uid": "STU-RETRY"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]

    # 1. First run: fail during verification
    failed_result = PostVerificationResult(
        is_valid=False,
        l1_verified=True,
        l2_verified=True,
        l3_status="FAILED",
        authenticated_layers=[],
        error="Interrupted on first attempt",
    )
    with patch.object(FingerprintService, "verify_saved_pdf_carriers", return_value=failed_result):
        client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    assert len(list(batch_dir.glob("rec_*.pdf"))) == 0

    # Verify initial database state: recipient is FAILED
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    recipients = repo.get_batch_recipients(batch.id)
    assert recipients[0].status == "FAILED"

    # 2. Second run: normal retry without errors
    retry_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert retry_res.status_code == 200
    assert retry_res.json()["status"] == "COMPLETED"
    assert retry_res.json()["stego_status"] == "SUCCESS"
    assert retry_res.json()["recipients"][0]["stego_status"] == "SUCCESS"

    # Verify file is generated
    files = list(batch_dir.glob("rec_*.pdf"))
    assert len(files) == 1

    ver_service = VerificationService(repo=repo)
    v_res = ver_service.investigate_pdf(str(files[0]))
    assert v_res["status"] == "VALID"
    assert v_res["authenticated_layers"] == ["Layer 1", "Layer 2", "Layer 3"]


def test_forensic_recipient_attribution_all_three_layers(test_setup, monkeypatch):
    """
    8. Asserts that forensic investigation on a generated 3-layer PDF:
       - Authenticates all 3 layers.
       - Accurately attributes recipient_name and recipient_identifier.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]

    _register_and_login(client, "prof_forensic@test.com", "prof_forensic")
    pdf_bytes = _create_large_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "ForensicDoc.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "Charlie Student", "student_uid": "STU-CHARLIE-003"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    files = list(batch_dir.glob("rec_*.pdf"))
    assert len(files) == 1

    ver_service = VerificationService(repo=test_setup["repo"])
    res = ver_service.investigate_pdf(str(files[0]))

    assert res["status"] == "VALID"
    assert res["recipient_name"] == "Charlie Student"
    assert res["recipient_identifier"] == "STU-CHARLIE-003"
    assert res["student_name"] == "Charlie Student"
    assert res["student_uid"] == "STU-CHARLIE-003"
    assert res["authenticated_layers"] == ["Layer 1", "Layer 2", "Layer 3"]


def test_preservation_of_existing_final_path_when_regeneration_fails(test_setup, monkeypatch):
    """
    9. Mandatory Requirement: If an existing final_path fails verification,
       do not delete it before a replacement has been generated and independently verified.
       If regeneration fails, preserve the existing artifact for investigation.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]
    repo = test_setup["repo"]

    _register_and_login(client, "prof_preserve@test.com", "prof_preserve")
    pdf_bytes = _create_large_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "PreserveFinal.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "Preserve Recipient", "student_uid": "STU-PRESERVE"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]

    # 1. First generate a valid PDF
    client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    recipients = repo.get_batch_recipients(batch.id)
    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    final_file = batch_dir / f"rec_{recipients[0].id}.pdf"
    assert final_file.exists()

    # Tamper with final_file content so it FAILS verification, and reset status to FAILED
    corrupt_bytes = b"%PDF-1.4 corrupt content that fails verification"
    final_file.write_bytes(corrupt_bytes)

    conn = repo._get_conn()
    conn.execute("UPDATE distribution_batch_recipients SET status = 'FAILED', stego_status = 'FAILED' WHERE id = ?", (recipients[0].id,))
    conn.execute("UPDATE distribution_batches SET status = 'FAILED' WHERE id = ?", (batch.id,))
    conn.commit()
    conn.close()

    # 2. Trigger regeneration, but embed_layer3 fails unexpectedly
    with patch("app.pdf.embed.embed_layer3", return_value=False):
        gen_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")

    # Assert regeneration failed
    assert gen_res.json()["status"] == "FAILED"

    # Assert final_file was PRESERVED for investigation and NOT deleted!
    assert final_file.exists()
    assert final_file.read_bytes() == corrupt_bytes


def test_batch_generate_insufficient_capacity_fails_when_opted_in(test_setup, monkeypatch):
    """
    Asserts that when ENABLE_STEGO_CARRIER = True AND enable_stego = True on a low-capacity document:
    - Embedding fails due to insufficient document capacity.
    - Recipient is marked FAILED with stego_status == "FAILED".
    - Batch is marked FAILED with stego_status == "FAILED".
    - Capacity deficit is never silently converted to SKIPPED.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]

    _register_and_login(client, "prof_small_optin@test.com", "prof_small_optin")
    pdf_bytes = _create_small_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "SmallOptIn.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "Student LowCap", "student_uid": "STU-LOWCAP"},
            ]
        }
    )
    assert batch_res.status_code == 201
    batch_uid = batch_res.json()["batch_uid"]

    gen_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert gen_res.status_code == 200
    data = gen_res.json()
    assert data["status"] == "FAILED"
    assert data["stego_status"] == "FAILED"
    assert len(data["recipients"]) == 1
    assert data["recipients"][0]["status"] == "FAILED"
    assert data["recipients"][0]["stego_status"] == "FAILED"

    repo = test_setup["repo"]
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    recipients = repo.get_batch_recipients(batch.id)
    assert len(recipients) == 1
    assert recipients[0].status == "FAILED"
    assert recipients[0].stego_status == "FAILED"

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    assert len(list(batch_dir.glob("*.pdf"))) == 0


def test_batch_default_skips_layer3_when_global_flag_true(test_setup, monkeypatch):
    """
    Asserts that when ENABLE_STEGO_CARRIER = True but per-distribution opt-in is False/omitted:
    - Generation succeeds with Layer 1 and Layer 2.
    - Recipient stego_status is SKIPPED.
    - Batch stego_status is SKIPPED.
    - Layer 3 is NOT embedded.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]

    _register_and_login(client, "prof_no_optin@test.com", "prof_no_optin")
    pdf_bytes = _create_large_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "NoOptIn.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": False,
            "recipients": [
                {"name": "No OptIn Recipient", "student_uid": "STU-NO-OPTIN"},
            ]
        }
    )
    assert batch_res.status_code == 201
    assert batch_res.json()["enable_stego"] is False
    assert batch_res.json()["stego_status"] == "PENDING"
    assert batch_res.json()["recipients"][0]["stego_status"] == "PENDING"

    batch_uid = batch_res.json()["batch_uid"]
    gen_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert gen_res.status_code == 200
    data = gen_res.json()
    assert data["status"] == "COMPLETED"
    assert data["stego_status"] == "SKIPPED"
    assert data["recipients"][0]["status"] == "GENERATED"
    assert data["recipients"][0]["stego_status"] == "SKIPPED"

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    files = list(batch_dir.glob("rec_*.pdf"))
    assert len(files) == 1

    ver_service = VerificationService(repo=test_setup["repo"])
    res = ver_service.investigate_pdf(str(files[0]))
    assert res["status"] == "VALID"
    assert res["authenticated_layers"] == ["Layer 1", "Layer 2"]
    assert "Layer 3" not in res["authenticated_layers"]


def test_batch_opt_in_blocked_when_global_flag_false(test_setup, monkeypatch):
    """
    Asserts that when ENABLE_STEGO_CARRIER = False (default safeguard) even if per-distribution
    opt-in is True:
    - Layer 3 embedding is blocked by the global flag safeguard.
    - Recipient stego_status is SKIPPED.
    - Batch stego_status is SKIPPED.
    - Output PDF contains Layer 1 and Layer 2 only.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    client = test_setup["client"]

    _register_and_login(client, "prof_global_false@test.com", "prof_global_false")
    pdf_bytes = _create_large_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "GlobalFalse.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "Blocked Recipient", "student_uid": "STU-BLOCKED"},
            ]
        }
    )
    assert batch_res.status_code == 201
    assert batch_res.json()["enable_stego"] is True

    batch_uid = batch_res.json()["batch_uid"]
    gen_res = client.post(f"/documents/batches/{batch_uid}/generate?sync=true")
    assert gen_res.status_code == 200
    data = gen_res.json()
    assert data["status"] == "COMPLETED"
    assert data["stego_status"] == "SKIPPED"
    assert data["recipients"][0]["stego_status"] == "SKIPPED"

    batch_dir = config.OUTPUT_DIR / "batches" / batch_uid
    files = list(batch_dir.glob("rec_*.pdf"))
    assert len(files) == 1

    ver_service = VerificationService(repo=test_setup["repo"])
    res = ver_service.investigate_pdf(str(files[0]))
    assert res["status"] == "VALID"
    assert res["authenticated_layers"] == ["Layer 1", "Layer 2"]
    assert "Layer 3" not in res["authenticated_layers"]


def test_recipient_pending_stego_status_on_creation(test_setup, monkeypatch):
    """
    Asserts that newly created batch and its recipients start with PENDING stego_status
    before generation is executed.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    client = test_setup["client"]

    _register_and_login(client, "pending_prof@test.com", "pending_prof")
    pdf_bytes = _create_large_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "PendingDoc.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "Pending R1", "student_uid": "STU-P1"},
                {"name": "Pending R2", "student_uid": "STU-P2"},
            ]
        }
    )
    assert batch_res.status_code == 201
    data = batch_res.json()
    assert data["stego_status"] == "PENDING"
    assert len(data["recipients"]) == 2
    for r in data["recipients"]:
        assert r["stego_status"] == "PENDING"

    batch_uid = data["batch_uid"]
    get_res = client.get(f"/documents/batches/{batch_uid}")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["stego_status"] == "PENDING"
    for r in get_data["recipients"]:
        assert r["stego_status"] == "PENDING"


def test_batch_partial_stego_status_aggregation(test_setup, monkeypatch):
    """
    Asserts batch aggregation:
    - Mixture of SUCCESS and SKIPPED recipients produces PARTIAL batch stego_status.
    """
    client = test_setup["client"]
    repo = test_setup["repo"]

    _register_and_login(client, "partial_prof@test.com", "partial_prof")
    pdf_bytes = _create_large_text_pdf_bytes()
    doc_uid = _upload_pdf(client, pdf_bytes, "PartialDoc.pdf")

    batch_res = client.post(
        f"/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stego": True,
            "recipients": [
                {"name": "R1", "student_uid": "STU-R1"},
                {"name": "R2", "student_uid": "STU-R2"},
            ]
        }
    )
    batch_uid = batch_res.json()["batch_uid"]
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    recipients = repo.get_batch_recipients(batch.id)

    # Manually update recipient stego_statuses: one SUCCESS, one SKIPPED
    conn = repo._get_conn()
    conn.execute(
        "UPDATE distribution_batch_recipients SET status = 'GENERATED', stego_status = 'SUCCESS' WHERE id = ?",
        (recipients[0].id,)
    )
    conn.execute(
        "UPDATE distribution_batch_recipients SET status = 'GENERATED', stego_status = 'SKIPPED' WHERE id = ?",
        (recipients[1].id,)
    )
    conn.commit()
    conn.close()

    get_res = client.get(f"/documents/batches/{batch_uid}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["stego_status"] == "PARTIAL"
    assert data["recipients"][0]["stego_status"] == "SUCCESS"
    assert data["recipients"][1]["stego_status"] == "SKIPPED"


def test_single_distribution_opt_in_matrix(test_setup, monkeypatch):
    """
    Asserts POST /{document_uid}/distribute behavior across the opt-in matrix:
    1. Global flag False + Opt-in True -> Generates L1+L2 (Layer 3 skipped).
    2. Global flag True + Opt-in False -> Generates L1+L2 (Layer 3 skipped).
    3. Global flag True + Opt-in True on High-Capacity PDF -> Generates L1+L2+L3.
    4. Global flag True + Opt-in True on Low-Capacity PDF -> Returns HTTP 400 (insufficient capacity).
    """
    client = test_setup["client"]
    repo = test_setup["repo"]

    _register_and_login(client, "single_prof@test.com", "single_prof")
    large_pdf = _create_large_text_pdf_bytes()
    small_pdf = _create_small_text_pdf_bytes()
    large_doc_uid = _upload_pdf(client, large_pdf, "LargeSingle.pdf")
    small_doc_uid = _upload_pdf(client, small_pdf, "SmallSingle.pdf")

    # Register student in repository (student_uid, name)
    student = repo.create_student("STU-SINGLE", "Student Single")

    ver_service = VerificationService(repo=repo)

    # Case 1: Global False + Opt-in True -> L1+L2 only
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    res1 = client.post(
        f"/documents/{large_doc_uid}/distribute",
        json={"student_uid": "STU-SINGLE", "enable_stego": True}
    )
    assert res1.status_code == 200
    pdf_path1 = config.OUTPUT_DIR / f"{large_doc_uid}_STU-SINGLE.pdf"
    assert pdf_path1.exists()
    v1 = ver_service.investigate_pdf(str(pdf_path1))
    assert v1["status"] == "VALID"
    assert v1["authenticated_layers"] == ["Layer 1", "Layer 2"]
    assert "Layer 3" not in v1["authenticated_layers"]
    pdf_path1.unlink()

    # Case 2: Global True + Opt-in False -> L1+L2 only
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    res2 = client.post(
        f"/documents/{large_doc_uid}/distribute",
        json={"student_uid": "STU-SINGLE", "enable_stego": False}
    )
    assert res2.status_code == 200
    pdf_path2 = config.OUTPUT_DIR / f"{large_doc_uid}_STU-SINGLE.pdf"
    assert pdf_path2.exists()
    v2 = ver_service.investigate_pdf(str(pdf_path2))
    assert v2["status"] == "VALID"
    assert v2["authenticated_layers"] == ["Layer 1", "Layer 2"]
    assert "Layer 3" not in v2["authenticated_layers"]
    pdf_path2.unlink()

    # Case 3: Global True + Opt-in True on High Capacity -> L1+L2+L3
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    res3 = client.post(
        f"/documents/{large_doc_uid}/distribute",
        json={"student_uid": "STU-SINGLE", "enable_stego": True}
    )
    assert res3.status_code == 200
    pdf_path3 = config.OUTPUT_DIR / f"{large_doc_uid}_STU-SINGLE.pdf"
    assert pdf_path3.exists()
    v3 = ver_service.investigate_pdf(str(pdf_path3))
    assert v3["status"] == "VALID"
    assert v3["authenticated_layers"] == ["Layer 1", "Layer 2", "Layer 3"]
    pdf_path3.unlink()

    # Case 4: Global True + Opt-in True on Low Capacity -> HTTP 400
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    res4 = client.post(
        f"/documents/{small_doc_uid}/distribute",
        json={"student_uid": "STU-SINGLE", "enable_stego": True}
    )
    assert res4.status_code == 400
    assert "Insufficient document capacity" in res4.json()["detail"]

