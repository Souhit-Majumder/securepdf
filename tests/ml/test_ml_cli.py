"""
Tests for ML and Forensic CLI Commands.
Verifies:
- CLI argument parsing and execution for 'ml dataset', 'ml train', 'ml evaluate'.
- Forensic 'analyze' command output and graceful behavior when model is absent.
"""
from pathlib import Path
import fitz
import pytest

from app.cli.main import main


def test_cli_ml_dataset_train_evaluate_workflow(tmp_path: Path, capsys):
    dataset_dir = tmp_path / "dataset"
    source_dir = dataset_dir / "sources"
    model_path = tmp_path / "model.joblib"
    manifest_path = dataset_dir / "manifest.json"

    # 1. ml dataset with synthetic source generation
    ret_ds = main([
        "ml", "dataset",
        "--source-dir", str(source_dir),
        "--output-dir", str(dataset_dir),
        "--generate-synthetic-sources", "5",
        "--seed", "42",
    ])
    assert ret_ds == 0
    assert manifest_path.exists()

    # 2. ml train
    ret_train = main([
        "ml", "train",
        "--manifest", str(manifest_path),
        "--output", str(model_path),
        "--seed", "42",
        "--n-estimators", "20",
    ])
    assert ret_train == 0
    assert model_path.exists()

    # 3. ml evaluate
    ret_eval = main([
        "ml", "evaluate",
        "--manifest", str(manifest_path),
        "--model", str(model_path),
    ])
    assert ret_eval == 0


def test_cli_analyze_command(tmp_path: Path, capsys):
    test_pdf = tmp_path / "leak.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Suspected leak document")
    doc.save(str(test_pdf))
    doc.close()

    # 1. Analyze without model present
    missing_model = tmp_path / "missing_model.joblib"
    ret = main(["analyze", str(test_pdf), "--model", str(missing_model)])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "FILE VALIDATION" in captured
    assert "CRYPTOGRAPHIC INTEGRITY & ATTRIBUTION" in captured
    assert "ML FORENSIC ASSESSMENT" in captured
    assert "UNAVAILABLE" in captured

    # 2. Analyze on non-existent file
    ret_missing = main(["analyze", str(tmp_path / "does_not_exist.pdf")])
    assert ret_missing == 1
