"""
Reproducible Dataset Generation Pipeline for PDF Forensic Analysis.

Transforms source PDFs using known, controlled transformations into labeled variants:
- original
- benign_transformation
- modified
- marker_tampering

Enforces:
- Source-grouped splitting (no variants of the same source document in both train and test).
- Zero data leakage (no secret keys, personal names, nonces, or absolute paths in manifest).
- Deterministic random seeding.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import fitz

from app.ml.feature_extractor import (
    FEATURE_SCHEMA,
    FeatureExtractionError,
    extract_features,
)

LABEL_ORIGINAL = "original"
LABEL_BENIGN = "benign_transformation"
LABEL_MODIFIED = "modified"
LABEL_TAMPERED = "marker_tampering"

ALL_LABELS = [LABEL_ORIGINAL, LABEL_BENIGN, LABEL_MODIFIED, LABEL_TAMPERED]
CLASS_LABELS = ALL_LABELS


@dataclass
class DatasetRecord:
    source_document_id: str
    variant_id: str
    transformation: str
    label: str
    relative_path: str
    feature_extraction_status: str
    split: str
    features: dict[str, float] | None = None
    baseline_id: str | None = None
    source_sha256: str = ""
    output_sha256: str = ""



# ---------------------------------------------------------------------------
# Transformation functions (All operate purely on documents, safely)
# ---------------------------------------------------------------------------

def _transform_original(src: fitz.Document, dst_path: str) -> bool:
    src.save(dst_path)
    return True


def _transform_benign_resave(src: fitz.Document, dst_path: str) -> bool:
    src.save(dst_path, garbage=3, deflate=True)
    return True


def _transform_benign_clear_metadata(src: fitz.Document, dst_path: str) -> bool:
    src.set_metadata({})
    src.save(dst_path)
    return True


def _transform_benign_touch_metadata(src: fitz.Document, dst_path: str) -> bool:
    meta = src.metadata or {}
    meta["title"] = "Document Study Copy"
    meta["subject"] = "Study Material"
    src.set_metadata(meta)
    src.save(dst_path)
    return True


def _transform_modified_add_page(src: fitz.Document, dst_path: str) -> bool:
    page = src.new_page()
    page.insert_text((50, 50), "Appended Study Notes Page")
    src.save(dst_path)
    return True


def _transform_modified_delete_page(src: fitz.Document, dst_path: str) -> bool:
    if src.page_count > 1:
        src.delete_page(src.page_count - 1)
    else:
        # If single page, add annotation as content modification
        page = src[0]
        page.add_rect_annot(fitz.Rect(10, 10, 100, 50))
    src.save(dst_path)
    return True


def _transform_modified_reorder_pages(src: fitz.Document, dst_path: str) -> bool:
    if src.page_count > 1:
        order = list(reversed(range(src.page_count)))
        src.select(order)
    else:
        page = src[0]
        page.insert_text((20, 100), "Modified text content")
    src.save(dst_path)
    return True


def _transform_modified_insert_text(src: fitz.Document, dst_path: str) -> bool:
    if src.page_count > 0:
        src[0].insert_text((72, 72), "User highlighted section")
    src.save(dst_path)
    return True


def _transform_tamper_catalog_corrupt(src: fitz.Document, dst_path: str) -> bool:
    cat = src.pdf_catalog()
    src.xref_set_key(cat, "SPDFPayload", "<535044462d56317c4a554e4b>")
    src.save(dst_path)
    return True


def _transform_tamper_catalog_delete(src: fitz.Document, dst_path: str) -> bool:
    cat = src.pdf_catalog()
    src.xref_set_key(cat, "SPDFPayload", "null")
    src.save(dst_path)
    return True


def _transform_tamper_annotations_corrupt(src: fitz.Document, dst_path: str) -> bool:
    touched = False
    for page in src:
        for annot in page.annots():
            info = annot.info or {}
            if info.get("title", "").startswith("SPDF"):
                info["content"] = "SPDF1|DOC|NONCE|TAMPERED"
                annot.set_info(info)
                annot.update()
                touched = True
    if not touched and src.page_count > 0:
        # If no SPDF annot exists, add corrupted one
        annot = src[0].add_rect_annot(fitz.Rect(0, 0, 0.1, 0.1))
        info = annot.info or {}
        info["title"] = "SPDF0"
        info["content"] = "CORRUPTED_PAYLOAD"
        annot.set_info(info)
        annot.update()
    src.save(dst_path)
    return True


def _transform_tamper_annotations_delete(src: fitz.Document, dst_path: str) -> bool:
    for page in src:
        for annot in page.annots():
            info = annot.info or {}
            if info.get("title", "").startswith("SPDF"):
                page.delete_annot(annot)
    src.save(dst_path)
    return True


TRANSFORMATIONS: list[tuple[str, str, Callable[[fitz.Document, str], bool]]] = [
    # (variant_suffix, label, handler)
    ("orig", LABEL_ORIGINAL, _transform_original),
    ("benign_resave", LABEL_BENIGN, _transform_benign_resave),
    ("benign_clearmeta", LABEL_BENIGN, _transform_benign_clear_metadata),
    ("benign_touchmeta", LABEL_BENIGN, _transform_benign_touch_metadata),
    ("mod_add_page", LABEL_MODIFIED, _transform_modified_add_page),
    ("mod_del_page", LABEL_MODIFIED, _transform_modified_delete_page),
    ("mod_reorder", LABEL_MODIFIED, _transform_modified_reorder_pages),
    ("mod_text", LABEL_MODIFIED, _transform_modified_insert_text),
    ("tamper_cat_corrupt", LABEL_TAMPERED, _transform_tamper_catalog_corrupt),
    ("tamper_cat_del", LABEL_TAMPERED, _transform_tamper_catalog_delete),
    ("tamper_annot_corrupt", LABEL_TAMPERED, _transform_tamper_annotations_corrupt),
    ("tamper_annot_del", LABEL_TAMPERED, _transform_tamper_annotations_delete),
]


def generate_synthetic_sources(target_dir: Path, count: int = 5, seed: int = 42) -> list[Path]:
    """Generates synthetic baseline PDFs with distinct structures and fingerprinted carriers."""
    from app.crypto.fingerprint import generate_fingerprint, generate_nonce
    from app.crypto.keys import get_or_create_master_key
    from app.pdf.embed import embed_payload

    target_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    master_key = get_or_create_master_key()
    source_paths = []

    for idx in range(count):
        doc = fitz.open()
        num_pages = rng.randint(1, 4)
        for p in range(num_pages):
            page = doc.new_page(width=595, height=842)
            page.insert_text((50, 50 + p * 20), f"Synthetic Lecture {idx + 1} - Page {p + 1}")
            # Randomly add an annotation or text block
            if p == 0:
                page.insert_text((50, 100), f"Course Content Hash {rng.getrandbits(32):x}")

        # Embed standard SecurePDF payload on source (representing distributed document)
        doc_uid = f"SYN-DOC-{idx + 1:03d}"
        stu_uid = f"SYN-STU-{idx + 1:03d}"
        nonce = generate_nonce()
        fp = generate_fingerprint(master_key, doc_uid, stu_uid, nonce)
        embed_payload(doc, doc_uid, nonce, fp)

        src_file = target_dir / f"source_{doc_uid}.pdf"
        doc.save(str(src_file))
        doc.close()
        source_paths.append(src_file)

    return source_paths


def _compute_sha256(path: Path, block_size: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block_size):
            h.update(chunk)
    return h.hexdigest()


def _has_carriers(path: Path) -> bool:
    from app.pdf.extract import extract_layer1, extract_layer2
    try:
        doc = fitz.open(str(path))
        has_l1 = extract_layer1(doc) is not None
        has_l2 = len(extract_layer2(doc)) > 0
        doc.close()
        return has_l1 or has_l2
    except Exception:
        return False


def build_dataset(
    source_pdfs: list[Path],
    output_dir: Path,
    test_split_ratio: float = 0.3,
    random_seed: int = 42,
    reject_unfingerprinted: bool = False,
) -> dict:
    """
    Builds a labeled dataset from source PDFs by executing reproducible transformations.
    Enforces that all labeled examples originate from genuine SecurePDF-generated documents.
    If a source lacks carriers, generates an ephemeral personalized baseline first,
    or rejects it if reject_unfingerprinted=True.

    Returns:
        dict: The dataset manifest including split statistics and metadata.
    """
    from Crypto.Random import get_random_bytes
    from app.crypto.fingerprint import generate_fingerprint, generate_nonce
    from app.pdf.embed import embed_payload

    output_dir.mkdir(parents=True, exist_ok=True)
    variants_dir = output_dir / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)
    baselines_dir = output_dir / "baselines"
    baselines_dir.mkdir(parents=True, exist_ok=True)

    ephemeral_key = get_random_bytes(32)

    # 1. Assign splits by source document (never split variants of the same source)
    rng = random.Random(random_seed)
    unique_sources = sorted([p.stem for p in source_pdfs])
    shuffled_sources = list(unique_sources)
    rng.shuffle(shuffled_sources)

    num_test_sources = max(1, int(len(shuffled_sources) * test_split_ratio)) if len(shuffled_sources) > 1 else 0
    test_sources = set(shuffled_sources[:num_test_sources])
    train_sources = set(shuffled_sources[num_test_sources:])

    records: list[DatasetRecord] = []
    unlabeled_sources_metadata: list[dict] = []

    for src_path in source_pdfs:
        src_id = src_path.stem
        split = "test" if src_id in test_sources else "train"
        src_sha = _compute_sha256(src_path)

        # Check if source is already a SecurePDF fingerprinted baseline
        if _has_carriers(src_path):
            transform_baseline = src_path
            baseline_id = src_id
        else:
            if reject_unfingerprinted:
                raise ValueError(
                    f"Source document '{src_path.name}' lacks SecurePDF carrier markers. "
                    "Raw un-fingerprinted documents cannot enter the labeled dataset without "
                    "first generating a personalized SecurePDF baseline."
                )
            # Personalize source into a genuine SecurePDF baseline
            baseline_file = baselines_dir / f"{src_id}_baseline.pdf"
            doc = fitz.open(str(src_path))
            nonce = generate_nonce()
            doc_uid = f"DOC-{src_id}"
            stu_uid = f"STU-{src_id}"
            fp = generate_fingerprint(ephemeral_key, doc_uid, stu_uid, nonce)
            embed_payload(doc, doc_uid, nonce, fp)
            doc.save(str(baseline_file))
            doc.close()

            transform_baseline = baseline_file
            baseline_id = f"{src_id}_baseline"

            unlabeled_sources_metadata.append({
                "source_id": src_id,
                "source_filename": src_path.name,
                "source_sha256": src_sha,
                "split": split,
                "label": None,
            })

        for suffix, label, transform_fn in TRANSFORMATIONS:
            variant_id = f"{src_id}_{suffix}"
            rel_path = f"variants/{variant_id}.pdf"
            dst_path = variants_dir / f"{variant_id}.pdf"

            try:
                # Open fresh baseline document for each transformation
                doc = fitz.open(str(transform_baseline))
                transform_fn(doc, str(dst_path))
                doc.close()

                # Extract features
                feats = extract_features(dst_path)
                status = "success"
                out_sha = _compute_sha256(dst_path)
            except Exception:
                feats = None
                status = "failed"
                out_sha = ""

            record = DatasetRecord(
                source_document_id=src_id,
                variant_id=variant_id,
                transformation=suffix,
                label=label,
                relative_path=rel_path,
                feature_extraction_status=status,
                split=split,
                features=feats,
                baseline_id=baseline_id,
                source_sha256=src_sha,
                output_sha256=out_sha,
            )
            records.append(record)

    # 2. Compute dataset statistics
    class_distribution: dict[str, int] = {}
    split_distribution: dict[str, int] = {"train": 0, "test": 0}
    for r in records:
        if r.feature_extraction_status == "success":
            class_distribution[r.label] = class_distribution.get(r.label, 0) + 1
            split_distribution[r.split] = split_distribution.get(r.split, 0) + 1

    manifest = {
        "schema_version": "1.0.0",
        "random_seed": random_seed,
        "feature_schema": FEATURE_SCHEMA,
        "labels": ALL_LABELS,
        "total_sources": len(unique_sources),
        "train_sources": sorted(list(train_sources)),
        "test_sources": sorted(list(test_sources)),
        "total_samples": len(records),
        "successful_samples": sum(1 for r in records if r.feature_extraction_status == "success"),
        "failed_samples": sum(1 for r in records if r.feature_extraction_status != "success"),
        "class_distribution": class_distribution,
        "split_distribution": split_distribution,
        "unlabeled_sources": unlabeled_sources_metadata,
        "samples": [{**asdict(r), "source_document": r.source_document_id} for r in records],
    }

    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest


# Aliases and helper entrypoints
create_synthetic_source_documents = generate_synthetic_sources


def build_forensic_dataset(
    source_dir: Path | str | list[Path],
    output_dir: Path | str,
    random_seed: int = 42,
    split_ratio: float = 0.7,
) -> dict:
    """Convenience wrapper accepting a source directory or list of source PDFs."""
    out_dir = Path(output_dir)
    if isinstance(source_dir, list):
        source_pdfs = source_dir
    else:
        src_path = Path(source_dir)
        source_pdfs = sorted(list(src_path.glob("*.pdf")))
    test_split_ratio = max(0.0, 1.0 - split_ratio)
    return build_dataset(
        source_pdfs=source_pdfs,
        output_dir=out_dir,
        test_split_ratio=test_split_ratio,
        random_seed=random_seed,
    )
