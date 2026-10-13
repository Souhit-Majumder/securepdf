"""
Tests for Reproducible Forensic Dataset Generation.
Verifies:
- Controlled transformations across all 4 target classes.
- Manifest generation and relative path safety (no PII or secrets).
- Strict source-grouped train/test split isolation.
"""
import json
from pathlib import Path
import fitz
import pytest

from app.ml.dataset import (
    CLASS_LABELS,
    build_dataset,
    build_forensic_dataset,
    create_synthetic_source_documents,
)


def test_create_synthetic_source_documents(tmp_path: Path):
    source_dir = tmp_path / "sources"
    docs = create_synthetic_source_documents(source_dir, count=4)
    assert len(docs) == 4
    for p in docs:
        assert p.exists()
        assert p.suffix == ".pdf"
        assert p.stat().st_size > 0


def test_build_forensic_dataset_and_source_isolation(tmp_path: Path):
    source_dir = tmp_path / "sources"
    output_dir = tmp_path / "dataset"
    _ = create_synthetic_source_documents(source_dir, count=5)

    manifest = build_forensic_dataset(
        source_dir=source_dir,
        output_dir=output_dir,
        random_seed=123,
        split_ratio=0.6,
    )

    manifest_file = output_dir / "manifest.json"
    assert manifest_file.exists()

    with open(manifest_file, encoding="utf-8") as f:
        data = json.load(f)

    # 1. Structure and metadata
    assert "samples" in data
    assert "train_sources" in data
    assert "test_sources" in data
    assert "class_distribution" in data

    train_sources = set(data["train_sources"])
    test_sources = set(data["test_sources"])

    # 2. Strict source-grouped isolation: NO overlap
    assert len(train_sources) > 0
    assert len(test_sources) > 0
    assert train_sources.isdisjoint(test_sources), "Train and test source sets must be strictly disjoint!"

    # 3. Every sample must match its source's assigned split
    samples = data["samples"]
    assert len(samples) > 0

    seen_labels = set()
    for s in samples:
        src = s["source_document"]
        split = s["split"]
        label = s["label"]
        seen_labels.add(label)

        if src in train_sources:
            assert split == "train", f"Sample from train source {src} found in split {split}"
        elif src in test_sources:
            assert split == "test", f"Sample from test source {src} found in split {split}"
        else:
            pytest.fail(f"Sample source {src} not in train or test sources")

        # Ensure no absolute paths leaked
        rel_path = s["relative_path"]
        assert not rel_path.startswith("/"), f"Absolute path found in manifest: {rel_path}"
        assert "\\" not in rel_path
        assert (output_dir / rel_path).exists(), f"Sample file not found at relative path: {rel_path}"

        # Feature extraction status
        assert s["feature_extraction_status"] == "success"
        assert "features" in s
        assert len(s["features"]) == 23

    # 4. Verify all defined classes are represented
    for expected_label in CLASS_LABELS:
        assert expected_label in seen_labels, f"Expected label {expected_label} missing from dataset"


def test_raw_safedocs_inputs_require_baseline_generation(tmp_path: Path):
    source_dir = tmp_path / "raw_sources"
    source_dir.mkdir()
    # Create raw, un-fingerprinted PDF (e.g. SAFEDOCS sample)
    raw_pdf = source_dir / "raw_001.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Raw SAFEDOCS text without carriers")
    doc.save(str(raw_pdf))
    doc.close()

    out_dir = tmp_path / "dataset_out"

    # 1. With reject_unfingerprinted=True, raises ValueError
    with pytest.raises(ValueError, match="lacks SecurePDF carrier markers"):
        build_dataset([raw_pdf], out_dir, reject_unfingerprinted=True)

    # 2. With default behavior, generates baseline and records raw source as unlabeled
    manifest = build_dataset([raw_pdf], out_dir, reject_unfingerprinted=False)
    assert len(manifest["unlabeled_sources"]) == 1
    raw_meta = manifest["unlabeled_sources"][0]
    assert raw_meta["source_id"] == "raw_001"
    assert raw_meta["label"] is None
    assert raw_meta["source_sha256"] != ""

    # Check generated baselines directory
    baseline_pdf = out_dir / "baselines" / "raw_001_baseline.pdf"
    assert baseline_pdf.exists()

    # Check that all samples originate from baseline and have valid hashes
    samples = manifest["samples"]
    assert len(samples) > 0
    for s in samples:
        assert s["baseline_id"] == "raw_001_baseline"
        assert s["source_sha256"] == raw_meta["source_sha256"]
        assert s["output_sha256"] != ""
        assert s["label"] in CLASS_LABELS

