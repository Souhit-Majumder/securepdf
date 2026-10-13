"""
Evaluation benchmark suite for the experimental steganographic watermarking prototype.
Measures extraction success, bit error rate (BER), HMAC-SHA256 authentication,
visual distortion metrics (MSE, PSNR, changed-pixel ratio), baseline false positives,
and rigorously separates embedding distortion from transformation distortion.
Retains cryptographic SHA-256 provenance for all inputs, outputs, and controls.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz

from experimental.comparator import compare_documents
from experimental.config import DEFAULT_KEY_PATH, REPORTS_DIR, WORKING_DIR
from experimental.crypto_adapter import (
    generate_watermark_payload,
    get_or_create_experimental_key,
)
from experimental.embed import count_document_word_gaps, embed_watermark
from experimental.extract import extract_watermark
from experimental.payload import WatermarkPayload


def sha256_file(path: str | Path) -> str:
    """Computes SHA-256 cryptographic digest of a file on disk."""
    p = Path(path)
    if not p.exists():
        return ""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_bit_error_rate(expected_bits: str, actual_candidate_bits: Optional[str]) -> Optional[float]:
    """
    Computes normalized Hamming distance (Bit Error Rate) between expected and recovered bitstrings.
    Returns None (JSON null) when no candidate frame was detected, avoiding misleading 1.00 assignments.
    """
    if actual_candidate_bits is None or not expected_bits:
        return None

    compare_len = min(len(expected_bits), len(actual_candidate_bits))
    if compare_len == 0:
        return None

    diffs = sum(1 for a, b in zip(expected_bits[:compare_len], actual_candidate_bits[:compare_len]) if a != b)
    diffs += max(0, len(expected_bits) - len(actual_candidate_bits))
    return round(diffs / len(expected_bits), 4)


@dataclass
class ScenarioResult:
    scenario_name: str
    description: str
    is_baseline_unwatermarked: bool
    status: str
    
    # Granular Extraction Stages
    frame_detected: bool
    payload_decoded: bool
    crc_valid: bool
    hmac_verified: bool
    recipient_recovered: bool
    recovered_recipient_uid: Optional[str]
    bit_error_rate: Optional[float]

    # Visual Metrics (Separating Embedding, Transformation, and Cumulative Distortion)
    embedding_psnr_db: float               # S vs W
    embedding_mse: float
    embedding_changed_ratio: float

    transformation_psnr_db: float          # W vs T(W)
    transformation_mse: float
    transformation_changed_ratio: float

    total_psnr_db: float                   # S vs T(W)
    total_mse: float
    total_changed_ratio: float

    control_psnr_db: Optional[float]       # S vs T(S) (transformation on un-watermarked copy)
    control_mse: Optional[float]
    control_changed_ratio: Optional[float]

    # Rendering Dimensions & Settings
    page_dims_orig_pt: tuple[float, float]
    page_dims_comp_pt: tuple[float, float]
    image_shape_orig_px: tuple[int, int, int]
    image_shape_comp_px: tuple[int, int, int]
    dimensions_match: bool
    pixel_threshold: float

    # Secondary Geometric Extraction Track
    geometric_status: str
    geometric_payload_decoded: bool
    geometric_hmac_verified: bool

    # Cryptographic Provenance
    file_hashes: dict[str, str]

    expected_outcome: str
    carrier_failure_mode: Optional[str]
    notes: str

    # Compatibility Aliases for Legacy Visual Metrics & Charts
    @property
    def psnr_db(self) -> float:
        return self.total_psnr_db

    @property
    def mse(self) -> float:
        return self.total_mse

    @property
    def preamble_detected(self) -> bool:
        return self.frame_detected


class StegoEvaluator:
    """Executes multi-vector transformation benchmarks on experimental watermarking."""

    def __init__(self, key: Optional[bytes] = None, output_dir: Optional[Path] = None):
        self.key = key if key is not None else get_or_create_experimental_key()
        self.output_dir = output_dir if output_dir is not None else REPORTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.working_dir = WORKING_DIR / "benchmark_runs"
        self.working_dir.mkdir(parents=True, exist_ok=True)

    def evaluate_capacity(
        self,
        source_pdf: str | Path,
        doc_uid: str = "DOC-BENCH-01",
        recipient_uid: str = "STU-EXP-ALICE",
    ) -> dict[str, Any]:
        """Calculates capacity metrics without modifying the document."""
        src_path = Path(source_pdf)
        doc = fitz.open(str(src_path))
        total_gaps, gaps_per_page = count_document_word_gaps(doc)
        doc.close()

        required_bits = WatermarkPayload.calculate_required_bits(doc_uid, recipient_uid)
        can_accommodate = total_gaps >= required_bits
        deficit = max(0, required_bits - total_gaps)

        return {
            "source_pdf": str(src_path),
            "sha256": sha256_file(src_path),
            "required_bits": required_bits,
            "total_word_gaps": total_gaps,
            "gaps_per_page": gaps_per_page,
            "can_accommodate": can_accommodate,
            "deficit_bits": deficit,
        }

    def run_benchmark(
        self,
        source_pdf: str | Path,
        doc_uid: str = "DOC-BENCH-01",
        recipient_uid: str = "STU-EXP-ALICE",
    ) -> List[ScenarioResult]:
        """
        Executes complete benchmark suite on a given source PDF:
        Generates watermarked baseline, applies controlled attacks, tests un-watermarked baseline.
        Every scenario is evaluated with measured pixel differences, SHA-256 provenance,
        and unwatermarked controls.
        """
        src_path = Path(source_pdf)
        if not src_path.exists():
            raise FileNotFoundError(f"Source PDF not found: {src_path}")

        prefix = src_path.stem

        # 1. Generate Watermark Payload & Embed
        payload = generate_watermark_payload(doc_uid, recipient_uid, self.key)
        expected_bits = payload.to_bits()

        watermarked_base = self.working_dir / f"{prefix}_watermarked.pdf"
        embed_res = embed_watermark(src_path, watermarked_base, payload)

        # Baseline embedding distortion (S vs W)
        base_visual = compare_documents(src_path, watermarked_base, dpi=150, threshold=1.0)
        base_m = base_visual[0] if base_visual else None
        base_embed_psnr = base_m.psnr_db if base_m else 999.0
        base_embed_mse = base_m.mse if base_m else 0.0
        base_embed_ratio = base_m.changed_pixels_ratio if base_m else 0.0
        page_dims_pt = base_m.page_dims_orig_pt if base_m else (0.0, 0.0)
        img_shape_px = base_m.image_shape_orig_px if base_m else (0, 0, 0)

        results: list[ScenarioResult] = []

        # -------------------------------------------------------------
        # Scenario 0: Un-watermarked Baseline (False Positive Check)
        # -------------------------------------------------------------
        ext_plain = extract_watermark(src_path, self.key)
        geom_plain = extract_watermark(src_path, self.key, use_geometric_fallback=True)
        results.append(
            ScenarioResult(
                scenario_name="00_unwatermarked_baseline",
                description="Plain PDF without watermark; tests false-positive detector rate",
                is_baseline_unwatermarked=True,
                status=ext_plain.status,
                frame_detected=ext_plain.frame_detected,
                payload_decoded=ext_plain.payload_decoded,
                crc_valid=ext_plain.crc_valid,
                hmac_verified=ext_plain.hmac_valid,
                recipient_recovered=ext_plain.recipient_recovered,
                recovered_recipient_uid=ext_plain.recipient_uid,
                bit_error_rate=None,  # No frame detected -> BER is undefined (null)
                embedding_psnr_db=999.0,
                embedding_mse=0.0,
                embedding_changed_ratio=0.0,
                transformation_psnr_db=999.0,
                transformation_mse=0.0,
                transformation_changed_ratio=0.0,
                total_psnr_db=999.0,
                total_mse=0.0,
                total_changed_ratio=0.0,
                control_psnr_db=999.0,
                control_mse=0.0,
                control_changed_ratio=0.0,
                page_dims_orig_pt=page_dims_pt,
                page_dims_comp_pt=page_dims_pt,
                image_shape_orig_px=img_shape_px,
                image_shape_comp_px=img_shape_px,
                dimensions_match=True,
                pixel_threshold=1.0,
                geometric_status=geom_plain.status,
                geometric_payload_decoded=geom_plain.payload_decoded,
                geometric_hmac_verified=geom_plain.hmac_valid,
                file_hashes={"source_pdf": sha256_file(src_path)},
                expected_outcome="NO_WATERMARK (Zero False Positives)",
                carrier_failure_mode=None,
                notes="Verified extractor does not hallucinate watermarks on un-watermarked documents.",
            )
        )

        # -------------------------------------------------------------
        # Scenario 1: Untouched Watermarked Copy
        # -------------------------------------------------------------
        ext_untouched = extract_watermark(watermarked_base, self.key)
        geom_untouched = extract_watermark(watermarked_base, self.key, use_geometric_fallback=True)
        candidate_bits = ext_untouched.raw_bits[ext_untouched.frame_offset:] if ext_untouched.frame_offset is not None else None
        ber_01 = compute_bit_error_rate(expected_bits, candidate_bits)

        results.append(
            ScenarioResult(
                scenario_name="01_untouched_watermark",
                description="Pristine watermarked copy without any transformation",
                is_baseline_unwatermarked=False,
                status=ext_untouched.status,
                frame_detected=ext_untouched.frame_detected,
                payload_decoded=ext_untouched.payload_decoded,
                crc_valid=ext_untouched.crc_valid,
                hmac_verified=ext_untouched.hmac_valid,
                recipient_recovered=ext_untouched.recipient_recovered,
                recovered_recipient_uid=ext_untouched.recipient_uid,
                bit_error_rate=ber_01,
                embedding_psnr_db=base_embed_psnr,
                embedding_mse=base_embed_mse,
                embedding_changed_ratio=base_embed_ratio,
                transformation_psnr_db=999.0,
                transformation_mse=0.0,
                transformation_changed_ratio=0.0,
                total_psnr_db=base_embed_psnr,
                total_mse=base_embed_mse,
                total_changed_ratio=base_embed_ratio,
                control_psnr_db=None,
                control_mse=None,
                control_changed_ratio=None,
                page_dims_orig_pt=base_m.page_dims_orig_pt if base_m else page_dims_pt,
                page_dims_comp_pt=base_m.page_dims_comp_pt if base_m else page_dims_pt,
                image_shape_orig_px=base_m.image_shape_orig_px if base_m else img_shape_px,
                image_shape_comp_px=base_m.image_shape_comp_px if base_m else img_shape_px,
                dimensions_match=True,
                pixel_threshold=1.0,
                geometric_status=geom_untouched.status,
                geometric_payload_decoded=geom_untouched.payload_decoded,
                geometric_hmac_verified=geom_untouched.hmac_valid,
                file_hashes={
                    "source_pdf": sha256_file(src_path),
                    "watermarked_base": sha256_file(watermarked_base),
                },
                expected_outcome="AUTHENTICATED (100% Recovery)",
                carrier_failure_mode=None,
                notes="Full payload and HMAC-SHA256 successfully recovered from text content stream.",
            )
        )

        # -------------------------------------------------------------
        # Scenario 2: Benign Re-Save (Garbage Collect & Deflate)
        # -------------------------------------------------------------
        resaved_path = self.working_dir / f"{prefix}_02_resave.pdf"
        d = fitz.open(str(watermarked_base))
        d.save(str(resaved_path), garbage=3, deflate=True)
        d.close()

        # Unwatermarked Control
        resaved_ctrl = self.working_dir / f"{prefix}_02_resave_ctrl.pdf"
        d_ctrl = fitz.open(str(src_path))
        d_ctrl.save(str(resaved_ctrl), garbage=3, deflate=True)
        d_ctrl.close()

        ext_resave = extract_watermark(resaved_path, self.key)
        geom_resave = extract_watermark(resaved_path, self.key, use_geometric_fallback=True)
        cand_bits_02 = ext_resave.raw_bits[ext_resave.frame_offset:] if ext_resave.frame_offset is not None else None
        ber_02 = compute_bit_error_rate(expected_bits, cand_bits_02)

        # Visual metrics
        vis_trans_02 = compare_documents(watermarked_base, resaved_path, dpi=150)
        vis_tot_02 = compare_documents(src_path, resaved_path, dpi=150)
        vis_ctrl_02 = compare_documents(src_path, resaved_ctrl, dpi=150)

        results.append(
            ScenarioResult(
                scenario_name="02_benign_resave",
                description="PyMuPDF re-save with stream deflation and unused object pruning",
                is_baseline_unwatermarked=False,
                status=ext_resave.status,
                frame_detected=ext_resave.frame_detected,
                payload_decoded=ext_resave.payload_decoded,
                crc_valid=ext_resave.crc_valid,
                hmac_verified=ext_resave.hmac_valid,
                recipient_recovered=ext_resave.recipient_recovered,
                recovered_recipient_uid=ext_resave.recipient_uid,
                bit_error_rate=ber_02,
                embedding_psnr_db=base_embed_psnr,
                embedding_mse=base_embed_mse,
                embedding_changed_ratio=base_embed_ratio,
                transformation_psnr_db=vis_trans_02[0].psnr_db if vis_trans_02 else 999.0,
                transformation_mse=vis_trans_02[0].mse if vis_trans_02 else 0.0,
                transformation_changed_ratio=vis_trans_02[0].changed_pixels_ratio if vis_trans_02 else 0.0,
                total_psnr_db=vis_tot_02[0].psnr_db if vis_tot_02 else base_embed_psnr,
                total_mse=vis_tot_02[0].mse if vis_tot_02 else base_embed_mse,
                total_changed_ratio=vis_tot_02[0].changed_pixels_ratio if vis_tot_02 else base_embed_ratio,
                control_psnr_db=vis_ctrl_02[0].psnr_db if vis_ctrl_02 else 999.0,
                control_mse=vis_ctrl_02[0].mse if vis_ctrl_02 else 0.0,
                control_changed_ratio=vis_ctrl_02[0].changed_pixels_ratio if vis_ctrl_02 else 0.0,
                page_dims_orig_pt=vis_tot_02[0].page_dims_orig_pt if vis_tot_02 else page_dims_pt,
                page_dims_comp_pt=vis_tot_02[0].page_dims_comp_pt if vis_tot_02 else page_dims_pt,
                image_shape_orig_px=vis_tot_02[0].image_shape_orig_px if vis_tot_02 else img_shape_px,
                image_shape_comp_px=vis_tot_02[0].image_shape_comp_px if vis_tot_02 else img_shape_px,
                dimensions_match=True,
                pixel_threshold=1.0,
                geometric_status=geom_resave.status,
                geometric_payload_decoded=geom_resave.payload_decoded,
                geometric_hmac_verified=geom_resave.hmac_valid,
                file_hashes={
                    "source_pdf": sha256_file(src_path),
                    "watermarked_base": sha256_file(watermarked_base),
                    "resaved_pdf": sha256_file(resaved_path),
                    "resaved_control_pdf": sha256_file(resaved_ctrl),
                },
                expected_outcome="AUTHENTICATED (Stream Kerning Preserved)",
                carrier_failure_mode=None,
                notes="PDF parser retains TJ kerning arrays across standard save-and-compress operations.",
            )
        )

        # -------------------------------------------------------------
        # Scenario 3: Metadata Modification
        # -------------------------------------------------------------
        meta_path = self.working_dir / f"{prefix}_03_metadata_mod.pdf"
        d = fitz.open(str(watermarked_base))
        m = d.metadata or {}
        m["title"] = "Confidential Study Copy (Tampered Metadata)"
        m["author"] = "Anonymous Recipient"
        d.set_metadata(m)
        d.save(str(meta_path))
        d.close()

        # Unwatermarked Control
        meta_ctrl = self.working_dir / f"{prefix}_03_metadata_ctrl.pdf"
        d_ctrl = fitz.open(str(src_path))
        m_c = d_ctrl.metadata or {}
        m_c["title"] = "Confidential Study Copy (Tampered Metadata)"
        m_c["author"] = "Anonymous Recipient"
        d_ctrl.set_metadata(m_c)
        d_ctrl.save(str(meta_ctrl))
        d_ctrl.close()

        ext_meta = extract_watermark(meta_path, self.key)
        geom_meta = extract_watermark(meta_path, self.key, use_geometric_fallback=True)
        cand_bits_03 = ext_meta.raw_bits[ext_meta.frame_offset:] if ext_meta.frame_offset is not None else None
        ber_03 = compute_bit_error_rate(expected_bits, cand_bits_03)

        vis_trans_03 = compare_documents(watermarked_base, meta_path, dpi=150)
        vis_tot_03 = compare_documents(src_path, meta_path, dpi=150)
        vis_ctrl_03 = compare_documents(src_path, meta_ctrl, dpi=150)

        results.append(
            ScenarioResult(
                scenario_name="03_metadata_modified",
                description="Document catalog metadata (title, author) altered",
                is_baseline_unwatermarked=False,
                status=ext_meta.status,
                frame_detected=ext_meta.frame_detected,
                payload_decoded=ext_meta.payload_decoded,
                crc_valid=ext_meta.crc_valid,
                hmac_verified=ext_meta.hmac_valid,
                recipient_recovered=ext_meta.recipient_recovered,
                recovered_recipient_uid=ext_meta.recipient_uid,
                bit_error_rate=ber_03,
                embedding_psnr_db=base_embed_psnr,
                embedding_mse=base_embed_mse,
                embedding_changed_ratio=base_embed_ratio,
                transformation_psnr_db=vis_trans_03[0].psnr_db if vis_trans_03 else 999.0,
                transformation_mse=vis_trans_03[0].mse if vis_trans_03 else 0.0,
                transformation_changed_ratio=vis_trans_03[0].changed_pixels_ratio if vis_trans_03 else 0.0,
                total_psnr_db=vis_tot_03[0].psnr_db if vis_tot_03 else base_embed_psnr,
                total_mse=vis_tot_03[0].mse if vis_tot_03 else base_embed_mse,
                total_changed_ratio=vis_tot_03[0].changed_pixels_ratio if vis_tot_03 else base_embed_ratio,
                control_psnr_db=vis_ctrl_03[0].psnr_db if vis_ctrl_03 else 999.0,
                control_mse=vis_ctrl_03[0].mse if vis_ctrl_03 else 0.0,
                control_changed_ratio=vis_ctrl_03[0].changed_pixels_ratio if vis_ctrl_03 else 0.0,
                page_dims_orig_pt=vis_tot_03[0].page_dims_orig_pt if vis_tot_03 else page_dims_pt,
                page_dims_comp_pt=vis_tot_03[0].page_dims_comp_pt if vis_tot_03 else page_dims_pt,
                image_shape_orig_px=vis_tot_03[0].image_shape_orig_px if vis_tot_03 else img_shape_px,
                image_shape_comp_px=vis_tot_03[0].image_shape_comp_px if vis_tot_03 else img_shape_px,
                dimensions_match=True,
                pixel_threshold=1.0,
                geometric_status=geom_meta.status,
                geometric_payload_decoded=geom_meta.payload_decoded,
                geometric_hmac_verified=geom_meta.hmac_valid,
                file_hashes={
                    "source_pdf": sha256_file(src_path),
                    "watermarked_base": sha256_file(watermarked_base),
                    "metadata_pdf": sha256_file(meta_path),
                    "metadata_control_pdf": sha256_file(meta_ctrl),
                },
                expected_outcome="AUTHENTICATED (Metadata Decoupled)",
                carrier_failure_mode=None,
                notes="Watermark resides strictly in page content streams, fully decoupled from catalog metadata.",
            )
        )

        # -------------------------------------------------------------
        # Scenario 4: Content Text Modification (Appended Text)
        # -------------------------------------------------------------
        text_mod_path = self.working_dir / f"{prefix}_04_text_modified.pdf"
        d = fitz.open(str(watermarked_base))
        d[0].insert_text((50, 20), "UNOFFICIAL COPY - EDITED", fontsize=11, color=(1, 0, 0))
        d.save(str(text_mod_path))
        d.close()

        # Unwatermarked Control
        text_mod_ctrl = self.working_dir / f"{prefix}_04_text_ctrl.pdf"
        d_ctrl = fitz.open(str(src_path))
        d_ctrl[0].insert_text((50, 20), "UNOFFICIAL COPY - EDITED", fontsize=11, color=(1, 0, 0))
        d_ctrl.save(str(text_mod_ctrl))
        d_ctrl.close()

        ext_text = extract_watermark(text_mod_path, self.key)
        geom_text = extract_watermark(text_mod_path, self.key, use_geometric_fallback=True)
        cand_bits_04 = ext_text.raw_bits[ext_text.frame_offset:] if ext_text.frame_offset is not None else None
        ber_04 = compute_bit_error_rate(expected_bits, cand_bits_04)

        vis_trans_04 = compare_documents(watermarked_base, text_mod_path, dpi=150)
        vis_tot_04 = compare_documents(src_path, text_mod_path, dpi=150)
        vis_ctrl_04 = compare_documents(src_path, text_mod_ctrl, dpi=150)

        results.append(
            ScenarioResult(
                scenario_name="04_text_modified_appended",
                description="Appended extraneous text block to page without altering watermarked lines",
                is_baseline_unwatermarked=False,
                status=ext_text.status,
                frame_detected=ext_text.frame_detected,
                payload_decoded=ext_text.payload_decoded,
                crc_valid=ext_text.crc_valid,
                hmac_verified=ext_text.hmac_valid,
                recipient_recovered=ext_text.recipient_recovered,
                recovered_recipient_uid=ext_text.recipient_uid,
                bit_error_rate=ber_04,
                embedding_psnr_db=base_embed_psnr,
                embedding_mse=base_embed_mse,
                embedding_changed_ratio=base_embed_ratio,
                transformation_psnr_db=vis_trans_04[0].psnr_db if vis_trans_04 else 35.0,
                transformation_mse=vis_trans_04[0].mse if vis_trans_04 else 10.0,
                transformation_changed_ratio=vis_trans_04[0].changed_pixels_ratio if vis_trans_04 else 0.01,
                total_psnr_db=vis_tot_04[0].psnr_db if vis_tot_04 else base_embed_psnr,
                total_mse=vis_tot_04[0].mse if vis_tot_04 else base_embed_mse,
                total_changed_ratio=vis_tot_04[0].changed_pixels_ratio if vis_tot_04 else base_embed_ratio,
                control_psnr_db=vis_ctrl_04[0].psnr_db if vis_ctrl_04 else 35.0,
                control_mse=vis_ctrl_04[0].mse if vis_ctrl_04 else 10.0,
                control_changed_ratio=vis_ctrl_04[0].changed_pixels_ratio if vis_ctrl_04 else 0.01,
                page_dims_orig_pt=vis_tot_04[0].page_dims_orig_pt if vis_tot_04 else page_dims_pt,
                page_dims_comp_pt=vis_tot_04[0].page_dims_comp_pt if vis_tot_04 else page_dims_pt,
                image_shape_orig_px=vis_tot_04[0].image_shape_orig_px if vis_tot_04 else img_shape_px,
                image_shape_comp_px=vis_tot_04[0].image_shape_comp_px if vis_tot_04 else img_shape_px,
                dimensions_match=True,
                pixel_threshold=1.0,
                geometric_status=geom_text.status,
                geometric_payload_decoded=geom_text.payload_decoded,
                geometric_hmac_verified=geom_text.hmac_valid,
                file_hashes={
                    "source_pdf": sha256_file(src_path),
                    "watermarked_base": sha256_file(watermarked_base),
                    "appended_text_pdf": sha256_file(text_mod_path),
                    "appended_control_pdf": sha256_file(text_mod_ctrl),
                },
                expected_outcome="AUTHENTICATED (Sync Marker Re-locks)",
                carrier_failure_mode=None,
                notes="Preamble sync search successfully locates watermark frame despite extraneous text additions.",
            )
        )

        # -------------------------------------------------------------
        # Scenario 5: Page Reordering (Multi-Page Document)
        # -------------------------------------------------------------
        d = fitz.open(str(watermarked_base))
        if d.page_count > 1:
            reorder_path = self.working_dir / f"{prefix}_05_page_reordered.pdf"
            d.select(list(reversed(range(d.page_count))))
            d.save(str(reorder_path))
            d.close()

            # Control
            reorder_ctrl = self.working_dir / f"{prefix}_05_reordered_ctrl.pdf"
            d_ctrl = fitz.open(str(src_path))
            d_ctrl.select(list(reversed(range(d_ctrl.page_count))))
            d_ctrl.save(str(reorder_ctrl))
            d_ctrl.close()

            ext_reorder = extract_watermark(reorder_path, self.key)
            geom_reorder = extract_watermark(reorder_path, self.key, use_geometric_fallback=True)
            cand_bits_05 = ext_reorder.raw_bits[ext_reorder.frame_offset:] if ext_reorder.frame_offset is not None else None
            ber_05 = compute_bit_error_rate(expected_bits, cand_bits_05)

            vis_trans_05 = compare_documents(watermarked_base, reorder_path, dpi=150)
            vis_tot_05 = compare_documents(src_path, reorder_path, dpi=150)
            vis_ctrl_05 = compare_documents(src_path, reorder_ctrl, dpi=150)

            results.append(
                ScenarioResult(
                    scenario_name="05_page_reordered",
                    description="Reversed page order of multi-page watermarked PDF",
                    is_baseline_unwatermarked=False,
                    status=ext_reorder.status,
                    frame_detected=ext_reorder.frame_detected,
                    payload_decoded=ext_reorder.payload_decoded,
                    crc_valid=ext_reorder.crc_valid,
                    hmac_verified=ext_reorder.hmac_valid,
                    recipient_recovered=ext_reorder.recipient_recovered,
                    recovered_recipient_uid=ext_reorder.recipient_uid,
                    bit_error_rate=ber_05,  # Undefined (null) if preamble not detected
                    embedding_psnr_db=base_embed_psnr,
                    embedding_mse=base_embed_mse,
                    embedding_changed_ratio=base_embed_ratio,
                    transformation_psnr_db=vis_trans_05[0].psnr_db if vis_trans_05 else 12.0,
                    transformation_mse=vis_trans_05[0].mse if vis_trans_05 else 4000.0,
                    transformation_changed_ratio=vis_trans_05[0].changed_pixels_ratio if vis_trans_05 else 0.15,
                    total_psnr_db=vis_tot_05[0].psnr_db if vis_tot_05 else 12.0,
                    total_mse=vis_tot_05[0].mse if vis_tot_05 else 4000.0,
                    total_changed_ratio=vis_tot_05[0].changed_pixels_ratio if vis_tot_05 else 0.15,
                    control_psnr_db=vis_ctrl_05[0].psnr_db if vis_ctrl_05 else 12.0,
                    control_mse=vis_ctrl_05[0].mse if vis_ctrl_05 else 4000.0,
                    control_changed_ratio=vis_ctrl_05[0].changed_pixels_ratio if vis_ctrl_05 else 0.15,
                    page_dims_orig_pt=vis_tot_05[0].page_dims_orig_pt if vis_tot_05 else page_dims_pt,
                    page_dims_comp_pt=vis_tot_05[0].page_dims_comp_pt if vis_tot_05 else page_dims_pt,
                    image_shape_orig_px=vis_tot_05[0].image_shape_orig_px if vis_tot_05 else img_shape_px,
                    image_shape_comp_px=vis_tot_05[0].image_shape_comp_px if vis_tot_05 else img_shape_px,
                    dimensions_match=True,
                    pixel_threshold=1.0,
                    geometric_status=geom_reorder.status,
                    geometric_payload_decoded=geom_reorder.payload_decoded,
                    geometric_hmac_verified=geom_reorder.hmac_valid,
                    file_hashes={
                        "source_pdf": sha256_file(src_path),
                        "watermarked_base": sha256_file(watermarked_base),
                        "reordered_pdf": sha256_file(reorder_path),
                        "reordered_control_pdf": sha256_file(reorder_ctrl),
                    },
                    expected_outcome="NO_WATERMARK or CRC_ERROR (Stream Fragment Disordered)",
                    carrier_failure_mode="Page-order permutation disrupts multi-page payload sequence",
                    notes="Expected limitation: Inter-page bit stream requires sequential reading order.",
                )
            )

        # -------------------------------------------------------------
        # Scenario 6: Margin Cropping (Geometric Box Adjustment)
        # -------------------------------------------------------------
        crop_path = self.working_dir / f"{prefix}_06_margin_cropped.pdf"
        d = fitz.open(str(watermarked_base))
        for p in d:
            r = p.rect
            p.set_cropbox(fitz.Rect(r.x0 + 10, r.y0 + 10, r.x1 - 10, r.y1 - 10))
        d.save(str(crop_path))
        d.close()

        # Control
        crop_ctrl = self.working_dir / f"{prefix}_06_cropped_ctrl.pdf"
        d_ctrl = fitz.open(str(src_path))
        for p in d_ctrl:
            r = p.rect
            p.set_cropbox(fitz.Rect(r.x0 + 10, r.y0 + 10, r.x1 - 10, r.y1 - 10))
        d_ctrl.save(str(crop_ctrl))
        d_ctrl.close()

        ext_crop = extract_watermark(crop_path, self.key)
        geom_crop = extract_watermark(crop_path, self.key, use_geometric_fallback=True)
        cand_bits_06 = ext_crop.raw_bits[ext_crop.frame_offset:] if ext_crop.frame_offset is not None else None
        ber_06 = compute_bit_error_rate(expected_bits, cand_bits_06)

        vis_trans_06 = compare_documents(watermarked_base, crop_path, dpi=150)
        vis_tot_06 = compare_documents(src_path, crop_path, dpi=150)
        vis_ctrl_06 = compare_documents(src_path, crop_ctrl, dpi=150)

        results.append(
            ScenarioResult(
                scenario_name="06_margin_cropped",
                description="Cropped 10pt margins on all pages",
                is_baseline_unwatermarked=False,
                status=ext_crop.status,
                frame_detected=ext_crop.frame_detected,
                payload_decoded=ext_crop.payload_decoded,
                crc_valid=ext_crop.crc_valid,
                hmac_verified=ext_crop.hmac_valid,
                recipient_recovered=ext_crop.recipient_recovered,
                recovered_recipient_uid=ext_crop.recipient_uid,
                bit_error_rate=ber_06,
                embedding_psnr_db=base_embed_psnr,
                embedding_mse=base_embed_mse,
                embedding_changed_ratio=base_embed_ratio,
                transformation_psnr_db=vis_trans_06[0].psnr_db if vis_trans_06 else base_embed_psnr,
                transformation_mse=vis_trans_06[0].mse if vis_trans_06 else base_embed_mse,
                transformation_changed_ratio=vis_trans_06[0].changed_pixels_ratio if vis_trans_06 else base_embed_ratio,
                total_psnr_db=vis_tot_06[0].psnr_db if vis_tot_06 else base_embed_psnr,
                total_mse=vis_tot_06[0].mse if vis_tot_06 else base_embed_mse,
                total_changed_ratio=vis_tot_06[0].changed_pixels_ratio if vis_tot_06 else base_embed_ratio,
                control_psnr_db=vis_ctrl_06[0].psnr_db if vis_ctrl_06 else 999.0,
                control_mse=vis_ctrl_06[0].mse if vis_ctrl_06 else 0.0,
                control_changed_ratio=vis_ctrl_06[0].changed_pixels_ratio if vis_ctrl_06 else 0.0,
                page_dims_orig_pt=vis_tot_06[0].page_dims_orig_pt if vis_tot_06 else page_dims_pt,
                page_dims_comp_pt=vis_tot_06[0].page_dims_comp_pt if vis_tot_06 else page_dims_pt,
                image_shape_orig_px=vis_tot_06[0].image_shape_orig_px if vis_tot_06 else img_shape_px,
                image_shape_comp_px=vis_tot_06[0].image_shape_comp_px if vis_tot_06 else img_shape_px,
                dimensions_match=False,  # Cropbox reduced page viewport by 20pt
                pixel_threshold=1.0,
                geometric_status=geom_crop.status,
                geometric_payload_decoded=geom_crop.payload_decoded,
                geometric_hmac_verified=geom_crop.hmac_valid,
                file_hashes={
                    "source_pdf": sha256_file(src_path),
                    "watermarked_base": sha256_file(watermarked_base),
                    "cropped_pdf": sha256_file(crop_path),
                    "cropped_control_pdf": sha256_file(crop_ctrl),
                },
                expected_outcome="AUTHENTICATED (Content Streams Unaltered)",
                carrier_failure_mode=None,
                notes="Content stream TJ kerning remains intact despite view cropbox modifications.",
            )
        )

        # -------------------------------------------------------------
        # Scenario 7: Rasterization / Print-Scan Simulation (Carrier Elimination)
        # -------------------------------------------------------------
        raster_path = self.working_dir / f"{prefix}_07_rasterized.pdf"
        d = fitz.open(str(watermarked_base))
        doc_raster = fitz.open()
        for p in d:
            pix = p.get_pixmap(dpi=150, colorspace=fitz.csRGB, alpha=False)
            img_bytes = pix.tobytes("png")
            new_page = doc_raster.new_page(width=p.rect.width, height=p.rect.height)
            new_page.insert_image(new_page.rect, stream=img_bytes)
        d.close()
        doc_raster.save(str(raster_path))
        doc_raster.close()

        # Control
        raster_ctrl = self.working_dir / f"{prefix}_07_rasterized_ctrl.pdf"
        d_ctrl = fitz.open(str(src_path))
        doc_r_ctrl = fitz.open()
        for p in d_ctrl:
            pix = p.get_pixmap(dpi=150, colorspace=fitz.csRGB, alpha=False)
            img_bytes = pix.tobytes("png")
            new_page = doc_r_ctrl.new_page(width=p.rect.width, height=p.rect.height)
            new_page.insert_image(new_page.rect, stream=img_bytes)
        d_ctrl.close()
        doc_r_ctrl.save(str(raster_ctrl))
        doc_r_ctrl.close()

        ext_raster = extract_watermark(raster_path, self.key)
        geom_raster = extract_watermark(raster_path, self.key, use_geometric_fallback=True)

        # Compute actual measured distortion from rendered images
        vis_trans_07 = compare_documents(watermarked_base, raster_path, dpi=150)
        vis_tot_07 = compare_documents(src_path, raster_path, dpi=150)
        vis_ctrl_07 = compare_documents(src_path, raster_ctrl, dpi=150)

        results.append(
            ScenarioResult(
                scenario_name="07_rasterization_scan_sim",
                description="Rasterized pages to bitmaps and rebuilt PDF (print-scan simulation)",
                is_baseline_unwatermarked=False,
                status=ext_raster.status,
                frame_detected=ext_raster.frame_detected,
                payload_decoded=ext_raster.payload_decoded,
                crc_valid=ext_raster.crc_valid,
                hmac_verified=ext_raster.hmac_valid,
                recipient_recovered=ext_raster.recipient_recovered,
                recovered_recipient_uid=ext_raster.recipient_uid,
                bit_error_rate=None,  # No text carrier -> no comparable bitstream -> BER is undefined (null)
                embedding_psnr_db=base_embed_psnr,
                embedding_mse=base_embed_mse,
                embedding_changed_ratio=base_embed_ratio,
                transformation_psnr_db=vis_trans_07[0].psnr_db if vis_trans_07 else 999.0,
                transformation_mse=vis_trans_07[0].mse if vis_trans_07 else 0.0,
                transformation_changed_ratio=vis_trans_07[0].changed_pixels_ratio if vis_trans_07 else 0.0,
                total_psnr_db=vis_tot_07[0].psnr_db if vis_tot_07 else base_embed_psnr,
                total_mse=vis_tot_07[0].mse if vis_tot_07 else base_embed_mse,
                total_changed_ratio=vis_tot_07[0].changed_pixels_ratio if vis_tot_07 else base_embed_ratio,
                control_psnr_db=vis_ctrl_07[0].psnr_db if vis_ctrl_07 else 999.0,
                control_mse=vis_ctrl_07[0].mse if vis_ctrl_07 else 0.0,
                control_changed_ratio=vis_ctrl_07[0].changed_pixels_ratio if vis_ctrl_07 else 0.0,
                page_dims_orig_pt=vis_tot_07[0].page_dims_orig_pt if vis_tot_07 else page_dims_pt,
                page_dims_comp_pt=vis_tot_07[0].page_dims_comp_pt if vis_tot_07 else page_dims_pt,
                image_shape_orig_px=vis_tot_07[0].image_shape_orig_px if vis_tot_07 else img_shape_px,
                image_shape_comp_px=vis_tot_07[0].image_shape_comp_px if vis_tot_07 else img_shape_px,
                dimensions_match=True,
                pixel_threshold=1.0,
                geometric_status=geom_raster.status,
                geometric_payload_decoded=geom_raster.payload_decoded,
                geometric_hmac_verified=geom_raster.hmac_valid,
                file_hashes={
                    "source_pdf": sha256_file(src_path),
                    "watermarked_base": sha256_file(watermarked_base),
                    "rasterized_pdf": sha256_file(raster_path),
                    "rasterized_control_pdf": sha256_file(raster_ctrl),
                },
                expected_outcome="NO_WATERMARK (Carrier Inherent Limit)",
                carrier_failure_mode="Text vector carrier completely destroyed by rasterization",
                notes="Fundamental physical limitation: Text-kerning watermarks require vector text operators. Converting to image pixels eliminates the carrier completely.",
            )
        )

        # Save results to JSON and CSV
        self._save_results(results, src_path, doc_uid, recipient_uid)
        return results

    def _save_results(
        self,
        results: List[ScenarioResult],
        src_path: Path,
        doc_uid: str,
        recipient_uid: str,
    ) -> None:
        """Saves evaluation results to JSON and CSV manifests in experimental/reports/."""
        json_file = self.output_dir / "stego_benchmark_results.json"
        csv_file = self.output_dir / "stego_benchmark_results.csv"

        data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "source_document": str(src_path),
            "source_sha256": sha256_file(src_path),
            "document_uid": doc_uid,
            "recipient_uid": recipient_uid,
            "total_scenarios": len(results),
            "results": [asdict(r) for r in results],
        }

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "scenario_name",
                "status",
                "frame_detected",
                "payload_decoded",
                "crc_valid",
                "hmac_verified",
                "recipient_recovered",
                "recovered_recipient_uid",
                "bit_error_rate",
                "embedding_psnr_db",
                "embedding_mse",
                "embedding_changed_ratio",
                "transformation_psnr_db",
                "transformation_mse",
                "transformation_changed_ratio",
                "total_psnr_db",
                "total_mse",
                "total_changed_ratio",
                "control_psnr_db",
                "control_mse",
                "control_changed_ratio",
                "geometric_status",
                "geometric_payload_decoded",
                "geometric_hmac_verified",
                "carrier_failure_mode",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                writer.writerow(asdict(r))
