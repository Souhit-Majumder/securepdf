"""
Tests for ML Feature Extraction.
Verifies:
- Fixed schema completeness and deterministic ordering.
- Non-modification of target PDFs during extraction.
- Safe handling of malformed, empty, and non-PDF inputs.
- Accurate structural carrier detection without verifying HMAC.
"""
import hashlib
from pathlib import Path
import fitz
import pytest

from app.ml.feature_extractor import (
    FEATURE_SCHEMA,
    FeatureExtractionError,
    extract_pdf_features,
    features_to_vector,
)


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Hello SecurePDF ML Test")
    doc.set_metadata({"title": "Sample Doc", "author": "Test Author"})
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_feature_extractor_schema_completeness(sample_pdf: Path):
    features = extract_pdf_features(sample_pdf)
    assert isinstance(features, dict)

    for field in FEATURE_SCHEMA:
        assert field in features, f"Missing feature in output: {field}"
        assert isinstance(features[field], (int, float)), f"Feature {field} is not numeric"

    assert features["page_count"] == 1
    assert features["file_size_bytes"] > 0
    assert features["has_title"] == 1
    assert features["has_author"] == 1


def test_features_to_vector_deterministic_ordering(sample_pdf: Path):
    features = extract_pdf_features(sample_pdf)
    vec1 = features_to_vector(features)
    vec2 = features_to_vector(features)

    assert len(vec1) == len(FEATURE_SCHEMA)
    assert len(vec1) == 23
    assert (vec1 == vec2).all()

    # Verify order matches FEATURE_SCHEMA exactly
    for i, name in enumerate(FEATURE_SCHEMA):
        assert vec1[i] == features[name]


def test_feature_extractor_does_not_modify_pdf(sample_pdf: Path):
    before_hash = hashlib.sha256(sample_pdf.read_bytes()).hexdigest()
    _ = extract_pdf_features(sample_pdf)
    after_hash = hashlib.sha256(sample_pdf.read_bytes()).hexdigest()

    assert before_hash == after_hash, "Feature extractor modified input file"


def test_malformed_and_empty_files(tmp_path: Path):
    empty_file = tmp_path / "empty.pdf"
    empty_file.write_bytes(b"")

    with pytest.raises(FeatureExtractionError, match="File too small"):
        extract_pdf_features(empty_file)

    corrupt_file = tmp_path / "corrupt.pdf"
    corrupt_file.write_bytes(b"Not a valid PDF header format")

    with pytest.raises(FeatureExtractionError, match="magic header"):
        extract_pdf_features(corrupt_file)

    missing_file = tmp_path / "nonexistent.pdf"
    with pytest.raises(FeatureExtractionError, match="not found"):
        extract_pdf_features(missing_file)


def test_oversized_file_limit(tmp_path: Path, monkeypatch):
    from app.ml import feature_extractor
    monkeypatch.setattr(feature_extractor, "MAX_FILE_SIZE_BYTES", 100)

    big_file = tmp_path / "big.pdf"
    big_file.write_bytes(b"%PDF-1.4 " + b"X" * 200)

    with pytest.raises(FeatureExtractionError, match="exceeds"):
        extract_pdf_features(big_file)


def test_carrier_structural_indicators(tmp_path: Path):
    from app.pdf.embed import embed_payload

    doc_path = tmp_path / "carrier_doc.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Document with carriers")

    embed_payload(doc, "DOC123", "NONCE456", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

    doc.save(str(doc_path))
    doc.close()

    feats = extract_pdf_features(doc_path)
    assert feats["has_catalog_carrier"] == 1.0
    assert feats["catalog_carrier_format_valid"] == 1.0
    assert feats["annotation_carrier_count"] >= 1.0
    assert feats["annotation_carrier_format_valid_count"] >= 1.0


def test_carrier_format_validation_unit_tests():
    import base64
    from app.ml.feature_extractor import (
        validate_layer1_carrier_format,
        validate_layer2_carrier_format,
    )

    valid_hex = "a" * 64
    valid_b64 = base64.b64encode(b"x" * 32).decode("ascii")

    # Layer 1 Valid
    assert validate_layer1_carrier_format(f"SPDF-V1|DOC1|NONCE1|{valid_hex}") is True

    # Layer 1 Malformed
    assert validate_layer1_carrier_format("SPDF-V1|DOC1|NONCE1") is False  # too few fields
    assert validate_layer1_carrier_format(f"SPDF-V2|DOC1|NONCE1|{valid_hex}") is False  # wrong prefix
    assert validate_layer1_carrier_format(f"SPDF-V1||NONCE1|{valid_hex}") is False  # empty doc_uid
    assert validate_layer1_carrier_format(f"SPDF-V1|DOC1||{valid_hex}") is False  # empty nonce
    assert validate_layer1_carrier_format("SPDF-V1|DOC1|NONCE1|short_hex") is False  # len != 64
    assert validate_layer1_carrier_format("SPDF-V1|DOC1|NONCE1|" + "z" * 64) is False  # non-hex chars

    # Layer 2 Valid
    assert validate_layer2_carrier_format(f"SPDF1|DOC1|NONCE1|{valid_b64}") is True

    # Layer 2 Malformed
    assert validate_layer2_carrier_format("SPDF1|DOC1|NONCE1") is False  # too few fields
    assert validate_layer2_carrier_format(f"SPDF2|DOC1|NONCE1|{valid_b64}") is False  # wrong prefix
    assert validate_layer2_carrier_format(f"SPDF1||NONCE1|{valid_b64}") is False  # empty doc_uid
    assert validate_layer2_carrier_format(f"SPDF1|DOC1||{valid_b64}") is False  # empty nonce
    assert validate_layer2_carrier_format("SPDF1|DOC1|NONCE1|TAMPERED") is False  # decodes to 6 bytes != 32
    assert validate_layer2_carrier_format("SPDF1|DOC1|NONCE1|not_valid_b64!@#$") is False  # invalid base64
    short_b64 = base64.b64encode(b"short").decode("ascii")
    assert validate_layer2_carrier_format(f"SPDF1|DOC1|NONCE1|{short_b64}") is False  # short bytes


def test_carrier_tampered_payload_not_format_valid(tmp_path: Path):
    doc_path = tmp_path / "tampered_annot.pdf"
    doc = fitz.open()
    page = doc.new_page()
    annot = page.add_rect_annot(fitz.Rect(0, 0, 0.1, 0.1))
    info = annot.info or {}
    info["title"] = "SPDF0"
    info["content"] = "SPDF1|DOC|NONCE|TAMPERED"
    annot.set_info(info)
    annot.update()
    doc.save(str(doc_path))
    doc.close()

    feats = extract_pdf_features(doc_path)
    assert feats["annotation_carrier_count"] == 1.0
    # Must NOT be counted as format valid because TAMPERED is not a valid 32-byte Base64 HMAC
    assert feats["annotation_carrier_format_valid_count"] == 0.0

