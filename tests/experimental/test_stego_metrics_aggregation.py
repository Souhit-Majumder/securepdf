"""
Regression and mathematical correctness tests for document-level distortion aggregation.
Validates that multi-page MSE and PSNR aggregations are computed across all pixels and pages,
confirming the exact derivation between single-page metrics (e.g. 18.03 dB) and document-level metrics (18.54 dB).
"""
import math
import pytest
from experimental.comparator import DistortionMetrics, aggregate_document_distortion


def test_document_distortion_equal_page_sizes_5_pages():
    """
    Validates exact aggregation for the 5-page sample_lecture.pdf:
    Page 1: MSE = 1023.9014 (PSNR = 18.03 dB)
    Page 2: MSE = 1239.1579 (PSNR = 17.20 dB)
    Page 3: MSE = 1123.9995 (PSNR = 17.62 dB)
    Page 4: MSE = 867.9457  (PSNR = 18.75 dB)
    Page 5: MSE = 300.1096  (PSNR = 23.36 dB)

    Under equal page dimensions (2,176,200 pixels/page):
    Mean MSE = 911.0228
    Aggregate PSNR = 10 * log10(255^2 / 911.0228) = 18.5356 dB -> 18.54 dB.
    """
    page_mses = [1023.9014, 1239.1579, 1123.9995, 867.9457, 300.1096]
    pixels_per_page = 2176200

    metrics = [
        DistortionMetrics(
            page_number=i + 1,
            page_dims_orig_pt=(720.0, 540.0),
            page_dims_comp_pt=(720.0, 540.0),
            image_shape_orig_px=(1125, 1500, 3),
            image_shape_comp_px=(1125, 1500, 3),
            threshold=1.0,
            mse=mse,
            psnr_db=round(10.0 * math.log10((255.0 ** 2) / mse), 2),
            changed_pixels_count=int(0.01 * pixels_per_page),
            total_pixels_count=pixels_per_page,
            changed_pixels_ratio=0.01,
            is_visually_identical=False,
            dimensions_match=True,
        )
        for i, mse in enumerate(page_mses)
    ]

    # Verify Page 1 in isolation gives the previously reported 18.03 dB
    assert metrics[0].psnr_db == 18.03

    # Aggregate across all 5 pages
    summary = aggregate_document_distortion(metrics)

    assert summary.total_pages == 5
    assert summary.total_pixels_count == 5 * pixels_per_page
    assert summary.aggregate_mse == 911.0228
    assert summary.aggregate_psnr_db == 18.54
    assert summary.all_dimensions_match is True
    assert len(summary.page_metrics) == 5


def test_document_distortion_weighted_unequal_pages():
    """Validates pixel-weighted aggregation when pages have unequal pixel dimensions."""
    # Page 1: 1,000,000 pixels, MSE = 100.0
    # Page 2: 3,000,000 pixels, MSE = 400.0
    # Weighted MSE = (1M * 100 + 3M * 400) / 4M = (100M + 1200M) / 4M = 1300 / 4 = 325.0
    # Weighted PSNR = 10 * log10(255^2 / 325.0) = 23.01 dB
    m1 = DistortionMetrics(
        page_number=1,
        page_dims_orig_pt=(500, 500),
        page_dims_comp_pt=(500, 500),
        image_shape_orig_px=(1000, 1000, 3),
        image_shape_comp_px=(1000, 1000, 3),
        threshold=1.0,
        mse=100.0,
        psnr_db=round(10.0 * math.log10((255.0 ** 2) / 100.0), 2),
        changed_pixels_count=10000,
        total_pixels_count=1000000,
        changed_pixels_ratio=0.01,
        is_visually_identical=False,
        dimensions_match=True,
    )
    m2 = DistortionMetrics(
        page_number=2,
        page_dims_orig_pt=(500, 1500),
        page_dims_comp_pt=(500, 1500),
        image_shape_orig_px=(1000, 3000, 3),
        image_shape_comp_px=(1000, 3000, 3),
        threshold=1.0,
        mse=400.0,
        psnr_db=round(10.0 * math.log10((255.0 ** 2) / 400.0), 2),
        changed_pixels_count=30000,
        total_pixels_count=3000000,
        changed_pixels_ratio=0.01,
        is_visually_identical=False,
        dimensions_match=True,
    )

    summary = aggregate_document_distortion([m1, m2])
    assert summary.total_pixels_count == 4000000
    assert summary.aggregate_mse == 325.0
    expected_psnr = round(10.0 * math.log10((255.0 ** 2) / 325.0), 2)
    assert summary.aggregate_psnr_db == expected_psnr


