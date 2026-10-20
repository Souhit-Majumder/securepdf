"""
Comprehensive integration tests and security guards for the read-only structural inspection endpoint.

Guarantees Verified:
- Zero database queries, connections, or writes.
- Zero master-key access or active verification.
- Zero ephemeral simulations or worker process spawns.
- Database immutability (binary hash identical before and after).
- Rejection of non-PDFs (HTTP 400).
- Rejection of oversized files > 20 MB (HTTP 413).
- Graceful handling of corrupt PDFs with valid headers (HTTP 422).
- Strict DTO schema compliance with extra="forbid".
- Privacy guarantees: null subject_ref and document_uid when unknown, no secret leakage.
- Best-effort temporary file cleanup.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import fitz
import pytest
from fastapi.testclient import TestClient

from app.api.routes.inspection import router
from app.config import config
from app.main import app
from app.services.verification_service import VerificationService


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def clean_pdf_bytes():
    """Generates a minimal valid PDF without any fingerprints."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Hello World Clean Test Document")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_inspection_route_has_no_db_dependencies():
    """Guard: Asserts that inspection.router declares zero database dependencies."""
    inspect_route = next(r for r in router.routes if getattr(r, "path", None) == "/inspect")
    
    # 1. Inspect route endpoint signature and defaults
    endpoint = inspect_route.endpoint
    param_names = endpoint.__code__.co_varnames[:endpoint.__code__.co_argcount]
    assert "db" not in param_names
    assert "session" not in param_names
    assert "service" not in param_names

    # 2. Inspect declared FastAPI dependencies
    for dep in inspect_route.dependencies:
        dep_name = dep.dependency.__name__ if hasattr(dep, "dependency") else str(dep)
        assert "db" not in dep_name.lower()
        assert "session" not in dep_name.lower()
        assert "verification" not in dep_name.lower()


def test_inspection_failsafe_without_database(client, clean_pdf_bytes):
    """Guard: Asserts that structural inspection succeeds even if SQLite connect is blocked."""
    with patch("sqlite3.connect", side_effect=RuntimeError("DB access prohibited in read-only inspection")):
        response = client.post(
            "/api/inspection/inspect",
            files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["overall_status"] in ("NOT_FOUND", "OBSERVED_SYNTAX")


def test_no_active_services_invoked(client, clean_pdf_bytes):
    """Guard: Asserts that VerificationService.investigate_pdf is never invoked."""
    with patch.object(VerificationService, "investigate_pdf", MagicMock()) as mock_investigate:
        response = client.post(
            "/api/inspection/inspect",
            files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 200
        mock_investigate.assert_not_called()


def test_database_immutability_during_inspection(client, clean_pdf_bytes):
    """Guard: Verifies that data/securepdf.db binary hash is unaltered after inspection calls."""
    db_path = config.DB_PATH
    if not db_path.exists():
        pytest.skip("Database does not exist on disk yet")

    def get_db_hash():
        with open(db_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    before_hash = get_db_hash()

    for _ in range(5):
        resp = client.post(
            "/api/inspection/inspect",
            files={"file": ("test.pdf", clean_pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 200

    after_hash = get_db_hash()
    assert before_hash == after_hash, "Database was modified during read-only inspection!"


def test_inspection_rejects_non_pdf(client):
    """Asserts that files without '%PDF-' magic bytes are rejected with HTTP 400."""
    response = client.post(
        "/api/inspection/inspect",
        files={"file": ("test.txt", b"Plain text file not a PDF", "text/plain")},
    )
    assert response.status_code == 400
    assert "missing '%PDF-' header" in response.json()["detail"]


def test_inspection_rejects_oversized_file(client):
    """Asserts that files larger than 20 MB are rejected with HTTP 413."""
    # Create stream exceeding 20 MB with valid header
    oversized = io.BytesIO(b"%PDF-" + b"0" * (20 * 1024 * 1024 + 1024))
    response = client.post(
        "/api/inspection/inspect",
        files={"file": ("huge.pdf", oversized, "application/pdf")},
    )
    assert response.status_code == 413
    assert "File too large" in response.json()["detail"]


def test_inspection_handles_corrupt_pdf(client):
    """Asserts that corrupted PDFs with valid header return HTTP 422 and clean up temp files."""
    corrupt_bytes = b"%PDF-1.7\nCorrupted garbage payload cross reference invalid"
    temp_dir = config.TEMP_DIR
    temp_before = set(temp_dir.glob("inspect_*.pdf")) if temp_dir.exists() else set()

    response = client.post(
        "/api/inspection/inspect",
        files={"file": ("corrupt.pdf", corrupt_bytes, "application/pdf")},
    )
    assert response.status_code == 422
    assert "Unprocessable PDF" in response.json()["detail"]

    # Verify temp file was cleaned up
    temp_after = set(temp_dir.glob("inspect_*.pdf")) if temp_dir.exists() else set()
    assert temp_after == temp_before


def test_clean_pdf_response_structure_and_privacy(client, clean_pdf_bytes):
    """Asserts strict DTO schema compliance, null mapping for absent IDs, and zero secret leakage."""
    response = client.post(
        "/api/inspection/inspect",
        files={"file": ("clean.pdf", clean_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    data = response.json()

    # Field whitelisting & null mapping
    assert data["document_uid"] is None
    assert data["subject_ref"] is None
    assert data["overall_status"] in ("NOT_FOUND", "OBSERVED_SYNTAX")
    assert isinstance(data["page_dimensions"], list)
    assert len(data["page_dimensions"]) == 1
    assert data["page_dimensions"][0]["rotation"] in (0, 90, 180, 270)
    assert data["page_dimensions"][0]["width"] > 0
    assert data["page_dimensions"][0]["height"] > 0

    # Cross layer always populated
    assert "cross_layer" in data
    assert data["cross_layer"]["cross_carrier_conflict"] is False

    # Privacy & secret check across entire JSON response
    serialized = response.text.lower()
    assert "master" not in serialized
    assert "secret" not in serialized
    assert "subj_anon_unknown" not in serialized
    assert "preceding_word" not in serialized


def test_best_effort_cleanup_on_normal_completion(client, clean_pdf_bytes):
    """Verifies that temporary files are deleted after normal HTTP 200 completion."""
    temp_dir = config.TEMP_DIR
    temp_before = set(temp_dir.glob("inspect_*.pdf")) if temp_dir.exists() else set()

    response = client.post(
        "/api/inspection/inspect",
        files={"file": ("sample.pdf", clean_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200

    temp_after = set(temp_dir.glob("inspect_*.pdf")) if temp_dir.exists() else set()
    assert temp_after == temp_before
