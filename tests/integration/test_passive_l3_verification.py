import fitz
import pytest
import threading

from app.config import config
from app.database.database import init_db
from app.database.repository import Repository
from app.services.fingerprint_service import FingerprintService
from app.services.verification_service import VerificationService
from app.inspection.service import InspectionService
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
            text_line = "SecurePDF document verification forensic integrity carrier text sample."
            page.insert_text((50, 50 + line_idx * 30), text_line)
    doc.save(path)
    doc.close()


def test_passive_l3_detected_when_generation_disabled(test_env, monkeypatch):
    """
    Asserts that when ENABLE_STEGO_CARRIER = False:
    - Layer 3 is passively detected and cryptographically authenticated.
    - authenticated_layers is ["Layer 1", "Layer 2", "Layer 3"].
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "src_stego.pdf")
    create_text_pdf(src_pdf, pages=10, lines_per_page=15)
    out_pdf = str(tmp_path / "out_stego.pdf")

    # 1. Issue with stego generation enabled
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-ALICE", "DOC-STEGO-OFF", src_pdf, out_pdf)

    # 2. Disable generation flag globally
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    assert config.ENABLE_STEGO_CARRIER is False

    # 3. Passive verification must still extract and verify Layer 3
    ver_service = VerificationService(repo=repo, master_key=master_key)
    res = ver_service.investigate_pdf(out_pdf)

    assert res["status"] == "VALID"
    assert res["student_uid"] == "STU-ALICE"
    assert res["authenticated_layers"] == ["Layer 1", "Layer 2", "Layer 3"]


def test_passive_l3_detected_when_generation_enabled(test_env, monkeypatch):
    """
    Asserts that when ENABLE_STEGO_CARRIER = True:
    - Layer 3 is detected and authenticated as normal.
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "src_stego_on.pdf")
    create_text_pdf(src_pdf, pages=10, lines_per_page=15)
    out_pdf = str(tmp_path / "out_stego_on.pdf")

    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-ALICE", "DOC-STEGO-ON", src_pdf, out_pdf)

    ver_service = VerificationService(repo=repo, master_key=master_key)
    res = ver_service.investigate_pdf(out_pdf)

    assert res["status"] == "VALID"
    assert res["student_uid"] == "STU-ALICE"
    assert res["authenticated_layers"] == ["Layer 1", "Layer 2", "Layer 3"]


def test_l1_l2_only_pdf_compatible_when_generation_disabled(test_env, monkeypatch):
    """
    Asserts that an L1/L2-only PDF:
    - Validates with authenticated_layers = ["Layer 1", "Layer 2"].
    - Does not fail or raise error when Layer 3 is absent and generation is False.
    - Evidence report records Layer 3 as NOT_FOUND.
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "src_legacy.pdf")
    create_text_pdf(src_pdf, pages=5, lines_per_page=10)
    out_pdf = str(tmp_path / "out_legacy.pdf")

    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-ALICE", "DOC-LEGACY", src_pdf, out_pdf)

    insp_service = InspectionService(repo=repo, master_key=master_key)
    r_dict, report = insp_service.investigate_with_evidence(out_pdf)

    assert r_dict["status"] == "VALID"
    assert r_dict["student_uid"] == "STU-ALICE"
    assert r_dict["authenticated_layers"] == ["Layer 1", "Layer 2"]
    assert "Layer 3" not in r_dict["authenticated_layers"]

    l3_eval = next(c for c in report.carriers if "Layer 3" in c.carrier_name)
    assert l3_eval.status == "NOT_FOUND"


def test_l1_l2_only_pdf_compatible_when_generation_enabled(test_env, monkeypatch):
    """
    Asserts that an L1/L2-only PDF remains valid even if generation flag is True.
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "src_legacy_on.pdf")
    create_text_pdf(src_pdf, pages=5, lines_per_page=10)
    out_pdf = str(tmp_path / "out_legacy_on.pdf")

    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-ALICE", "DOC-LEGACY-ON", src_pdf, out_pdf)

    # Set generation flag to True during verification
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    ver_service = VerificationService(repo=repo, master_key=master_key)
    res = ver_service.investigate_pdf(out_pdf)

    assert res["status"] == "VALID"
    assert res["authenticated_layers"] == ["Layer 1", "Layer 2"]
    assert "Layer 3" not in res["authenticated_layers"]


