"""
Model Evaluation Module for PDF Forensic Analysis.

Evaluates a trained Random Forest model artifact against a source-grouped dataset manifest.
Computes comprehensive metrics:
- Accuracy & Baseline (dummy) comparison.
- Macro F1 and per-class precision, recall, F1-score, support.
- Confusion matrix.
- Source document isolation statistics.
- Top feature importances with non-causation disclaimer.
- Documented evaluation limitations and false-positive caveats.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)

from app.ml.feature_extractor import FEATURE_SCHEMA
from app.ml.train import MODEL_ARTIFACT_VERSION, load_dataset_from_manifest


class EvaluationError(Exception):
    """Raised when evaluation fails due to missing artifacts or invalid data."""
    pass


def evaluate_model(
    model_path: Path,
    manifest_path: Path,
    use_test_split_only: bool = True,
) -> dict[str, Any]:
    """
    Evaluates a trained model artifact using data from a dataset manifest.

    Args:
        model_path: Path to the serialized joblib artifact.
        manifest_path: Path to the dataset manifest.json.
        use_test_split_only: If True, evaluates strictly on test split.
            If test split is empty or only 1 sample, falls back to evaluating both splits with explicit disclosure.

    Returns:
        dict: Detailed evaluation metrics and limitation disclosures.
    """
    if not model_path.exists():
        raise EvaluationError(f"Model artifact not found at {model_path}")
    if not manifest_path.exists():
        raise EvaluationError(f"Dataset manifest not found at {manifest_path}")

    try:
        artifact = joblib.load(str(model_path))
    except Exception as err:
        raise EvaluationError(f"Failed to load model artifact: {err}") from err

    if not isinstance(artifact, dict) or "model" not in artifact:
        raise EvaluationError("Invalid model artifact structure: missing 'model' key.")

    artifact_version = artifact.get("artifact_version")
    if artifact_version != MODEL_ARTIFACT_VERSION:
        raise EvaluationError(
            f"Artifact version mismatch: expected {MODEL_ARTIFACT_VERSION}, got {artifact_version}"
        )

    saved_schema = artifact.get("feature_schema", [])
    if saved_schema != FEATURE_SCHEMA:
        raise EvaluationError(
            f"Feature schema mismatch between model artifact ({len(saved_schema)} features) "
            f"and current pipeline ({len(FEATURE_SCHEMA)} features)."
        )

    model = artifact["model"]
    baseline_model = artifact.get("baseline_model")
    classes: list[str] = [str(c) for c in artifact.get("classes", model.classes_)]

    X_train, y_train, X_test, y_test, manifest = load_dataset_from_manifest(manifest_path)

    # Determine evaluation split
    eval_split_name = "test"
    if use_test_split_only and len(X_test) > 0 and len(set(y_test)) >= 1:
        X_eval = X_test
        y_eval = y_test
    else:
        eval_split_name = "train (fallback - test split insufficient)"
        X_eval = X_train
        y_eval = y_train

    if len(X_eval) == 0:
        raise EvaluationError("No evaluation samples found in the specified manifest.")

    # Predictions
    y_pred = model.predict(X_eval)
    acc = float(accuracy_score(y_eval, y_pred))

    baseline_acc: float | None = None
    if baseline_model is not None:
        try:
            y_baseline_pred = baseline_model.predict(X_eval)
            baseline_acc = float(accuracy_score(y_eval, y_baseline_pred))
        except Exception:
            baseline_acc = None

    # Per-class metrics
    present_classes = sorted(list(set(y_eval) | set(y_pred)))
    # Map to classes known to the model
    eval_classes = [c for c in classes if c in present_classes]
    if not eval_classes:
        eval_classes = present_classes

    precision, recall, f1, support = precision_recall_fscore_support(
        y_eval, y_pred, labels=eval_classes, zero_division=0
    )

    per_class_metrics: dict[str, dict[str, float]] = {}
    for idx, cls_name in enumerate(eval_classes):
        per_class_metrics[cls_name] = {
            "precision": float(precision[idx]),
            "recall": float(recall[idx]),
            "f1_score": float(f1[idx]),
            "support": int(support[idx]),
        }

    macro_precision, macro_recall, macro_f1, _ = precision_recall_fscore_support(
        y_eval, y_pred, average="macro", zero_division=0
    )

    # Confusion matrix
    cm = confusion_matrix(y_eval, y_pred, labels=eval_classes)
    cm_dict = {
        "labels": eval_classes,
        "matrix": cm.tolist(),
    }

    # Top feature importances
    top_features = []
    if hasattr(model, "feature_importances_"):
        importances = dict(zip(FEATURE_SCHEMA, [float(x) for x in model.feature_importances_]))
        top_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]

    train_sources = manifest.get("train_sources", [])
    test_sources = manifest.get("test_sources", [])
    class_dist = manifest.get("class_distribution", {})

    return {
        "model_version": artifact_version,
        "eval_split": eval_split_name,
        "eval_samples": len(X_eval),
        "accuracy": acc,
        "baseline_accuracy": baseline_acc,
        "macro_f1": float(macro_f1),
        "macro_precision": float(macro_precision),
        "macro_recall": float(macro_recall),
        "per_class": per_class_metrics,
        "confusion_matrix": cm_dict,
        "top_features": top_features,
        "dataset_statistics": {
            "total_samples": len(manifest.get("samples", [])),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "train_sources_count": len(train_sources),
            "test_sources_count": len(test_sources),
            "train_sources": train_sources,
            "test_sources": test_sources,
            "class_distribution": class_dist,
        },
        "limitations": [
            "Trained on synthetic and controlled document transformations; may not generalize to real-world PDF manipulation tools.",
            "Predictions are advisory structural indicators, not cryptographic proofs of malicious tampering or integrity.",
            "Feature importance reflects statistical correlation within the synthetic training set, not physical causation.",
            "Confidence estimates are uncalibrated tree vote proportions and should not be interpreted as absolute Bayesian probabilities.",
            "Cryptographic verification (HMAC-SHA256) remains the sole authoritative mechanism for recipient attribution.",
        ],
    }


def format_evaluation_report(eval_results: dict[str, Any]) -> str:
    """Formats evaluation results into a human-readable text report."""
    lines: list[str] = []
    lines.append("=" * 68)
    lines.append("        SECUREPDF ML FORENSIC MODEL EVALUATION REPORT")
    lines.append("=" * 68)
    lines.append(f"Model Artifact Version : {eval_results['model_version']}")
    lines.append(f"Evaluation Split       : {eval_results['eval_split']}")
    lines.append(f"Evaluated Samples      : {eval_results['eval_samples']}")
    lines.append(f"Overall Accuracy       : {eval_results['accuracy']:.4f}")
    if eval_results.get("baseline_accuracy") is not None:
        lines.append(f"Baseline Accuracy (maj): {eval_results['baseline_accuracy']:.4f}")
    lines.append(f"Macro F1-Score         : {eval_results['macro_f1']:.4f}")
    lines.append("")

    lines.append("--- Per-Class Performance ---")
    lines.append(f"{'Class':<25} {'Precision':<10} {'Recall':<10} {'F1-Score':<10} {'Support':<8}")
    lines.append("-" * 65)
    for cls_name, metrics in eval_results["per_class"].items():
        lines.append(
            f"{cls_name:<25} {metrics['precision']:<10.4f} {metrics['recall']:<10.4f} "
            f"{metrics['f1_score']:<10.4f} {metrics['support']:<8}"
        )
    lines.append("")

    lines.append("--- Confusion Matrix ---")
    cm = eval_results["confusion_matrix"]
    labels = cm["labels"]
    matrix = cm["matrix"]
    header = "True \\ Pred".ljust(22) + "".join(f"{lbl[:10]:>12}" for lbl in labels)
    lines.append(header)
    for i, true_lbl in enumerate(labels):
        row_str = f"{true_lbl[:20]:<22}" + "".join(f"{matrix[i][j]:>12}" for j in range(len(labels)))
        lines.append(row_str)
    lines.append("")

    stats = eval_results.get("dataset_statistics", {})
    lines.append("--- Dataset Source-Grouped Isolation ---")
    lines.append(f"Train Source Documents : {stats.get('train_sources_count', 0)} ({stats.get('train_samples', 0)} variants)")
    lines.append(f"Test Source Documents  : {stats.get('test_sources_count', 0)} ({stats.get('test_samples', 0)} variants)")
    lines.append("Class Distribution     : " + json.dumps(stats.get("class_distribution", {})))
    lines.append("")

    if eval_results.get("top_features"):
        lines.append("--- Top Feature Importances (Random Forest Gini) ---")
        lines.append("(Note: Statistical association only; does NOT prove causation)")
        for feat, score in eval_results["top_features"]:
            lines.append(f"  - {feat:<28}: {score:.4f}")
        lines.append("")

    lines.append("--- Important Disclaimers & Limitations ---")
    for lim in eval_results.get("limitations", []):
        lines.append(f"  * {lim}")
    lines.append("=" * 68)

    return "\n".join(lines)
