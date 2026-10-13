"""
Machine Learning Subcommands for PDF Forensic Analysis.

Provides CLI handlers for:
- python -m app.cli ml dataset
- python -m app.cli ml train
- python -m app.cli ml evaluate
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import config
from app.ml.dataset import build_forensic_dataset, create_synthetic_source_documents
from app.ml.evaluate import evaluate_model, format_evaluation_report
from app.ml.train import train_model


def ml_dataset_cmd(
    source_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    seed: int = 42,
    split_ratio: float = 0.7,
    generate_synthetic_sources: int = 0,
) -> dict:
    """Generates a reproducible forensic dataset with source-grouped splits."""
    out_dir = Path(output_dir) if output_dir else config.DATASET_DIR
    src_dir = Path(source_dir) if source_dir else out_dir / "sources"

    if generate_synthetic_sources > 0:
        print(f"[*] Generating {generate_synthetic_sources} synthetic source PDFs in {src_dir}...")
        created = create_synthetic_source_documents(src_dir, count=generate_synthetic_sources)
        print(f"[+] Created {len(created)} synthetic source documents.")

    if not src_dir.exists() or not list(src_dir.glob("*.pdf")):
        print(f"[-] No source PDFs found in {src_dir}.")
        print("    Tip: Use --generate-synthetic-sources N (e.g. --generate-synthetic-sources 5) to create sources.")
        return {"status": "ERROR", "reason": "No source PDFs found"}

    print(f"[*] Generating dataset from {src_dir} into {out_dir} (seed={seed})...")
    manifest = build_forensic_dataset(
        source_dir=src_dir,
        output_dir=out_dir,
        random_seed=seed,
        split_ratio=split_ratio,
    )

    print("\n" + "=" * 60)
    print("      FORENSIC DATASET GENERATION COMPLETE")
    print("=" * 60)
    print(f"Manifest written to: {out_dir / 'manifest.json'}")
    print(f"Total samples       : {len(manifest.get('samples', []))}")
    print(f"Train sources       : {len(manifest.get('train_sources', []))}")
    print(f"Test sources        : {len(manifest.get('test_sources', []))}")
    print("Class distribution  :")
    for cls_name, count in manifest.get("class_distribution", {}).items():
        print(f"  - {cls_name:<25}: {count}")
    print("=" * 60 + "\n")

    return manifest


def ml_train_cmd(
    manifest_path: str | Path | None = None,
    output_path: str | Path | None = None,
    seed: int = 42,
    n_estimators: int = 100,
) -> dict:
    """Trains a Random Forest classifier on dataset manifest."""
    man_path = Path(manifest_path) if manifest_path else config.DATASET_DIR / "manifest.json"
    mod_path = Path(output_path) if output_path else config.MODEL_PATH

    print(f"[*] Loading dataset manifest from {man_path}...")
    try:
        summary = train_model(
            manifest_path=man_path,
            model_output_path=mod_path,
            random_seed=seed,
            n_estimators=n_estimators,
        )
    except Exception as err:
        print(f"[-] Training failed: {err}")
        return {"status": "ERROR", "reason": str(err)}

    print("\n" + "=" * 60)
    print("          MODEL TRAINING COMPLETE")
    print("=" * 60)
    print(f"Saved artifact to  : {mod_path}")
    print(f"Artifact version   : {summary['artifact_version']}")
    print(f"Classes ({len(summary['classes'])}): {', '.join(summary['classes'])}")
    print(f"Training samples   : {summary['train_samples']}")
    print(f"Test samples       : {summary['test_samples']}")
    print(f"Train Accuracy     : {summary['train_accuracy']:.4f}")
    if summary.get("test_accuracy") is not None:
        print(f"Test Accuracy      : {summary['test_accuracy']:.4f} "
              f"(Baseline: {summary.get('baseline_test_accuracy', 0.0):.4f})")
    print("\nTop 5 Most Informative Features (Gini Importance):")
    for feat, imp in summary.get("top_features", []):
        print(f"  - {feat:<28}: {imp:.4f}")
    print("=" * 60 + "\n")

    return summary


def ml_evaluate_cmd(
    manifest_path: str | Path | None = None,
    model_path: str | Path | None = None,
    use_test_split_only: bool = True,
) -> dict:
    """Evaluates a trained model artifact and prints a full forensic report."""
    man_path = Path(manifest_path) if manifest_path else config.DATASET_DIR / "manifest.json"
    mod_path = Path(model_path) if model_path else config.MODEL_PATH

    print(f"[*] Evaluating model {mod_path} against {man_path}...")
    try:
        results = evaluate_model(
            model_path=mod_path,
            manifest_path=man_path,
            use_test_split_only=use_test_split_only,
        )
    except Exception as err:
        print(f"[-] Evaluation failed: {err}")
        return {"status": "ERROR", "reason": str(err)}

    report_text = format_evaluation_report(results)
    print("\n" + report_text + "\n")
    return results


def ml_inspect_cmd(
    input_dir: str | Path,
    output_dir: str | Path | None = None,
    max_pdfs: int | None = None,
    overwrite: bool = False,
) -> dict:
    """
    Inspects a directory of real-world PDFs using the existing feature extractor.
    Produces manifest.csv, features.csv, extraction_report.json, and feature_summary.json.
    Real-world PDFs receive NO synthetic labels.
    """
    from app.ml.inspect import inspect_dataset

    out_dir = Path(output_dir) if output_dir else config.DATA_DIR / "ml" / "safedocs"

    print(f"[*] Input  : {input_dir}")
    print(f"[*] Output : {out_dir}")

    try:
        report = inspect_dataset(
            input_dir=input_dir,
            output_dir=out_dir,
            max_pdfs=max_pdfs,
            overwrite=overwrite,
        )
        return report
    except (FileNotFoundError, NotADirectoryError) as err:
        print(f"[-] Input path error: {err}")
        return {"status": "ERROR", "reason": str(err)}
    except FileExistsError as err:
        print(f"[-] Output conflict: {err}")
        print("    Add --overwrite to replace existing results.")
        return {"status": "ERROR", "reason": str(err)}
    except Exception as err:
        print(f"[-] Unexpected inspection error: {err}")
        return {"status": "ERROR", "reason": str(err)}


def ml_experiment_cmd(
    source_dir: str | Path,
    output_dir: str | Path | None = None,
    max_sources: int | None = None,
    test_split_ratio: float = 0.3,
    seed: int = 42,
    overwrite: bool = False,
) -> dict:
    """
    Executes the controlled transformation experiment on real-world SAFEDOCS PDFs.
    Tracks readability, cryptographic verification, carrier survival, and features.
    Enforces strict source preservation and source-grouped partitioning.
    """
    from app.ml.experiment import run_safedocs_experiment

    out_dir = Path(output_dir) if output_dir else config.DATA_DIR / "ml" / "safedocs_experiment"

    print(f"[*] Experiment source : {source_dir}")
    print(f"[*] Experiment output : {out_dir}")

    try:
        summary = run_safedocs_experiment(
            source_dir=source_dir,
            output_dir=out_dir,
            max_sources=max_sources,
            test_split_ratio=test_split_ratio,
            seed=seed,
            overwrite=overwrite,
        )
        return summary
    except (FileNotFoundError, NotADirectoryError, ValueError) as err:
        print(f"[-] Experiment input error: {err}")
        return {"status": "ERROR", "reason": str(err)}
    except FileExistsError as err:
        print(f"[-] Output conflict: {err}")
        print("    Add --overwrite to replace existing results.")
        return {"status": "ERROR", "reason": str(err)}
    except Exception as err:
        print(f"[-] Unexpected experiment error: {err}")
        return {"status": "ERROR", "reason": str(err)}

