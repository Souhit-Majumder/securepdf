"""
Minimal Command-Line Interface for Experimental Steganographic Watermarking.
Provides embed, extract, verify, compare, and evaluate commands without
duplicating existing registration or database subsystems.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure repository root is on sys.path when invoked directly as a script
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from experimental.charts import generate_evaluation_charts
from experimental.comparator import compare_documents, render_visual_comparison_figure
from experimental.config import CHARTS_DIR, DEFAULT_KEY_PATH, EXPERIMENTAL_DIR, OUTPUT_DIR, REPORTS_DIR
from experimental.crypto_adapter import (
    generate_watermark_payload,
    get_or_create_experimental_key,
)
from experimental.embed import StegoEmbeddingError, embed_watermark
from experimental.evaluator import StegoEvaluator
from experimental.extract import extract_watermark


def _resolve_path(p: str | Path | None, default_parent: Path = EXPERIMENTAL_DIR) -> Path:
    """Resolves path relative to CWD if specified with directories, or relative to default_parent."""
    if p is None:
        raise ValueError("Path argument required")
    path_obj = Path(p)
    if path_obj.is_absolute():
        return path_obj
    cwd_candidate = Path.cwd() / path_obj
    if cwd_candidate.exists() or (len(path_obj.parts) > 1 and cwd_candidate.parent.exists()):
        return cwd_candidate.resolve()
    return (default_parent / path_obj).resolve()


def cmd_embed(args: argparse.Namespace) -> int:
    """Embeds an authenticated steganographic watermark into a PDF."""
    in_path = _resolve_path(args.input)
    out_path = _resolve_path(args.output, OUTPUT_DIR)
    key_path = _resolve_path(args.key) if args.key else DEFAULT_KEY_PATH

    print("\n" + "=" * 65)
    print("  EXPERIMENTAL STEGANOGRAPHIC WATERMARK EMBEDDING")
    print("=" * 65)
    print(f"Input Document : {in_path}")
    print(f"Output Document: {out_path}")
    print(f"Document UID   : {args.doc_uid}")
    print(f"Recipient UID  : {args.recipient_uid}")
    print(f"Master Key Path: {key_path}")

    key = get_or_create_experimental_key(key_path)
    payload = generate_watermark_payload(args.doc_uid, args.recipient_uid, key)
    print(f"Total Payload  : {payload.total_bits} bits (Includes untruncated 256-bit HMAC-SHA256)")

    try:
        res = embed_watermark(in_path, out_path, payload, shift=args.shift)
        print(f"\n[✓] Embedding Successful!")
        print(f"    Bits Embedded      : {res.total_bits_embedded}")
        print(f"    Available Word Gaps: {res.total_word_gaps_available}")
        print(f"    Kerning Shift      : {res.kerning_shift} (1/1000 em)")
        print(f"    Pages Modulated    : {res.pages_used}")
        print(f"    Text Preserved     : {res.text_preserved}")
        return 0
    except Exception as err:
        print(f"\n[X] Embedding Failed: {err}")
        return 1


def cmd_extract(args: argparse.Namespace) -> int:
    """Extracts and displays steganographic watermark information from a PDF."""
    in_path = _resolve_path(args.input)
    key_path = _resolve_path(args.key) if args.key else DEFAULT_KEY_PATH
    key = get_or_create_experimental_key(key_path)

    print("\n" + "=" * 65)
    print("  EXPERIMENTAL STEGANOGRAPHIC WATERMARK EXTRACTION")
    print("=" * 65)
    print(f"Target PDF: {in_path}")

    res = extract_watermark(in_path, key, use_geometric_fallback=args.geometric)

    # Display granular multi-stage extraction diagnostic results
    print(f"Extraction Status : {res.status}")
    print(f"Extraction Method : {res.method_used}")
    print(f"Frame Detected    : {res.frame_detected}")
    print(f"Payload Decoded   : {res.payload_decoded}")
    print(f"CRC-32 Valid      : {res.crc_valid}")
    print(f"HMAC-SHA256 Valid : {res.hmac_valid}")
    print(f"Recipient Found   : {res.recipient_recovered}")
    print(f"Bits Recovered    : {res.bits_recovered}")
    print(f"Document UID      : {res.document_uid or 'None'}")
    print(f"Recipient UID     : {res.recipient_uid or 'None'}")
    print(f"Diagnostic Reason : {res.reason}")

    return 0 if res.status == "AUTHENTICATED" else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Alias for extraction and strict authentication verification."""
    return cmd_extract(args)


