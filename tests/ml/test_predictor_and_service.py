"""
Tests for MLPredictor and ForensicService Integration.
Verifies:
- Predictor resilience when model is missing or incompatible.
- Qualified advisory output and structural indicators.
- Strict independence of cryptographic attribution and ML assessment.
- Fail-closed security behavior preserved during conflicts.
"""
from pathlib import Path
import fitz
import joblib
import pytest

from app.crypto.fingerprint import generate_fingerprint
from app.crypto.keys import get_or_create_master_key
from app.database.repository import Repository
from app.ml.dataset import build_forensic_dataset, create_synthetic_source_documents
from app.ml.predictor import MLPredictor
from app.ml.train import MODEL_ARTIFACT_VERSION, train_model
from app.pdf.embed import embed_payload
from app.services.forensic_service import ForensicService
from app.services.verification_service import VerificationService


@pytest.fixture
def trained_model_path(tmp_path: Path) -> Path:
    source_dir = tmp_path / "sources"
    dataset_dir = tmp_path / "dataset"
    _ = create_synthetic_source_documents(source_dir, count=5)
    manifest = build_forensic_dataset(
        source_dir=source_dir,
        output_dir=dataset_dir,
        random_seed=42,
        split_ratio=0.6,
    )
    model_path = tmp_path / "forensic_model.joblib"
    _ = train_model(
        manifest_path=dataset_dir / "manifest.json",
        model_output_path=model_path,
        random_seed=42,
        n_estimators=20,
    )
    return model_path


def test_predictor_when_model_is_missing(tmp_path: Path):
    missing_path = tmp_path / "nonexistent.joblib"
    predictor = MLPredictor(model_path=missing_path)

    assert not predictor.is_available()

    # Create dummy pdf
    dummy_pdf = tmp_path / "dummy.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(dummy_pdf))
    doc.close()

    result = predictor.predict(dummy_pdf)
    assert result["status"] == "UNAVAILABLE"
    assert result["predicted_class"] is None
    assert "advisory_notice" in result


def test_predictor_with_valid_model(trained_model_path: Path, tmp_path: Path):
    predictor = MLPredictor(model_path=trained_model_path)
    assert predictor.is_available()

    test_pdf = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Test content for prediction")
    embed_payload(doc, "DOC-001", "NONCE-001", "a" * 64)
    doc.save(str(test_pdf))
    doc.close()

    result = predictor.predict(test_pdf)
    assert result["status"] == "AVAILABLE"
    assert result["predicted_class"] is not None
    assert result["model_version"] == MODEL_ARTIFACT_VERSION
    assert 0.0 <= result["confidence_score"] <= 1.0
    assert "structural_indicators" in result
    assert "advisory_notice" in result


def test_predictor_unsupported_on_ordinary_pdf(trained_model_path: Path, tmp_path: Path):
    predictor = MLPredictor(model_path=trained_model_path)
    assert predictor.is_available()

    ordinary_pdf = tmp_path / "ordinary.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Plain document without carriers")
    doc.save(str(ordinary_pdf))
    doc.close()

    result = predictor.predict(ordinary_pdf)
    assert result["status"] == "UNSUPPORTED"
    assert result["predicted_class"] is None
    assert result["confidence_score"] is None
    assert "No SecurePDF fingerprint carrier markers detected" in result["reason"]
    assert "both carrier layers" in result["reason"]


def test_predictor_incompatible_artifact(tmp_path: Path):
    bad_model_path = tmp_path / "bad.joblib"
    joblib.dump({"artifact_version": "99.9.9", "model": None}, str(bad_model_path))

    predictor = MLPredictor(model_path=bad_model_path)
    assert not predictor.is_available()

    test_pdf = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(test_pdf))
    doc.close()

    res = predictor.predict(test_pdf)
    assert res["status"] == "UNAVAILABLE"


def test_forensic_service_with_authentic_pdf(trained_model_path: Path, tmp_path: Path):
    repo = Repository()
    master_key = get_or_create_master_key()

    # Setup student and document
    doc_record = repo.get_or_create_document("DOC-001", "orig.pdf")
    student = repo.create_student("STU-001", "Alice Smith")
    nonce = "NONCE-001"
    fp = generate_fingerprint(master_key, "DOC-001", "STU-001", nonce)
    repo.create_fingerprint(doc_record.id, student.id, nonce, fp)

    output_pdf = tmp_path / "fingerprinted.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Authentic document")
    embed_payload(doc, "DOC-001", nonce, fp)
    doc.save(str(output_pdf))
    doc.close()

    # Analyze with ForensicService
    service = ForensicService(
        verification_service=VerificationService(repo=repo, master_key=master_key),
        predictor=MLPredictor(model_path=trained_model_path),
    )
    report = service.analyze_pdf(output_pdf)

    # 1. Authoritative crypto verification
    assert report["cryptographic_verification"]["status"] == "VALID"
    assert report["attribution"] is not None
    assert report["attribution"]["student_uid"] == "STU-001"
    assert report["attribution"]["student_name"] == "Alice Smith"

    # 2. Advisory ML assessment
    assert report["ml_assessment"]["status"] == "AVAILABLE"
    assert "disclaimer" in report


