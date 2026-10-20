/**
 * Comprehensive cross-renderer coordinate mapping verification test.
 * Compares PyMuPDF reported annotation geometry against PDF.js viewport coordinates
 * across all 8 synthetic configurations (4 rotations x standard/offset CropBoxes).
 */
import { describe, it, expect } from "vitest";
import * as fs from "fs";
import * as path from "path";
import * as pdfjsLib from "pdfjs-dist/legacy/build/pdf.mjs";
import { mapPyMuPdfToPdfJs, pyMuPdfToPdfUserSpace } from "../utils/coordinateMapping";

interface ManifestItem {
  case_name: string;
  rotation: 0 | 90 | 180 | 270;
  file_path: string;
  filename: string;
  mediabox: [number, number, number, number];
  cropbox: [number, number, number, number];
  page_rect: [number, number, number, number];
  raw_rect: [number, number, number, number];
  annot_rect: [number, number, number, number];
  corners: {
    TL: [number, number];
    TR: [number, number];
    BR: [number, number];
    BL: [number, number];
  };
}

describe("Cross-Renderer Coordinate Mapping Verification (PyMuPDF <-> PDF.js)", () => {
  const manifestPath = path.resolve(
    __dirname,
    "../../../tests/cross_renderer/generated_pdfs/manifest.json"
  );

  if (!fs.existsSync(manifestPath)) {
    it.skip("Manifest not found on disk; skipping headless cross-renderer test", () => {});
    return;
  }

  const manifest: ManifestItem[] = JSON.parse(fs.readFileSync(manifestPath, "utf-8"));

  it("verifies all 8 synthetic configurations (4 rotations x standard/offset CropBoxes)", async () => {
    expect(manifest.length).toBe(8);

    for (const item of manifest) {
      const pdfBytes = new Uint8Array(fs.readFileSync(item.file_path));
      const loadingTask = pdfjsLib.getDocument({
        data: pdfBytes,
        useSystemFonts: true,
        disableFontFace: true,
      });

      const pdfDoc = await loadingTask.promise;
      expect(pdfDoc.numPages).toBe(1);

      const page = await pdfDoc.getPage(1);
      const viewport = page.getViewport({ scale: 1.0, rotation: page.rotate });

      // Ensure PDF.js rotation matches the tested rotation
      expect(page.rotate % 360).toBe(item.rotation);

      // Verify mapping: PyMuPDF annot.rect -> PDF.js viewport
      const mappedBox = mapPyMuPdfToPdfJs(item.annot_rect, item.cropbox, viewport);

      // Compute ground truth corners directly from raw PDF user units via PDF.js native API
      const [llx, lly, urx, ury] = item.raw_rect;
      const expectedTL = viewport.convertToViewportPoint(llx, ury);
      const expectedTR = viewport.convertToViewportPoint(urx, ury);
      const expectedBR = viewport.convertToViewportPoint(urx, lly);
      const expectedBL = viewport.convertToViewportPoint(llx, lly);

      // Assert that our pyMuPdfToPdfUserSpace accurately reconstructs the PDF user rectangle
      // Note: PyMuPDF adds ~1.0pt margin for rectangle annotation borders by default.
      const reconstructed = pyMuPdfToPdfUserSpace(item.annot_rect, item.cropbox);
      expect(Math.abs(reconstructed[0] - llx)).toBeLessThanOrEqual(1.5);
      expect(Math.abs(reconstructed[1] - lly)).toBeLessThanOrEqual(1.5);
      expect(Math.abs(reconstructed[2] - urx)).toBeLessThanOrEqual(1.5);
      expect(Math.abs(reconstructed[3] - ury)).toBeLessThanOrEqual(1.5);

      // Assert that mapped corners match PDF.js native viewport points within 1.5 px
      // (accounting for PyMuPDF's 1.0pt stroke margin)
      expect(Math.abs(mappedBox.corners.TL[0] - expectedTL[0])).toBeLessThanOrEqual(1.5);
      expect(Math.abs(mappedBox.corners.TL[1] - expectedTL[1])).toBeLessThanOrEqual(1.5);

      expect(Math.abs(mappedBox.corners.TR[0] - expectedTR[0])).toBeLessThanOrEqual(1.5);
      expect(Math.abs(mappedBox.corners.TR[1] - expectedTR[1])).toBeLessThanOrEqual(1.5);

      expect(Math.abs(mappedBox.corners.BR[0] - expectedBR[0])).toBeLessThanOrEqual(1.5);
      expect(Math.abs(mappedBox.corners.BR[1] - expectedBR[1])).toBeLessThanOrEqual(1.5);

      expect(Math.abs(mappedBox.corners.BL[0] - expectedBL[0])).toBeLessThanOrEqual(1.5);
      expect(Math.abs(mappedBox.corners.BL[1] - expectedBL[1])).toBeLessThanOrEqual(1.5);
    }
  });
});
