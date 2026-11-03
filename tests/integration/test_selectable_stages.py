import io
import os
import sqlite3
import pymupdf
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.database.database import init_db
from app.database.repository import Repository
from app.config import config
from app.services.fingerprint_service import FingerprintService
from app.services.verification_service import VerificationService
from app.pdf.extract import extract_layer1, extract_layer2
from app.pdf.stego.supervisor import extract_layer3_with_timeout

@pytest.fixture
def stages_env(tmp_path, monkeypatch):
    test_data = tmp_path / "data"
    test_db = test_data / "test_selectable_stages.db"
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

    client = TestClient(app)
    repo = Repository(db_path=str(test_db))
    service = FingerprintService(repo=repo)
    v_service = VerificationService(repo=repo)

    return {
        "client": client,
        "repo": repo,
        "service": service,
        "v_service": v_service,
        "tmp_path": tmp_path,
        "test_db": test_db,
        "test_docs": test_docs,
        "test_output": test_output,
    }

def _create_high_capacity_pdf_bytes(pages: int = 8, lines: int = 15) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        for line_idx in range(lines):
            page.insert_text(
                (50, 50 + line_idx * 30),
                "SecurePDF forensic security testing document for multi-carrier verification."
            )
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes

def _register_and_login(client: TestClient, email: str = "author@securepdf.test", username: str = "author"):
    client.post("/api/auth/register", json={"email": email, "username": username, "password": "Password123!"})
    res = client.post("/api/auth/login", json={"identifier": username, "password": "Password123!"})
    assert res.status_code == 200

def _upload_test_pdf(client: TestClient, pdf_bytes: bytes, title: str = "Doc.pdf") -> str:
    res = client.post(
        "/documents/",
        files={"file": (title, io.BytesIO(pdf_bytes), "application/pdf")},
        data={"title": title}
    )
    assert res.status_code == 201
    return res.json()["document_uid"]

# ---------------------------------------------------------------------------
# Test 1: Global Stage 3 environment gating removal
# ---------------------------------------------------------------------------
def test_stage3_environment_gating_removed():
    """Verify SECUREPDF_ENABLE_STEGO_CARRIER is completely removed from config."""
    assert not hasattr(config, "ENABLE_STEGO_CARRIER")
    assert not hasattr(config, "_enable_stego_carrier")


# ---------------------------------------------------------------------------
# Test 2: Rejection of zero selected stages with HTTP 422
# ---------------------------------------------------------------------------
def test_zero_stages_rejected_http_422(stages_env):
    """Verify batch and single distribution reject requests with all 3 stages disabled using HTTP 422."""
    client = stages_env["client"]
    _register_and_login(client)

    pdf_bytes = _create_high_capacity_pdf_bytes(pages=2, lines=5)
    doc_uid = _upload_test_pdf(client, pdf_bytes)

    # 1. Batch endpoint with 0 stages
    batch_res = client.post(
        f"/api/documents/{doc_uid}/batches",
        json={
            "expiry_duration_seconds": 300,
            "enable_stage1": False,
            "enable_stage2": False,
            "enable_stage3": False,
            "recipients": [{"name": "Student A", "student_uid": "STU_001"}],
        }
    )
    assert batch_res.status_code == 422
    assert "At least one security stage must be selected" in str(batch_res.json())

    # 2. Single distribute endpoint with 0 stages
    single_res = client.post(
        f"/documents/{doc_uid}/distribute",
        json={
            "student_uid": "STU_001",
            "enable_stage1": False,
            "enable_stage2": False,
            "enable_stage3": False,
        }
    )
    assert single_res.status_code == 422
    assert "At least one security stage must be selected" in str(single_res.json())


