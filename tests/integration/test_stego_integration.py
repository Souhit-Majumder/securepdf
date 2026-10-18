import fitz
import pytest
from unittest.mock import patch

from app.config import config
from app.database.database import init_db
from app.database.repository import Repository
from app.services.fingerprint_service import FingerprintService
from app.services.verification_service import VerificationService
from app.pdf.embed import embed_payload
from app.pdf.stego.embed import embed_layer3


@pytest.fixture
def test_env(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    repo = Repository(db_path=db_path)
    repo.create_student("STU-ALICE", "Alice Smith")
    repo.create_student("STU-BOB", "Bob Jones")
    master_key = b"\x01" * 32
    return {"repo": repo, "master_key": master_key, "tmp_path": tmp_path}


def create_text_pdf(path: str, pages: int = 10, lines_per_page: int = 15):
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        for line_idx in range(lines_per_page):
            # 8 words per line, 15 lines = 120 words per page
            text_line = "SecurePDF document verification forensic integrity carrier text sample."
            page.insert_text((50, 50 + line_idx * 30), text_line)
    doc.save(path)
    doc.close()


def test_baseline_equivalence_when_stego_disabled(test_env, monkeypatch):
    """
    Asserts that when ENABLE_STEGO_CARRIER = False:
    - FingerprintService and VerificationService behave identically to baseline.
    - authenticated_layers is ["Layer 1", "Layer 2"].
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "src_equiv.pdf")
    create_text_pdf(src_pdf, pages=2, lines_per_page=5)

    out_pdf = str(tmp_path / "out_equiv.pdf")

    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-ALICE", "DOC-EQUIV", src_pdf, out_pdf)

    ver_service = VerificationService(repo=repo, master_key=master_key)
    res = ver_service.investigate_pdf(out_pdf)

    assert res["status"] == "VALID"
    assert res["student_uid"] == "STU-ALICE"
    assert res["authenticated_layers"] == ["Layer 1", "Layer 2"]


def test_end_to_end_layer3_issuance_and_verification(test_env, monkeypatch):
    """
    Asserts that when ENABLE_STEGO_CARRIER = True:
    - Layer 3 is embedded and authenticated.
    - authenticated_layers is ["Layer 1", "Layer 2", "Layer 3"].
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "src_stego.pdf")
    # 10 pages * 15 lines = 150 lines * 7 gaps = 1050 word gaps (> 664 required)
    create_text_pdf(src_pdf, pages=10, lines_per_page=15)

    out_pdf = str(tmp_path / "out_stego.pdf")

    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-ALICE", "DOC-STEGO", src_pdf, out_pdf)

    ver_service = VerificationService(repo=repo, master_key=master_key)
    res = ver_service.investigate_pdf(out_pdf)

    assert res["status"] == "VALID"
    assert res["student_uid"] == "STU-ALICE"
    assert res["authenticated_layers"] == ["Layer 1", "Layer 2", "Layer 3"]


def test_cross_carrier_security_conflict(test_env, monkeypatch):
    """
    Asserts that if Layer 1 authenticates to Alice, and Layer 3 authenticates to Bob,
    the verifier returns SECURITY_CONFLICT with absolute precedence.
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "src_conflict.pdf")
    create_text_pdf(src_pdf, pages=10, lines_per_page=15)

    # 1. Issue for Alice with stego disabled to set up L1 + L2 for Alice in database
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    fp_alice = FingerprintService(repo=repo, master_key=master_key)
    alice_pdf = str(tmp_path / "alice_doc.pdf")
    fp_alice.fingerprint_pdf("STU-ALICE", "DOC-CONFLICT", src_pdf, alice_pdf)

    # 2. Also register Bob for same document in database with nonce_bob
    doc_rec = repo.get_document_by_uid("DOC-CONFLICT")
    bob_rec = repo.get_student_by_uid("STU-BOB")
    nonce_bob = b"\x09" * 16
    repo.create_fingerprint(
        document_id=doc_rec.id,
        student_id=bob_rec.id,
        nonce=nonce_bob.hex(),
        fingerprint="b" * 64
    )

    # 3. Manually embed Layer 3 for Bob into Alice's PDF
    doc = fitz.open(alice_pdf)
    embed_layer3(doc, "DOC-CONFLICT", "STU-BOB", nonce_bob, master_key)
    conflict_pdf = str(tmp_path / "conflict_doc.pdf")
    doc.save(conflict_pdf)
    doc.close()

    # 4. Verify: Layer 1 is Alice, Layer 3 is Bob -> must trigger SECURITY_CONFLICT
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    ver_service = VerificationService(repo=repo, master_key=master_key)
    res = ver_service.investigate_pdf(conflict_pdf)

    assert res["status"] == "SECURITY_CONFLICT"
    assert "different identities" in res["reason"]


def test_capacity_deficit_fallback(test_env, monkeypatch):
    """
    Asserts that if a document has insufficient text capacity for Layer 3,
    it falls back gracefully to Layers 1 and 2 without failing.
    """
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    # Only 1 short page: 5 words = 4 gaps (< 664 required)
    src_pdf = str(tmp_path / "src_small.pdf")
    create_text_pdf(src_pdf, pages=1, lines_per_page=1)

    out_pdf = str(tmp_path / "out_small.pdf")

    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-ALICE", "DOC-SMALL", src_pdf, out_pdf)

    ver_service = VerificationService(repo=repo, master_key=master_key)
    res = ver_service.investigate_pdf(out_pdf)

    # Survives and validates with Layer 1 and 2
    assert res["status"] == "VALID"
    assert res["authenticated_layers"] == ["Layer 1", "Layer 2"]
