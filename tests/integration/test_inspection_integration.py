"""
Integration tests for SecurePDF Inspection Service and Pipeline Integration (Stage 4).
"""
import hashlib
import os
from pathlib import Path
import sqlite3
import threading
import fitz
import pytest

from app.config import config
from app.database.database import init_db
from app.database.repository import Repository
from app.inspection import (
    EvidenceCollector,
    InspectionService,
    AuthorizationContext,
)
from app.pdf.embed import embed_payload
from app.pdf.processor import save_pdf
from app.services.fingerprint_service import FingerprintService


@pytest.fixture
def integration_env(tmp_path):
    """Sets up a clean test database and repository with sample records."""
    db_path = str(tmp_path / "inspection_test.db")
    init_db(db_path)
    repo = Repository(db_path=db_path)
    repo.create_student("STU-ALICE", "Alice Smith")
    repo.create_student("STU-BOB", "Bob Jones")
    master_key = b"\x01" * 32
    return {"repo": repo, "master_key": master_key, "tmp_path": tmp_path, "db_path": db_path}


def create_multi_page_pdf(path: str, pages: int = 10, lines_per_page: int = 15):
    """Creates a text-rich PDF fixture with sufficient word gaps for all layers."""
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        for line_idx in range(lines_per_page):
            page.insert_text(
                (50, 50 + line_idx * 30),
                "SecurePDF document verification forensic integrity carrier text sample.",
            )
    doc.save(path)
    doc.close()


def test_mandatory_byte_identity_l1_l2(integration_env):
    """
    Mandatory byte-identity assertion:
    Embedding operations with fixed inputs must produce 100% byte-identical PDFs
    when executed with collector=None vs collector=EvidenceCollector().
    """
    tmp_path = integration_env["tmp_path"]
    src_pdf = str(tmp_path / "src_base.pdf")
    create_multi_page_pdf(src_pdf, pages=2, lines_per_page=5)

    doc_bytes = Path(src_pdf).read_bytes()

    doc_uninstrumented = fitz.open(stream=doc_bytes, filetype="pdf")
    doc_instrumented = fitz.open(stream=doc_bytes, filetype="pdf")

    fixed_nonce = "0102030405060708090a0b0c0d0e0f10"
    fixed_fp = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
    fixed_doc_uid = "DOC-FIXED-01"

    # 1. Uninstrumented embedding (collector=None)
    embed_payload(
        doc_uninstrumented,
        document_uid=fixed_doc_uid,
        nonce=fixed_nonce,
        fingerprint=fixed_fp,
        enable_stego=False,
        collector=None,
    )
    out_uninstrumented = str(tmp_path / "out_uninstrumented.pdf")
    save_pdf(doc_uninstrumented, out_uninstrumented, no_new_id=1)
    doc_uninstrumented.close()

    # 2. Instrumented embedding (collector=EvidenceCollector())
    collector = EvidenceCollector()
    embed_payload(
        doc_instrumented,
        document_uid=fixed_doc_uid,
        nonce=fixed_nonce,
        fingerprint=fixed_fp,
        enable_stego=False,
        collector=collector,
    )
    out_instrumented = str(tmp_path / "out_instrumented.pdf")
    save_pdf(doc_instrumented, out_instrumented, no_new_id=1)
    doc_instrumented.close()

    # Mandatory Byte-Identity Regression Assertion
    bytes_a = Path(out_uninstrumented).read_bytes()
    bytes_b = Path(out_instrumented).read_bytes()
    assert bytes_a == bytes_b, "Byte identity failed between uninstrumented and instrumented embedding!"


def test_mandatory_byte_identity_l3_stego(integration_env):
    """
    Mandatory byte-identity assertion across all three layers including Stego kerning.
    """
    tmp_path = integration_env["tmp_path"]
    src_pdf = str(tmp_path / "src_stego_base.pdf")
    create_multi_page_pdf(src_pdf, pages=10, lines_per_page=15)

    doc_bytes = Path(src_pdf).read_bytes()

    doc_a = fitz.open(stream=doc_bytes, filetype="pdf")
    doc_b = fitz.open(stream=doc_bytes, filetype="pdf")

    fixed_nonce = "11223344556677889900aabbccddeeff"
    fixed_fp = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
    fixed_doc_uid = "DOC-STEGO-BYTE"
    fixed_student_uid = "STU-BOB-42"
    master_key = integration_env["master_key"]

    # Uninstrumented
    embed_payload(
        doc_a,
        document_uid=fixed_doc_uid,
        nonce=fixed_nonce,
        fingerprint=fixed_fp,
        enable_stego=True,
        student_uid=fixed_student_uid,
        master_key=master_key,
        collector=None,
    )
    out_a = str(tmp_path / "out_stego_uninstrumented.pdf")
    save_pdf(doc_a, out_a, no_new_id=1)
    doc_a.close()

    # Instrumented
    collector = EvidenceCollector()
    embed_payload(
        doc_b,
        document_uid=fixed_doc_uid,
        nonce=fixed_nonce,
        fingerprint=fixed_fp,
        enable_stego=True,
        student_uid=fixed_student_uid,
        master_key=master_key,
        collector=collector,
    )
    out_b = str(tmp_path / "out_stego_instrumented.pdf")
    save_pdf(doc_b, out_b, no_new_id=1)
    doc_b.close()

    bytes_a = Path(out_a).read_bytes()
    bytes_b = Path(out_b).read_bytes()
    assert bytes_a == bytes_b, "Byte identity failed for Layer 3 stego embedding!"