# ---------------------------------------------------------------------------
# Test 3: All seven non-empty stage combinations
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("s1,s2,s3", [
    (True, False, False),   # Stage 1 only
    (False, True, False),   # Stage 2 only
    (False, False, True),   # Stage 3 only
    (True, True, False),    # Stage 1 + Stage 2
    (True, False, True),    # Stage 1 + Stage 3
    (False, True, True),    # Stage 2 + Stage 3
    (True, True, True),     # Stage 1 + Stage 2 + Stage 3
])
def test_all_seven_stage_combinations(stages_env, s1, s2, s3):
    """
    Asserts that all 7 non-empty combinations:
    1. Embed cleanly into the generated PDF with only selected carriers present.
    2. Pass post-generation verification without requiring unselected carriers.
    3. Are independently detected by forensic investigation.
    """
    service = stages_env["service"]
    v_service = stages_env["v_service"]
    repo = stages_env["repo"]
    tmp_path = stages_env["tmp_path"]

    doc_uid = f"doc_{int(s1)}{int(s2)}{int(s3)}"
    student_uid = f"STU_{int(s1)}{int(s2)}{int(s3)}"

    input_pdf_path = str(tmp_path / f"in_{doc_uid}.pdf")
    output_pdf_path = str(tmp_path / f"out_{doc_uid}.pdf")
    Path(input_pdf_path).write_bytes(_create_high_capacity_pdf_bytes(pages=10, lines=15))

    doc = repo.get_or_create_document(doc_uid, f"{doc_uid}.pdf")
    student = repo.create_student(student_uid, "Test Student")
    nonce, fingerprint_hex = service.generate_fingerprint_payload(student_uid, doc_uid)

    # Embed with exact stage selections
    embed_res = service.embed_and_save_pdf(
        document_uid=doc_uid,
        student_uid=student_uid,
        nonce=nonce,
        fingerprint_hex=fingerprint_hex,
        input_pdf_path=input_pdf_path,
        output_pdf_path=output_pdf_path,
        enable_stage1=s1,
        enable_stage2=s2,
        enable_stage3=s3,
    )
    assert embed_res.success is True

    # Check stage embedding statuses
    assert (embed_res.l1_status == "EMBEDDED") if s1 else (embed_res.l1_status == "SKIPPED")
    assert (embed_res.l2_status == "EMBEDDED") if s2 else (embed_res.l2_status == "SKIPPED")
    assert (embed_res.l3_status == "EMBEDDED") if s3 else (embed_res.l3_status == "SKIPPED")

    # Post-generation verification
    verify_res = service.verify_saved_pdf_carriers(
        pdf_path=output_pdf_path,
        document_uid=doc_uid,
        recipient_uid=student_uid,
        nonce=nonce,
        fingerprint_hex=fingerprint_hex,
        enable_stage1=s1,
        enable_stage2=s2,
        enable_stage3=s3,
    )
    assert verify_res.is_valid is True

    # Inspect physical carriers directly
    doc_fitz = pymupdf.open(output_pdf_path)
    l1_ext = extract_layer1(doc_fitz)
    l2_ext = extract_layer2(doc_fitz)
    doc_fitz.close()

    if s1:
        assert l1_ext is not None
        parts = l1_ext.split("|")
        assert parts[0] == "SPDF-V1"
        assert parts[1] == doc_uid
        assert parts[2] == nonce
        assert parts[3] == fingerprint_hex
    else:
        assert l1_ext is None, "Stage 1 carrier was embedded when unselected!"

    if s2:
        assert l2_ext is not None
        assert len(l2_ext) > 0
    else:
        assert l2_ext is None or len(l2_ext) == 0, "Stage 2 carrier was embedded when unselected!"

    if s3:
        l3_res = extract_layer3_with_timeout(output_pdf_path, timeout=10)
        assert l3_res is not None
        assert l3_res.get("crc_valid") is True
        assert l3_res.get("payload") is not None
    else:
        l3_res = extract_layer3_with_timeout(output_pdf_path, timeout=5)
        assert l3_res is None or l3_res.get("payload") is None

    # Record fingerprint in repo for forensic investigation
    repo.create_fingerprint(
        document_id=doc.id,
        student_id=student.id,
        nonce=nonce,
        fingerprint=fingerprint_hex,
    )

    # Forensic investigation: must detect present carriers independently
    investigation = v_service.investigate_pdf(output_pdf_path)
    assert investigation["status"] == "VALID"
    assert investigation["student_uid"] == student_uid

    expected_layers = []
    if s1: expected_layers.append("Layer 1")
    if s2: expected_layers.append("Layer 2")
    if s3: expected_layers.append("Layer 3")

    for layer in expected_layers:
        assert layer in investigation["authenticated_layers"]


# ---------------------------------------------------------------------------
# Test 4: Database persistence and retrieval of enable_stage1,2,3
# ---------------------------------------------------------------------------
def test_database_persistence_and_retrieval(stages_env):
    """Verify repository correctly persists and retrieves enable_stage1, enable_stage2, enable_stage3."""
    repo = stages_env["repo"]

    user = repo.create_user("test@securepdf.test", "testuser", "hashed_pw", "salt")
    doc = repo.get_or_create_document("doc_db_test", "doc.pdf", user_id=user.id)

    # Create batch with custom stages: Stage 2 and Stage 3 only
    batch = repo.create_distribution_batch(
        batch_uid="batch_custom_stages_1",
        user_id=user.id,
        document_id=doc.id,
        expiry_duration_seconds=600,
        recipients_data=[{"name": "Alice", "student_uid": "STU_ALICE"}],
        enable_stage1=False,
        enable_stage2=True,
        enable_stage3=True,
    )

    retrieved = repo.get_distribution_batch_by_uid("batch_custom_stages_1")
    assert retrieved is not None
    assert retrieved.enable_stage1 is False or retrieved.enable_stage1 == 0
    assert retrieved.enable_stage2 is True or retrieved.enable_stage2 == 1
    assert retrieved.enable_stage3 is True or retrieved.enable_stage3 == 1

    # Create batch with Stage 1 only
    batch2 = repo.create_distribution_batch(
        batch_uid="batch_custom_stages_2",
        user_id=user.id,
        document_id=doc.id,
        expiry_duration_seconds=600,
        recipients_data=[{"name": "Bob", "student_uid": "STU_BOB"}],
        enable_stage1=True,
        enable_stage2=False,
        enable_stage3=False,
    )
    retrieved2 = repo.get_distribution_batch_by_uid("batch_custom_stages_2")
    assert retrieved2 is not None
    assert retrieved2.enable_stage1 is True or retrieved2.enable_stage1 == 1
    assert retrieved2.enable_stage2 is False or retrieved2.enable_stage2 == 0
    assert retrieved2.enable_stage3 is False or retrieved2.enable_stage3 == 0