def cmd_compare(args: argparse.Namespace) -> int:
    """Computes visual distortion metrics and optionally renders a difference figure."""
    orig_path = _resolve_path(args.original)
    wm_path = _resolve_path(args.watermarked)
    threshold = getattr(args, "threshold", 1.0)

    print("\n" + "=" * 65)
    print("  VISUAL DISTORTION & IMAGE COMPARISON")
    print("=" * 65)
    print(f"Original PDF   : {orig_path}")
    print(f"Watermarked PDF: {wm_path}")
    print(f"Rendering DPI  : {args.dpi}")
    print(f"Pixel Threshold: {threshold}")

    metrics = compare_documents(orig_path, wm_path, dpi=args.dpi, threshold=threshold)
    for m in metrics:
        print(f"\nPage {m.page_number}:")
        print(f"  • Dimensions Match     : {m.dimensions_match} (Orig: {m.page_dims_orig_pt} pt, Comp: {m.page_dims_comp_pt} pt)")
        print(f"  • Image Shape          : {m.image_shape_comp_px[1]}x{m.image_shape_comp_px[0]} px (at {args.dpi} DPI)")
        print(f"  • MSE                  : {m.mse:.4f}")
        print(f"  • PSNR                 : {m.psnr_db:.2f} dB")
        print(f"  • Changed Pixels Ratio : {m.changed_pixels_ratio * 100:.4f}% ({m.changed_pixels_count}/{m.total_pixels_count}, threshold > {m.threshold})")
        print(f"  • Visually Identical   : {m.is_visually_identical}")

    if args.diff_image:
        diff_path = _resolve_path(args.diff_image, REPORTS_DIR)
        render_visual_comparison_figure(orig_path, wm_path, diff_path, dpi=args.dpi)
        print(f"\n[✓] Rendered difference heatmap figure to: {diff_path}")

    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Executes multi-vector transformation benchmark and generates evaluation charts."""
    in_path = _resolve_path(args.input)
    key_path = _resolve_path(args.key) if args.key else DEFAULT_KEY_PATH
    out_dir = _resolve_path(args.output_dir, REPORTS_DIR) if args.output_dir else REPORTS_DIR
    key = get_or_create_experimental_key(key_path)

    print("\n" + "=" * 65)
    print("  STEGANOGRAPHIC WATERMARK EVALUATION BENCHMARK")
    print("=" * 65)
    print(f"Source PDF   : {in_path}")
    print(f"Document UID : {args.doc_uid}")
    print(f"Recipient UID: {args.recipient_uid}")
    print(f"Output Report: {out_dir}")

    evaluator = StegoEvaluator(key=key, output_dir=out_dir)
    results = evaluator.run_benchmark(in_path, doc_uid=args.doc_uid, recipient_uid=args.recipient_uid)

    print("\nScenario Results Summary:")
    for r in results:
        status_tag = "[✓]" if r.hmac_verified else ("[X]" if not r.is_baseline_unwatermarked else "[O]")
        ber_str = f"{r.bit_error_rate:.2f}" if r.bit_error_rate is not None else "None"
        print(f"  {status_tag} {r.scenario_name:<30}: Status={r.status:<22} | BER={ber_str:<5} | PSNR={r.total_psnr_db:.1f} dB")
        if r.carrier_failure_mode:
            print(f"      Failure Mode: {r.carrier_failure_mode}")

    # Generate charts
    json_path = out_dir / "stego_benchmark_results.json"
    charts_dir = (out_dir / "charts") if args.output_dir else CHARTS_DIR
    charts = generate_evaluation_charts(benchmark_json_path=json_path, output_dir=charts_dir)
    print(f"\n[✓] Generated {len(charts)} presentation charts in: {charts_dir}")

    return 0


def main(args: list[str] | None = None) -> int:
    """
    Main entrypoint for the experimental steganographic watermarking CLI.
    Constructs argument parsers for embedding, extraction, verification,
    visual comparison, and multi-vector transformation benchmarking.
    """
    parser = argparse.ArgumentParser(
        prog="stego-cli",
        description="Experimental Steganographic Watermarking CLI for SecurePDF Research",
        epilog="Designed for isolated evaluation of PDF text-stream kerning watermarks.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # -------------------------------------------------------------
    # Subcommand: embed
    # Embeds a full 256-bit HMAC-SHA256 authenticated watermark
    # into a PDF text content stream via inter-word TJ micro-kerning.
    # -------------------------------------------------------------
    p_embed = subparsers.add_parser(
        "embed",
        help="Embed steganographic watermark into PDF",
        description="Embed an authenticated watermark payload using inter-word TJ kerning displacement.",
    )
    p_embed.add_argument(
        "--input",
        required=True,
        help="Path to source un-watermarked PDF document",
    )
    p_embed.add_argument(
        "--output",
        required=True,
        help="Destination path for the watermarked PDF",
    )
    p_embed.add_argument(
        "--doc-uid",
        default="DOC-EXP-001",
        help="Unique document identifier to bind in canonical HMAC message (default: DOC-EXP-001)",
    )
    p_embed.add_argument(
        "--recipient-uid",
        default="STU-EXP-ALICE",
        help="Authorized recipient identifier to bind in canonical HMAC message (default: STU-EXP-ALICE)",
    )
    p_embed.add_argument(
        "--key",
        default=None,
        help="Path to 256-bit experimental master key (defaults to experimental/working/exp_master.key)",
    )
    p_embed.add_argument(
        "--shift",
        type=int,
        default=-25,
        help="Kerning displacement in 1/1000 em for bit '1' (default: -25, ~0.24-0.30 pt rightward shift)",
    )

    # -------------------------------------------------------------
    # Subcommand: extract
    # Parses PDF content streams for TJ kerning displacements,
    # detects sync preamble, validates CRC-32, and verifies HMAC-SHA256.
    # -------------------------------------------------------------
    p_extract = subparsers.add_parser(
        "extract",
        help="Extract and authenticate watermark from PDF",
        description="Extract and verify steganographic watermark payload from PDF content streams.",
    )
    p_extract.add_argument(
        "--input",
        required=True,
        help="Target PDF path to inspect for embedded watermark",
    )
    p_extract.add_argument(
        "--key",
        default=None,
        help="Path to experimental master key for HMAC verification (default: experimental/working/exp_master.key)",
    )
    p_extract.add_argument(
        "--geometric",
        action="store_true",
        help="Enable secondary experimental geometric word-gap extraction fallback if stream parsing finds no mark",
    )

    # -------------------------------------------------------------
    # Subcommand: verify
    # Semantic alias for 'extract', emphasizing cryptographic authentication check.
    # Returns exit code 0 if authenticated, 1 if invalid or not found.
    # -------------------------------------------------------------
    p_verify = subparsers.add_parser(
        "verify",
        help="Verify watermark authenticity in PDF",
        description="Cryptographically authenticate embedded watermark against master secret key.",
    )
    p_verify.add_argument(
        "--input",
        required=True,
        help="Target PDF path to authenticate",
    )
    p_verify.add_argument(
        "--key",
        default=None,
        help="Path to experimental master key (default: experimental/working/exp_master.key)",
    )
    p_verify.add_argument(
        "--geometric",
        action="store_true",
        help="Enable secondary experimental geometric fallback",
    )

    # -------------------------------------------------------------
    # Subcommand: compare
    # Computes page-by-page visual distortion metrics (MSE, PSNR, changed pixels)
    # and optionally exports a 3-panel difference heatmap graphic.
    # -------------------------------------------------------------
    p_compare = subparsers.add_parser(
        "compare",
        help="Compare original and watermarked PDFs visually",
        description="Compute objective visual distortion metrics (MSE, PSNR, changed-pixel ratio) and export heatmaps.",
    )
    p_compare.add_argument(
        "--original",
        required=True,
        help="Path to reference original PDF document",
    )
    p_compare.add_argument(
        "--watermarked",
        required=True,
        help="Path to comparison/watermarked PDF document",
    )
    p_compare.add_argument(
        "--diff-image",
        default=None,
        help="Optional output PNG path to render side-by-side comparison and pixel difference heatmap",
    )
    p_compare.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="Rasterization resolution for pixel-level distortion evaluation (default: 150 DPI)",
    )
    p_compare.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="Per-pixel max RGB channel divergence threshold for changed pixel counting (default: 1.0 out of 255)",
    )

    # -------------------------------------------------------------
    # Subcommand: evaluate
    # Executes the 8-scenario transformation attack benchmark:
    # baseline, pristine, resave, metadata, appended text, page reorder,
    # margin crop, and rasterization / print-scan simulation.
    # -------------------------------------------------------------
    p_eval = subparsers.add_parser(
        "evaluate",
        help="Run multi-vector transformation attack benchmark",
        description="Execute full 8-vector attack suite and generate report CSV, JSON, and evaluation charts.",
    )
    p_eval.add_argument(
        "--input",
        required=True,
        help="Path to source document to benchmark",
    )
    p_eval.add_argument(
        "--doc-uid",
        default="DOC-BENCH-01",
        help="Document UID for benchmark attribution payload (default: DOC-BENCH-01)",
    )
    p_eval.add_argument(
        "--recipient-uid",
        default="STU-EXP-ALICE",
        help="Recipient UID for benchmark attribution payload (default: STU-EXP-ALICE)",
    )
    p_eval.add_argument(
        "--key",
        default=None,
        help="Path to experimental master key (default: experimental/working/exp_master.key)",
    )
    p_eval.add_argument(
        "--output-dir",
        default=None,
        help="Destination directory to save JSON/CSV reports and charts (defaults to experimental/reports/)",
    )

    parsed = parser.parse_args(args)
    if not parsed.command:
        parser.print_help()
        return 0

    # Dispatch to appropriate handler
    if parsed.command == "embed":
        return cmd_embed(parsed)
    elif parsed.command == "extract":
        return cmd_extract(parsed)
    elif parsed.command == "verify":
        return cmd_verify(parsed)
    elif parsed.command == "compare":
        return cmd_compare(parsed)
    elif parsed.command == "evaluate":
        return cmd_evaluate(parsed)

    return 0


if __name__ == "__main__":
    sys.exit(main())
