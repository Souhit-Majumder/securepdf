"""
Model Training Pipeline for PDF Forensic Analysis.

Trains a Random Forest classifier using scikit-learn on source-grouped dataset splits.
Includes:
- Strict source-grouped train/test isolation.
- Fixed random seed.
- Dummy baseline comparison.
- Versioned artifact serialization (saving model, feature schema, class labels, and metadata).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier

from app.ml.feature_extractor import FEATURE_SCHEMA, features_to_vector

MODEL_ARTIFACT_VERSION = "1.0.0"


class TrainingError(Exception):
    """Raised when model training cannot proceed due to data or configuration issues."""
    pass


def load_dataset_from_manifest(
    manifest_path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
    """
    Loads feature matrices and label vectors for train and test splits from a manifest file.

    Returns:
        tuple: (X_train, y_train, X_test, y_test, manifest_dict)
    """
    if not manifest_path.exists():
        raise TrainingError(f"Manifest file not found: {manifest_path}")

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as err:
        raise TrainingError(f"Failed to parse manifest JSON: {err}") from err

    samples = manifest.get("samples", [])
    if not samples:
        raise TrainingError("Manifest contains no samples.")

    train_X: list[list[float]] = []
    train_y: list[str] = []
    test_X: list[list[float]] = []
    test_y: list[str] = []

    for s in samples:
        if s.get("feature_extraction_status") != "success":
            continue
        feats = s.get("features")
        if not feats:
            continue

        vec = features_to_vector(feats).tolist()
        label = s["label"]
        split = s.get("split", "train")

        if split == "test":
            test_X.append(vec)
            test_y.append(label)
        else:
            train_X.append(vec)
            train_y.append(label)

    return (
        np.array(train_X, dtype=np.float64),
        np.array(train_y),
        np.array(test_X, dtype=np.float64),
        np.array(test_y),
        manifest,
    )


def train_model(
    manifest_path: Path,
    model_output_path: Path,
    random_seed: int = 42,
    n_estimators: int = 100,
) -> dict[str, Any]:
    """
    Trains a Random Forest classifier on the dataset and persists the versioned artifact.

    Returns:
        dict: Summary of training performance and metadata.
    """
    X_train, y_train, X_test, y_test, manifest = load_dataset_from_manifest(manifest_path)

    if len(X_train) == 0:
        raise TrainingError("No training samples available in manifest.")

    unique_classes = sorted(list(set(y_train)))
    if len(unique_classes) < 2:
        raise TrainingError(
            f"Dataset must contain at least 2 distinct classes to train a classifier. Found: {unique_classes}"
        )

    # 1. Train primary Random Forest Classifier
    clf = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=8,
        random_state=random_seed,
        class_weight="balanced",
    )
    clf.fit(X_train, y_train)

    # 2. Train Dummy baseline classifier (most frequent class) for comparison
    dummy = DummyClassifier(strategy="most_frequent")
    dummy.fit(X_train, y_train)

    # 3. Compute baseline metrics
    train_acc = float(clf.score(X_train, y_train))
    baseline_train_acc = float(dummy.score(X_train, y_train))

    test_acc: float | None = None
    baseline_test_acc: float | None = None
    if len(X_test) > 0 and len(set(y_test)) > 0:
        test_acc = float(clf.score(X_test, y_test))
        baseline_test_acc = float(dummy.score(X_test, y_test))

    # Feature importances
    importances = dict(zip(FEATURE_SCHEMA, [float(x) for x in clf.feature_importances_]))
    top_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]

    # Build artifact bundle
    artifact = {
        "artifact_version": MODEL_ARTIFACT_VERSION,
        "model_type": "RandomForestClassifier",
        "feature_schema": FEATURE_SCHEMA,
        "classes": [str(c) for c in clf.classes_],
        "model": clf,
        "baseline_model": dummy,
        "training_metadata": {
            "random_seed": random_seed,
            "train_samples": int(len(X_train)),
            "test_samples": int(len(X_test)),
            "train_sources": manifest.get("train_sources", []),
            "test_sources": manifest.get("test_sources", []),
            "class_distribution": manifest.get("class_distribution", {}),
            "train_accuracy": train_acc,
            "baseline_train_accuracy": baseline_train_acc,
            "test_accuracy": test_acc,
            "baseline_test_accuracy": baseline_test_acc,
            "top_features": top_features,
        },
    }

    model_output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, str(model_output_path))

    return {
        "status": "SUCCESS",
        "model_path": str(model_output_path),
        "artifact_version": MODEL_ARTIFACT_VERSION,
        "classes": artifact["classes"],
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "train_accuracy": train_acc,
        "test_accuracy": test_acc,
        "baseline_test_accuracy": baseline_test_acc,
        "top_features": top_features,
    }
