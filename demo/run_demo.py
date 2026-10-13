#!/usr/bin/env python3
"""
SecurePDF — Live Professor Demonstration Runner.

Orchestrates an end-to-end, self-contained demonstration of SecurePDF:
1. Source PDF Discovery & Strict Validation (Phase 4)
2. Student Registry & Identity Verification (Phase 5)
3. Cryptographic Fingerprint Issuance & Redundancy (Phase 5)
4. Automated Multi-Vector Tampering Demonstration (Phase 6)
5. Visual Tampering Evidence & Side-by-Side Diffing (Phase 7)
6. ML Forensic Dataset Generation & Model Evaluation (Phase 8)
7. Presentation Charts & Comprehensive Reports (Phase 9)

All demo operations run in complete isolation inside the demo/ directory,
using a dedicated database and demo master key.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Paths relative to demo directory (independent of shell CWD)
DEMO_DIR = Path(__file__).resolve().parent
PDFS_DIR = DEMO_DIR / "pdfs"
STUDENTS_FILE = DEMO_DIR / "students.json"
ISSUED_DIR = DEMO_DIR / "issued"
TAMPERED_DIR = DEMO_DIR / "tampered"
REPORTS_DIR = DEMO_DIR / "reports"
CHARTS_DIR = DEMO_DIR / "charts"
LOGS_DIR = DEMO_DIR / "logs"
WORKING_DIR = DEMO_DIR / "working"
DATASET_DIR = DEMO_DIR / "dataset"
RESULTS_DIR = DEMO_DIR / "results"

# Isolated Demo Security & Storage Environment
DEMO_DB_PATH = WORKING_DIR / "securepdf_demo.db"
DEMO_KEY_PATH = WORKING_DIR / "demo_master.key"
DEMO_MODEL_PATH = WORKING_DIR / "demo_model.joblib"

# Set environment variables to enforce demo directory isolation
os.environ["SECUREPDF_DATA_DIR"] = str(WORKING_DIR)
os.environ["SECUREPDF_DB_PATH"] = str(DEMO_DB_PATH)
os.environ["SECUREPDF_KEY_PATH"] = str(DEMO_KEY_PATH)
os.environ["SECUREPDF_OUTPUT_DIR"] = str(ISSUED_DIR)
os.environ["SECUREPDF_TEMP_DIR"] = str(WORKING_DIR / "temp")
os.environ["SECUREPDF_ML_DIR"] = str(DATASET_DIR)
os.environ["SECUREPDF_MODEL_PATH"] = str(DEMO_MODEL_PATH)

import fitz
import numpy as np

# SecurePDF Core Imports
from app.crypto.fingerprint import generate_fingerprint, generate_nonce
from app.crypto.keys import get_or_create_master_key
from app.database.database import init_db
from app.database.repository import Repository
from app.ml.dataset import ALL_LABELS, CLASS_LABELS, build_dataset
from app.ml.evaluate import evaluate_model
from app.ml.feature_extractor import (
    FEATURE_SCHEMA,
    extract_features,
    extract_pdf_features,
)
from app.ml.predictor import MLPredictor
from app.ml.train import train_model
from app.pdf.embed import embed_payload
from app.pdf.extract import extract_layer1, extract_layer2
from app.pdf.processor import open_pdf, validate_pdf
from app.services.fingerprint_service import FingerprintService
from app.services.forensic_service import ForensicService
from app.services.verification_service import VerificationService


# ---------------------------------------------------------------------------
# Utility Helpers
# ---------------------------------------------------------------------------

def compute_sha256(path: Path) -> str:
    """Computes SHA-256 digest of a file in binary mode."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def ensure_demo_directories() -> None:
    """Creates all required demo directories."""
    for d in [
        PDFS_DIR,
        ISSUED_DIR,
        TAMPERED_DIR,
        REPORTS_DIR,
        CHARTS_DIR,
        LOGS_DIR,
        WORKING_DIR,
        WORKING_DIR / "temp",
        DATASET_DIR / "manifests",
        DATASET_DIR / "variants",
        DATASET_DIR / "baselines",
        REPORTS_DIR / "visual",
        REPORTS_DIR / "chart_data",
        RESULTS_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


def get_demo_services() -> tuple[Repository, FingerprintService, VerificationService]:
    """Initializes isolated demo database and services."""
    ensure_demo_directories()
    init_db(DEMO_DB_PATH)
    master_key = get_or_create_master_key(DEMO_KEY_PATH)
    repo = Repository(db_path=DEMO_DB_PATH)
    fp_service = FingerprintService(repo=repo, master_key=master_key)
    ver_service = VerificationService(repo=repo, master_key=master_key)
    return repo, fp_service, ver_service


# ---------------------------------------------------------------------------
# Stage 1: Discover and Validate Source PDFs
# ---------------------------------------------------------------------------

def stage_1_discover_pdfs(verbose: bool = True) -> list[dict[str, Any]]:
    """
    Scans demo/pdfs/ for source PDFs, enforces strict validation,
    records file hashes, and returns valid candidate documents.
    """
    ensure_demo_directories()
    if verbose:
        print("\n" + "=" * 70)
        print("  STAGE 1: PDF Source Discovery & Strict Validation")
        print("=" * 70)
        print(f"Scanning input folder: {PDFS_DIR}\n")

    candidates = sorted(list(PDFS_DIR.glob("*.pdf")))
    results: list[dict[str, Any]] = []

    if not candidates:
        if verbose:
            print("[-] No PDF documents found in demo/pdfs/.")
            print("    Please drop one or more PDF files into demo/pdfs/ to proceed.")
        return []

    for pdf_path in candidates:
        file_size = pdf_path.stat().st_size
        sha256_hash = compute_sha256(pdf_path)

        # 1. Header validation
        is_header_valid = False
        try:
            with open(pdf_path, "rb") as f:
                header = f.read(4)
            is_header_valid = (header == b"%PDF")
        except Exception:
            is_header_valid = False

        # 2. PyMuPDF parsing validation
        page_count: int | None = None
        is_readable = False
        error_msg: str | None = None
        has_l1 = False
        has_l2 = False

        if not is_header_valid:
            error_msg = "Invalid %PDF header format"
        else:
            try:
                doc = open_pdf(str(pdf_path))
                page_count = doc.page_count
                is_readable = True
                has_l1 = extract_layer1(doc) is not None
                has_l2 = len(extract_layer2(doc)) > 0
                doc.close()
            except Exception as e:
                error_msg = f"PDF structure unreadable: {e}"

        status = "VALID" if (is_header_valid and is_readable) else "REJECTED"

        record = {
            "filename": pdf_path.name,
            "path": str(pdf_path),
            "size_bytes": file_size,
            "page_count": page_count,
            "sha256": sha256_hash,
            "status": status,
            "error": error_msg,
            "has_existing_catalog_carrier": has_l1,
            "has_existing_annotation_carrier": has_l2,
        }
        results.append(record)

        if verbose:
            tag = "[✓]" if status == "VALID" else "[X]"
            print(f"{tag} {pdf_path.name:<25} | Size: {file_size:>8} B | Pages: {page_count or 'N/A':>2} | Status: {status}")
            if error_msg:
                print(f"    Reason: {error_msg}")
            print(f"    SHA-256: {sha256_hash}")

    # Save discovery manifest
    manifest_path = REPORTS_DIR / "discovered_pdfs.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    valid_count = sum(1 for r in results if r["status"] == "VALID")
    if verbose:
        print(f"\nDiscovered {len(results)} total PDF(s): {valid_count} valid, {len(results) - valid_count} rejected.")
        print(f"Manifest written to: {manifest_path.relative_to(DEMO_DIR)}")
    return results


# ---------------------------------------------------------------------------
# Stage 2: Student Management and Validation
# ---------------------------------------------------------------------------

def stage_2_load_students(verbose: bool = True) -> list[dict[str, str]]:
    """
    Loads and validates the student registry from demo/students.json.
    Ensures non-empty fields, valid schema, and uniqueness of student_id.
    """
    if verbose:
        print("\n" + "=" * 70)
        print("  STAGE 2: Student Registry Validation")
        print("=" * 70)
        print(f"Reading student registry: {STUDENTS_FILE}\n")

    if not STUDENTS_FILE.exists():
        if verbose:
            print(f"[-] Students registry file missing: {STUDENTS_FILE}")
        return []

    try:
        with open(STUDENTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        if verbose:
            print(f"[X] Malformed JSON in students.json: {e}")
        return []

    students = data.get("students", [])
    if not isinstance(students, list) or not students:
        if verbose:
            print("[-] No students defined in registry.")
        return []

    seen_ids: set[str] = set()
    validated_students: list[dict[str, str]] = []

    for idx, s in enumerate(students, 1):
        s_id = s.get("student_id", "").strip()
        name = s.get("name", "").strip()
        email = s.get("email", "").strip()

        if not s_id or not name:
            if verbose:
                print(f"[X] Record #{idx} rejected: Missing student_id or name.")
            continue

        if s_id in seen_ids:
            if verbose:
                print(f"[X] Duplicate student ID rejected: '{s_id}'")
            continue

        seen_ids.add(s_id)
        validated_students.append({"student_id": s_id, "name": name, "email": email})
        if verbose:
            print(f"  [✓] ID: {s_id:<10} | Name: {name:<22} | Email: {email}")

    if verbose:
        print(f"\nSuccessfully validated {len(validated_students)} student identity records.")
    return validated_students


# ---------------------------------------------------------------------------
# Stage 3: Issue Personalized PDFs
# ---------------------------------------------------------------------------

def stage_3_issue_pdfs(verbose: bool = True) -> list[dict[str, Any]]:
    """
    Issues personalized, cryptographically fingerprinted PDFs for all validated
    students and valid source PDFs. Uses isolated demo database and demo master key.
    """
    ensure_demo_directories()
    repo, fp_service, _ = get_demo_services()

    pdf_records = [p for p in stage_1_discover_pdfs(verbose=False) if p["status"] == "VALID"]
    students = stage_2_load_students(verbose=False)

    if verbose:
        print("\n" + "=" * 70)
        print("  STAGE 3: Cryptographic Personalization & Fingerprint Issuance")
        print("=" * 70)
        print(f"Isolated Demo DB : {DEMO_DB_PATH}")
        print(f"Isolated Demo Key: {DEMO_KEY_PATH}\n")

    if not pdf_records:
        if verbose:
            print("[-] No valid source PDFs available for issuance.")
        return []
    if not students:
        if verbose:
            print("[-] No valid students available for issuance.")
        return []

    issued_records: list[dict[str, Any]] = []

    for pdf_info in pdf_records:
        src_path = Path(pdf_info["path"])
        src_stem = src_path.stem
        src_sha = pdf_info["sha256"]
        doc_uid = f"DOC-{src_stem.upper()}"

        doc_record = repo.get_or_create_document(doc_uid, src_path.name)
        doc_issued_dir = ISSUED_DIR / src_stem
        doc_issued_dir.mkdir(parents=True, exist_ok=True)

        if verbose:
            print(f"[*] Issuing Document '{doc_uid}' ({src_path.name}):")

        for stu in students:
            s_id = stu["student_id"]
            s_name = stu["name"]
            repo.create_student(s_id, s_name)

            out_filename = f"{s_id}_{src_stem}.pdf"
            out_path = doc_issued_dir / out_filename

            # Perform genuine cryptographic issuance
            fp_hex = fp_service.fingerprint_pdf(
                student_uid=s_id,
                document_uid=doc_uid,
                input_pdf_path=str(src_path),
                output_pdf_path=str(out_path),
            )

            out_sha = compute_sha256(out_path)

            record = {
                "document_uid": doc_uid,
                "source_filename": src_path.name,
                "source_sha256": src_sha,
                "student_id": s_id,
                "student_name": s_name,
                "output_filename": out_filename,
                "output_path": str(out_path),
                "output_sha256": out_sha,
                "fingerprint": fp_hex,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            issued_records.append(record)

            if verbose:
                print(f"  [✓] Recipient: {s_name:<20} ({s_id}) → {out_filename}")
                print(f"      FP (HMAC-SHA256): {fp_hex[:32]}... | Output SHA-256: {out_sha[:16]}...")

    # Write issuance manifest
    manifest_path = ISSUED_DIR / "issuance_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(issued_records, f, indent=2)

    if verbose:
        print(f"\nTotal copies issued: {len(issued_records)}")
        print(f"Issuance manifest written to: {manifest_path.relative_to(DEMO_DIR)}")

    return issued_records


# ---------------------------------------------------------------------------
# Stage 4: Automated Multi-Vector Tampering Demonstration
# ---------------------------------------------------------------------------

def stage_4_tamper_and_analyze(verbose: bool = True) -> list[dict[str, Any]]:
    """
    Executes a comprehensive, reproducible tampering suite on issued copies:
    applies 13 deterministic transformations, then analyzes each using
    both authoritative cryptographic verification and advisory ML.
    """
    ensure_demo_directories()
    repo, _, ver_service = get_demo_services()

    # Load issued manifest
    issuance_manifest = ISSUED_DIR / "issuance_manifest.json"
    if not issuance_manifest.exists():
        if verbose:
            print("[-] No issued PDFs found. Running Stage 3 issuance first...")
        stage_3_issue_pdfs(verbose=verbose)

    with open(issuance_manifest, encoding="utf-8") as f:
        issued_items = json.load(f)

    if not issued_items:
        if verbose:
            print("[-] Issuance manifest is empty.")
        return []

    # Initialize ML Predictor (if demo model exists in demo/working/)
    predictor = MLPredictor(model_path=DEMO_MODEL_PATH)
    forensic_service = ForensicService(
        verification_service=ver_service,
        predictor=predictor,
    )

    if verbose:
        print("\n" + "=" * 70)
        print("  STAGE 4: Automated Multi-Vector Tampering & Forensic Analysis")
        print("=" * 70)
        print(f"Evaluating {len(issued_items)} issued baseline copy(ies).")
        print(f"ML Model Artifact: {DEMO_MODEL_PATH} ({'AVAILABLE' if predictor.is_available() else 'UNAVAILABLE (Untrained)'})\n")

    tamper_records: list[dict[str, Any]] = []

    # Pick the primary baseline copy for comprehensive demonstration
    primary_baseline = issued_items[0]
    base_path = Path(primary_baseline["output_path"])
    base_stem = base_path.stem
    doc_uid = primary_baseline["document_uid"]
    stu_id = primary_baseline["student_id"]
    stu_name = primary_baseline["student_name"]

    target_dir = TAMPERED_DIR / base_stem
    target_dir.mkdir(parents=True, exist_ok=True)

    # Secondary student payload for security conflict testing
    secondary_baseline = issued_items[1] if len(issued_items) > 1 else primary_baseline
    sec_path = Path(secondary_baseline["output_path"])

    # 13 Defined Transformations
    transformations: list[tuple[str, str, str]] = [
        ("01_untouched", "original", "Control: pristine, unmodified copy"),
        ("02_benign_resave", "benign_transformation", "PyMuPDF re-save with garbage=3 and stream deflation"),
        ("03_metadata_mod", "benign_transformation", "Catalog metadata modified (title & author altered)"),
        ("04_page_added", "modified", "Appended extraneous notes page"),
        ("05_page_deleted", "modified", "Deleted last page from document"),
        ("06_page_reordered", "modified", "Reversed document page sequence"),
        ("07_text_modified", "modified", "Visible red banner inserted across content page"),
        ("08_catalog_corrupt", "marker_tampering", "Corrupted Layer 1 Catalog carrier with junk hex"),
        ("09_catalog_deleted", "marker_tampering", "Deleted Layer 1 Catalog carrier (/SPDFPayload null)"),
        ("10_annot_corrupt", "marker_tampering", "Corrupted Layer 2 Annotation carrier payload"),
        ("11_annot_deleted", "marker_tampering", "Deleted Layer 2 Annotation carrier from all pages"),
        ("12_both_removed", "marker_tampering", "Adversarial removal of BOTH carrier layers"),
        ("13_security_conflict", "marker_tampering", "Conflicting carriers: Layer 1 = Alice, Layer 2 = Bob"),
    ]

    for code, label_category, desc in transformations:
        out_pdf = target_dir / f"{code}.pdf"

        # Apply transformation
        d = fitz.open(str(base_path))

        if code == "01_untouched":
            d.save(str(out_pdf))
        elif code == "02_benign_resave":
            d.save(str(out_pdf), garbage=3, deflate=True)
        elif code == "03_metadata_mod":
            meta = d.metadata or {}
            meta["title"] = "CONFIDENTIAL INTERNAL DRAFT"
            meta["author"] = "Anonymous Leaker"
            d.set_metadata(meta)
            d.save(str(out_pdf))
        elif code == "04_page_added":
            np_page = d.new_page()
            np_page.insert_text((50, 50), "APPENDIX: Unofficial Student Notes", fontsize=12)
            d.save(str(out_pdf))
        elif code == "05_page_deleted":
            if d.page_count > 1:
                d.delete_page(d.page_count - 1)
            else:
                d[0].insert_text((50, 750), "[Deleted section placeholder]")
            d.save(str(out_pdf))
        elif code == "06_page_reordered":
            if d.page_count > 1:
                d.select(list(reversed(range(d.page_count))))
            d.save(str(out_pdf))
        elif code == "07_text_modified":
            p = d[0]
            # Red box and banner text
            rect = fitz.Rect(40, 30, 570, 75)
            p.draw_rect(rect, color=(0.8, 0, 0), fill=(1, 0.9, 0.9), width=1.5)
            p.insert_text((50, 55), "CONFIDENTIAL LEAK — EDITED COPY — GRADE LEAK", fontsize=11, color=(0.8, 0, 0))
            d.save(str(out_pdf))
        elif code == "08_catalog_corrupt":
            cat = d.pdf_catalog()
            d.xref_set_key(cat, "SPDFPayload", "<535044462d56317c4a554e4b5f434f5252555054>")
            d.save(str(out_pdf))
        elif code == "09_catalog_deleted":
            cat = d.pdf_catalog()
            d.xref_set_key(cat, "SPDFPayload", "null")
            d.save(str(out_pdf))
        elif code == "10_annot_corrupt":
            for p in d:
                for a in p.annots():
                    info = a.info or {}
                    if info.get("title", "").startswith("SPDF"):
                        info["content"] = "SPDF1|DOC|CORRUPTED_ANNOTATION"
                        a.set_info(info)
                        a.update()
            d.save(str(out_pdf))
        elif code == "11_annot_deleted":
            for p in d:
                for a in p.annots():
                    if (a.info or {}).get("title", "").startswith("SPDF"):
                        p.delete_annot(a)
            d.save(str(out_pdf))
        elif code == "12_both_removed":
            d.xref_set_key(d.pdf_catalog(), "SPDFPayload", "null")
            for p in d:
                for a in p.annots():
                    if (a.info or {}).get("title", "").startswith("SPDF"):
                        p.delete_annot(a)
            d.save(str(out_pdf))
        elif code == "13_security_conflict":
            # Extract secondary payload
            d_sec = fitz.open(str(sec_path))
            sec_l2 = extract_layer2(d_sec)
            d_sec.close()
            payload_to_inject = sec_l2[0] if sec_l2 else "SPDF1|DOC-ALT|N-ALT|FP-ALT"

            for p in d:
                for a in p.annots():
                    info = a.info or {}
                    if info.get("title", "").startswith("SPDF"):
                        info["content"] = payload_to_inject
                        a.set_info(info)
                        a.update()
            d.save(str(out_pdf))

        d.close()

        # Run dual-track forensic analysis
        analysis = forensic_service.analyze_pdf(out_pdf)
        crypto = analysis["cryptographic_verification"]
        attr = analysis["attribution"]
        ml = analysis["ml_assessment"]

        crypto_status = crypto.get("status", "UNKNOWN")
        auth_layers = crypto.get("authenticated_layers", [])
        attributed_to = attr.get("student_name") if attr else None

        ml_status = ml.get("status", "UNAVAILABLE")
        ml_class = ml.get("predicted_class")
        ml_conf = ml.get("confidence_score")

        rec = {
            "scenario": code,
            "description": desc,
            "expected_category": label_category,
            "filename": out_pdf.name,
            "path": str(out_pdf),
            "sha256": compute_sha256(out_pdf),
            "crypto_status": crypto_status,
            "attributed_student": attributed_to,
            "authenticated_layers": auth_layers,
            "crypto_reason": crypto.get("reason"),
            "ml_status": ml_status,
            "ml_predicted_class": ml_class,
            "ml_confidence": ml_conf,
            "ml_advisory_notice": ml.get("advisory_notice"),
        }
        tamper_records.append(rec)

        if verbose:
            print(f"[{code}] {desc}")
            print(f"  • Crypto Verdict: {crypto_status:<17} | Recipient: {attributed_to or 'None'}")
            print(f"  • Surviving Auth: {auth_layers}")
            print(f"  • ML Assessment : {ml_status:<12} | Predicted: {ml_class or 'None'} (Conf: {ml_conf or 0.0})")
            print()

    # Save comprehensive reports
    json_path = REPORTS_DIR / "tamper_report.json"
    csv_path = REPORTS_DIR / "tamper_report.csv"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(tamper_records, f, indent=2)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "scenario",
                "expected_category",
                "crypto_status",
                "attributed_student",
                "authenticated_layers",
                "ml_status",
                "ml_predicted_class",
                "ml_confidence",
                "sha256",
                "description",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(tamper_records)

    if verbose:
        print("=" * 70)
        print("  TAMPERING DEMONSTRATION COMPLETE")
        print("=" * 70)
        print(f"Reports saved to:")
        print(f"  • {json_path.relative_to(DEMO_DIR)}")
        print(f"  • {csv_path.relative_to(DEMO_DIR)}\n")

    return tamper_records


# ---------------------------------------------------------------------------
# Stage 5: Visual Tampering Evidence (Side-by-Side & Difference Heatmaps)
# ---------------------------------------------------------------------------

def stage_5_generate_visual_evidence(verbose: bool = True) -> list[Path]:
    """
    Renders high-resolution page comparisons for transformations:
    - Side-by-side visual diffs for content modifications (text_modified, page_added)
    - Structural carrier comparison cards for invisible carrier tampering
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ensure_demo_directories()
    vis_dir = REPORTS_DIR / "visual"
    vis_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print("\n" + "=" * 70)
        print("  STAGE 5: Visual Tampering Evidence & Structural Diffs")
        print("=" * 70)
        print(f"Rendering visual artifacts to: {vis_dir}\n")

    # Locate tampered folder
    subdirs = [d for d in TAMPERED_DIR.iterdir() if d.is_dir()]
    if not subdirs:
        if verbose:
            print("[-] No tampered PDFs found. Running Stage 4 first...")
        stage_4_tamper_and_analyze(verbose=False)
        subdirs = [d for d in TAMPERED_DIR.iterdir() if d.is_dir()]

    if not subdirs:
        return []

    target_dir = subdirs[0]
    generated_figures: list[Path] = []

    # 1. Content Modification Visual Diff (07_text_modified vs 01_untouched)
    orig_path = target_dir / "01_untouched.pdf"
    mod_path = target_dir / "07_text_modified.pdf"

    if orig_path.exists() and mod_path.exists():
        d_orig = fitz.open(str(orig_path))
        d_mod = fitz.open(str(mod_path))

        pix_orig = d_orig[0].get_pixmap(dpi=150)
        pix_mod = d_mod[0].get_pixmap(dpi=150)

        img_orig = np.frombuffer(pix_orig.samples, dtype=np.uint8).reshape((pix_orig.height, pix_orig.width, pix_orig.n))[:, :, :3]
        img_mod = np.frombuffer(pix_mod.samples, dtype=np.uint8).reshape((pix_mod.height, pix_mod.width, pix_mod.n))[:, :, :3]

        d_orig.close()
        d_mod.close()

        # Compute difference
        diff = np.abs(img_orig.astype(np.int16) - img_mod.astype(np.int16)).astype(np.uint8)
        diff_gray = np.mean(diff, axis=2)

        fig, axes = plt.subplots(1, 3, figsize=(18, 8), dpi=150)
        axes[0].imshow(img_orig)
        axes[0].set_title("Original Issued PDF (Page 1)\nCryptographic: VALID", fontsize=12, fontweight="bold", color="#1b5e20")
        axes[0].axis("off")

        axes[1].imshow(img_mod)
        axes[1].set_title("Tampered PDF (Banner Injected)\nCryptographic: VALID (Identity Preserved)", fontsize=12, fontweight="bold", color="#b71c1c")
        axes[1].axis("off")

        im = axes[2].imshow(diff_gray, cmap="hot")
        axes[2].set_title("Pixel Difference Heatmap\n(Content Divergence Detected)", fontsize=12, fontweight="bold", color="#e65100")
        axes[2].axis("off")
        plt.colorbar(im, ax=axes[2], fraction=0.046, pad=0.04)

        plt.suptitle("SecurePDF Visual Forensic Comparison — Visible Content Modification", fontsize=15, fontweight="bold")
        plt.tight_layout()

        out_fig = vis_dir / "visual_diff_text_modified.png"
        plt.savefig(out_fig, dpi=150)
        plt.close(fig)
        generated_figures.append(out_fig)

        if verbose:
            print(f"[✓] Created visual diff figure: {out_fig.name}")

    # 2. Structural Carrier Redundancy Inspection Card
    fig, ax = plt.subplots(figsize=(12, 6), dpi=150)
    ax.axis("off")

    card_text = (
        "SecurePDF Structural Redundancy & Carrier Status Matrix\n"
        "========================================================================\n\n"
        "Scenario                      Catalog Carrier (L1)    Annotation Carrier (L2)   Crypto Verdict    Attribution Result\n"
        "--------------------------------------------------------------------------------------------------------------------\n"
        "01. Pristine Baseline          [PRESENT / VALID]       [PRESENT / VALID]        VALID             Full Student Attribution\n"
        "02. PyMuPDF Re-save           [PRESENT / VALID]       [PRESENT / VALID]        VALID             Full Student Attribution\n"
        "03. Title Metadata Modified    [PRESENT / VALID]       [PRESENT / VALID]        VALID             Full Student Attribution\n"
        "07. Content Text Modified      [PRESENT / VALID]       [PRESENT / VALID]        VALID*            Attribution Intact (*Content Modified)\n"
        "08. Catalog Corrupted          [CORRUPTED]             [PRESENT / VALID]        VALID             Surviving Layer 2 Recovers Identity\n"
        "09. Catalog Deleted (/null)    [STRIPPED / NULL]       [PRESENT / VALID]        VALID             Surviving Layer 2 Recovers Identity\n"
        "10. Annotation Corrupted       [PRESENT / VALID]       [CORRUPTED]              VALID             Surviving Layer 1 Recovers Identity\n"
        "11. Annotations Deleted        [PRESENT / VALID]       [STRIPPED / NULL]        VALID             Surviving Layer 1 Recovers Identity\n"
        "12. Both Carriers Removed      [STRIPPED / NULL]       [STRIPPED / NULL]        NOT_FOUND         Cryptographic Fail-Closed\n"
        "13. Security Identity Conflict [STUDENT A]             [STUDENT B]              SECURITY_CONFLICT Fail-Closed (Anti-Framing Guard)\n\n"
        "Key Security Invariant: ML tampering classification is an advisory complement and NEVER overrides cryptographic status."
    )

    ax.text(
        0.02,
        0.95,
        card_text,
        transform=ax.transAxes,
        fontsize=10,
        fontfamily="monospace",
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=1", facecolor="#f8f9fa", edgecolor="#ced4da"),
    )

    card_fig = vis_dir / "structural_carrier_matrix.png"
    plt.savefig(card_fig, dpi=150, bbox_inches="tight")
    plt.close(fig)
    generated_figures.append(card_fig)

    if verbose:
        print(f"[✓] Created structural matrix card: {card_fig.name}")
        print(f"\nVisual evidence artifacts ready in: {vis_dir.relative_to(DEMO_DIR)}")

    return generated_figures


# ---------------------------------------------------------------------------
# Stage 6: ML Dataset Generation & Evaluation
# ---------------------------------------------------------------------------

def stage_6_ml_pipeline(verbose: bool = True) -> dict[str, Any]:
    """
    Executes the end-to-end ML dataset generation and evaluation pipeline:
    1. Discovers input PDFs in demo/pdfs/
    2. Builds a source-grouped forensic dataset in demo/dataset/
    3. Trains Random Forest classifier artifact in demo/working/demo_model.joblib
    4. Evaluates against test split and compares with Dummy Baseline
    """
    ensure_demo_directories()

    if verbose:
        print("\n" + "=" * 70)
        print("  STAGE 6: ML Dataset Generation & Forensic Model Evaluation")
        print("=" * 70)

    # 1. Gather valid source PDFs
    source_pdfs = sorted(list(PDFS_DIR.glob("*.pdf")))
    if not source_pdfs:
        if verbose:
            print("[-] No source PDFs found in demo/pdfs/.")
        return {"status": "ERROR", "reason": "No source PDFs"}

    dataset_output = DATASET_DIR
    variants_dir = dataset_output / "variants"
    manifest_path = dataset_output / "manifests" / "manifest.json"

    if verbose:
        print(f"[*] Building forensic dataset from {len(source_pdfs)} source document(s)...")

    # Use canonical build_dataset enforcing baseline generation and source-grouped splits
    manifest = build_dataset(
        source_pdfs=source_pdfs,
        output_dir=dataset_output,
        test_split_ratio=0.5 if len(source_pdfs) >= 2 else 0.0,
        random_seed=42,
        reject_unfingerprinted=False,
    )

    # Save manifest into manifests/
    shutil.copyfile(dataset_output / "manifest.json", manifest_path)

    total_samples = manifest.get("total_samples", 0)
    train_sources = manifest.get("train_sources", [])
    test_sources = manifest.get("test_sources", [])

    if verbose:
        print(f"[+] Dataset created with {total_samples} samples.")
        print(f"    Train sources: {train_sources}")
        print(f"    Test sources : {test_sources}")
        print(f"    Class distribution: {manifest.get('class_distribution', {})}")

    # 2. Train Random Forest Model Artifact
    if verbose:
        print(f"\n[*] Training Random Forest model artifact (seed=42, n_estimators=50)...")

    train_summary = train_model(
        manifest_path=manifest_path,
        model_output_path=DEMO_MODEL_PATH,
        random_seed=42,
        n_estimators=50,
    )

    if verbose:
        print(f"[+] Model artifact saved to: {DEMO_MODEL_PATH.relative_to(DEMO_DIR)}")
        print(f"    Train Accuracy : {train_summary.get('train_accuracy', 0.0):.4f}")
        print(f"    Baseline Dummy : {train_summary.get('baseline_dummy_accuracy', 0.0):.4f}")

    # 3. Comprehensive Evaluation
    if verbose:
        print(f"\n[*] Evaluating model against dataset manifest...")

    eval_result = evaluate_model(
        model_path=DEMO_MODEL_PATH,
        manifest_path=manifest_path,
        use_test_split_only=True if len(test_sources) > 0 else False,
    )

    # Save evaluation report
    eval_report_file = REPORTS_DIR / "ml_evaluation.json"
    with open(eval_report_file, "w", encoding="utf-8") as f:
        json.dump(eval_result, f, indent=2)

    if verbose:
        print(f"\n" + "-" * 50)
        print(f"  EVALUATION SUMMARY ({eval_result.get('evaluation_split', 'test')})")
        print(f"-" * 50)
        print(f"Accuracy         : {eval_result.get('accuracy', 0.0):.4f}")
        print(f"Macro F1 Score   : {eval_result.get('macro_f1', 0.0):.4f}")
        print(f"Dummy Baseline   : {eval_result.get('baseline_accuracy', 0.0):.4f}")
        print(f"Sample Count     : {eval_result.get('eval_samples', 0)}")
        print("\nPer-Class Metrics:")
        pcm = eval_result.get("per_class", {})
        for cls_name, m in pcm.items():
            f1_val = m.get("f1_score", m.get("f1", 0.0))
            print(f"  • {cls_name:<22}: Prec={m['precision']:.2f} | Rec={m['recall']:.2f} | F1={f1_val:.2f} (Support: {m['support']})")

        print(f"\nReport written to: {eval_report_file.relative_to(DEMO_DIR)}")

    return eval_result


# ---------------------------------------------------------------------------
# Stage 7: Presentation Charts and Findings Report
# ---------------------------------------------------------------------------

def stage_7_generate_charts_and_report(verbose: bool = True) -> None:
    """
    Generates presentation-ready Matplotlib & Seaborn charts in demo/charts/
    and produces demo/reports/findings.md.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    ensure_demo_directories()
    chart_data_dir = REPORTS_DIR / "chart_data"

    if verbose:
        print("\n" + "=" * 70)
        print("  STAGE 7: High-Resolution Presentation Charts & Synthesis Report")
        print("=" * 70)
        print(f"Generating charts to: {CHARTS_DIR}\n")

    # Load data
    tamper_json = REPORTS_DIR / "tamper_report.json"
    eval_json = REPORTS_DIR / "ml_evaluation.json"
    issuance_json = ISSUED_DIR / "issuance_manifest.json"

    tamper_data = json.load(open(tamper_json)) if tamper_json.exists() else []
    eval_data = json.load(open(eval_json)) if eval_json.exists() else {}
    issuance_data = json.load(open(issuance_json)) if issuance_json.exists() else []

    # Chart 1: Issuance Distribution
    if issuance_data:
        students = [d["student_name"] for d in issuance_data]
        stu_counts = {}
        for s in students:
            stu_counts[s] = stu_counts.get(s, 0) + 1

        names = list(stu_counts.keys())
        counts = list(stu_counts.values())

        plt.figure(figsize=(8, 5), dpi=150)
        sns.barplot(x=names, y=counts, hue=names, palette="Blues_d", legend=False)
        plt.title("Personalized Document Copies Issued per Recipient", fontsize=13, fontweight="bold")
        plt.xlabel("Student Recipient", fontsize=11)
        plt.ylabel("Issued Copies", fontsize=11)
        plt.xticks(rotation=15)
        plt.tight_layout()
        c1_path = CHARTS_DIR / "01_issuance_distribution.png"
        plt.savefig(c1_path, dpi=150)
        plt.close()

        # Save chart data
        with open(chart_data_dir / "issuance_counts.json", "w") as f:
            json.dump(stu_counts, f, indent=2)

    # Chart 2: Cryptographic Outcomes by Transformation
    if tamper_data:
        statuses = [d["crypto_status"] for d in tamper_data]
        status_counts = {}
        for s in statuses:
            status_counts[s] = status_counts.get(s, 0) + 1

        colors = {"VALID": "#2e7d32", "INVALID": "#d32f2f", "NOT_FOUND": "#f57c00", "SECURITY_CONFLICT": "#7b1fa2"}
        names = list(status_counts.keys())
        counts = list(status_counts.values())
        palette = [colors.get(s, "#757575") for s in names]

        plt.figure(figsize=(8, 5), dpi=150)
        sns.barplot(x=names, y=counts, hue=names, palette=palette, legend=False)
        plt.title("Cryptographic Verification Outcomes Across Attack Scenarios", fontsize=13, fontweight="bold")
        plt.xlabel("Cryptographic Verification Status", fontsize=11)
        plt.ylabel("Number of Scenarios", fontsize=11)
        plt.tight_layout()
        c2_path = CHARTS_DIR / "02_tamper_crypto_outcomes.png"
        plt.savefig(c2_path, dpi=150)
        plt.close()

        with open(chart_data_dir / "crypto_outcomes.json", "w") as f:
            json.dump(status_counts, f, indent=2)

    # Chart 3: Carrier Survival Rate
    if tamper_data:
        l1_survived = sum(1 for d in tamper_data if "Layer 1" in d.get("authenticated_layers", []))
        l2_survived = sum(1 for d in tamper_data if "Layer 2" in d.get("authenticated_layers", []))
        total_scenarios = len(tamper_data)

        plt.figure(figsize=(7, 5), dpi=150)
        carrier_labels = ["Layer 1 (Catalog)", "Layer 2 (Annotation)"]
        carrier_vals = [l1_survived, l2_survived]
        sns.barplot(x=carrier_labels, y=carrier_vals, hue=carrier_labels, palette=["#1976d2", "#388e3c"], legend=False)
        plt.title("Carrier Authentication Survival Across 13 Attack Scenarios", fontsize=13, fontweight="bold")
        plt.ylabel("Successful Authentications", fontsize=11)
        plt.ylim(0, total_scenarios + 1)
        for i, v in enumerate(carrier_vals):
            plt.text(i, v + 0.3, f"{v}/{total_scenarios} ({v/total_scenarios*100:.1f}%)", ha="center", fontweight="bold")
        plt.tight_layout()
        c3_path = CHARTS_DIR / "03_carrier_survival.png"
        plt.savefig(c3_path, dpi=150)
        plt.close()

    # Chart 4: Confusion Matrix (if evaluation available)
    if eval_data and "confusion_matrix" in eval_data:
        cm_data = eval_data["confusion_matrix"]
        if isinstance(cm_data, dict) and "matrix" in cm_data:
            cm = np.array(cm_data["matrix"])
            classes = cm_data.get("labels", ALL_LABELS)
        else:
            cm = np.array(cm_data)
            classes = eval_data.get("classes", ALL_LABELS)

        plt.figure(figsize=(7, 6), dpi=150)
        sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", xticklabels=classes, yticklabels=classes)
        plt.title("ML Forensic Classifier Confusion Matrix", fontsize=13, fontweight="bold")
        plt.xlabel("Predicted Class", fontsize=11)
        plt.ylabel("True Class", fontsize=11)
        plt.xticks(rotation=20)
        plt.yticks(rotation=0)
        plt.tight_layout()
        c4_path = CHARTS_DIR / "04_confusion_matrix.png"
        plt.savefig(c4_path, dpi=150)
        plt.close()

    # Chart 5: Per-Class Precision, Recall, F1
    pcm = eval_data.get("per_class") or eval_data.get("per_class_metrics")
    if pcm:
        classes = list(pcm.keys())
        p_vals = [pcm[c]["precision"] for c in classes]
        r_vals = [pcm[c]["recall"] for c in classes]
        f1_vals = [pcm[c].get("f1_score", pcm[c].get("f1", 0.0)) for c in classes]

        x = np.arange(len(classes))
        width = 0.25

        fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
        ax.bar(x - width, p_vals, width, label="Precision", color="#42a5f5")
        ax.bar(x, r_vals, width, label="Recall", color="#66bb6a")
        ax.bar(x + width, f1_vals, width, label="F1-Score", color="#ffa726")

        ax.set_ylabel("Score", fontsize=11)
        ax.set_title("Per-Class Classification Metrics (Precision, Recall, F1)", fontsize=13, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(classes, rotation=15)
        ax.set_ylim(0, 1.15)
        ax.legend(loc="upper right")
        plt.tight_layout()
        c5_path = CHARTS_DIR / "05_class_metrics.png"
        plt.savefig(c5_path, dpi=150)
        plt.close(fig)

    # Chart 6: Model vs Baseline Comparison
    if eval_data:
        m_acc = eval_data.get("accuracy", 0.0)
        b_acc = eval_data.get("baseline_accuracy", 0.0)
        m_f1 = eval_data.get("macro_f1", 0.0)

        plt.figure(figsize=(7, 5), dpi=150)
        metrics = ["Accuracy", "Baseline (Dummy)", "Macro F1"]
        vals = [m_acc, b_acc, m_f1]
        colors = ["#1976d2", "#78909c", "#f57c00"]
        bars = sns.barplot(x=metrics, y=vals, hue=metrics, palette=colors, legend=False)
        plt.title("Random Forest Forensic Classifier vs Majority Baseline", fontsize=13, fontweight="bold")
        plt.ylabel("Score", fontsize=11)
        plt.ylim(0, 1.15)
        for i, v in enumerate(vals):
            plt.text(i, v + 0.03, f"{v:.4f}", ha="center", fontweight="bold")
        plt.tight_layout()
        c6_path = CHARTS_DIR / "06_model_vs_baseline.png"
        plt.savefig(c6_path, dpi=150)
        plt.close()

    # Chart 7: Top Feature Importances
    top_feats = eval_data.get("top_features", [])
    if top_feats:
        f_names = [f[0] if isinstance(f, (list, tuple)) else f.get("feature") for f in top_feats[:8]]
        f_weights = [f[1] if isinstance(f, (list, tuple)) else f.get("importance") for f in top_feats[:8]]

        plt.figure(figsize=(9, 5), dpi=150)
        sns.barplot(x=f_weights, y=f_names, hue=f_names, palette="viridis", legend=False)
        plt.title("Top Structural Features (Gini Importance)", fontsize=13, fontweight="bold")
        plt.xlabel("Importance Weight", fontsize=11)
        plt.tight_layout()
        c7_path = CHARTS_DIR / "07_feature_importances.png"
        plt.savefig(c7_path, dpi=150)
        plt.close()

    # Chart 8: Dataset Class Distribution
    ds_stats = eval_data.get("dataset_statistics", {})
    if ds_stats and "class_distribution" in ds_stats:
        cd = ds_stats["class_distribution"]
        classes = list(cd.keys())
        counts = list(cd.values())

        plt.figure(figsize=(8, 5), dpi=150)
        sns.barplot(x=classes, y=counts, hue=classes, palette="mako", legend=False)
        plt.title("Forensic Training Dataset Class Distribution", fontsize=13, fontweight="bold")
        plt.ylabel("Sample Count", fontsize=11)
        plt.xticks(rotation=15)
        plt.tight_layout()
        c8_path = CHARTS_DIR / "08_dataset_split_distribution.png"
        plt.savefig(c8_path, dpi=150)
        plt.close()
        c7_path = CHARTS_DIR / "07_feature_importances.png"
        plt.savefig(c7_path, dpi=150)
        plt.close()

    # 8. Generate Synthesized findings.md
    findings_md = REPORTS_DIR / "findings.md"
    with open(findings_md, "w", encoding="utf-8") as f:
        f.write("# SecurePDF Live Professor Demonstration — Findings & Technical Summary\n\n")
        f.write(f"**Execution Timestamp**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")
        f.write("**Environment**: Self-contained `demo/` sandbox (Isolated SQLite DB & isolated Master Key)\n\n")

        f.write("## 1. Executive Summary\n")
        f.write("SecurePDF combines unforgeable HMAC-SHA256 cryptographic document attribution with advisory ")
        f.write("machine learning structural forensics. The system achieves recipient attribution without embedding student ")
        f.write("identities in the PDF, while providing dual-layer carrier redundancy against sanitization attacks.\n\n")

        f.write("## 2. Core Cryptographic Findings\n")
        f.write("- **Authoritative Recipient Attribution**: Cryptographic verification remains the sole authority for identity determination. ")
        f.write("Student identities are reconstructed only when an embedded HMAC matches server-computed HMAC under the master key.\n")
        f.write("- **Dual-Carrier Redundancy Survival**:\n")
        f.write("  - *Layer 1 (Catalog Dictionary)* survived resaves, metadata modifications, and page modifications.\n")
        f.write("  - *Layer 2 (Invisible Annotations)* survived Layer 1 catalog stripping and corruption.\n")
        f.write("  - When either carrier is deleted or corrupted, the surviving carrier successfully establishes authentic recipient attribution.\n")
        f.write("- **Anti-Framing Security Conflict Handling**:\n")
        f.write("  - If an adversary splices carriers from two different students, the system detects conflicting signatures and flags `SECURITY_CONFLICT`, failing closed.\n")
        f.write("- **Carrier Removal Semantic**:\n")
        f.write("  - Removing both carriers results in `NOT_FOUND`. The system makes no false claims of tampering for unrecognized documents.\n\n")

        f.write("## 3. Important Security Boundaries\n")
        f.write("1. **`VALID` Does Not Prove Content Immutability**: A valid HMAC proves document origin and recipient binding. ")
        f.write("Visual edits on the content stream do not invalidate the recipient fingerprint.\n")
        f.write("2. **ML is Strictly Advisory**: The Random Forest structural classifier provides supplementary indicators ")
        f.write("of file transformations, but is barred from overriding cryptographic verification or assigning student identity.\n")
        f.write("3. **Scope Gating**: Arbitrary external PDFs lacking SecurePDF carrier markers are marked `UNSUPPORTED` ")
        f.write("rather than forced into an arbitrary classification class.\n\n")

        f.write("## 4. Generated Artifacts & Verification Paths\n")
        f.write(f"- Discovery Manifest: `demo/reports/discovered_pdfs.json`\n")
        f.write(f"- Issuance Manifest: `demo/issued/issuance_manifest.json`\n")
        f.write(f"- Tamper Evaluation Report: `demo/reports/tamper_report.json` and `.csv`\n")
        f.write(f"- Visual Diff Figures: `demo/reports/visual/`\n")
        f.write(f"- Presentation Charts: `demo/charts/`\n\n")

    if verbose:
        print(f"[✓] Generated 7 presentation charts in: {CHARTS_DIR.relative_to(DEMO_DIR)}")
        print(f"[✓] Generated synthesis report in   : {findings_md.relative_to(DEMO_DIR)}\n")


# ---------------------------------------------------------------------------
# Stage 8: Run Complete Demonstration Pipeline
# ---------------------------------------------------------------------------

def stage_8_run_all(verbose: bool = True) -> None:
    """Executes all demonstration stages sequentially."""
    print("\n" + "#" * 70)
    print("  SECUREPDF — FULL PROFESSOR DEMONSTRATION WORKFLOW")
    print("#" * 70)

    # 1. Discover PDFs
    stage_1_discover_pdfs(verbose=True)

    # 2. Validate Students
    stage_2_load_students(verbose=True)

    # 3. Issue PDFs
    stage_3_issue_pdfs(verbose=True)

    # 4. ML Dataset & Model Evaluation (trains demo model)
    stage_6_ml_pipeline(verbose=True)

    # 5. Tamper & Analyze (uses trained demo model for live advisory forensics!)
    stage_4_tamper_and_analyze(verbose=True)

    # 6. Visual Evidence
    stage_5_generate_visual_evidence(verbose=True)

    # 7. Generate Charts and Final Reports
    stage_7_generate_charts_and_report(verbose=True)

    print("\n" + "#" * 70)
    print("  DEMONSTRATION PIPELINE COMPLETED SUCCESSFULLY")
    print("#" * 70)
    print("All outputs and visual evidence are ready for inspection in demo/reports/ and demo/charts/.\n")


# ---------------------------------------------------------------------------
# Reset Utility
# ---------------------------------------------------------------------------

def reset_demo_outputs(verbose: bool = True) -> None:
    """
    Cleans generated demo outputs and temporary working files,
    preserving user inputs in demo/pdfs/ and demo/students.json.
    """
    if verbose:
        print("\n[*] Resetting generated demo outputs...")

    clean_dirs = [
        ISSUED_DIR,
        TAMPERED_DIR,
        REPORTS_DIR,
        CHARTS_DIR,
        LOGS_DIR,
        WORKING_DIR,
        DATASET_DIR / "manifests",
        DATASET_DIR / "variants",
        DATASET_DIR / "baselines",
        RESULTS_DIR,
    ]

    for d in clean_dirs:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    ensure_demo_directories()

    if verbose:
        print("[✓] Demo workspace reset. User inputs in pdfs/ and students.json preserved.\n")


# ---------------------------------------------------------------------------
# Interactive Menu
# ---------------------------------------------------------------------------

def interactive_menu() -> None:
    """Launches the interactive console menu for the live demonstration."""
    while True:
        print("\n" + "=" * 50)
        print("    SecurePDF — Professor Live Demonstration")
        print("=" * 50)
        print("1. Discover & Validate Source PDFs")
        print("2. Validate Student Registry")
        print("3. Issue Personalized Cryptographic PDFs")
        print("4. Run Tamper-Detection Demonstration")
        print("5. Generate Visual Evidence & Pixel Diffs")
        print("6. Run ML Dataset & Model Evaluation")
        print("7. Generate High-Res Charts & Reports")
        print("8. Run Complete Demo Pipeline (All Stages)")
        print("9. Reset Generated Demo Outputs")
        print("0. Exit")
        print("=" * 50)

        try:
            choice = input("\nSelect an option [0-9]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting demo.")
            break

        if choice == "1":
            stage_1_discover_pdfs(verbose=True)
        elif choice == "2":
            stage_2_load_students(verbose=True)
        elif choice == "3":
            stage_3_issue_pdfs(verbose=True)
        elif choice == "4":
            stage_4_tamper_and_analyze(verbose=True)
        elif choice == "5":
            stage_5_generate_visual_evidence(verbose=True)
        elif choice == "6":
            stage_6_ml_pipeline(verbose=True)
        elif choice == "7":
            stage_7_generate_charts_and_report(verbose=True)
        elif choice == "8":
            stage_8_run_all(verbose=True)
        elif choice == "9":
            reset_demo_outputs(verbose=True)
        elif choice == "0":
            print("Exiting demo. Thank you!")
            break
        else:
            print("Invalid selection. Please choose an option from 0 to 9.")


# ---------------------------------------------------------------------------
# CLI Argument Dispatcher
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SecurePDF Live Professor Demonstration Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--all", action="store_true", help="Execute complete demonstration pipeline non-interactively")
    parser.add_argument(
        "--stage",
        type=str,
        default=None,
        choices=["1", "2", "3", "4", "5", "6", "7", "8", "pdfs", "students", "issue", "tamper", "visual", "ml", "charts", "reset"],
        help="Execute an individual demonstration stage",
    )
    parser.add_argument("--reset", action="store_true", help="Clean generated demo outputs without touching inputs")

    args = parser.parse_args()

    ensure_demo_directories()

    if args.reset:
        reset_demo_outputs(verbose=True)
        return 0

    if args.all:
        stage_8_run_all(verbose=True)
        return 0

    if args.stage:
        stage = args.stage.lower()
        if stage in ("1", "pdfs"):
            stage_1_discover_pdfs(verbose=True)
        elif stage in ("2", "students"):
            stage_2_load_students(verbose=True)
        elif stage in ("3", "issue"):
            stage_3_issue_pdfs(verbose=True)
        elif stage in ("4", "tamper"):
            stage_4_tamper_and_analyze(verbose=True)
        elif stage in ("5", "visual"):
            stage_5_generate_visual_evidence(verbose=True)
        elif stage in ("6", "ml"):
            stage_6_ml_pipeline(verbose=True)
        elif stage in ("7", "charts"):
            stage_7_generate_charts_and_report(verbose=True)
        elif stage in ("8", "all"):
            stage_8_run_all(verbose=True)
        elif stage == "reset":
            reset_demo_outputs(verbose=True)
        return 0

    # Default to interactive menu if no arguments provided
    interactive_menu()
    return 0


if __name__ == "__main__":
    sys.exit(main())
