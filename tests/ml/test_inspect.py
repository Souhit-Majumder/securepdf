"""
Tests for the real-world PDF dataset inspection module (app/ml/inspect.py)
and the corresponding CLI command (ml inspect-dataset).

Coverage:
- Empty input directory → zero records, well-formed output files.
- Mixed valid/invalid/duplicate PDFs → correct categorisation.
- Duplicate detection by SHA-256.
- Feature schema alignment (features.csv columns match FEATURE_SCHEMA).
- Extraction report keys and types.
- Feature summary statistics present for each schema field.
- Overwrite protection (FileExistsError when overwrite=False).
- max_pdfs cap is respected.
- Non-PDF files in input directory are silently ignored.
- CLI integration via app.cli.main.main.
- Source PDFs are NOT modified during inspection.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import fitz
import pytest

from app.ml.feature_extractor import FEATURE_SCHEMA
from app.ml.inspect import inspect_dataset


# ─────────────────────────── helpers ────────────────────────────────────────


def _make_pdf(path: Path, text: str = "Hello") -> Path:
    """Create a minimal, syntactically valid PDF using PyMuPDF."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text)
    doc.save(str(path))
    doc.close()
    return path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _read_manifest(out_dir: Path) -> list[dict]:
    with open(out_dir / "manifest.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_features(out_dir: Path) -> list[dict]:
    with open(out_dir / "features.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_report(out_dir: Path) -> dict:
    with open(out_dir / "extraction_report.json", encoding="utf-8") as f:
        return json.load(f)


def _read_summary(out_dir: Path) -> dict:
    with open(out_dir / "feature_summary.json", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────── tests ──────────────────────────────────────────


class TestInspectDatasetEmpty:
    def test_empty_directory(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        out = tmp_path / "out"

        report = inspect_dataset(src, out)

        assert report["total_files_found"] == 0
        assert report["successfully_processed"] == 0

        manifest = _read_manifest(out)
        assert manifest == []

        features = _read_features(out)
        assert features == []

        summary = _read_summary(out)
        assert summary["n_documents"] == 0
        assert summary["features"] == {}

    def test_missing_input_dir_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            inspect_dataset(tmp_path / "nonexistent", tmp_path / "out")

    def test_input_path_not_a_dir_raises(self, tmp_path: Path):
        not_a_dir = tmp_path / "file.txt"
        not_a_dir.write_text("hello")
        with pytest.raises(NotADirectoryError):
            inspect_dataset(not_a_dir, tmp_path / "out")


class TestInspectDatasetValidPDFs:
    def test_three_valid_pdfs(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        for i in range(3):
            _make_pdf(src / f"{i:03d}.pdf", text=f"Doc {i}")

        out = tmp_path / "out"
        report = inspect_dataset(src, out)

        assert report["total_files_found"] == 3
        assert report["successfully_processed"] == 3
        assert report["failed"] == 0
        assert report["duplicates"] == 0
        assert report["skipped"] == 0

        manifest = _read_manifest(out)
        assert len(manifest) == 3
        assert all(row["status"] == "ok" for row in manifest)

    def test_features_csv_has_correct_columns(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "a.pdf")

        out = tmp_path / "out"
        inspect_dataset(src, out)

        features_rows = _read_features(out)
        assert len(features_rows) == 1
        header = set(features_rows[0].keys())
        expected = {"filename", "sha256"} | set(FEATURE_SCHEMA)
        assert expected == header, f"Columns mismatch: {header ^ expected}"

    def test_feature_values_are_numeric(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "a.pdf")

        out = tmp_path / "out"
        inspect_dataset(src, out)

        row = _read_features(out)[0]
        for feat in FEATURE_SCHEMA:
            float(row[feat])  # should not raise

    def test_features_csv_has_no_label_column(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "a.pdf")

        out = tmp_path / "out"
        inspect_dataset(src, out)

        row = _read_features(out)[0]
        assert "label" not in row, "Real-world PDFs must not receive synthetic labels"

    def test_feature_summary_statistics(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        for i in range(3):
            _make_pdf(src / f"{i:03d}.pdf", text=f"Doc {i}")

        out = tmp_path / "out"
        inspect_dataset(src, out)

        summary = _read_summary(out)
        assert summary["n_documents"] == 3
        for feat in FEATURE_SCHEMA:
            assert feat in summary["features"], f"Missing feature '{feat}' in summary"
            s = summary["features"][feat]
            assert "min" in s and "max" in s and "mean" in s
            assert "median" in s and "stdev" in s
            assert "zero_count" in s and "nonzero_count" in s


class TestInspectDatasetDuplicates:
    def test_duplicate_detected_by_sha256(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        # Use names that sort deterministically: "aaa.pdf" before "zzz.pdf"
        original = _make_pdf(src / "aaa.pdf", text="Unique content")

        # Exact byte copy — same SHA-256 → should be flagged as duplicate
        dup = src / "zzz.pdf"
        shutil.copy2(original, dup)

        out = tmp_path / "out"
        report = inspect_dataset(src, out)

        assert report["total_files_found"] == 2
        assert report["successfully_processed"] == 1  # only original succeeds
        assert report["duplicates"] == 1

        manifest = _read_manifest(out)
        dup_row = next(r for r in manifest if r["filename"] == "zzz.pdf")
        assert dup_row["status"] == "duplicate"
        assert dup_row["duplicate_of"] == "aaa.pdf"

    def test_duplicate_not_in_features_csv(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        # "aaa" sorts before "zzz" so aaa is always processed first
        orig = _make_pdf(src / "aaa.pdf")
        shutil.copy2(orig, src / "zzz.pdf")

        out = tmp_path / "out"
        inspect_dataset(src, out)

        rows = _read_features(out)
        filenames = [r["filename"] for r in rows]
        assert "aaa.pdf" in filenames
        assert "zzz.pdf" not in filenames


class TestInspectDatasetBadFiles:
    def test_non_pdf_files_are_ignored(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "real.pdf")
        (src / "readme.txt").write_text("not a pdf")
        (src / "data.csv").write_bytes(b"a,b,c")

        out = tmp_path / "out"
        report = inspect_dataset(src, out)

        # Only the .pdf file is counted
        assert report["total_files_found"] == 1
        assert report["successfully_processed"] == 1

    def test_corrupt_pdf_marked_failed(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        bad = src / "corrupt.pdf"
        bad.write_bytes(b"%PDF garbage bytes not a real pdf \x00\x01\x02")

        out = tmp_path / "out"
        report = inspect_dataset(src, out)

        manifest = _read_manifest(out)
        assert manifest[0]["status"] == "failed"
        assert report["failed"] == 1
        assert report["successfully_processed"] == 0

    def test_empty_file_marked_skipped(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        empty = src / "empty.pdf"
        empty.write_bytes(b"")

        out = tmp_path / "out"
        report = inspect_dataset(src, out)

        manifest = _read_manifest(out)
        assert manifest[0]["status"] == "skipped"
        assert report["skipped"] == 1

    def test_mixed_valid_and_invalid(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "good.pdf")
        (src / "bad.pdf").write_bytes(b"%PDF garbage")
        (src / "empty.pdf").write_bytes(b"")

        out = tmp_path / "out"
        report = inspect_dataset(src, out)

        assert report["total_files_found"] == 3
        assert report["successfully_processed"] == 1
        assert report["failed"] == 1
        assert report["skipped"] == 1


class TestInspectDatasetOutputFiles:
    def test_all_four_output_files_created(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "a.pdf")

        out = tmp_path / "out"
        inspect_dataset(src, out)

        assert (out / "manifest.csv").exists()
        assert (out / "features.csv").exists()
        assert (out / "extraction_report.json").exists()
        assert (out / "feature_summary.json").exists()

    def test_report_note_confirms_no_labels(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "a.pdf")

        out = tmp_path / "out"
        inspect_dataset(src, out)

        report = _read_report(out)
        assert "note" in report
        assert "NO" in report["note"].upper()

    def test_report_feature_schema_matches(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "a.pdf")

        out = tmp_path / "out"
        inspect_dataset(src, out)

        report = _read_report(out)
        assert report["feature_schema"] == FEATURE_SCHEMA
        assert report["feature_count"] == len(FEATURE_SCHEMA)

    def test_manifest_sha256_matches_file(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        pdf = _make_pdf(src / "doc.pdf")

        out = tmp_path / "out"
        inspect_dataset(src, out)

        expected_sha = _sha256(pdf)
        manifest = _read_manifest(out)
        assert manifest[0]["sha256"] == expected_sha


class TestInspectDatasetOverwrite:
    def test_overwrite_false_raises_if_manifest_exists(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "a.pdf")
        out = tmp_path / "out"

        inspect_dataset(src, out, overwrite=True)  # first run

        with pytest.raises(FileExistsError, match="manifest"):
            inspect_dataset(src, out, overwrite=False)  # second run should fail

    def test_overwrite_true_replaces_existing(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "a.pdf")
        out = tmp_path / "out"

        inspect_dataset(src, out, overwrite=True)
        inspect_dataset(src, out, overwrite=True)  # should not raise

        report = _read_report(out)
        assert report["successfully_processed"] == 1


class TestInspectDatasetMaxPdfs:
    def test_max_pdfs_caps_processing(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        for i in range(5):
            _make_pdf(src / f"{i:03d}.pdf", text=f"Doc {i}")

        out = tmp_path / "out"
        report = inspect_dataset(src, out, max_pdfs=3)

        assert report["total_files_found"] == 3

    def test_max_pdfs_zero_processes_none(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "a.pdf")

        out = tmp_path / "out"
        report = inspect_dataset(src, out, max_pdfs=0)

        assert report["total_files_found"] == 0
        assert report["successfully_processed"] == 0


class TestInspectDatasetSourceUnmodified:
    def test_source_pdfs_are_not_modified(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        pdf = _make_pdf(src / "doc.pdf")

        before_sha = _sha256(pdf)
        before_size = pdf.stat().st_size
        before_mtime = pdf.stat().st_mtime

        out = tmp_path / "out"
        inspect_dataset(src, out)

        after_sha = _sha256(pdf)
        after_size = pdf.stat().st_size
        after_mtime = pdf.stat().st_mtime

        assert before_sha == after_sha, "SHA-256 changed — source PDF was modified!"
        assert before_size == after_size, "File size changed — source PDF was modified!"
        assert before_mtime == after_mtime, "mtime changed — source PDF was written!"


class TestInspectDatasetCLI:
    """Integration tests through the CLI entry point."""

    def test_cli_inspect_dataset_basic(self, tmp_path: Path):
        from app.cli.main import main

        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "a.pdf")
        _make_pdf(src / "b.pdf", text="B document")
        out = tmp_path / "out"

        ret = main([
            "ml", "inspect-dataset",
            "--input", str(src),
            "--output", str(out),
        ])
        assert ret == 0
        assert (out / "manifest.csv").exists()
        assert (out / "features.csv").exists()

    def test_cli_inspect_dataset_bad_input_returns_nonzero(self, tmp_path: Path):
        from app.cli.main import main

        ret = main([
            "ml", "inspect-dataset",
            "--input", str(tmp_path / "nonexistent"),
            "--output", str(tmp_path / "out"),
        ])
        assert ret != 0

    def test_cli_inspect_dataset_overwrite_flag(self, tmp_path: Path):
        from app.cli.main import main

        src = tmp_path / "src"
        src.mkdir()
        _make_pdf(src / "a.pdf")
        out = tmp_path / "out"

        ret1 = main(["ml", "inspect-dataset", "--input", str(src), "--output", str(out)])
        assert ret1 == 0

        # Without --overwrite → should fail (nonzero exit)
        ret2 = main(["ml", "inspect-dataset", "--input", str(src), "--output", str(out)])
        assert ret2 != 0

        # With --overwrite → should succeed
        ret3 = main([
            "ml", "inspect-dataset",
            "--input", str(src),
            "--output", str(out),
            "--overwrite",
        ])
        assert ret3 == 0

    def test_cli_inspect_dataset_max_pdfs_arg(self, tmp_path: Path):
        from app.cli.main import main

        src = tmp_path / "src"
        src.mkdir()
        for i in range(5):
            _make_pdf(src / f"{i:03d}.pdf", text=f"Doc {i}")
        out = tmp_path / "out"

        ret = main([
            "ml", "inspect-dataset",
            "--input", str(src),
            "--output", str(out),
            "--max-pdfs", "2",
        ])
        assert ret == 0

        report = _read_report(out)
        assert report["total_files_found"] == 2
