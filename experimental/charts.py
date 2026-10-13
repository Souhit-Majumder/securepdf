"""
High-resolution Matplotlib & Seaborn evaluation charts for the experimental watermarking prototype.
Saves technical figures to experimental/charts/.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from experimental.config import CHARTS_DIR, REPORTS_DIR


def generate_evaluation_charts(
    benchmark_json_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> List[Path]:
    """Generates 4 meaningful technical evaluation charts from benchmark results."""
    json_path = benchmark_json_path if benchmark_json_path is not None else (REPORTS_DIR / "stego_benchmark_results.json")
    out_dir = output_dir if output_dir is not None else CHARTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if not json_path.exists():
        raise FileNotFoundError(f"Benchmark results not found at: {json_path}")

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    scenarios = data.get("results", [])
    if not scenarios:
        return []

    generated: list[Path] = []

    # Chart 1: Watermark Authentication Survival by Attack
    names = [s["scenario_name"].replace("_", "\n") for s in scenarios]
    statuses = [1 if s["hmac_verified"] else 0 for s in scenarios]
    colors = ["#2e7d32" if s["hmac_verified"] else ("#f57c00" if s["is_baseline_unwatermarked"] else "#d32f2f") for s in scenarios]

    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    bars = ax.bar(names, statuses, color=colors, width=0.55)
    ax.set_title("Steganographic Watermark Authentication Survival Across Attack Scenarios", fontsize=12, fontweight="bold")
    ax.set_ylabel("HMAC-SHA256 Authenticated (1 = Yes, 0 = No)", fontsize=10)
    ax.set_ylim(0, 1.25)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["FAILED / NOT FOUND", "AUTHENTICATED"])
    ax.tick_params(axis="x", labelsize=8)

    for bar, s in zip(bars, scenarios):
        label = s["status"]
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05, label, ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    plt.tight_layout()
    c1 = out_dir / "01_watermark_survival_by_attack.png"
    plt.savefig(c1, dpi=150)
    plt.close(fig)
    generated.append(c1)

    # Chart 2: Bit Error Rate (BER) by Attack Vector
    plot_bers = [s["bit_error_rate"] if s.get("bit_error_rate") is not None else 0.0 for s in scenarios]
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    sns.barplot(x=names, y=plot_bers, hue=names, palette="Reds_r", legend=False, ax=ax)
    ax.set_title("Bit Error Rate (BER) by Attack Vector (Evaluated Frame Only)", fontsize=12, fontweight="bold")
    ax.set_ylabel("Normalized Bit Error Rate (0.0 to 1.0)", fontsize=10)
    ax.set_ylim(0, 1.20)
    ax.tick_params(axis="x", labelsize=8)

    for i, (s, v) in enumerate(zip(scenarios, plot_bers)):
        lbl = f"{v:.2f}" if s.get("bit_error_rate") is not None else "N/A (No Frame)"
        ax.text(i, v + 0.04, lbl, ha="center", fontsize=7.5, fontweight="bold")

    plt.tight_layout()
    c2 = out_dir / "02_bit_error_rate_by_attack.png"
    plt.savefig(c2, dpi=150)
    plt.close(fig)
    generated.append(c2)

    # Chart 3: Visual Distortion (PSNR in dB)
    # Filter scenarios that have valid finite PSNR measurements (< 900.0 dB)
    psnr_scenarios = [s for s in scenarios if s.get("total_psnr_db", s.get("psnr_db", 999.0)) < 900.0]
    if psnr_scenarios:
        p_names = [s["scenario_name"].replace("_", "\n") for s in psnr_scenarios]
        p_vals = [s.get("total_psnr_db", s.get("psnr_db", 0.0)) for s in psnr_scenarios]

        fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
        sns.barplot(x=p_names, y=p_vals, hue=p_names, palette="Blues_r", legend=False, ax=ax)
        ax.axhline(40.0, color="#d32f2f", linestyle="--", linewidth=1.5, label="High Quality Imperceptibility Threshold (40 dB)")
        ax.set_title("Peak Signal-to-Noise Ratio (PSNR) — Cumulative Distortion vs Original", fontsize=12, fontweight="bold")
        ax.set_ylabel("PSNR (dB) — Higher indicates closer visual match", fontsize=10)
        ax.set_ylim(0, max(50.0, max(p_vals) + 10.0))
        ax.legend(loc="lower right", fontsize=8.5)
        ax.tick_params(axis="x", labelsize=8.5)

        for i, v in enumerate(p_vals):
            ax.text(i, v + 1.0, f"{v:.1f} dB", ha="center", fontsize=8, fontweight="bold")

        plt.tight_layout()
        c3 = out_dir / "03_visual_distortion_psnr_mse.png"
        plt.savefig(c3, dpi=150)
        plt.close(fig)
        generated.append(c3)

    # Chart 4: Full HMAC-SHA256 Payload Capacity Breakdown
    payload_components = {
        "Preamble (Sync)": 32,
        "Version Header": 8,
        "Document UID": 56,
        "Recipient UID": 88,
        "Salt Nonce (128-bit)": 128,
        "Full HMAC-SHA256 (256-bit)": 256,
        "CRC-32 Checksum": 32,
    }
    total_bits = sum(payload_components.values())

    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    keys = list(payload_components.keys())
    vals = list(payload_components.values())
    colors_pie = ["#78909c", "#8d6e63", "#42a5f5", "#26a69a", "#ab47bc", "#ef5350", "#ffa726"]

    ax.pie(vals, labels=[f"{k}\n({v} bits)" for k, v in zip(keys, vals)], colors=colors_pie, autopct="%1.1f%%", startangle=140, textprops={"fontsize": 8})
    ax.set_title(f"Full HMAC-SHA256 Watermark Capacity Budget ({total_bits} bits total)", fontsize=12, fontweight="bold")

    plt.tight_layout()
    c4 = out_dir / "04_capacity_and_payload_breakdown.png"
    plt.savefig(c4, dpi=150)
    plt.close(fig)
    generated.append(c4)

    return generated
