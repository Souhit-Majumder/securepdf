"""
Tests for Model Training, Evaluation, and Artifact Serialization.
Verifies:
- Training Random Forest + Dummy baseline on source-grouped dataset.
- Evaluation metrics computation (accuracy, per-class F1, confusion matrix).
- Artifact integrity and version validation.
- Handling of schema mismatches and invalid manifests.
"""
import json
from pathlib import Path
import joblib
import pytest

from app.ml.dataset import build_forensic_dataset, create_synthetic_source_documents
from app.ml.evaluate import EvaluationError, evaluate_model, format_evaluation_report
from app.ml.train import (
    MODEL_ARTIFACT_VERSION,
    TrainingError,
    load_dataset_from_manifest,
    train_model,
)


@pytest.fixture
def sample_manifest(tmp_path: Path) -> Path:
    source_dir = tmp_path / "sources"
    dataset_dir = tmp_path / "dataset"
    _ = create_synthetic_source_documents(source_dir, count=5)
    _ = build_forensic_dataset(
        source_dir=source_dir,
        output_dir=dataset_dir,
        random_seed=42,
        split_ratio=0.6,
    )
    return dataset_dir / "manifest.json"


def test_load_dataset_from_manifest(sample_manifest: Path):
    X_train, y_train, X_test, y_test, manifest = load_dataset_from_manifest(sample_manifest)
    assert len(X_train) > 0
    assert len(y_train) == len(X_train)
    assert len(X_test) > 0
    assert len(y_test) == len(X_test)
    assert X_train.shape[1] == 23
    assert X_test.shape[1] == 23


def test_train_model_success_and_artifact(sample_manifest: Path, tmp_path: Path):
    model_path = tmp_path / "model.joblib"
    summary = train_model(
        manifest_path=sample_manifest,
        model_output_path=model_path,
        random_seed=42,
        n_estimators=20,
    )

    assert summary["status"] == "SUCCESS"
    assert model_path.exists()
    assert summary["artifact_version"] == MODEL_ARTIFACT_VERSION
    assert summary["train_samples"] > 0
    assert summary["test_samples"] > 0
    assert 0.0 <= summary["train_accuracy"] <= 1.0

    # Load artifact and inspect structure
    artifact = joblib.load(str(model_path))
    assert artifact["artifact_version"] == MODEL_ARTIFACT_VERSION
    assert "model" in artifact
    assert "baseline_model" in artifact
    assert "feature_schema" in artifact
    assert len(artifact["classes"]) >= 2


def test_evaluate_model_and_report(sample_manifest: Path, tmp_path: Path):
    model_path = tmp_path / "model.joblib"
    _ = train_model(
        manifest_path=sample_manifest,
        model_output_path=model_path,
        random_seed=42,
        n_estimators=20,
    )

    results = evaluate_model(model_path, sample_manifest, use_test_split_only=True)
    assert "accuracy" in results
    assert "macro_f1" in results
    assert "per_class" in results
    assert "confusion_matrix" in results
    assert "limitations" in results
    assert len(results["limitations"]) > 0

    # Check text report generation
    report_text = format_evaluation_report(results)
    assert "SECUREPDF ML FORENSIC MODEL EVALUATION REPORT" in report_text
    assert "Per-Class Performance" in report_text
    assert "Confusion Matrix" in report_text
    assert "Important Disclaimers & Limitations" in report_text


def test_training_error_on_missing_or_corrupt_manifest(tmp_path: Path):
    missing_manifest = tmp_path / "missing.json"
    with pytest.raises(TrainingError, match="not found"):
        train_model(missing_manifest, tmp_path / "model.joblib")

    empty_manifest = tmp_path / "empty.json"
    empty_manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(TrainingError, match="no samples"):
        train_model(empty_manifest, tmp_path / "model.joblib")


def test_evaluate_schema_mismatch_rejection(sample_manifest: Path, tmp_path: Path):
    model_path = tmp_path / "bad_schema_model.joblib"
    _ = train_model(
        manifest_path=sample_manifest,
        model_output_path=model_path,
        random_seed=42,
        n_estimators=20,
    )

    # Corrupt the feature schema in the artifact
    artifact = joblib.load(str(model_path))
    artifact["feature_schema"] = ["dummy_feature_1", "dummy_feature_2"]
    joblib.dump(artifact, str(model_path))

    with pytest.raises(EvaluationError, match="Feature schema mismatch"):
        evaluate_model(model_path, sample_manifest)
