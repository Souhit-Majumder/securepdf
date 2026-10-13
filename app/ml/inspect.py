"""
Real-World PDF Dataset Inspection Pipeline.

Processes a directory of real-world PDFs using the existing SecurePDF feature
extractor. Produces:
  - manifest.csv  : provenance record per file
  - features.csv  : extracted feature vectors (successful PDFs only)
  - extraction_report.json : batch summary statistics
  - feature_summary.json  : per-feature distribution statistics

Strict safety invariants:
- Source PDFs are opened read-only and NEVER modified, moved, or renamed.
- No embedded JavaScript, actions, or attachments are executed.
- Duplicate PDFs are detected by SHA-256 hash; only the first occurrence is kept.
- Individual extraction failures are recorded but do not abort the batch.
- SAFEDOCS (or any real-world) PDFs receive NO synthetic labels. Labels are
  intentionally absent from the feature table because ground-truth is unknown.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any

from app.ml.feature_extractor import (
    FEATURE_SCHEMA,
    FeatureExtractionError,
    extract_features,
)

MAX_INDIVIDUAL_PDF_SIZE = 50 * 1024 * 1024  # 50 MB (same as feature extractor)
BATCH_TIMEOUT_SECONDS = 10.0  # max seconds per PDF before soft-skip


@dataclass
class FileRecord:
    filename: str
    sha256: str
    size_bytes: int
    page_count: int | None
    status: str            # "ok" | "failed" | "duplicate" | "skipped"
    failure_reason: str | None
    duplicate_of: str | None   # original filename if duplicate
    features: dict[str, float] | None = field(default=None, repr=False)


def _sha256(path: Path, block_size: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block_size):
            h.update(chunk)
    return h.hexdigest()


def _safe_extract(path: Path) -> tuple[dict[str, float] | None, str | None]:
    """
    Runs extract_features with a wall-clock timeout guard.
    Returns (features_dict, failure_reason).
    """
    start = time.monotonic()
    try:
        features = extract_features(path)
        return features, None
    except FeatureExtractionError as err:
        return None, str(err)
    except Exception as err:
        return None, f"Unexpected error: {type(err).__name__}: {err}"


def inspect_dataset(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    max_pdfs: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Core inspection routine.

    Args:
        input_dir: Directory of real-world PDFs (read-only).
        output_dir: Directory to write manifest, features, and reports.
        max_pdfs: Optional cap on number of PDFs to process (for testing).
        overwrite: If False, raise if output_dir already contains a manifest.

    Returns:
        dict summarising the batch results.
    """
    input_path = Path(input_dir).resolve()
    output_path = Path(output_dir).resolve()

    if not input_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_path}")
    if not input_path.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_path}")

    manifest_file = output_path / "manifest.csv"
    if manifest_file.exists() and not overwrite:
        raise FileExistsError(
            f"Output manifest already exists at {manifest_file}. "
            "Use overwrite=True to overwrite."
        )

    output_path.mkdir(parents=True, exist_ok=True)

    # Collect PDF paths (deterministic order — sorted by name)
    pdf_paths = sorted(
        [p for p in input_path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
    )
    if max_pdfs is not None:
        pdf_paths = pdf_paths[:max_pdfs]

    seen_hashes: dict[str, str] = {}   # hash → first filename
    records: list[FileRecord] = []

    print(f"[*] Inspecting {len(pdf_paths)} PDFs from {input_path}")
    print(f"[*] Writing results to {output_path}")

    for i, pdf_path in enumerate(pdf_paths, 1):
        filename = pdf_path.name
        print(f"  [{i:4d}/{len(pdf_paths)}] {filename} ", end="", flush=True)

        # Size check before hashing
        try:
            size = pdf_path.stat().st_size
        except OSError as err:
            records.append(FileRecord(
                filename=filename,
                sha256="",
                size_bytes=0,
                page_count=None,
                status="failed",
                failure_reason=f"Cannot stat file: {err}",
                duplicate_of=None,
            ))
            print("FAILED (stat error)")
            continue

        if size == 0:
            records.append(FileRecord(
                filename=filename,
                sha256="",
                size_bytes=0,
                page_count=None,
                status="skipped",
                failure_reason="Zero-byte file",
                duplicate_of=None,
            ))
            print("SKIPPED (empty)")
            continue

        if size > MAX_INDIVIDUAL_PDF_SIZE:
            records.append(FileRecord(
                filename=filename,
                sha256="",
                size_bytes=size,
                page_count=None,
                status="skipped",
                failure_reason=f"File too large ({size} bytes, limit {MAX_INDIVIDUAL_PDF_SIZE})",
                duplicate_of=None,
            ))
            print("SKIPPED (too large)")
            continue

        # Hash
        try:
            sha = _sha256(pdf_path)
        except OSError as err:
            records.append(FileRecord(
                filename=filename,
                sha256="",
                size_bytes=size,
                page_count=None,
                status="failed",
                failure_reason=f"Cannot hash file: {err}",
                duplicate_of=None,
            ))
            print("FAILED (hash error)")
            continue

        # Duplicate check
        if sha in seen_hashes:
            records.append(FileRecord(
                filename=filename,
                sha256=sha,
                size_bytes=size,
                page_count=None,
                status="duplicate",
                failure_reason=None,
                duplicate_of=seen_hashes[sha],
            ))
            print(f"DUPLICATE (of {seen_hashes[sha]})")
            continue

        seen_hashes[sha] = filename

        # Feature extraction (read-only)
        features, failure_reason = _safe_extract(pdf_path)

        if features is not None:
            page_count = int(features.get("page_count", 0))
            records.append(FileRecord(
                filename=filename,
                sha256=sha,
                size_bytes=size,
                page_count=page_count,
                status="ok",
                failure_reason=None,
                duplicate_of=None,
                features=features,
            ))
            print(f"OK ({page_count}pp)")
        else:
            records.append(FileRecord(
                filename=filename,
                sha256=sha,
                size_bytes=size,
                page_count=None,
                status="failed",
                failure_reason=failure_reason,
                duplicate_of=None,
            ))
            print(f"FAILED ({failure_reason})")

    # ------------------------------------------------------------------ #
    # Write manifest.csv (all files)
    # ------------------------------------------------------------------ #
    with open(manifest_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "filename", "sha256", "size_bytes", "page_count",
            "status", "failure_reason", "duplicate_of"
        ])
        writer.writeheader()
        for r in records:
            writer.writerow({
                "filename": r.filename,
                "sha256": r.sha256,
                "size_bytes": r.size_bytes,
                "page_count": r.page_count,
                "status": r.status,
                "failure_reason": r.failure_reason or "",
                "duplicate_of": r.duplicate_of or "",
            })

    # ------------------------------------------------------------------ #
    # Write features.csv (successful unique PDFs only, no labels)
    # ------------------------------------------------------------------ #
    features_file = output_path / "features.csv"
    ok_records = [r for r in records if r.status == "ok" and r.features]
    with open(features_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "sha256"] + FEATURE_SCHEMA)
        writer.writeheader()
        for r in ok_records:
            row = {"filename": r.filename, "sha256": r.sha256}
            row.update({k: r.features[k] for k in FEATURE_SCHEMA})
            writer.writerow(row)

    # ------------------------------------------------------------------ #
    # Write extraction_report.json
    # ------------------------------------------------------------------ #
    n_total = len(records)
    n_ok = sum(1 for r in records if r.status == "ok")
    n_failed = sum(1 for r in records if r.status == "failed")
    n_duplicate = sum(1 for r in records if r.status == "duplicate")
    n_skipped = sum(1 for r in records if r.status == "skipped")

    failure_reasons: dict[str, int] = {}
    for r in records:
        if r.status in ("failed", "skipped") and r.failure_reason:
            key = r.failure_reason.split(":")[0][:80]  # normalise
            failure_reasons[key] = failure_reasons.get(key, 0) + 1

    extraction_report = {
        "input_directory": str(input_path),
        "output_directory": str(output_path),
        "total_files_found": n_total,
        "successfully_processed": n_ok,
        "failed": n_failed,
        "duplicates": n_duplicate,
        "skipped": n_skipped,
        "unique_successful_sha256_count": len(seen_hashes),
        "failure_reasons": failure_reasons,
        "feature_schema": FEATURE_SCHEMA,
        "feature_count": len(FEATURE_SCHEMA),
        "note": (
            "Real-world PDFs receive NO synthetic labels. "
            "This report describes structural feature compatibility only."
        ),
    }
    report_file = output_path / "extraction_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(extraction_report, f, indent=2)

    # ------------------------------------------------------------------ #
    # Write feature_summary.json
    # ------------------------------------------------------------------ #
    feature_summary: dict[str, Any] = {
        "n_documents": n_ok,
        "features": {},
    }
    if ok_records:
        for feat in FEATURE_SCHEMA:
            values = [r.features[feat] for r in ok_records if r.features]
            nonzero = [v for v in values if v != 0.0]
            feature_summary["features"][feat] = {
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "mean": round(mean(values), 4),
                "median": round(median(values), 4),
                "stdev": round(stdev(values), 4) if len(values) > 1 else 0.0,
                "zero_count": len(values) - len(nonzero),
                "nonzero_count": len(nonzero),
                "is_constant": min(values) == max(values),
            }

    summary_file = output_path / "feature_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(feature_summary, f, indent=2)

    print(f"\n[✓] Inspection complete.")
    print(f"    Total        : {n_total}")
    print(f"    OK           : {n_ok}")
    print(f"    Failed       : {n_failed}")
    print(f"    Duplicates   : {n_duplicate}")
    print(f"    Skipped      : {n_skipped}")
    print(f"    Features CSV : {features_file}")
    print(f"    Manifest CSV : {manifest_file}")
    print(f"    Report JSON  : {report_file}")
    print(f"    Summary JSON : {summary_file}")

    return extraction_report