def test_simulation_isolation_db_immutability(integration_env):
    """
    Verifies that simulation produces ZERO database writes.
    """
    repo = integration_env["repo"]
    master_key = integration_env["master_key"]
    tmp_path = integration_env["tmp_path"]
    db_path = integration_env["db_path"]

    src_pdf = str(tmp_path / "sim_src.pdf")
    create_multi_page_pdf(src_pdf, pages=3, lines_per_page=10)

    # Count rows before simulation
    conn_before = sqlite3.connect(db_path)
    fp_count_before = conn_before.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
    doc_count_before = conn_before.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    conn_before.close()

    service = InspectionService(repo=repo, master_key=master_key)
    auth = AuthorizationContext(principal="tester", has_pii_clearance=False)

    fp_hex, report = service.simulate_fingerprinting(
        pdf_path=src_pdf,
        student_uid="STU-ALICE",
        doc_uid="DOC-SIM-1",
        auth_ctx=auth,
        enable_stego=False,
    )

    assert fp_hex is not None
    assert report.telemetry_source == "EPHEMERAL_SIMULATION"
    assert report.overall_status == "VALID"

    # Count rows after simulation: must be strictly identical
    conn_after = sqlite3.connect(db_path)
    fp_count_after = conn_after.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
    doc_count_after = conn_after.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    conn_after.close()

    assert fp_count_before == fp_count_after, "Simulation wrote new rows to fingerprints table!"
    assert doc_count_before == doc_count_after, "Simulation wrote new rows to documents table!"


def test_simulation_source_pdf_immutability(integration_env):
    """
    Verifies that the source PDF is not modified during simulation.
    """
    repo = integration_env["repo"]
    master_key = integration_env["master_key"]
    tmp_path = integration_env["tmp_path"]

    src_pdf = str(tmp_path / "sim_immut_src.pdf")
    create_multi_page_pdf(src_pdf, pages=2, lines_per_page=5)

    hash_before = hashlib.sha256(Path(src_pdf).read_bytes()).hexdigest()

    service = InspectionService(repo=repo, master_key=master_key)
    service.simulate_fingerprinting(
        pdf_path=src_pdf,
        student_uid="STU-ALICE",
        doc_uid="DOC-SIM-IMMUT",
        enable_stego=False,
    )

    hash_after = hashlib.sha256(Path(src_pdf).read_bytes()).hexdigest()
    assert hash_before == hash_after, "Source PDF file was modified during simulation!"


def test_simulation_cleanup_on_injected_failure(integration_env, monkeypatch):
    """
    Verifies that temporary files in config.TEMP_DIR are deleted unconditionally
    even when an exception is raised during embedding.
    """
    repo = integration_env["repo"]
    master_key = integration_env["master_key"]
    tmp_path = integration_env["tmp_path"]

    src_pdf = str(tmp_path / "sim_fail_src.pdf")
    create_multi_page_pdf(src_pdf, pages=2, lines_per_page=5)

    # Point TEMP_DIR to isolated directory for this test
    test_temp_dir = str(tmp_path / "test_temp_dir")
    os.makedirs(test_temp_dir, exist_ok=True)
    monkeypatch.setenv("SECUREPDF_TEMP_DIR", test_temp_dir)

    service = InspectionService(repo=repo, master_key=master_key)

    # Monkeypatch embed_payload to raise an artificial error
    def crashing_embed(*args, **kwargs):
        raise RuntimeError("Injected embedding crash for failure test")

    monkeypatch.setattr("app.inspection.service.embed_payload", crashing_embed)

    with pytest.raises(RuntimeError, match="Injected embedding crash"):
        service.simulate_fingerprinting(
            pdf_path=src_pdf,
            student_uid="STU-ALICE",
            doc_uid="DOC-CRASH",
        )

    # Verify no leaked temporary files remain in test_temp_dir
    remaining_files = os.listdir(test_temp_dir)
    assert len(remaining_files) == 0, f"Temporary files were leaked on failure: {remaining_files}"


def test_investigate_with_evidence_full_pipeline(integration_env):
    """
    Verifies that investigate_with_evidence returns both the standard attribution dict
    and the rich, validated EvidenceReport.
    """
    repo = integration_env["repo"]
    master_key = integration_env["master_key"]
    tmp_path = integration_env["tmp_path"]

    src_pdf = str(tmp_path / "src_full.pdf")
    create_multi_page_pdf(src_pdf, pages=2, lines_per_page=5)
    out_pdf = str(tmp_path / "out_full.pdf")

    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-ALICE", "DOC-FULL-1", src_pdf, out_pdf)

    service = InspectionService(repo=repo, master_key=master_key)
    auth = AuthorizationContext(principal="auditor", has_pii_clearance=False)

    res_dict, report = service.investigate_with_evidence(out_pdf, auth_ctx=auth)

    assert res_dict["status"] == "VALID"
    assert res_dict["student_uid"] == "STU-ALICE"

    assert report.overall_status == "VALID"
    assert report.telemetry_source == "ACTIVE_VERIFICATION"
    assert report.subject.student_uid is None  # Redacted because has_pii_clearance=False
    assert report.subject.subject_ref.startswith("subj_anon_")


def test_investigate_with_evidence_cancellation(integration_env):
    """
    Verifies that investigate_with_evidence handles a pre-set cancel_event cleanly.
    """
    repo = integration_env["repo"]
    master_key = integration_env["master_key"]
    tmp_path = integration_env["tmp_path"]

    src_pdf = str(tmp_path / "src_cancel.pdf")
    create_multi_page_pdf(src_pdf, pages=2, lines_per_page=5)

    service = InspectionService(repo=repo, master_key=master_key)
    cancel_event = threading.Event()
    cancel_event.set()

    res_dict, report = service.investigate_with_evidence(src_pdf, cancel_event=cancel_event)
    assert res_dict["status"] in ["NOT_FOUND", "INVALID"]
    assert report.telemetry_source == "ACTIVE_VERIFICATION"
