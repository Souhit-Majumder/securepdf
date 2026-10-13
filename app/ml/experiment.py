"""
Controlled Transformation Experiment Pipeline for Real-World SAFEDOCS PDFs.

This module evaluates the reproducibility and forensic behavior of the SecurePDF
pipeline when applied to real-world source documents (e.g. SAFEDOCS).

Methodological Principles:
1. Source Preservation: Source PDFs are opened strictly read-only and never modified.
2. Provenance Tracking: Every variant records source SHA-256 and output SHA-256.
3. Label Justification: Original SAFEDOCS files remain strictly UNLABELED (label=None).
   Variants receive labels (original, benign_transformation, modified, marker_tampering)
   strictly based on their documented, controlled transformation history.
4. Source-Grouped Partitioning: All variants generated from the same source PDF
   are assigned to the same train/test split. No source document variants cross splits.
5. Dual-Track Analysis:
   - Track 1 (Cryptographic): VerificationService evaluates carrier retention and HMAC attribution.
   - Track 2 (Structural ML): Feature extractor extracts the 23-feature vector.
6. Readability & Integrity: Each variant is tested for PDF parser readability.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import fitz

from app.crypto.fingerprint import generate_fingerprint, generate_nonce
from app.crypto.keys import get_or_create_master_key
from app.database.database import init_db
from app.database.repository import Repository
from app.ml.dataset import (
    ALL_LABELS,
    LABEL_BENIGN,
    LABEL_MODIFIED,
    LABEL_ORIGINAL,
    LABEL_TAMPERED,
    TRANSFORMATIONS,
)
from app.ml.feature_extractor import (
    FEATURE_SCHEMA,
    FeatureExtractionError,
    extract_features,
)
from app.pdf.embed import embed_payload
from app.pdf.extract import extract_layer1, extract_layer2
from app.services.verification_service import VerificationService


@dataclass
class ExperimentRecord:
    source_id: str
    source_filename: str
    source_sha256: str
    variant_id: str
    transformation: str
    label: str | None                 # None for raw source; string for controlled variants
    split: str                        # "train" or "test" (source-grouped)
    relative_path: str
    output_sha256: str
    is_readable: bool
    page_count: int | None
    crypto_status: str               # "VALID", "INVALID", "NOT_FOUND", etc.
    authenticated_layers: list[str]
    has_layer1_carrier: bool
    layer2_carrier_count: int
    feature_extraction_status: str    # "success", "failed", "skipped"
    features: dict[str, float] | None = field(default=None, repr=False)


def _compute_sha256(path: Path, block_size: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block_size):
            h.update(chunk)
    return h.hexdigest()


def run_safedocs_experiment(
    source_dir: Path | str,
    output_dir: Path | str,
    *,
    max_sources: int | None = None,
    test_split_ratio: float = 0.3,
    seed: int = 42,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Executes the controlled transformation experiment on SAFEDOCS PDFs.

    Args:
        source_dir: Directory containing valid SAFEDOCS PDFs (read-only).
        output_dir: Directory to save generated variants and experiment reports.
        max_sources: Optional cap on the number of source PDFs to process.
        test_split_ratio: Proportion of source documents assigned to test split.
        seed: Random seed for reproducible source document splitting.
        overwrite: Whether to overwrite existing experiment artifacts.

    Returns:
        dict containing comprehensive experiment statistics and outcomes.
    """
    source_path = Path(source_dir).resolve()
    output_path = Path(output_dir).resolve()

    if not source_path.exists() or not source_path.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source_path}")

    summary_file = output_path / "experiment_summary.json"
    if summary_file.exists() and not overwrite:
        raise FileExistsError(
            f"Experiment summary already exists at {summary_file}. "
            "Pass overwrite=True to replace."
        )

    output_path.mkdir(parents=True, exist_ok=True)
    variants_dir = output_path / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)

    # 1. Gather valid candidate PDFs (filtering out files that fail %PDF header)
    candidate_paths = sorted(
        [p for p in source_path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
    )
    valid_sources: list[Path] = []
    for p in candidate_paths:
        try:
            with open(p, "rb") as f:
                if f.read(4) == b"%PDF":
                    valid_sources.append(p)
        except OSError:
            continue

    if max_sources is not None:
        valid_sources = valid_sources[:max_sources]

    if not valid_sources:
        raise ValueError(f"No valid PDF sources found in {source_path}")

    # 2. Source-Grouped Splitting
    # Splitting occurs STRICTLY on source documents.
    rng = random.Random(seed)
    source_ids = [p.stem for p in valid_sources]
    shuffled_sources = list(source_ids)
    rng.shuffle(shuffled_sources)

    num_test = max(1, int(len(shuffled_sources) * test_split_ratio)) if len(shuffled_sources) > 1 else 0
    test_sources = set(shuffled_sources[:num_test])
    train_sources = set(shuffled_sources[num_test:])

    print(f"[*] Starting controlled SAFEDOCS experiment on {len(valid_sources)} source PDFs.")
    print(f"    Train sources: {len(train_sources)} | Test sources: {len(test_sources)}")
    print(f"    Variants dir : {variants_dir}")

    # 3. Setup temporary cryptographic verification environment
    temp_crypto_dir = Path(tempfile.mkdtemp(prefix="spdf_exp_"))
    try:
        db_path = temp_crypto_dir / "experiment.db"
        key_path = temp_crypto_dir / "master.key"
        master_key = get_or_create_master_key(key_path)
        init_db(db_path)
        repo = Repository(db_path=db_path)
        verification_service = VerificationService(repo=repo, master_key=master_key)

        records: list[ExperimentRecord] = []

        for idx, src_file in enumerate(valid_sources, 1):
            src_id = src_file.stem
            split = "test" if src_id in test_sources else "train"
            src_sha256 = _compute_sha256(src_file)

            print(f"  [{idx:3d}/{len(valid_sources)}] Processing {src_file.name} (split: {split})...")

            # Record entry for raw, un-fingerprinted source (STRICTLY UNLABELED)
            raw_features: dict[str, float] | None = None
            try:
                raw_features = extract_features(src_file)
                raw_feat_status = "success"
            except Exception:
                raw_feat_status = "failed"

            raw_crypto = verification_service.investigate_pdf(str(src_file))
            records.append(
                ExperimentRecord(
                    source_id=src_id,
                    source_filename=src_file.name,
                    source_sha256=src_sha256,
                    variant_id=f"{src_id}_raw",
                    transformation="untransformed_raw_source",
                    label=None,  # STRICTLY UNLABELED
                    split=split,
                    relative_path=f"source/{src_file.name}",
                    output_sha256=src_sha256,
                    is_readable=True,
                    page_count=int(raw_features.get("page_count", 0)) if raw_features else None,
                    crypto_status=raw_crypto.get("status", "NOT_FOUND"),
                    authenticated_layers=raw_crypto.get("authenticated_layers", []),
                    has_layer1_carrier=False,
                    layer2_carrier_count=0,
                    feature_extraction_status=raw_feat_status,
                    features=raw_features,
                )
            )

            # Register document and student in experiment repository for attribution
            doc_uid = f"DOC-{src_id}"
            stu_uid = f"STU-{src_id}"
            student_name = f"Recipient {src_id}"
            repo.create_student(stu_uid, student_name)
            doc_record = repo.get_or_create_document(doc_uid, src_file.name)
            nonce = generate_nonce()
            fingerprint_hex = generate_fingerprint(master_key, doc_uid, stu_uid, nonce)
            repo.create_fingerprint(doc_record.id, repo.get_student_by_uid(stu_uid).id, nonce, fingerprint_hex)

            # Create baseline fingerprinted document for this source
            base_temp_path = temp_crypto_dir / f"{src_id}_baseline.pdf"
            base_doc = fitz.open(str(src_file))
            embed_payload(base_doc, doc_uid, nonce, fingerprint_hex)
            base_doc.save(str(base_temp_path))
            base_doc.close()

            # Execute each controlled transformation on the fingerprinted baseline
            for suffix, label, transform_fn in TRANSFORMATIONS:
                variant_id = f"{src_id}_{suffix}"
                variant_filename = f"{variant_id}.pdf"
                variant_dest = variants_dir / variant_filename
                rel_path = f"variants/{variant_filename}"

                # Apply transformation
                try:
                    doc = fitz.open(str(base_temp_path))
                    transform_fn(doc, str(variant_dest))
                    doc.close()
                    transform_ok = True
                except Exception as err:
                    transform_ok = False

                if not transform_ok or not variant_dest.exists():
                    records.append(
                        ExperimentRecord(
                            source_id=src_id,
                            source_filename=src_file.name,
                            source_sha256=src_sha256,
                            variant_id=variant_id,
                            transformation=suffix,
                            label=label,
                            split=split,
                            relative_path=rel_path,
                            output_sha256="",
                            is_readable=False,
                            page_count=None,
                            crypto_status="ERROR",
                            authenticated_layers=[],
                            has_layer1_carrier=False,
                            layer2_carrier_count=0,
                            feature_extraction_status="failed",
                            features=None,
                        )
                    )
                    continue

                # Compute output SHA-256
                out_sha = _compute_sha256(variant_dest)

                # Check readability & carriers
                is_readable = False
                page_count = None
                has_l1 = False
                l2_count = 0
                try:
                    check_doc = fitz.open(str(variant_dest))
                    is_readable = True
                    page_count = len(check_doc)
                    has_l1 = extract_layer1(check_doc) is not None
                    l2_count = len(extract_layer2(check_doc))
                    check_doc.close()
                except Exception:
                    is_readable = False

                # Check cryptographic verification
                crypto_result = verification_service.investigate_pdf(str(variant_dest))
                c_status = crypto_result.get("status", "ERROR")
                auth_layers = crypto_result.get("authenticated_layers", [])

                # Extract features
                feat_dict = None
                try:
                    feat_dict = extract_features(variant_dest)
                    feat_status = "success"
                except Exception:
                    feat_status = "failed"

                records.append(
                    ExperimentRecord(
                        source_id=src_id,
                        source_filename=src_file.name,
                        source_sha256=src_sha256,
                        variant_id=variant_id,
                        transformation=suffix,
                        label=label,
                        split=split,
                        relative_path=rel_path,
                        output_sha256=out_sha,
                        is_readable=is_readable,
                        page_count=page_count,
                        crypto_status=c_status,
                        authenticated_layers=auth_layers,
                        has_layer1_carrier=has_l1,
                        layer2_carrier_count=l2_count,
                        feature_extraction_status=feat_status,
                        features=feat_dict,
                    )
                )

        # 4. Generate Manifests and Summary
        # Manifest CSV
        manifest_csv_path = output_path / "experiment_manifest.csv"
        with open(manifest_csv_path, "w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "source_id", "source_filename", "source_sha256", "variant_id",
                "transformation", "label", "split", "relative_path", "output_sha256",
                "is_readable", "page_count", "crypto_status", "authenticated_layers",
                "has_layer1_carrier", "layer2_carrier_count", "feature_extraction_status"
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                row = asdict(r)
                row.pop("features", None)
                row["authenticated_layers"] = ";".join(r.authenticated_layers)
                writer.writerow(row)

        # Manifest JSON (full record including features)
        manifest_json_path = output_path / "experiment_manifest.json"
        with open(manifest_json_path, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in records], f, indent=2)

        # Compute Summary Statistics
        total_records = len(records)
        raw_source_records = [r for r in records if r.transformation == "untransformed_raw_source"]
        variant_records = [r for r in records if r.transformation != "untransformed_raw_source"]

        # Readability stats
        readable_count = sum(1 for r in variant_records if r.is_readable)

        # Cryptographic verification by transformation
        crypto_by_transformation: dict[str, dict[str, int]] = {}
        carrier_retention_by_transformation: dict[str, dict[str, Any]] = {}

        for r in variant_records:
            t = r.transformation
            if t not in crypto_by_transformation:
                crypto_by_transformation[t] = {}
            crypto_by_transformation[t][r.crypto_status] = crypto_by_transformation[t].get(r.crypto_status, 0) + 1

            if t not in carrier_retention_by_transformation:
                carrier_retention_by_transformation[t] = {
                    "total": 0,
                    "layer1_present": 0,
                    "layer2_present": 0,
                    "dual_present": 0,
                }
            carrier_retention_by_transformation[t]["total"] += 1
            if r.has_layer1_carrier:
                carrier_retention_by_transformation[t]["layer1_present"] += 1
            if r.layer2_carrier_count > 0:
                carrier_retention_by_transformation[t]["layer2_present"] += 1
            if r.has_layer1_carrier and r.layer2_carrier_count > 0:
                carrier_retention_by_transformation[t]["dual_present"] += 1

        # Class counts
        class_distribution: dict[str, int] = {}
        for r in variant_records:
            lbl = r.label or "unlabeled"
            class_distribution[lbl] = class_distribution.get(lbl, 0) + 1

        # Split counts
        split_distribution = {"train": 0, "test": 0}
        for r in variant_records:
            split_distribution[r.split] = split_distribution.get(r.split, 0) + 1

        summary = {
            "source_directory": str(source_path),
            "output_directory": str(output_path),
            "random_seed": seed,
            "test_split_ratio": test_split_ratio,
            "total_source_documents": len(valid_sources),
            "train_source_ids": sorted(list(train_sources)),
            "test_source_ids": sorted(list(test_sources)),
            "total_records": total_records,
            "raw_unlabeled_source_count": len(raw_source_records),
            "variant_count": len(variant_records),
            "readable_variant_count": readable_count,
            "class_distribution": class_distribution,
            "split_distribution": split_distribution,
            "crypto_status_by_transformation": crypto_by_transformation,
            "carrier_retention_by_transformation": carrier_retention_by_transformation,
            "notes": {
                "source_preservation": "Original SAFEDOCS PDFs were opened read-only and remain unmodified.",
                "unlabeled_sources": "Raw SAFEDOCS source files are explicitly assigned label=None.",
                "source_grouped_partition": "Variants of the same source PDF are strictly isolated to either train or test.",
                "crypto_attribution": "Cryptographic attribution is validated via HMAC-SHA256 independently of ML."
            }
        }

        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        print(f"\n[✓] Experiment finished successfully.")
        print(f"    Sources processed   : {len(valid_sources)}")
        print(f"    Variants generated   : {len(variant_records)}")
        print(f"    Variants readable    : {readable_count} / {len(variant_records)}")
        print(f"    Manifest CSV         : {manifest_csv_path}")
        print(f"    Manifest JSON        : {manifest_json_path}")
        print(f"    Summary JSON         : {summary_file}")

        return summary

    finally:
        shutil.rmtree(temp_crypto_dir, ignore_errors=True)
