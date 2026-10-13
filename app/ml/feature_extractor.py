"""
Structural PDF Feature Extractor for Forensic Analysis.

Extracts a deterministic, fixed-schema numerical feature vector from PDF documents.
Analyzes purely structural, syntactical, and metadata properties.

Security Guarantees:
- Never executes embedded JavaScript or actions.
- Never trusts filenames or paths.
- Does not use recipient identities, nonces, HMAC values, or database attribution.
- Keeps feature extraction independent from cryptographic verification results.
- Does not modify the input PDF.
"""
from __future__ import annotations

import base64
import binascii
import os
from collections import Counter
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import numpy as np

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB limit

FEATURE_SCHEMA: list[str] = [
    # Document size & structure
    "file_size_bytes",
    "page_count",
    "total_text_length",
    "avg_text_per_page",
    "annotation_count",
    "avg_annotations_per_page",
    "image_count",
    "embedded_file_count",
    "is_encrypted",
    # Metadata presence & attributes
    "has_metadata",
    "metadata_field_count",
    "has_title",
    "has_author",
    "has_creation_date",
    "has_mod_date",
    "dates_match",
    # Structural script/action indicators (passive scan, no execution)
    "javascript_action_count",
    # SecurePDF structural indicators (presence and format only, NOT cryptographic validity)
    "has_catalog_carrier",
    "catalog_carrier_format_valid",
    "annotation_carrier_count",
    "annotation_carrier_format_valid_count",
    "annotation_carrier_duplicate_count",
    "carrier_count_total",
]


class FeatureExtractionError(Exception):
    """Raised when feature extraction fails due to malformed or unreadable input."""
    pass


def validate_layer1_carrier_format(payload_str: str) -> bool:
    """
    Validates structural formatting of Layer 1 (Catalog) payload.
    Expected format: SPDF-V1|{document_uid}|{nonce}|{fingerprint_hex}
    - 4 pipe-delimited fields
    - parts[0] == 'SPDF-V1'
    - parts[1] (doc_uid) non-empty
    - parts[2] (nonce) non-empty
    - parts[3] 64-character hexadecimal string representing a 32-byte digest
    Does NOT verify the HMAC value or consult any database.
    """
    parts = payload_str.split("|")
    if len(parts) != 4 or parts[0] != "SPDF-V1":
        return False
    if not parts[1] or not parts[2]:
        return False
    fp_hex = parts[3]
    if len(fp_hex) != 64:
        return False
    try:
        bytes.fromhex(fp_hex)
        return True
    except ValueError:
        return False


def validate_layer2_carrier_format(content_str: str) -> bool:
    """
    Validates structural formatting of Layer 2 (Annotation) payload.
    Expected format: SPDF1|{document_uid}|{nonce}|{hmac_b64}
    - 4 pipe-delimited fields
    - parts[0] == 'SPDF1'
    - parts[1] (doc_uid) non-empty
    - parts[2] (nonce) non-empty
    - parts[3] valid Base64 string that decodes to exactly 32 bytes
    Does NOT verify the HMAC value or consult any database.
    """
    parts = content_str.split("|")
    if len(parts) != 4 or parts[0] != "SPDF1":
        return False
    if not parts[1] or not parts[2]:
        return False
    b64_str = parts[3]
    try:
        decoded = base64.b64decode(b64_str, validate=True)
        return len(decoded) == 32
    except (binascii.Error, ValueError, Exception):
        return False



