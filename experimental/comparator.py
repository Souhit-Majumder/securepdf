"""
Visual and image-difference comparison utilities for the experimental watermarking prototype.
Measures visual fidelity, Mean Squared Error (MSE), Peak Signal-to-Noise Ratio (PSNR),
and renders high-resolution side-by-side comparisons and difference heatmaps.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import fitz
import numpy as np


@dataclass
class DistortionMetrics:
    page_number: int
    page_dims_orig_pt: tuple[float, float]
    page_dims_comp_pt: tuple[float, float]
    image_shape_orig_px: tuple[int, int, int]
    image_shape_comp_px: tuple[int, int, int]
    threshold: float
    mse: float
    psnr_db: float
    changed_pixels_count: int
    total_pixels_count: int
    changed_pixels_ratio: float
    is_visually_identical: bool
    dimensions_match: bool


def calculate_page_distortion(
    orig_page: fitz.Page,
    watermarked_page: fitz.Page,
    dpi: int = 150,
    threshold: float = 1.0,
) -> DistortionMetrics:
    """
    Renders corresponding pages to RGB arrays using identical settings
    (150 DPI, csRGB colorspace, alpha=False) and computes objective visual distortion metrics:
    MSE, PSNR (dB), and pixel divergence ratio at specified threshold.
    """
    pix_orig = orig_page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    pix_wm = watermarked_page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)

    img_orig = np.frombuffer(pix_orig.samples, dtype=np.uint8).reshape((pix_orig.height, pix_orig.width, 3))
    img_wm = np.frombuffer(pix_wm.samples, dtype=np.uint8).reshape((pix_wm.height, pix_wm.width, 3))

    dims_match = (pix_orig.height == pix_wm.height and pix_orig.width == pix_wm.width)

    # Ensure shape alignment on intersecting viewport
    min_h = min(img_orig.shape[0], img_wm.shape[0])
    min_w = min(img_orig.shape[1], img_wm.shape[1])
    arr_orig = img_orig[:min_h, :min_w].astype(np.float64)
    arr_wm = img_wm[:min_h, :min_w].astype(np.float64)

    total_pixels = min_h * min_w
    diff = np.abs(arr_orig - arr_wm)
    diff_per_pixel = np.max(diff, axis=2)  # Max channel difference per pixel

    changed_pixels = int(np.sum(diff_per_pixel > threshold))
    changed_ratio = changed_pixels / total_pixels if total_pixels > 0 else 0.0

    mse = float(np.mean((arr_orig - arr_wm) ** 2))
    if mse == 0.0:
        psnr = 999.0  # Sentinel for infinite PSNR (identical pixels)
    else:
        psnr = float(10.0 * math.log10((255.0 ** 2) / mse))

    return DistortionMetrics(
        page_number=orig_page.number + 1,
        page_dims_orig_pt=(round(orig_page.rect.width, 2), round(orig_page.rect.height, 2)),
        page_dims_comp_pt=(round(watermarked_page.rect.width, 2), round(watermarked_page.rect.height, 2)),
        image_shape_orig_px=(pix_orig.height, pix_orig.width, 3),
        image_shape_comp_px=(pix_wm.height, pix_wm.width, 3),
        threshold=threshold,
        mse=round(mse, 4),
        psnr_db=round(psnr, 2),
        changed_pixels_count=changed_pixels,
        total_pixels_count=total_pixels,
        changed_pixels_ratio=round(changed_ratio, 6),
        is_visually_identical=(changed_pixels == 0 and dims_match),
        dimensions_match=dims_match,
    )


def compare_documents(
    orig_pdf_path: str | Path,
    watermarked_pdf_path: str | Path,
    dpi: int = 150,
    threshold: float = 1.0,
) -> list[DistortionMetrics]:
    """Computes distortion metrics for all corresponding pages of two PDF documents."""
    doc_orig = fitz.open(str(orig_pdf_path))
    doc_wm = fitz.open(str(watermarked_pdf_path))

    metrics_list = []
    num_pages = min(doc_orig.page_count, doc_wm.page_count)
    for p in range(num_pages):
        m = calculate_page_distortion(doc_orig[p], doc_wm[p], dpi=dpi, threshold=threshold)
        metrics_list.append(m)

    doc_orig.close()
    doc_wm.close()
    return metrics_list


def render_visual_comparison_figure(
    orig_pdf_path: str | Path,
    watermarked_pdf_path: str | Path,
    output_image_path: str | Path,
    page_number: int = 1,
    dpi: int = 150,
) -> Path:
    """
    Renders a 3-panel visual comparison figure:
    1. Original Page
    2. Watermarked Page
    3. Pixel Difference Heatmap
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    doc_orig = fitz.open(str(orig_pdf_path))
    doc_wm = fitz.open(str(watermarked_pdf_path))

    p_idx = max(0, page_number - 1)
    page_orig = doc_orig[p_idx]
    page_wm = doc_wm[p_idx]

    pix_orig = page_orig.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    pix_wm = page_wm.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)

    img_orig = np.frombuffer(pix_orig.samples, dtype=np.uint8).reshape((pix_orig.height, pix_orig.width, 3))
    img_wm = np.frombuffer(pix_wm.samples, dtype=np.uint8).reshape((pix_wm.height, pix_wm.width, 3))

    doc_orig.close()
    doc_wm.close()

    min_h = min(img_orig.shape[0], img_wm.shape[0])
    min_w = min(img_orig.shape[1], img_wm.shape[1])
    arr_orig = img_orig[:min_h, :min_w]
    arr_wm = img_wm[:min_h, :min_w]

    diff = np.abs(arr_orig.astype(np.int16) - arr_wm.astype(np.int16)).astype(np.uint8)
    diff_gray = np.mean(diff, axis=2)

    fig, axes = plt.subplots(1, 3, figsize=(18, 8), dpi=150)
    axes[0].imshow(arr_orig)
    axes[0].set_title(f"Original Page {page_number}", fontsize=12, fontweight="bold")
    axes[0].axis("off")

    axes[1].imshow(arr_wm)
    axes[1].set_title(f"Watermarked Page {page_number}\n(Inter-Word TJ Kerning Modulation)", fontsize=12, fontweight="bold")
    axes[1].axis("off")

    im = axes[2].imshow(diff_gray, cmap="inferno", vmin=0, vmax=max(10, float(np.max(diff_gray))))
    axes[2].set_title("Pixel Difference Heatmap\n(Divergence Magnified)", fontsize=12, fontweight="bold")
    axes[2].axis("off")
    plt.colorbar(im, ax=axes[2], fraction=0.046, pad=0.04)

    plt.suptitle("Experimental Steganographic Watermark — Visual Distortion Assessment", fontsize=15, fontweight="bold")
    plt.tight_layout()

    out_path = Path(output_image_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path
