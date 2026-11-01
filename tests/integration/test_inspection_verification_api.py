"""
Integration tests and security guards for the active fingerprint verification endpoint:
POST /api/inspection/verify

Guarantees Verified:
- 503 Service Unavailable when SECUREPDF_FORENSIC_KEY is not configured.
- 401 Unauthorized when 'X-SecurePDF-Audit-Key' header is missing.
- 403 Forbidden when forensic audit key does not match (constant-time verification).
- 429 Too Many Requests when anti-oracle rate limits are exceeded.
- Successful verification mapping to ActiveVerificationResponseDTO with extra="forbid".
- Privacy guarantees: zero student PII (student_uid / student_name omitted), opaque subject_ref.
- Database immutability (binary SHA-256 hash identical before and after).
- Rejection of non-PDFs (HTTP 400) and oversized files > 20 MB (HTTP 413).
- Best-effort temporary file cleanup in config.TEMP_DIR.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch
import fitz
import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_rate_limiter
from app.config import config
from app.database.database import init_db
from app.database.repository import Repository
from app.inspection.models import (
    CarrierInspectionResult,
    CrossLayerEvidence,
    EvidenceReport,
    SubjectEvidence,
)
from app.inspection.service import InspectionService
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def clean_pdf_bytes():
    """Generates a minimal valid PDF without any fingerprints."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Hello World Clean Test Document for Active Verification")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Resets the in-memory anti-oracle rate limiter before every test."""
    limiter = get_rate_limiter()
    with limiter._lock:
        limiter._requests.clear()
    yield
    with limiter._lock:
        limiter._requests.clear()


def test_verify_503_when_forensic_key_unconfigured(client, clean_pdf_bytes, monkeypatch):
    """Guard: Asserts that /verify returns 503 when SECUREPDF_FORENSIC_KEY is unset."""
    monkeypatch.delenv("SECUREPDF_FORENSIC_KEY", raising=False)
    response = client.post(
        "/api/inspection/verify",
        files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
        headers={"X-SecurePDF-Audit-Key": "some_key"},
    )
    assert response.status_code == 503
    assert "Active verification disabled" in response.json()["detail"]


def test_verify_401_when_key_header_missing(client, clean_pdf_bytes, monkeypatch):
    """Guard: Asserts that /verify returns 401 when 'X-SecurePDF-Audit-Key' header is missing."""
    monkeypatch.setenv("SECUREPDF_FORENSIC_KEY", "correct_audit_key_secret_123")
    response = client.post(
        "/api/inspection/verify",
        files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 401
    assert "missing 'X-SecurePDF-Audit-Key'" in response.json()["detail"]


def test_verify_403_when_key_invalid(client, clean_pdf_bytes, monkeypatch):
    """Guard: Asserts that /verify returns 403 when forensic key does not match."""
    monkeypatch.setenv("SECUREPDF_FORENSIC_KEY", "correct_audit_key_secret_123")
    response = client.post(
        "/api/inspection/verify",
        files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
        headers={"X-SecurePDF-Audit-Key": "incorrect_key_attempt"},
    )
    assert response.status_code == 403
    assert "invalid forensic audit key" in response.json()["detail"]


def test_verify_429_anti_oracle_rate_limiting(client, clean_pdf_bytes, monkeypatch):
    """Guard: Asserts that more than 5 requests in a minute return 429 Too Many Requests."""
    monkeypatch.setenv("SECUREPDF_FORENSIC_KEY", "correct_audit_key_secret_123")
    headers = {"X-SecurePDF-Audit-Key": "correct_audit_key_secret_123"}

    # Mock the internal service to respond fast
    mock_report = EvidenceReport(
        document_uid="DOC-TEST",
        overall_status="NOT_FOUND",
        subject=SubjectEvidence(subject_ref="subj_anon_12345678"),
        carriers=[],
        cross_layer=CrossLayerEvidence(),
        telemetry_source="ACTIVE_VERIFICATION",
        timestamp="2026-10-20T00:00:00Z",
    )
    mock_dict = {"status": "NOT_FOUND", "reason": "No fingerprint"}

    with patch.object(InspectionService, "investigate_with_evidence", return_value=(mock_dict, mock_report)):
        # First 5 calls must succeed
        for _ in range(5):
            resp = client.post(
                "/api/inspection/verify",
                files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
                headers=headers,
            )
            assert resp.status_code == 200

        # 6th call must be rejected by anti-oracle limiter
        sixth_resp = client.post(
            "/api/inspection/verify",
            files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
            headers=headers,
        )
        assert sixth_resp.status_code == 429
        assert "rate limit exceeded" in sixth_resp.json()["detail"].lower()
        assert "retry-after" in sixth_resp.headers


def test_verify_valid_layer1_outcome(client, clean_pdf_bytes, monkeypatch):
    """Verifies that an authenticated Layer 1 payload maps to VALID verification_status."""
    monkeypatch.setenv("SECUREPDF_FORENSIC_KEY", "correct_audit_key_secret_123")
    headers = {"X-SecurePDF-Audit-Key": "correct_audit_key_secret_123"}

    mock_report = EvidenceReport(
        document_uid="DOC-AUTHENTIC-01",
        overall_status="VALID",
        subject=SubjectEvidence(subject_ref="subj_anon_a1b2c3d4"),
        carriers=[
            CarrierInspectionResult(
                carrier_name="Layer 1 (Catalog)",
                status="VALID",
                signature_ref="evref_sig_01",
            ),
            CarrierInspectionResult(
                carrier_name="Layer 2 (Annotations)",
                status="NOT_FOUND",
            ),
            CarrierInspectionResult(
                carrier_name="Layer 3 (Stego Kerning)",
                status="NOT_FOUND",
            ),
        ],
        cross_layer=CrossLayerEvidence(l1_signature_ref="evref_sig_01"),
        telemetry_source="ACTIVE_VERIFICATION",
        timestamp="2026-10-20T00:00:00Z",
    )
    mock_dict = {
        "status": "VALID",
        "document_uid": "DOC-AUTHENTIC-01",
        "authenticated_layers": ["Layer 1 (Catalog)"],
    }

    with patch.object(InspectionService, "investigate_with_evidence", return_value=(mock_dict, mock_report)):
        resp = client.post(
            "/api/inspection/verify",
            files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["verification_status"] == "VALID"
        assert data["authenticated_layers"] == ["Layer 1 (Catalog)"]
        assert data["document_uid"] == "DOC-AUTHENTIC-01"
        assert data["subject_ref"] == "subj_anon_a1b2c3d4"
        assert len(data["carriers"]) == 3
        assert data["carriers"][0]["status"] == "VALID"
        assert data["carriers"][1]["status"] == "NOT_FOUND"

        # Privacy invariant: no student personal identifiers in serialized payload
        assert "student_uid" not in data
        assert "student_name" not in data
        assert "nonce" not in data
        assert "fingerprint" not in data


def test_verify_security_conflict_outcome(client, clean_pdf_bytes, monkeypatch):
    """Verifies that cross-carrier or internal conflicts return SECURITY_CONFLICT."""
    monkeypatch.setenv("SECUREPDF_FORENSIC_KEY", "correct_audit_key_secret_123")
    headers = {"X-SecurePDF-Audit-Key": "correct_audit_key_secret_123"}

    mock_report = EvidenceReport(
        document_uid="DOC-CONFLICT-01",
        overall_status="SECURITY_CONFLICT",
        subject=SubjectEvidence(subject_ref="subj_anon_unknown"),
        carriers=[
            CarrierInspectionResult(carrier_name="Layer 1 (Catalog)", status="VALID", signature_ref="evref_sig_01"),
            CarrierInspectionResult(carrier_name="Layer 2 (Annotations)", status="VALID", signature_ref="evref_sig_02"),
        ],
        cross_layer=CrossLayerEvidence(
            l1_signature_ref="evref_sig_01",
            l2_signature_refs=["evref_sig_02"],
            signatures_match=False,
            cross_carrier_conflict=True,
            conflict_reason="Carriers authenticate to different identities",
        ),
        telemetry_source="ACTIVE_VERIFICATION",
        timestamp="2026-10-20T00:00:00Z",
    )
    mock_dict = {
        "status": "SECURITY_CONFLICT",
        "reason": "Carriers authenticate to different identities",
    }

    with patch.object(InspectionService, "investigate_with_evidence", return_value=(mock_dict, mock_report)):
        resp = client.post(
            "/api/inspection/verify",
            files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["verification_status"] == "SECURITY_CONFLICT"
        assert data["cross_layer"]["cross_carrier_conflict"] is True
        assert "different identities" in data["reason"]


def test_verify_rejection_of_non_pdf(client, monkeypatch):
    """Guard: Asserts that non-PDF files are rejected with HTTP 400."""
    monkeypatch.setenv("SECUREPDF_FORENSIC_KEY", "correct_audit_key_secret_123")
    headers = {"X-SecurePDF-Audit-Key": "correct_audit_key_secret_123"}

    response = client.post(
        "/api/inspection/verify",
        files={"file": ("test.txt", b"plain text content not a pdf", "text/plain")},
        headers=headers,
    )
    assert response.status_code == 400
    assert "Invalid PDF" in response.json()["detail"]


def test_verify_rejection_of_oversized_file(client, monkeypatch):
    """Guard: Asserts that uploads exceeding 20 MB are rejected with HTTP 413."""
    monkeypatch.setenv("SECUREPDF_FORENSIC_KEY", "correct_audit_key_secret_123")
    headers = {"X-SecurePDF-Audit-Key": "correct_audit_key_secret_123"}

    # Generate oversized chunk stream exceeding 20 MB
    oversized_data = b"%PDF-" + b"0" * (20 * 1024 * 1024 + 1024)
    response = client.post(
        "/api/inspection/verify",
        files={"file": ("big.pdf", oversized_data, "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 413
    assert "File too large" in response.json()["detail"]


def test_verify_temporary_file_cleanup(client, clean_pdf_bytes, monkeypatch):
    """Guard: Verifies that verify_*.pdf files in config.TEMP_DIR are deleted after execution."""
    monkeypatch.setenv("SECUREPDF_FORENSIC_KEY", "correct_audit_key_secret_123")
    headers = {"X-SecurePDF-Audit-Key": "correct_audit_key_secret_123"}

    temp_dir = config.TEMP_DIR
    temp_dir.mkdir(parents=True, exist_ok=True)
    before_files = set(temp_dir.glob("verify_*.pdf"))

    mock_report = EvidenceReport(
        document_uid="DOC-CLEANUP",
        overall_status="NOT_FOUND",
        subject=SubjectEvidence(subject_ref="subj_anon_11112222"),
        carriers=[],
        cross_layer=CrossLayerEvidence(),
        telemetry_source="ACTIVE_VERIFICATION",
        timestamp="2026-10-20T00:00:00Z",
    )
    mock_dict = {"status": "NOT_FOUND"}

    with patch.object(InspectionService, "investigate_with_evidence", return_value=(mock_dict, mock_report)):
        response = client.post(
            "/api/inspection/verify",
            files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
            headers=headers,
        )
        assert response.status_code == 200

    after_files = set(temp_dir.glob("verify_*.pdf"))
    assert after_files == before_files, f"Leaked temporary verification files: {after_files - before_files}"


def test_verify_database_immutability(client, clean_pdf_bytes, monkeypatch):
    """Guard: Verifies that the SQLite database SHA-256 hash is identical before and after verification."""
    monkeypatch.setenv("SECUREPDF_FORENSIC_KEY", "correct_audit_key_secret_123")
    headers = {"X-SecurePDF-Audit-Key": "correct_audit_key_secret_123"}

    db_path = config.DB_PATH
    if not db_path.exists():
        pytest.skip("Database does not exist on disk yet")

    hash_before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    # Call endpoint with clean PDF
    response = client.post(
        "/api/inspection/verify",
        files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 200

    hash_after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert hash_before == hash_after, "Database file was mutated during active verification!"
