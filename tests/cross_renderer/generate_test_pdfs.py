"""
Synthetic PDF Generator for Cross-Renderer Coordinate Mapping Validation.

Generates 8 test PDFs:
- 4 rotations: 0, 90, 180, 270 with standard CropBox == MediaBox [0, 0, 612, 792].
- 4 rotations: 0, 90, 180, 270 with offset CropBox [50, 40, 550, 750] != MediaBox [0, 0, 612, 792].
- Each page contains an annotation with exact known /Rect geometry.
"""
from __future__ import annotations

import json
from pathlib import Path
import fitz

OUTPUT_DIR = Path(__file__).resolve().parent / "generated_pdfs"


def generate_synthetic_pdfs() -> list[dict]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []

    rotations = [0, 90, 180, 270]
    cases = [
        ("standard", [0.0, 0.0, 612.0, 792.0], [0.0, 0.0, 612.0, 792.0], [100.0, 150.0, 250.0, 200.0]),
        ("offset", [0.0, 0.0, 612.0, 792.0], [50.0, 40.0, 550.0, 750.0], [150.0, 190.0, 300.0, 240.0]),
    ]

    for case_name, mediabox, cropbox, raw_rect in cases:
        for rot in rotations:
            doc = fitz.open()
            page = doc.new_page(width=mediabox[2], height=mediabox[3])
            page.set_cropbox(fitz.Rect(cropbox))
            page.set_rotation(rot)

            # In PyMuPDF, add_rect_annot expects rect in current page coordinates.
            # Standard PDF /Rect [llx, lly, urx, ury] in user space:
            # llx = raw_rect[0], lly = raw_rect[1], urx = raw_rect[2], ury = raw_rect[3]
            # Convert to PyMuPDF page coordinate space:
            # PyMuPDF page.rect is relative to cropbox: (0, 0, crop_width, crop_height)
            crop_h = cropbox[3] - cropbox[1]
            pymupdf_x0 = raw_rect[0] - cropbox[0]
            pymupdf_y0 = (cropbox[3] - raw_rect[3])
            pymupdf_x1 = raw_rect[2] - cropbox[0]
            pymupdf_y1 = (cropbox[3] - raw_rect[1])
            fitz_rect = fitz.Rect(pymupdf_x0, pymupdf_y0, pymupdf_x1, pymupdf_y1)

            annot = page.add_rect_annot(fitz_rect)
            annot.set_info(title="SPDF_TEST_ANNOT", content="Cross-renderer coordinate test")
            annot.update()

            filename = f"test_{case_name}_rot{rot}.pdf"
            file_path = OUTPUT_DIR / filename
            doc.save(str(file_path))
            doc.close()

            # Re-open and record actual PyMuPDF inspection metadata
            doc_verify = fitz.open(str(file_path))
            v_page = doc_verify[0]
            v_annot = next(v_page.annots())
            annot_rect = [float(v_annot.rect.x0), float(v_annot.rect.y0), float(v_annot.rect.x1), float(v_annot.rect.y1)]

            # Four corners in raw PDF user space [x, y]:
            corners = {
                "TL": [raw_rect[0], raw_rect[3]],
                "TR": [raw_rect[2], raw_rect[3]],
                "BR": [raw_rect[2], raw_rect[1]],
                "BL": [raw_rect[0], raw_rect[1]],
            }

            manifest.append({
                "case_name": case_name,
                "rotation": rot,
                "file_path": str(file_path),
                "filename": filename,
                "mediabox": mediabox,
                "cropbox": cropbox,
                "page_rect": [float(v_page.rect.x0), float(v_page.rect.y0), float(v_page.rect.x1), float(v_page.rect.y1)],
                "raw_rect": raw_rect,
                "annot_rect": annot_rect,
                "corners": corners,
            })
            doc_verify.close()

    manifest_path = OUTPUT_DIR / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return manifest


if __name__ == "__main__":
    items = generate_synthetic_pdfs()
    print(f"Generated {len(items)} synthetic test PDFs in {OUTPUT_DIR}")
