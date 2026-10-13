import sys
import argparse
from app.database.database import init_db
from app.cli.commands.verify import verify_cmd
from app.cli.commands.demo import demo_cmd
from app.cli.commands.register import register_document_cmd, register_student_cmd
from app.cli.commands.distribute import distribute_cmd
from app.cli.commands.interactive import interactive_mode
from app.cli.commands.analyze import analyze_cmd
from app.cli.commands.ml import (
    ml_dataset_cmd,
    ml_train_cmd,
    ml_evaluate_cmd,
    ml_inspect_cmd,
    ml_experiment_cmd,
)

def main(args=None):
    """Entry point for the SecurePDF CLI."""
    init_db()
    
    parser = argparse.ArgumentParser(
        prog="securepdf-cli",
        description="SecurePDF Cryptographic Document Fingerprinting and Attribution CLI"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # verify
    verify_parser = subparsers.add_parser("verify", help="Verify a PDF and identify recipient")
    verify_parser.add_argument("pdf_path", help="Path to the PDF file to inspect")

    # analyze
    analyze_parser = subparsers.add_parser("analyze", help="Perform comprehensive forensic analysis (crypto + advisory ML)")
    analyze_parser.add_argument("pdf_path", help="Path to the PDF file to inspect")
    analyze_parser.add_argument("--model", default=None, help="Optional custom path to model artifact")

    # ml
    ml_parser = subparsers.add_parser("ml", help="PDF forensic machine learning tools")
    ml_subparsers = ml_parser.add_subparsers(dest="ml_subcommand", help="ML subcommands")

    # ml dataset
    ds_parser = ml_subparsers.add_parser("dataset", help="Generate forensic training dataset")
    ds_parser.add_argument("--source-dir", default=None, help="Directory containing source PDFs")
    ds_parser.add_argument("--output-dir", default=None, help="Directory to save generated dataset")
    ds_parser.add_argument("--seed", type=int, default=42, help="Random seed")
    ds_parser.add_argument("--split-ratio", type=float, default=0.7, help="Source split ratio")
    ds_parser.add_argument("--generate-synthetic-sources", type=int, default=0, help="Generate synthetic source PDFs")

    # ml train
    train_parser = ml_subparsers.add_parser("train", help="Train Random Forest classifier on dataset manifest")
    train_parser.add_argument("--manifest", default=None, help="Path to dataset manifest.json")
    train_parser.add_argument("--output", default=None, help="Output path for trained model artifact")
    train_parser.add_argument("--seed", type=int, default=42, help="Random seed")
    train_parser.add_argument("--n-estimators", type=int, default=100, help="Number of trees")

    # ml evaluate
    eval_parser = ml_subparsers.add_parser("evaluate", help="Evaluate trained model artifact against manifest")
    eval_parser.add_argument("--manifest", default=None, help="Path to dataset manifest.json")
    eval_parser.add_argument("--model", default=None, help="Path to model artifact")
    eval_parser.add_argument("--eval-all", action="store_true", help="Evaluate on all samples if test set is small")

    # ml inspect-dataset
    inspect_parser = ml_subparsers.add_parser(
        "inspect-dataset",
        help="Inspect a directory of real-world PDFs and extract structural features (no labels assigned)",
    )
    inspect_parser.add_argument("--input", required=True, help="Directory containing real-world PDFs")
    inspect_parser.add_argument("--output", default=None, help="Directory to save results (default: data/ml/safedocs)")
    inspect_parser.add_argument("--max-pdfs", type=int, default=None, help="Process at most N PDFs (testing)")
    inspect_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")

    # ml experiment
    exp_parser = ml_subparsers.add_parser(
        "experiment",
        help="Run controlled transformation experiment on real-world SAFEDOCS PDFs",
    )
    exp_parser.add_argument("--source-dir", required=True, help="Directory containing source SAFEDOCS PDFs")
    exp_parser.add_argument("--output-dir", default=None, help="Directory to save experiment variants and reports")
    exp_parser.add_argument("--max-sources", type=int, default=None, help="Cap on number of source documents")
    exp_parser.add_argument("--test-split-ratio", type=float, default=0.3, help="Ratio of test sources (default: 0.3)")
    exp_parser.add_argument("--seed", type=int, default=42, help="Random seed for splitting")
    exp_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing experiment output")

    # demo
    demo_parser = subparsers.add_parser("demo", help="Run automated multi-student demo workflow")
    demo_parser.add_argument("--output-dir", default=None, help="Directory to save generated copies")

    # register-document
    reg_doc_parser = subparsers.add_parser("register-document", help="Register an original PDF")
    reg_doc_parser.add_argument("pdf_path", help="Path to the original PDF")
    reg_doc_parser.add_argument("--title", default=None, help="Document title/description")
    reg_doc_parser.add_argument("--uid", default=None, help="Custom document UID")

    # register-student
    reg_stu_parser = subparsers.add_parser("register-student", help="Register a student recipient")
    reg_stu_parser.add_argument("uid", help="Student unique ID (e.g. roll number)")
    reg_stu_parser.add_argument("name", help="Student full name")

    # distribute
    dist_parser = subparsers.add_parser("distribute", help="Generate a fingerprinted PDF for a student")
    dist_parser.add_argument("doc_uid", help="Document UID or path")
    dist_parser.add_argument("student_uid", help="Student UID")
    dist_parser.add_argument("--output", default=None, help="Output PDF file path")

    parsed = parser.parse_args(args)

    if not parsed.subcommand:
        interactive_mode()
        return 0

    if parsed.subcommand == "verify":
        res = verify_cmd(parsed.pdf_path)
        return 0 if res.get("status") == "VALID" else 1
    elif parsed.subcommand == "analyze":
        res = analyze_cmd(parsed.pdf_path, model_path=parsed.model)
        return 0 if res.get("file", {}).get("exists") else 1
    elif parsed.subcommand == "ml":
        if not parsed.ml_subcommand:
            ml_parser.print_help()
            return 1
        if parsed.ml_subcommand == "dataset":
            res = ml_dataset_cmd(
                source_dir=parsed.source_dir,
                output_dir=parsed.output_dir,
                seed=parsed.seed,
                split_ratio=parsed.split_ratio,
                generate_synthetic_sources=parsed.generate_synthetic_sources,
            )
            return 0 if res.get("status") != "ERROR" else 1
        elif parsed.ml_subcommand == "train":
            res = ml_train_cmd(
                manifest_path=parsed.manifest,
                output_path=parsed.output,
                seed=parsed.seed,
                n_estimators=parsed.n_estimators,
            )
            return 0 if res.get("status") == "SUCCESS" else 1
        elif parsed.ml_subcommand == "evaluate":
            res = ml_evaluate_cmd(
                manifest_path=parsed.manifest,
                model_path=parsed.model,
                use_test_split_only=not parsed.eval_all,
            )
            return 0 if res.get("status") != "ERROR" else 1
        elif parsed.ml_subcommand == "inspect-dataset":
            res = ml_inspect_cmd(
                input_dir=parsed.input,
                output_dir=parsed.output,
                max_pdfs=parsed.max_pdfs,
                overwrite=parsed.overwrite,
            )
            return 0 if res.get("status") != "ERROR" else 1
        elif parsed.ml_subcommand == "experiment":
            res = ml_experiment_cmd(
                source_dir=parsed.source_dir,
                output_dir=parsed.output_dir,
                max_sources=parsed.max_sources,
                test_split_ratio=parsed.test_split_ratio,
                seed=parsed.seed,
                overwrite=parsed.overwrite,
            )
            return 0 if res.get("status") != "ERROR" else 1
        else:
            ml_parser.print_help()
            return 1
    elif parsed.subcommand == "demo":
        demo_cmd(parsed.output_dir)
        return 0
    elif parsed.subcommand == "register-document":
        doc = register_document_cmd(parsed.pdf_path, title=parsed.title, doc_uid=parsed.uid)
        return 0 if doc else 1
    elif parsed.subcommand == "register-student":
        stu = register_student_cmd(parsed.uid, parsed.name)
        return 0 if stu else 1
    elif parsed.subcommand == "distribute":
        out = distribute_cmd(parsed.doc_uid, parsed.student_uid, output_path=parsed.output)
        return 0 if out else 1

if __name__ == "__main__":
    sys.exit(main())
