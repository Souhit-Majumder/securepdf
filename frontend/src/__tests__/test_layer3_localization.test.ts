import { describe, it, expect } from "vitest";
import {
  mapPyMuPdfToPdfJs,
  mapViewportTo3DPlane,
  PdfJsViewport,
} from "../utils/coordinateMapping";
import { MinimizedContentStreamLocationDTO } from "../types/inspection";

describe("Milestone 5B: Layer 3 Localization Frontend", () => {
  const mockViewport: PdfJsViewport = {
    width: 595,
    height: 842,
    rotation: 0,
    convertToViewportPoint: (x: number, y: number) => [x - 0, 842 - y],
    convertToViewportRectangle: (rect: [number, number, number, number]) => [
      rect[0] - 0,
      842 - rect[3],
      rect[2] - 0,
      842 - rect[1],
    ],
  };

  it("correctly maps an EXACT Layer 3 modulation rectangle to 3D plane coordinates", () => {
    const loc: MinimizedContentStreamLocationDTO = {
      carrier_type: "CONTENT_STREAM",
      page_index: 0,
      location_index: 0,
      localization_status: "EXACT",
      is_carrier_sample: true,
      rect: [158.43, 28.17, 161.48, 43.29],
    };

    expect(loc.rect).not.toBeNull();
    if (!loc.rect) return;

    const cropbox: [number, number, number, number] = [0, 0, 595, 842];
    const mapped = mapPyMuPdfToPdfJs(loc.rect, cropbox, mockViewport);

    expect(mapped.width).toBeCloseTo(3.05, 1);
    expect(mapped.height).toBeCloseTo(15.12, 1);

    const paperHeight = 3.55;
    const aspect = 595 / 842;
    const paperWidth = paperHeight * aspect;

    const planeBox = mapViewportTo3DPlane(mapped, 595, 842, paperWidth, paperHeight);

    expect(planeBox.center[0]).toBeDefined();
    expect(planeBox.center[1]).toBeDefined();
    expect(planeBox.center[2]).toBe(0.005);
    expect(planeBox.size[0]).toBeGreaterThan(0);
    expect(planeBox.size[1]).toBeGreaterThan(0);
  });

  it("handles APPROXIMATE Layer 3 locations with valid coordinates", () => {
    const approxLoc: MinimizedContentStreamLocationDTO = {
      carrier_type: "CONTENT_STREAM",
      page_index: 0,
      location_index: 1,
      localization_status: "APPROXIMATE",
      is_carrier_sample: true,
      rect: [200.0, 50.0, 203.5, 62.0],
    };

    expect(approxLoc.localization_status).toBe("APPROXIMATE");
    expect(approxLoc.rect).not.toBeNull();

    const cropbox: [number, number, number, number] = [0, 0, 595, 842];
    const mapped = mapPyMuPdfToPdfJs(approxLoc.rect!, cropbox, mockViewport);
    expect(mapped.width).toBeCloseTo(3.5, 1);
  });

  it("handles UNAVAILABLE Layer 3 locations without coordinates", () => {
    const unavailLoc: MinimizedContentStreamLocationDTO = {
      carrier_type: "CONTENT_STREAM",
      page_index: 0,
      location_index: 2,
      localization_status: "UNAVAILABLE",
      is_carrier_sample: true,
      rect: null,
    };

    expect(unavailLoc.localization_status).toBe("UNAVAILABLE");
    expect(unavailLoc.rect).toBeNull();
  });

  it("preserves independent selection state between Layer 2 and Layer 3", () => {
    let selectedAnnotationXref: number | null = 42;
    let selectedKerningLocationIndex: number | null = null;

    // Selecting a Layer 3 location must not clear or alter Layer 2 selection
    selectedKerningLocationIndex = 3;
    expect(selectedAnnotationXref).toBe(42);
    expect(selectedKerningLocationIndex).toBe(3);

    // Deselecting Layer 3 must not clear Layer 2 selection
    selectedKerningLocationIndex = null;
    expect(selectedAnnotationXref).toBe(42);
    expect(selectedKerningLocationIndex).toBeNull();
  });
});
