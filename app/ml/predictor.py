"""
Safe PDF Forensic ML Predictor.

Loads a versioned Random Forest model artifact and performs advisory forensic inference.
Guarantees:
- Validates model artifact integrity and feature schema compatibility.
- Never makes student attribution decisions.
- Never alters cryptographic verification results.
- Returns qualified, uncalibrated tree vote confidence scores.
- Fails gracefully when models are absent or PDFs are malformed.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from app.config import config
from app.ml.feature_extractor import (
    FEATURE_SCHEMA,
    FeatureExtractionError,
    extract_pdf_features,
    features_to_vector,
)
from app.ml.train import MODEL_ARTIFACT_VERSION

logger = logging.getLogger(__name__)


class PredictorError(Exception):
    """Raised when prediction cannot be executed."""
    pass


class ModelUnavailableError(PredictorError):
    """Raised when model artifact is missing or unreadable."""
    pass


class ModelIncompatibleError(PredictorError):
    """Raised when model artifact schema or version is incompatible."""
    pass


class MLPredictor:
    """
    Forensic ML predictor providing structural modification assessments.
    """

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = model_path if model_path is not None else config.MODEL_PATH
        self._model: Any = None
        self._classes: list[str] = []
        self._artifact_version: str | None = None
        self._loaded: bool = False

    def load_model(self) -> None:
        """
        Loads and validates the serialized model artifact.
        Raises ModelUnavailableError or ModelIncompatibleError if invalid.
        """
        if not self.model_path.exists():
            raise ModelUnavailableError(f"Model artifact not found at {self.model_path}")

        try:
            artifact = joblib.load(str(self.model_path))
        except Exception as err:
            raise ModelUnavailableError(f"Failed to load model file: {err}") from err

        if not isinstance(artifact, dict) or "model" not in artifact:
            raise ModelIncompatibleError("Invalid model artifact structure.")

        ver = artifact.get("artifact_version")
        if ver != MODEL_ARTIFACT_VERSION:
            raise ModelIncompatibleError(
                f"Incompatible artifact version: expected {MODEL_ARTIFACT_VERSION}, got {ver}"
            )

        saved_schema = artifact.get("feature_schema", [])
        if saved_schema != FEATURE_SCHEMA:
            raise ModelIncompatibleError(
                f"Feature schema mismatch: expected {len(FEATURE_SCHEMA)} features, "
                f"artifact has {len(saved_schema)}"
            )

        self._model = artifact["model"]
        self._classes = [str(c) for c in artifact.get("classes", self._model.classes_)]
        self._artifact_version = ver
        self._loaded = True

    def is_available(self) -> bool:
        """Checks if a valid model is loaded or loadable."""
        if self._loaded and self._model is not None:
            return True
        try:
            self.load_model()
            return True
        except (ModelUnavailableError, ModelIncompatibleError, Exception):
            return False

    def predict(self, pdf_path: Path) -> dict[str, Any]:
        """
        Extracts structural features from a PDF and returns an advisory forensic assessment.

        Returns a dictionary with status 'AVAILABLE', 'UNAVAILABLE', or 'ERROR'.
        """
        if not self._loaded:
            try:
                self.load_model()
            except (ModelUnavailableError, ModelIncompatibleError) as err:
                return {
                    "status": "UNAVAILABLE",
                    "reason": str(err),
                    "model_version": None,
                    "predicted_class": None,
                    "confidence_score": None,
                    "class_scores": {},
                    "advisory_notice": (
                        "ML forensic analysis is currently unavailable because no valid "
                        "trained model artifact is present."
                    ),
                }

        # Extract features
        try:
            features = extract_pdf_features(pdf_path)
            vec = features_to_vector(features).reshape(1, -1)
        except FeatureExtractionError as err:
            return {
                "status": "ERROR",
                "reason": f"Feature extraction failed: {err}",
                "model_version": self._artifact_version,
                "predicted_class": None,
                "confidence_score": None,
                "class_scores": {},
                "advisory_notice": "Structural analysis could not be completed for this file.",
            }

        # Highlight key structural indicators for human inspection
        has_catalog_carrier = bool(features.get("has_catalog_carrier", 0))
        annotation_carrier_count = int(features.get("annotation_carrier_count", 0))
        carrier_total = float(features.get("carrier_count_total", 0.0))

        structural_indicators = {
            "file_size_bytes": features.get("file_size_bytes"),
            "page_count": features.get("page_count"),
            "annotation_count": features.get("annotation_count"),
            "image_count": features.get("image_count"),
            "embedded_file_count": features.get("embedded_file_count"),
            "has_javascript_indicator": bool(features.get("javascript_action_count", 0) > 0),
            "carrier_catalog_present": has_catalog_carrier,
            "carrier_catalog_format_valid": bool(features.get("catalog_carrier_format_valid", 0)),
            "carrier_annotation_count": annotation_carrier_count,
            "carrier_annotation_format_valid_count": int(features.get("annotation_carrier_format_valid_count", 0)),
        }

        # Scope Gate: Tampering detection is exclusively supported for SecurePDF-generated documents.
        # If no carrier markings are detected, return explicit UNSUPPORTED status rather than forcing a class.
        if not has_catalog_carrier and annotation_carrier_count == 0 and carrier_total == 0.0:
            return {
                "status": "UNSUPPORTED",
                "reason": (
                    "No SecurePDF fingerprint carrier markers detected. Forensic tampering "
                    "classification is supported exclusively for documents issued by SecurePDF's "
                    "distribution pipeline. Note: Absence of carriers does not conclusively prove "
                    "the document was never issued by SecurePDF, as an attacker may have stripped "
                    "both carrier layers."
                ),
                "model_version": self._artifact_version,
                "predicted_class": None,
                "confidence_score": None,
                "class_scores": {},
                "structural_indicators": structural_indicators,
                "raw_features": features,
                "advisory_notice": (
                    "ADVISORY NOTICE: Document is outside the supported classification scope. "
                    "Classification is suppressed to prevent false positive attribution on arbitrary PDFs."
                ),
            }

        # Predict (for recognized SecurePDF documents containing carriers)
        predicted_idx = self._model.predict(vec)[0]
        predicted_class = str(predicted_idx)

        class_scores: dict[str, float] = {}
        confidence: float | None = None
        if hasattr(self._model, "predict_proba"):
            probs = self._model.predict_proba(vec)[0]
            for cls_name, prob in zip(self._model.classes_, probs):
                class_scores[str(cls_name)] = round(float(prob), 4)
            confidence = class_scores.get(predicted_class, 0.0)

        return {
            "status": "AVAILABLE",
            "model_version": self._artifact_version,
            "predicted_class": predicted_class,
            "confidence_score": confidence,
            "class_scores": class_scores,
            "structural_indicators": structural_indicators,
            "raw_features": features,
            "advisory_notice": (
                "ADVISORY NOTICE: This assessment reflects structural similarity to known "
                "training transformations. It does not replace cryptographic HMAC verification, "
                "does not prove malicious intent, and provides no student attribution."
            ),
        }