# ---------------------------------------------------------------------------
# Test 5: Legacy SQLite database migration
# ---------------------------------------------------------------------------
def test_legacy_database_migration(tmp_path):
    """Verify backward-compatible SQLite migration adds stage columns and preserves legacy data."""
    legacy_db = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy_db)
    cursor = conn.cursor()

    # Create legacy table schema without enable_stage1, enable_stage2, enable_stage3
    cursor.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            document_uid TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE distribution_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_uid TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            total_recipients INTEGER NOT NULL,
            expiry_duration_seconds INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            enable_stego INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE batch_recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            recipient_name TEXT NOT NULL,
            recipient_identifier TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            fingerprint_id INTEGER,
            generated_at TIMESTAMP,
            expires_at TIMESTAMP,
            download_token TEXT UNIQUE,
            stego_status TEXT NOT NULL DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE fingerprints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            nonce TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            student_id TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Insert legacy batch with enable_stego = 1 and another with enable_stego = 0
    cursor.execute("""
        INSERT INTO distribution_batches (batch_uid, user_id, document_id, total_recipients, expiry_duration_seconds, enable_stego)
        VALUES ('batch_old_stego', 1, 1, 1, 300, 1)
    """)
    cursor.execute("""
        INSERT INTO distribution_batches (batch_uid, user_id, document_id, total_recipients, expiry_duration_seconds, enable_stego)
        VALUES ('batch_old_nostego', 1, 1, 1, 300, 0)
    """)
    conn.commit()
    conn.close()

    # Run migration via init_db
    init_db(legacy_db)

    # Inspect migrated table
    conn = sqlite3.connect(legacy_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    old_stego = cursor.execute("SELECT * FROM distribution_batches WHERE batch_uid = 'batch_old_stego'").fetchone()
    assert old_stego["enable_stage1"] == 1
    assert old_stego["enable_stage2"] == 1
    assert old_stego["enable_stage3"] == 1  # Migrated from enable_stego = 1

    old_nostego = cursor.execute("SELECT * FROM distribution_batches WHERE batch_uid = 'batch_old_nostego'").fetchone()
    assert old_nostego["enable_stage1"] == 1
    assert old_nostego["enable_stage2"] == 1
    assert old_nostego["enable_stage3"] == 0  # Migrated from enable_stego = 0

    conn.close()


# ---------------------------------------------------------------------------
# Test 6: Post-generation carrier verification fails if selected carrier is missing
# ---------------------------------------------------------------------------
def test_verification_fails_if_selected_carrier_missing(stages_env):
    """Verify that if a stage is selected, its absence or corruption causes verification to fail."""
    service = stages_env["service"]
    tmp_path = stages_env["tmp_path"]

    doc_uid = "doc_corrupt_test"
    student_uid = "STU_CORRUPT"

    input_pdf_path = str(tmp_path / "in_corrupt.pdf")
    output_pdf_path = str(tmp_path / "out_corrupt.pdf")
    Path(input_pdf_path).write_bytes(_create_high_capacity_pdf_bytes(pages=3, lines=10))

    nonce, fingerprint_hex = service.generate_fingerprint_payload(student_uid, doc_uid)

    # Embed ONLY Stage 1
    service.embed_and_save_pdf(
        document_uid=doc_uid,
        student_uid=student_uid,
        nonce=nonce,
        fingerprint_hex=fingerprint_hex,
        input_pdf_path=input_pdf_path,
        output_pdf_path=output_pdf_path,
        enable_stage1=True,
        enable_stage2=False,
        enable_stage3=False,
    )

    # But request verification with enable_stage2=True (which is missing)
    verify_fail = service.verify_saved_pdf_carriers(
        pdf_path=output_pdf_path,
        document_uid=doc_uid,
        recipient_uid=student_uid,
        nonce=nonce,
        fingerprint_hex=fingerprint_hex,
        enable_stage1=True,
        enable_stage2=True,  # Missing!
        enable_stage3=False,
    )
    assert verify_fail.is_valid is False
    assert "Layer 2" in (verify_fail.error or "")

    # And request verification with enable_stage3=True (which is missing)
    verify_fail_l3 = service.verify_saved_pdf_carriers(
        pdf_path=output_pdf_path,
        document_uid=doc_uid,
        recipient_uid=student_uid,
        nonce=nonce,
        fingerprint_hex=fingerprint_hex,
        enable_stage1=True,
        enable_stage2=False,
        enable_stage3=True,  # Missing!
    )
    assert verify_fail_l3.is_valid is False
