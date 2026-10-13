"""
Tests for the SAFEDOCS transformation experiment pipeline (app/ml/experiment.py).

Verifies:
- Source PDF preservation: original files are read-only and never modified (SHA-256 match).
- Unlabeled source invariant: raw source records have label=None.
- Justified variant labels: variants receive labels corresponding to their transformation history.
- Source-grouped partitioning: all variants from a source document share the exact same split.
- Cryptographic tracking: dual-track carrier and HMAC status logged per variant.
- Output artifacts: CSV manifest, JSON manifest, summary report, and variant PDFs generated.
- Overwrite protection: FileExistsError raised when overwrite=False.
- CLI integration: ml experiment subcommand functions correctly.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import fitz
import pytest

from app.ml.dataset import ALL_LABELS
from app.ml.experiment import run_safedocs_experiment


def _create_test_pdf(path: Path, text: str = "Test SAFEDOCS content") -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), text)
    doc.save(str(path))
    doc.close()
    return path


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class TestSafedocsExperiment:
    def test_source_preservation_and_artifacts(self, tmp_path: Path):
        src_dir = tmp_path / "sources"
        src_dir.mkdir()
        src_file = _create_test_pdf(src_dir / "001.pdf", "Original Doc 1")

        before_sha = _file_sha256(src_file)
        before_size = src_file.stat().st_size

        out_dir = tmp_path / "exp_out"
        summary = run_safedocs_experiment(src_dir, out_dir, max_sources=1, seed=42)

        # 1. Source preservation
        after_sha = _file_sha256(src_file)
        after_size = src_file.stat().st_size
        assert before_sha == after_sha, "Source PDF was modified during experiment!"
        assert before_size == after_size, "Source PDF file size changed!"

        # 2. Output files created
        assert (out_dir / "experiment_manifest.csv").exists()
        assert (out_dir / "experiment_manifest.json").exists()
        assert (out_dir / "experiment_summary.json").exists()
        assert (out_dir / "variants").exists()

        # 3. Summary statistics
        assert summary["total_source_documents"] == 1
        assert summary["variant_count"] == 12  # 12 transformations
        assert summary["raw_unlabeled_source_count"] == 1
        assert summary["readable_variant_count"] == 12

    def test_unlabeled_sources_and_justified_variant_labels(self, tmp_path: Path):
        src_dir = tmp_path / "sources"
        src_dir.mkdir()
        _create_test_pdf(src_dir / "doc_a.pdf")

        out_dir = tmp_path / "exp_out"
        run_safedocs_experiment(src_dir, out_dir, max_sources=1, seed=42)

        with open(out_dir / "experiment_manifest.json", encoding="utf-8") as f:
            records = json.load(f)

        raw_records = [r for r in records if r["transformation"] == "untransformed_raw_source"]
        assert len(raw_records) == 1
        assert raw_records[0]["label"] is None, "Raw source must NOT have a synthetic label!"

        variant_records = [r for r in records if r["transformation"] != "untransformed_raw_source"]
        assert len(variant_records) == 12
        for r in variant_records:
            assert r["label"] in ALL_LABELS, f"Invalid label: {r['label']}"
            assert r["output_sha256"] != "", "Output SHA-256 missing"

    def test_source_grouped_partitioning(self, tmp_path: Path):
        src_dir = tmp_path / "sources"
        src_dir.mkdir()
        _create_test_pdf(src_dir / "doc_1.pdf")
        _create_test_pdf(src_dir / "doc_2.pdf")
        _create_test_pdf(src_dir / "doc_3.pdf")
        _create_test_pdf(src_dir / "doc_4.pdf")

        out_dir = tmp_path / "exp_out"
        summary = run_safedocs_experiment(
            src_dir, out_dir, max_sources=4, test_split_ratio=0.5, seed=42
        )

        with open(out_dir / "experiment_manifest.json", encoding="utf-8") as f:
            records = json.load(f)

        # Check that for each source_id, ALL records (raw and variants) have the same split
        splits_by_source: dict[str, set[str]] = {}
        for r in records:
            sid = r["source_id"]
            splits_by_source.setdefault(sid, set()).add(r["split"])

        for sid, splits in splits_by_source.items():
            assert len(splits) == 1, f"Source {sid} variants span multiple splits: {splits}"

        # Ensure both train and test splits exist
        assert len(summary["train_source_ids"]) > 0
        assert len(summary["test_source_ids"]) > 0

    def test_cryptographic_verification_tracking(self, tmp_path: Path):
        src_dir = tmp_path / "sources"
        src_dir.mkdir()
        _create_test_pdf(src_dir / "001.pdf")

        out_dir = tmp_path / "exp_out"
        summary = run_safedocs_experiment(src_dir, out_dir, max_sources=1, seed=42)

        # Verify tracking dictionaries exist in summary
        assert "crypto_status_by_transformation" in summary
        assert "carrier_retention_by_transformation" in summary

        crypto = summary["crypto_status_by_transformation"]
        # Baseline 'orig' should have VALID status
        assert "orig" in crypto
        assert crypto["orig"].get("VALID") == 1

        # Check carrier retention tracking
        retention = summary["carrier_retention_by_transformation"]
        assert "orig" in retention
        assert retention["orig"]["dual_present"] == 1

    def test_overwrite_protection(self, tmp_path: Path):
        src_dir = tmp_path / "sources"
        src_dir.mkdir()
        _create_test_pdf(src_dir / "001.pdf")

        out_dir = tmp_path / "exp_out"
        run_safedocs_experiment(src_dir, out_dir, max_sources=1, overwrite=True)

        with pytest.raises(FileExistsError):
            run_safedocs_experiment(src_dir, out_dir, max_sources=1, overwrite=False)

    def test_cli_experiment_subcommand(self, tmp_path: Path):
        from app.cli.main import main

        src_dir = tmp_path / "sources"
        src_dir.mkdir()
        _create_test_pdf(src_dir / "001.pdf")

        out_dir = tmp_path / "exp_out"
        ret = main([
            "ml", "experiment",
            "--source-dir", str(src_dir),
            "--output-dir", str(out_dir),
            "--max-sources", "1",
            "--seed", "42",
        ])
        assert ret == 0
        assert (out_dir / "experiment_summary.json").exists()

    def test_both_carriers_removed_or_invalidated_and_security_conflict(self, tmp_path: Path):
        """
        Evaluates fail-closed behavior when:
        1. Both carriers are deleted (status: NOT_FOUND)
        2. Both carriers are corrupted (status: INVALID)
        3. Carriers authenticate to conflicting identities (status: SECURITY_CONFLICT)
        """
        from app.database.database import init_db
        from app.database.repository import Repository
        from app.services.fingerprint_service import FingerprintService
        from app.services.verification_service import VerificationService
        from app.pdf.extract import extract_layer2

        db_path = tmp_path / "test.db"
        key_path = tmp_path / "master.key"
        init_db(db_path)
        repo = Repository(db_path=db_path)
        fp_svc = FingerprintService(repo=repo, key_path=key_path)
        ver_svc = VerificationService(repo=repo, key_path=key_path)

        src_pdf = _create_test_pdf(tmp_path / "base.pdf")
        repo.create_student("STU-1", "Student One")
        dist1_pdf = tmp_path / "dist1.pdf"
        fp_svc.fingerprint_pdf("STU-1", "DOC-1", str(src_pdf), str(dist1_pdf))

        # 1. Both carriers removed
        both_removed = tmp_path / "both_removed.pdf"
        d = fitz.open(str(dist1_pdf))
        d.xref_set_key(d.pdf_catalog(), "SPDFPayload", "null")
        for p in d:
            for a in p.annots():
                if (a.info or {}).get("title", "").startswith("SPDF"):
                    p.delete_annot(a)
        d.save(str(both_removed))
        d.close()

        res_removed = ver_svc.investigate_pdf(str(both_removed))
        assert res_removed["status"] == "NOT_FOUND"

        # 2. Both carriers corrupted
        both_corrupt = tmp_path / "both_corrupt.pdf"
        d = fitz.open(str(dist1_pdf))
        d.xref_set_key(d.pdf_catalog(), "SPDFPayload", "<535044462d56317c4a554e4b>")
        for p in d:
            for a in p.annots():
                info = a.info or {}
                if info.get("title", "").startswith("SPDF"):
                    info["content"] = "SPDF1|DOC-1|NONCE|CORRUPTED"
                    a.set_info(info)
                    a.update()
        d.save(str(both_corrupt))
        d.close()

        res_corrupt = ver_svc.investigate_pdf(str(both_corrupt))
        assert res_corrupt["status"] == "INVALID"

        # 3. Security conflict: L1 and L2 belong to different students
        repo.create_student("STU-2", "Student Two")
        dist2_pdf = tmp_path / "dist2.pdf"
        fp_svc.fingerprint_pdf("STU-2", "DOC-2", str(src_pdf), str(dist2_pdf))

        d2 = fitz.open(str(dist2_pdf))
        l2_stu2 = extract_layer2(d2)[0]
        d2.close()

        conflict_pdf = tmp_path / "conflict.pdf"
        d = fitz.open(str(dist1_pdf))
        for p in d:
            for a in p.annots():
                info = a.info or {}
                if info.get("title", "").startswith("SPDF"):
                    info["content"] = l2_stu2
                    a.set_info(info)
                    a.update()
        d.save(str(conflict_pdf))
        d.close()

        res_conflict = ver_svc.investigate_pdf(str(conflict_pdf))
        assert res_conflict["status"] == "SECURITY_CONFLICT"

