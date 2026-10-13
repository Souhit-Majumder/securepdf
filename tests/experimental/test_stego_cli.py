"""
Tests for experimental steganographic CLI commands:
embed, extract, verify, compare, evaluate.
"""
from pathlib import Path
import fitz
import pytest

from experimental.cli import main


def _create_cli_sample_pdf(path: Path) -> None:
    doc = fitz.open()
    sample_text = (
        "SecurePDF steganographic command line interface testing document. "
        "Each section verifies correct parameter passing, return codes, "
        "and error diagnostics without calling production database systems. "
    ) * 5
    for _ in range(7):
        p = doc.new_page(width=595, height=842)
        p.insert_textbox(fitz.Rect(50, 60, 545, 780), sample_text, fontsize=10, fontname="helv")
    doc.save(str(path))
    doc.close()


def test_cli_embed_extract_verify_flow(tmp_path, capsys):
    src = tmp_path / "cli_source.pdf"
    wm = tmp_path / "cli_wm.pdf"
    key = tmp_path / "cli.key"
    _create_cli_sample_pdf(src)

    # 1. embed
    rc = main([
        "embed",
        "--input", str(src),
        "--output", str(wm),
        "--doc-uid", "DOC-CLI-01",
        "--recipient-uid", "STU-CLI-BOB",
        "--key", str(key),
    ])
    assert rc == 0
    assert wm.exists()
    out = capsys.readouterr().out
    assert "Embedding Successful" in out

    # 2. extract
    rc = main([
        "extract",
        "--input", str(wm),
        "--key", str(key),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "AUTHENTICATED" in out
    assert "DOC-CLI-01" in out
    assert "STU-CLI-BOB" in out

    # 3. verify
    rc = main([
        "verify",
        "--input", str(wm),
        "--key", str(key),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "AUTHENTICATED" in out

    # 4. extract on plain un-watermarked PDF -> returns 1 (NO_WATERMARK)
    rc = main([
        "extract",
        "--input", str(src),
        "--key", str(key),
    ])
    assert rc == 1
    out = capsys.readouterr().out
    assert "NO_WATERMARK" in out


def test_cli_compare(tmp_path, capsys):
    src = tmp_path / "cli_source.pdf"
    wm = tmp_path / "cli_wm.pdf"
    diff_png = tmp_path / "diff.png"
    key = tmp_path / "cli.key"
    _create_cli_sample_pdf(src)

    main(["embed", "--input", str(src), "--output", str(wm), "--key", str(key)])
    capsys.readouterr()

    rc = main([
        "compare",
        "--original", str(src),
        "--watermarked", str(wm),
        "--diff-image", str(diff_png),
    ])
    assert rc == 0
    assert diff_png.exists()
    out = capsys.readouterr().out
    assert "PSNR" in out
    assert "MSE" in out


def test_cli_evaluate(tmp_path, capsys):
    src = tmp_path / "cli_source.pdf"
    out_dir = tmp_path / "eval_out"
    key = tmp_path / "cli.key"
    _create_cli_sample_pdf(src)

    rc = main([
        "evaluate",
        "--input", str(src),
        "--doc-uid", "DOC-EVAL-01",
        "--recipient-uid", "STU-EVAL-CHARLIE",
        "--key", str(key),
        "--output-dir", str(out_dir),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "STEGANOGRAPHIC WATERMARK EVALUATION BENCHMARK" in out
    assert "00_unwatermarked_baseline" in out
    assert "07_rasterization_scan_sim" in out
    assert (out_dir / "stego_benchmark_results.json").exists()
    assert (out_dir / "stego_benchmark_results.csv").exists()