def extract_features(pdf_path: str | Path) -> dict[str, float]:
    """
    Extracts deterministic structural features from a PDF document.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        dict[str, float]: Dictionary mapping feature name to numeric value.

    Raises:
        FeatureExtractionError: If the file is missing, oversized, or unreadable.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FeatureExtractionError(f"File not found: {path}")

    try:
        file_size = path.stat().st_size
    except OSError as err:
        raise FeatureExtractionError(f"Cannot stat file: {err}") from err

    if file_size > MAX_FILE_SIZE_BYTES:
        raise FeatureExtractionError(f"File size exceeds {MAX_FILE_SIZE_BYTES} bytes limit")

    if file_size < 4:
        raise FeatureExtractionError("File too small to be a valid PDF")

    # Verify %PDF magic bytes
    try:
        with open(path, "rb") as f:
            header = f.read(4)
            if header != b"%PDF":
                raise FeatureExtractionError("File does not start with %PDF magic header")
    except OSError as err:
        raise FeatureExtractionError(f"Cannot read file header: {err}") from err

    # Open document using PyMuPDF (passive read mode)
    try:
        doc = fitz.open(str(path))
    except Exception as err:
        raise FeatureExtractionError(f"PyMuPDF failed to parse document: {err}") from err

    try:
        return _extract_from_doc(doc, file_size)
    finally:
        doc.close()


def features_to_vector(features: dict[str, float]) -> np.ndarray:
    """Converts a feature dictionary into a 1D NumPy array adhering to FEATURE_SCHEMA."""
    return np.array([float(features[name]) for name in FEATURE_SCHEMA], dtype=np.float64)


def extract_feature_vector(pdf_path: str | Path) -> np.ndarray:
    """Convenience helper extracting directly to a 1D NumPy array."""
    features = extract_features(pdf_path)
    return features_to_vector(features)


def _extract_from_doc(doc: fitz.Document, file_size: int) -> dict[str, float]:
    page_count = doc.page_count
    is_encrypted = 1.0 if doc.is_encrypted else 0.0

    total_text_length = 0
    annotation_count = 0
    image_count = 0

    spdf_annot_contents: list[str] = []
    spdf_annot_valid_count = 0

    if not doc.is_encrypted or not doc.needs_pass:
        for page in doc:
            try:
                text = page.get_text()
                total_text_length += len(text)
            except Exception:
                pass

            try:
                images = page.get_images()
                image_count += len(images)
            except Exception:
                pass

            try:
                annots = list(page.annots())
                annotation_count += len(annots)
                for annot in annots:
                    info = annot.info or {}
                    title = info.get("title", "")
                    if title.startswith("SPDF"):
                        content = info.get("content", "")
                        spdf_annot_contents.append(content)
                        # Structural validation: check fields, encoding, and digest length without verifying HMAC
                        if validate_layer2_carrier_format(content):
                            spdf_annot_valid_count += 1
            except Exception:
                pass

    avg_text_per_page = total_text_length / max(page_count, 1)
    avg_annotations_per_page = annotation_count / max(page_count, 1)

    try:
        embedded_file_count = doc.embfile_count()
    except Exception:
        embedded_file_count = 0

    # Metadata analysis
    metadata = doc.metadata or {}
    has_metadata = 1.0 if any(metadata.values()) else 0.0

    standard_keys = ["title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate"]
    metadata_field_count = sum(1 for k in standard_keys if metadata.get(k))

    has_title = 1.0 if bool(metadata.get("title")) else 0.0
    has_author = 1.0 if bool(metadata.get("author")) else 0.0
    has_creation_date = 1.0 if bool(metadata.get("creationDate")) else 0.0
    has_mod_date = 1.0 if bool(metadata.get("modDate")) else 0.0

    c_date = metadata.get("creationDate")
    m_date = metadata.get("modDate")
    dates_match = 1.0 if c_date and m_date and c_date == m_date else 0.0

    # Passive static scan for action / script indicators without execution
    javascript_action_count = 0
    try:
        xref_len = doc.xref_length()
        # Sample xref entries (up to 500 to keep extraction fast)
        sample_limit = min(xref_len, 500)
        for xref in range(1, sample_limit):
            try:
                obj_str = doc.xref_object(xref)
                if any(k in obj_str for k in ("/JavaScript", "/JS", "/Action", "/Launch")):
                    javascript_action_count += 1
            except Exception:
                continue
    except Exception:
        pass

    # SecurePDF Structural Layer 1 check
    has_catalog_carrier = 0.0
    catalog_carrier_format_valid = 0.0
    try:
        cat_xref = doc.pdf_catalog()
        key_val = doc.xref_get_key(cat_xref, "SPDFPayload")
        if key_val[0] == "string" and key_val[1]:
            has_catalog_carrier = 1.0
            if validate_layer1_carrier_format(key_val[1]):
                catalog_carrier_format_valid = 1.0
    except Exception:
        pass

    # SecurePDF Structural Layer 2 analysis
    annotation_carrier_count = float(len(spdf_annot_contents))
    annotation_carrier_format_valid_count = float(spdf_annot_valid_count)

    # Redundancy check: count maximum duplicates of identical carrier content
    if spdf_annot_contents:
        counts = Counter(spdf_annot_contents)
        annotation_carrier_duplicate_count = float(counts.most_common(1)[0][1])
    else:
        annotation_carrier_duplicate_count = 0.0

    carrier_count_total = has_catalog_carrier + annotation_carrier_count

    return {
        "file_size_bytes": float(file_size),
        "page_count": float(page_count),
        "total_text_length": float(total_text_length),
        "avg_text_per_page": float(avg_text_per_page),
        "annotation_count": float(annotation_count),
        "avg_annotations_per_page": float(avg_annotations_per_page),
        "image_count": float(image_count),
        "embedded_file_count": float(embedded_file_count),
        "is_encrypted": is_encrypted,
        "has_metadata": has_metadata,
        "metadata_field_count": float(metadata_field_count),
        "has_title": has_title,
        "has_author": has_author,
        "has_creation_date": has_creation_date,
        "has_mod_date": has_mod_date,
        "dates_match": dates_match,
        "javascript_action_count": float(javascript_action_count),
        "has_catalog_carrier": has_catalog_carrier,
        "catalog_carrier_format_valid": catalog_carrier_format_valid,
        "annotation_carrier_count": annotation_carrier_count,
        "annotation_carrier_format_valid_count": annotation_carrier_format_valid_count,
        "annotation_carrier_duplicate_count": annotation_carrier_duplicate_count,
        "carrier_count_total": float(carrier_count_total),
    }


# Backwards-compatible / descriptive alias
extract_pdf_features = extract_features