def test_document_distortion_identical_pages():
    """Validates that zero MSE across all pages produces sentinel 999.0 dB and visually identical flag."""
    m = DistortionMetrics(
        page_number=1,
        page_dims_orig_pt=(600, 800),
        page_dims_comp_pt=(600, 800),
        image_shape_orig_px=(600, 800, 3),
        image_shape_comp_px=(600, 800, 3),
        threshold=1.0,
        mse=0.0,
        psnr_db=999.0,
        changed_pixels_count=0,
        total_pixels_count=480000,
        changed_pixels_ratio=0.0,
        is_visually_identical=True,
        dimensions_match=True,
    )
    summary = aggregate_document_distortion([m])
    assert summary.aggregate_mse == 0.0
    assert summary.aggregate_psnr_db == 999.0
    assert summary.is_visually_identical is True


def test_exported_benchmark_artifacts_consistency():
    """
    Validates that exported benchmark artifacts (JSON, CSV, per-page metrics) agree exactly:
    - Every scenario in JSON has mathematical consistency between per_page_metrics and total_mse/total_psnr.
    - Every row in CSV matches the corresponding JSON scenario metrics.
    - Scenario 01 embedding distortion matches total distortion.
    """
    import csv, json
    from pathlib import Path
    from experimental.config import REPORTS_DIR

    json_path = REPORTS_DIR / "stego_benchmark_results.json"
    csv_path = REPORTS_DIR / "stego_benchmark_results.csv"

    if not json_path.exists() or not csv_path.exists():
        pytest.skip("Benchmark artifacts not yet generated on disk")

    with open(json_path, encoding="utf-8") as f:
        json_data = json.load(f)

    with open(csv_path, encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))

    json_results = json_data.get("results", [])
    assert len(json_results) == len(csv_rows)

    for s_json, s_csv in zip(json_results, csv_rows):
        assert s_json["scenario_name"] == s_csv["scenario_name"]
        assert s_json["status"] == s_csv["status"]

        # If per_page_metrics is present, verify exact mathematical aggregation
        if s_json.get("per_page_metrics"):
            reconstructed_metrics = [
                DistortionMetrics(
                    page_number=pm["page_number"],
                    page_dims_orig_pt=tuple(pm["page_dims_orig_pt"]),
                    page_dims_comp_pt=tuple(pm["page_dims_comp_pt"]),
                    image_shape_orig_px=tuple(pm["image_shape_orig_px"]),
                    image_shape_comp_px=tuple(pm["image_shape_comp_px"]),
                    threshold=pm["threshold"],
                    mse=pm["mse"],
                    psnr_db=pm["psnr_db"],
                    changed_pixels_count=pm["changed_pixels_count"],
                    total_pixels_count=pm["total_pixels_count"],
                    changed_pixels_ratio=pm["changed_pixels_ratio"],
                    is_visually_identical=pm["is_visually_identical"],
                    dimensions_match=pm["dimensions_match"],
                )
                for pm in s_json["per_page_metrics"]
            ]
            agg = aggregate_document_distortion(reconstructed_metrics)
            assert round(agg.aggregate_mse, 4) == round(s_json["total_mse"], 4)
            assert round(agg.aggregate_psnr_db, 2) == round(s_json["total_psnr_db"], 2)
            assert round(agg.changed_pixels_ratio, 6) == round(s_json["total_changed_ratio"], 6)

        # CSV fields match JSON fields
        assert float(s_csv["total_psnr_db"]) == pytest.approx(s_json["total_psnr_db"], abs=0.01)
        assert float(s_csv["total_mse"]) == pytest.approx(s_json["total_mse"], abs=0.001)
        assert float(s_csv["total_changed_ratio"]) == pytest.approx(s_json["total_changed_ratio"], abs=1e-5)

