"""
Forensic Analysis CLI Command.

Executes dual-track analysis:
1. Authoritative cryptographic verification and student attribution.
2. Advisory structural ML classification.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import config
from app.ml.predictor import MLPredictor
from app.services.forensic_service import ForensicService


def analyze_cmd(pdf_path: str, model_path: str | None = None) -> dict[str, Any]:
    """
    Executes comprehensive forensic analysis on the target PDF.
    """
    custom_model_path = Path(model_path) if model_path else config.MODEL_PATH
    predictor = MLPredictor(model_path=custom_model_path)
    service = ForensicService(predictor=predictor)

    report = service.analyze_pdf(pdf_path)

    # Human-readable CLI formatting
    print("\n" + "=" * 68)
    print("           SECUREPDF COMPREHENSIVE FORENSIC REPORT")
    print("=" * 68)

    # 1. File Validation
    file_info = report["file"]
    print("\n[1] FILE VALIDATION")
    print(f"  Path        : {file_info['path']}")
    print(f"  Exists      : {'Yes' if file_info['exists'] else 'No'}")
    print(f"  Size        : {file_info['size_bytes']} bytes")

    if not file_info["exists"]:
        print("\n[-] Analysis aborted: Target file does not exist.")
        print("=" * 68 + "\n")
        return report

    # 2. Cryptographic Verification (Authoritative)
    crypto = report["cryptographic_verification"]
    print("\n[2] CRYPTOGRAPHIC INTEGRITY & ATTRIBUTION (Authoritative)")
    crypto_status = crypto.get("status")

    if crypto_status == "VALID":
        print("  Status      : AUTHENTIC (HMAC-SHA256 verified)")
        print(f"  Recipient   : {crypto.get('student_name')} ({crypto.get('student_uid')})")
        print(f"  Document UID: {crypto.get('document_uid')}")
        layers = crypto.get("authenticated_layers", [])
        if layers:
            print(f"  Carriers    : {', '.join(layers)}")
    elif crypto_status == "SECURITY_CONFLICT":
        print("  Status      : SECURITY_CONFLICT (Fail-closed)")
        print("  Details     : Redundant fingerprint layers conflict; attribution suppressed.")
    elif crypto_status == "NOT_FOUND":
        print("  Status      : UNVERIFIED (No fingerprint markers detected)")
    else:
        print(f"  Status      : UNVERIFIED ({crypto_status})")
        if crypto.get("reason"):
            print(f"  Details     : {crypto['reason']}")

    # 3. Structural Indicators
    ml = report["ml_assessment"]
    indicators = ml.get("structural_indicators", {})
    if indicators:
        print("\n[3] STRUCTURAL CHARACTERISTICS (Non-sensitive)")
        print(f"  Pages               : {int(indicators.get('page_count', 0))}")
        print(f"  Annotations         : {int(indicators.get('annotation_count', 0))}")
        print(f"  Images              : {int(indicators.get('image_count', 0))}")
        print(f"  Embedded Files      : {int(indicators.get('embedded_file_count', 0))}")
        print(f"  Action/JS Detected  : {'Yes' if indicators.get('has_javascript_indicator') else 'No'}")
        print(f"  Catalog Carrier     : {'Present' if indicators.get('carrier_catalog_present') else 'None'} "
              f"(Valid structure: {'Yes' if indicators.get('carrier_catalog_format_valid') else 'No'})")
        print(f"  Annotation Carrier  : {'Present' if indicators.get('carrier_annotation_count', 0) > 0 else 'None'} "
              f"(Valid structure count: {indicators.get('carrier_annotation_format_valid_count', 0)})")

    # 4. ML Forensic Assessment (Advisory)
    print("\n[4] ML FORENSIC ASSESSMENT (Advisory Only)")
    ml_status = ml.get("status")
    if ml_status == "AVAILABLE":
        pred_cls = ml.get("predicted_class")
        conf = ml.get("confidence_score")
        print(f"  Model Version       : {ml.get('model_version')}")
        print(f"  Predicted Class     : {pred_cls}")
        if conf is not None:
            print(f"  Tree Vote Proportion: {conf:.4f} (Uncalibrated RF vote frequency)")
        if ml.get("class_scores"):
            scores_str = ", ".join(f"{k}: {v:.2f}" for k, v in ml["class_scores"].items())
            print(f"  Vote Breakdown      : {scores_str}")
    elif ml_status == "UNAVAILABLE":
        print(f"  Status              : UNAVAILABLE")
        print(f"  Notice              : {ml.get('reason')}")
        print("                        (Run 'python -m app.cli ml train' to train a model)")
    elif ml_status == "UNSUPPORTED":
        print(f"  Status              : UNSUPPORTED (Document Outside Scope)")
        print(f"  Notice              : {ml.get('reason')}")
    else:
        print(f"  Status              : {ml_status}")
        print(f"  Notice              : {ml.get('reason')}")

    # 5. Advisory Disclaimer
    print("\n" + "-" * 68)
    print("DISCLAIMER:")
    print(f"  {report['disclaimer']}")
    print("=" * 68 + "\n")

    return report
