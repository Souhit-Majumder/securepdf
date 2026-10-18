"""
Tests for empirical false-positive qualification across diverse unwatermarked PDFs.
Verifies that extraction on unwatermarked controls reports exact empirical ratios
and does not claim an unqualified 0% rate without finite sample context.
"""
from pathlib import Path
import pytest
from experimental.evaluator import StegoEvaluator


def test_evaluate_unwatermarked_controls_reporting(tmp_path):
    """
    Runs the multi-document unwatermarked control suite and verifies:
    - Multiple control documents are tested
    - Zero false preambles, CRCs, or HMAC authentications occur
    - Empirical ratio false_accepts / total_controls is reported
    - Results are written to JSON
    """
    evaluator = StegoEvaluator(output_dir=tmp_path)
    # Target available PDFs in experimental/pdfs
    exp_dir = Path("experimental/pdfs")
    assert exp_dir.exists()
    controls = sorted(exp_dir.glob("*.pdf"))
    assert len(controls) >= 4

    audit = evaluator.evaluate_unwatermarked_controls(candidate_paths=controls)

    assert audit["total_controls_tested"] == len(controls)
    assert audit["false_accepts"] == 0
    assert audit["false_preambles"] == 0
    assert audit["false_crcs"] == 0
    assert audit["empirical_false_accept_rate"] == f"0 / {len(controls)}"
    assert "cannot prove a general 0% false-positive rate" in audit["qualification"]

    # Verify JSON report on disk
    json_path = tmp_path / "false_positive_controls.json"
    assert json_path.exists()