def test_forensic_service_unauthenticated_tampered_pdf(trained_model_path: Path, tmp_path: Path):
    repo = Repository()
    master_key = get_or_create_master_key()

    # Plain PDF with no fingerprint
    plain_pdf = tmp_path / "untracked.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Unregistered PDF")
    doc.save(str(plain_pdf))
    doc.close()

    service = ForensicService(
        verification_service=VerificationService(repo=repo, master_key=master_key),
        predictor=MLPredictor(model_path=trained_model_path),
    )
    report = service.analyze_pdf(plain_pdf)

    # Verification must be NOT_FOUND, attribution must be None
    assert report["cryptographic_verification"]["status"] == "NOT_FOUND"
    assert report["attribution"] is None

    # ML assessment must report UNSUPPORTED for untracked document without carriers
    assert report["ml_assessment"]["status"] == "UNSUPPORTED"
    assert report["ml_assessment"]["predicted_class"] is None
    assert "No SecurePDF fingerprint carrier markers detected" in report["ml_assessment"]["reason"]


def test_forensic_service_one_surviving_carrier(trained_model_path: Path, tmp_path: Path):
    repo = Repository()
    master_key = get_or_create_master_key()

    doc_rec = repo.get_or_create_document("DOC-SURV", "surv.pdf")
    stu = repo.create_student("STU-SURV", "Bob Surv")
    nonce = "NONCE-SURV"
    fp = generate_fingerprint(master_key, "DOC-SURV", "STU-SURV", nonce)
    repo.create_fingerprint(doc_rec.id, stu.id, nonce, fp)

    pdf_path = tmp_path / "surviving.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Surviving carrier test")
    embed_payload(doc, "DOC-SURV", nonce, fp)
    # Strip Layer 1 (catalog carrier), leave Layer 2 (annotation) intact
    doc.xref_set_key(doc.pdf_catalog(), "SPDFPayload", "null")
    doc.save(str(pdf_path))
    doc.close()

    service = ForensicService(
        verification_service=VerificationService(repo=repo, master_key=master_key),
        predictor=MLPredictor(model_path=trained_model_path),
    )
    report = service.analyze_pdf(pdf_path)

    # 1. Authoritative crypto verification succeeds with 1 surviving carrier
    assert report["cryptographic_verification"]["status"] == "VALID"
    assert report["attribution"]["student_uid"] == "STU-SURV"
    assert report["cryptographic_verification"]["authenticated_layers"] == ["Layer 2"]

    # 2. ML assessment recognizes document (carrier present) and is AVAILABLE
    assert report["ml_assessment"]["status"] == "AVAILABLE"
    assert report["ml_assessment"]["structural_indicators"]["carrier_annotation_count"] >= 1
    assert report["ml_assessment"]["structural_indicators"]["carrier_catalog_present"] is False


def test_forensic_service_corrupted_carriers_no_ml_override(trained_model_path: Path, tmp_path: Path):
    repo = Repository()
    master_key = get_or_create_master_key()

    pdf_path = tmp_path / "corrupt.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Corrupt carriers test")
    embed_payload(doc, "DOC-CORRUPT", "NONCE-CORRUPT", "f" * 64)
    # Tamper catalog
    doc.xref_set_key(doc.pdf_catalog(), "SPDFPayload", "<535044462d56317c4a554e4b>")
    doc.save(str(pdf_path))
    doc.close()

    service = ForensicService(
        verification_service=VerificationService(repo=repo, master_key=master_key),
        predictor=MLPredictor(model_path=trained_model_path),
    )
    report = service.analyze_pdf(pdf_path)

    # Verification must be INVALID (carriers present but fail authentication)
    assert report["cryptographic_verification"]["status"] == "INVALID"
    assert report["attribution"] is None

    # ML runs advisory evaluation without overriding INVALID crypto status
    assert report["ml_assessment"]["status"] == "AVAILABLE"
    assert report["cryptographic_verification"]["status"] == "INVALID"


def test_forensic_service_security_conflict_no_ml_override(trained_model_path: Path, tmp_path: Path):
    repo = Repository()
    master_key = get_or_create_master_key()

    doc_rec = repo.get_or_create_document("DOC-CONF", "conf.pdf")
    stu1 = repo.create_student("STU-C1", "Charlie")
    stu2 = repo.create_student("STU-C2", "Dana")

    fp1 = generate_fingerprint(master_key, "DOC-CONF", "STU-C1", "N1")
    fp2 = generate_fingerprint(master_key, "DOC-CONF", "STU-C2", "N2")
    repo.create_fingerprint(doc_rec.id, stu1.id, "N1", fp1)
    repo.create_fingerprint(doc_rec.id, stu2.id, "N2", fp2)

    # Base with stu1 payload
    pdf_path = tmp_path / "conflicted.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Conflicted test")
    embed_payload(doc, "DOC-CONF", "N1", fp1)

    # Extract stu2 layer2 payload
    doc2 = fitz.open()
    doc2.new_page().insert_text((50, 50), "Temp")
    embed_payload(doc2, "DOC-CONF", "N2", fp2)
    from app.pdf.extract import extract_layer2
    l2_stu2 = extract_layer2(doc2)[0]
    doc2.close()

    # Overwrite annotation with stu2's payload
    for page in doc:
        for annot in page.annots():
            info = annot.info or {}
            if info.get("title", "").startswith("SPDF"):
                info["content"] = l2_stu2
                annot.set_info(info)
                annot.update()
    doc.save(str(pdf_path))
    doc.close()

    service = ForensicService(
        verification_service=VerificationService(repo=repo, master_key=master_key),
        predictor=MLPredictor(model_path=trained_model_path),
    )
    report = service.analyze_pdf(pdf_path)

    # Verification must be SECURITY_CONFLICT
    assert report["cryptographic_verification"]["status"] == "SECURITY_CONFLICT"
    assert report["attribution"] is None

    # ML must never override SECURITY_CONFLICT
    assert report["ml_assessment"]["status"] == "AVAILABLE"
    assert report["cryptographic_verification"]["status"] == "SECURITY_CONFLICT"