def test_structurally_detected_l3_with_invalid_authentication(test_env, monkeypatch):
    """
    Asserts that a structurally detected Layer 3 carrier with invalid authentication:
    - Must NOT be added to authenticated_layers.
    - Must NOT be treated as a valid Layer 3 fingerprint.
    - Evidence report must show status STRUCTURALLY_DECODED (not VALID).
    - L1/L2 authentication remains intact.
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "src_forged.pdf")
    create_text_pdf(src_pdf, pages=10, lines_per_page=15)
    alice_pdf = str(tmp_path / "alice_pdf.pdf")

    # 1. Issue authentic L1 + L2 for Alice with stego disabled
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-ALICE", "DOC-FORGED", src_pdf, alice_pdf)

    # 2. Manually embed Layer 3 with a forged/wrong master key
    forged_key = b"\x99" * 32
    nonce_forged = b"\x42" * 16
    doc = fitz.open(alice_pdf)
    embed_layer3(doc, "DOC-FORGED", "STU-ALICE", nonce_forged, forged_key)
    forged_pdf = str(tmp_path / "forged_doc.pdf")
    doc.save(forged_pdf)
    doc.close()

    # 3. Investigate with evidence while generation is disabled
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    insp_service = InspectionService(repo=repo, master_key=master_key)
    r_dict, report = insp_service.investigate_with_evidence(forged_pdf)

    # L1 and L2 authenticate Alice
    assert r_dict["status"] == "VALID"
    assert r_dict["student_uid"] == "STU-ALICE"
    # Layer 3 must NOT be in authenticated_layers
    assert "Layer 3" not in r_dict["authenticated_layers"]
    assert r_dict["authenticated_layers"] == ["Layer 1", "Layer 2"]

    # Layer 3 evaluation must be STRUCTURALLY_DECODED, distinct from VALID
    l3_eval = next(c for c in report.carriers if "Layer 3" in c.carrier_name)
    assert l3_eval.status == "STRUCTURALLY_DECODED"
    assert l3_eval.status != "VALID"
    assert l3_eval.details.get("crc_valid") is True


def test_standalone_structurally_detected_l3_fails_when_unauthenticated(test_env, monkeypatch):
    """
    Asserts that a PDF with ONLY an unauthenticated/forged Layer 3 carrier
    (and no valid L1/L2) fails with INVALID rather than VALID or NOT_FOUND.
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "src_only_forged.pdf")
    create_text_pdf(src_pdf, pages=10, lines_per_page=15)

    # Embed ONLY Layer 3 with a forged key (no L1 or L2)
    forged_key = b"\x77" * 32
    nonce_forged = b"\x33" * 16
    doc = fitz.open(src_pdf)
    embed_layer3(doc, "DOC-ONLY-FORGED", "STU-ALICE", nonce_forged, forged_key)
    only_forged_pdf = str(tmp_path / "only_forged_doc.pdf")
    doc.save(only_forged_pdf)
    doc.close()

    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    ver_service = VerificationService(repo=repo, master_key=master_key)
    res = ver_service.investigate_pdf(only_forged_pdf)

    assert res["status"] == "INVALID"
    assert "Carriers present but none authenticate" in res["reason"]
    assert "authenticated_layers" not in res


def test_passive_l3_cancellation_signal_handled_gracefully(test_env, monkeypatch):
    """
    Asserts that cooperative cancellation does not crash or hang passive verification.
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "src_cancel.pdf")
    create_text_pdf(src_pdf, pages=10, lines_per_page=15)
    out_pdf = str(tmp_path / "out_cancel.pdf")

    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-ALICE", "DOC-CANCEL", src_pdf, out_pdf)

    cancel_event = threading.Event()
    cancel_event.set()

    ver_service = VerificationService(repo=repo, master_key=master_key)
    res = ver_service.investigate_pdf(out_pdf, cancel_event=cancel_event)

    # L1 and L2 still validly authenticate even if L3 extraction was cancelled
    assert res["status"] == "VALID"
    assert res["student_uid"] == "STU-ALICE"
