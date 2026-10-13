"""
Forensic Analysis Service.

Composes the authoritative cryptographic VerificationService and the advisory
MLPredictor without conflating their roles or merging their logic.
Provides a unified report suitable for CLI and future API endpoints.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.ml.predictor import MLPredictor
from app.services.verification_service import VerificationService


class ForensicService:
    """
    Forensic service combining authoritative cryptographic verification
    and advisory structural ML assessment.
    """

    def __init__(
        self,
        verification_service: VerificationService | None = None,
        predictor: MLPredictor | None = None,
    ) -> None:
        self.verification_service = verification_service or VerificationService()
        self.predictor = predictor or MLPredictor()

    def analyze_pdf(self, pdf_path: str | Path) -> dict[str, Any]:
        """
        Performs dual-track forensic analysis on a given PDF file:
        1. Authoritative cryptographic fingerprint verification and recipient attribution.
        2. Advisory structural ML classification estimating similarity to known transformations.

        Returns:
            dict containing file validation, cryptographic result, attribution (if valid),
            and ML assessment.
        """
        path = Path(pdf_path)
        file_valid = path.exists() and path.is_file()
        file_size = path.stat().st_size if file_valid else 0

        # Track 1: Cryptographic verification (Authoritative)
        crypto_result = self.verification_service.investigate_pdf(str(path))

        # Attribution: only derived if cryptographic status is VALID
        attribution: dict[str, Any] | None = None
        if crypto_result.get("status") == "VALID":
            attribution = {
                "student_uid": crypto_result.get("student_uid"),
                "student_name": crypto_result.get("student_name"),
                "document_uid": crypto_result.get("document_uid"),
                "nonce": crypto_result.get("nonce"),
                "authenticated_layers": crypto_result.get("authenticated_layers", []),
            }

        # Track 2: Advisory ML assessment (Structural)
        ml_result = self.predictor.predict(path)

        return {
            "file": {
                "path": str(path),
                "exists": file_valid,
                "size_bytes": file_size,
            },
            "cryptographic_verification": crypto_result,
            "attribution": attribution,
            "ml_assessment": ml_result,
            "disclaimer": (
                "Notice: Cryptographic verification (HMAC-SHA256) is the sole authoritative "
                "basis for recipient attribution. ML assessment is purely advisory and structural; "
                "it does not prove malicious intent or determine identity."
            ),
        }
