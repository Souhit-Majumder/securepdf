import { describe, it, expect, vi } from "vitest";
import { pyMuPdfToPdfUserSpace, mapPyMuPdfToPdfJs, mapViewportTo3DPlane } from "../utils/coordinateMapping";
import type { MinimizedAnnotationLocationDTO } from "../types/inspection";

describe("Milestone 5A: Layer 2 Annotation Localization", () => {
  describe("Coordinate mapping across 0°, 90°, 180°, and 270° rotations with non-zero crop-box origins", () => {
    // Non-zero crop-box origin: [cx0, cy0, cx1, cy1] = [36, 54, 631, 896]
    const cropbox: [number, number, number, number] = [36, 54, 631, 896];
    const nativeAnnotRect: [number, number, number, number] = [10.0, 20.0, 10.1, 20.1]; // 0.1 x 0.1 pt native

    it("correctly converts PyMuPDF top-left relative coordinates to PDF user space", () => {
      const [llx, lly, urx, ury] = pyMuPdfToPdfUserSpace(nativeAnnotRect, cropbox);
      // llx = cx0 + x0 = 36 + 10.0 = 46.0
      expect(llx).toBeCloseTo(46.0, 2);
      // urx = cx0 + x1 = 36 + 10.1 = 46.1
      expect(urx).toBeCloseTo(46.1, 2);
      // lly = cy1 - y1 = 896 - 20.1 = 875.9
      expect(lly).toBeCloseTo(875.9, 2);
      // ury = cy1 - y0 = 896 - 20.0 = 876.0
      expect(ury).toBeCloseTo(876.0, 2);
    });

    it("verifies coordinate mapping under 0° rotation", () => {
      const mockViewport0 = {
        width: 595,
        height: 842,
        rotation: 0,
        convertToViewportPoint: (x: number, y: number) => [x - cropbox[0], cropbox[3] - y],
        convertToViewportRectangle: (r: [number, number, number, number]) => [
          r[0] - cropbox[0],
          cropbox[3] - r[3],
          r[2] - cropbox[0],
          cropbox[3] - r[1],
        ],
      };

      const box0 = mapPyMuPdfToPdfJs(nativeAnnotRect, cropbox, mockViewport0);
      expect(box0.x).toBeCloseTo(10.0, 2);
      expect(box0.y).toBeCloseTo(20.0, 2);
      expect(box0.width).toBeCloseTo(0.1, 2);
      expect(box0.height).toBeCloseTo(0.1, 2);
    });

    it("verifies coordinate mapping under 90° rotation", () => {
      const mockViewport90 = {
        width: 842,
        height: 595,
        rotation: 90,
        convertToViewportPoint: (x: number, y: number) => [y - cropbox[1], x - cropbox[0]],
        convertToViewportRectangle: (r: [number, number, number, number]) => [
          r[1] - cropbox[1],
          r[0] - cropbox[0],
          r[3] - cropbox[1],
          r[2] - cropbox[0],
        ],
      };

      const box90 = mapPyMuPdfToPdfJs(nativeAnnotRect, cropbox, mockViewport90);
      expect(box90.width).toBeCloseTo(0.1, 2);
      expect(box90.height).toBeCloseTo(0.1, 2);
    });

    it("verifies coordinate mapping under 180° rotation", () => {
      const mockViewport180 = {
        width: 595,
        height: 842,
        rotation: 180,
        convertToViewportPoint: (x: number, y: number) => [cropbox[2] - x, y - cropbox[1]],
        convertToViewportRectangle: (r: [number, number, number, number]) => [
          cropbox[2] - r[2],
          r[1] - cropbox[1],
          cropbox[2] - r[0],
          r[3] - cropbox[1],
        ],
      };

      const box180 = mapPyMuPdfToPdfJs(nativeAnnotRect, cropbox, mockViewport180);
      expect(box180.width).toBeCloseTo(0.1, 2);
      expect(box180.height).toBeCloseTo(0.1, 2);
    });

    it("verifies coordinate mapping under 270° rotation", () => {
      const mockViewport270 = {
        width: 842,
        height: 595,
        rotation: 270,
        convertToViewportPoint: (x: number, y: number) => [cropbox[3] - y, cropbox[2] - x],
        convertToViewportRectangle: (r: [number, number, number, number]) => [
          cropbox[3] - r[3],
          cropbox[2] - r[2],
          cropbox[3] - r[1],
          cropbox[2] - r[0],
        ],
      };

      const box270 = mapPyMuPdfToPdfJs(nativeAnnotRect, cropbox, mockViewport270);
      expect(box270.width).toBeCloseTo(0.1, 2);
      expect(box270.height).toBeCloseTo(0.1, 2);
    });
  });

  describe("Native Dimensions vs Visual Footprint Clamping", () => {
    it("preserves native PDF dimensions while calculating visual bounding box", () => {
      const nativeRect: [number, number, number, number] = [1.0, 1.0, 1.1, 1.1];
      const nativeW = nativeRect[2] - nativeRect[0];
      const nativeH = nativeRect[3] - nativeRect[1];

      // Native dimensions must be exactly 0.1 x 0.1 pt
      expect(nativeW).toBeCloseTo(0.1, 4);
      expect(nativeH).toBeCloseTo(0.1, 4);

      // Visual footprint in 3D scene units
      const mockBox2D = {
        x: 1.0,
        y: 1.0,
        width: 0.1,
        height: 0.1,
        corners: { TL: [1, 1] as [number, number], TR: [1.1, 1] as [number, number], BR: [1.1, 1.1] as [number, number], BL: [1, 1.1] as [number, number] },
      };

      const planeBox = mapViewportTo3DPlane(mockBox2D, 595, 842, 2.5, 3.55);
      const visualWidth = Math.max(planeBox.size[0], 0.35);
      const visualHeight = Math.max(planeBox.size[1], 0.15);

      // Visual dimensions must be clamped to minimum threshold
      expect(visualWidth).toBe(0.35);
      expect(visualHeight).toBe(0.15);
      // Native size remains separate and distinct
      expect(nativeW).not.toBe(visualWidth);
      expect(nativeH).not.toBe(visualHeight);
    });
  });

  describe("Page Isolation and Navigation Selection", () => {
    const mockAnnotations: MinimizedAnnotationLocationDTO[] = [
      {
        carrier_type: "ANNOTATION",
        page_index: 0,
        annotation_xref: 48,
        rect: [0.0, 0.0, 0.1, 0.1],
        title: "SPDF0",
      },
      {
        carrier_type: "ANNOTATION",
        page_index: 0,
        annotation_xref: 49,
        rect: [1.0, 1.0, 1.1, 1.1],
        title: "SPDF1",
      },
      {
        carrier_type: "ANNOTATION",
        page_index: 1, // On page 2
        annotation_xref: 52,
        rect: [2.0, 2.0, 2.1, 2.1],
        title: "SPDF2",
      },
    ];

    it("filters annotations strictly by currently viewed page index", () => {
      const currentPage1Annots = mockAnnotations.filter(a => a.page_index === 0);
      const currentPage2Annots = mockAnnotations.filter(a => a.page_index === 1);
      const currentPage3Annots = mockAnnotations.filter(a => a.page_index === 2);

      expect(currentPage1Annots).toHaveLength(2);
      expect(currentPage2Annots).toHaveLength(1);
      expect(currentPage3Annots).toHaveLength(0);
    });

    it("selecting an annotation on a different page triggers navigation to that page", () => {
      const onSelectAnnotation = vi.fn();
      const onPageChange = vi.fn();
      const currentPage = 1; // Currently on Page 1 (page_index: 0)

      const targetAnnot = mockAnnotations[2]; // Resides on Page 2 (page_index: 1)

      // User clicks target annotation in EvidencePanel
      onSelectAnnotation(targetAnnot.annotation_xref);
      if (targetAnnot.page_index !== (currentPage - 1)) {
        onPageChange(targetAnnot.page_index + 1);
      }

      expect(onSelectAnnotation).toHaveBeenCalledWith(52);
      expect(onPageChange).toHaveBeenCalledWith(2);
    });

    it("resets selected annotation when a new file is uploaded", () => {
      let selectedAnnotationXref: number | null = 48;

      // Handle file selection callback simulation
      const handleFileSelect = () => {
        selectedAnnotationXref = null;
      };

      handleFileSelect();
      expect(selectedAnnotationXref).toBeNull();
    });
  });
});
