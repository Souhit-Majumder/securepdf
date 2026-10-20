/**
 * PyMuPDF to PDF.js and Three.js 3D Plane Coordinate Mapping.
 * Validated against synthetic cross-renderer test matrix.
 */

export interface PdfJsViewport {
  width: number;
  height: number;
  rotation: number;
  convertToViewportPoint(x: number, y: number): number[] | [number, number];
  convertToViewportRectangle(rect: [number, number, number, number]): number[] | [number, number, number, number];
}

export interface BoundingBox2D {
  x: number;      // Viewport pixels from left
  y: number;      // Viewport pixels from top
  width: number;  // Pixel width
  height: number; // Pixel height
  corners: {
    TL: [number, number];
    TR: [number, number];
    BR: [number, number];
    BL: [number, number];
  };
}

export interface PlaneBox3D {
  center: [number, number, number]; // [x, y, z] in Three.js plane local space (-0.5 to 0.5)
  size: [number, number];           // [width, height] normalized to plane dimensions
}

/**
 * Maps PyMuPDF annot.rect [x0, y0, x1, y1] to standard PDF User Space [llx, lly, urx, ury].
 * PyMuPDF annot.rect origin is top-left of the CropBox.
 */
export function pyMuPdfToPdfUserSpace(
  annotRect: [number, number, number, number],
  cropbox: [number, number, number, number]
): [number, number, number, number] {
  const [x0, y0, x1, y1] = annotRect;
  const [cx0, , , cy1] = cropbox;

  const llx = cx0 + x0;
  const lly = cy1 - y1;
  const urx = cx0 + x1;
  const ury = cy1 - y0;

  return [llx, lly, urx, ury];
}

/**
 * Maps PyMuPDF annot.rect to PDF.js rendered canvas viewport coordinates.
 */
export function mapPyMuPdfToPdfJs(
  annotRect: [number, number, number, number],
  cropbox: [number, number, number, number],
  viewport: PdfJsViewport
): BoundingBox2D {
  const [llx, lly, urx, ury] = pyMuPdfToPdfUserSpace(annotRect, cropbox);

  // Compute the 4 corners in PDF user space
  const rawTL = viewport.convertToViewportPoint(llx, ury);
  const rawTR = viewport.convertToViewportPoint(urx, ury);
  const rawBR = viewport.convertToViewportPoint(urx, lly);
  const rawBL = viewport.convertToViewportPoint(llx, lly);

  const tlPt: [number, number] = [rawTL[0], rawTL[1]];
  const trPt: [number, number] = [rawTR[0], rawTR[1]];
  const brPt: [number, number] = [rawBR[0], rawBR[1]];
  const blPt: [number, number] = [rawBL[0], rawBL[1]];

  const xs = [tlPt[0], trPt[0], brPt[0], blPt[0]];
  const ys = [tlPt[1], trPt[1], brPt[1], blPt[1]];

  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  return {
    x: minX,
    y: minY,
    width: maxX - minX,
    height: maxY - minY,
    corners: {
      TL: tlPt,
      TR: trPt,
      BR: brPt,
      BL: blPt,
    },
  };
}

/**
 * Converts viewport 2D coordinates into normalized 3D local coordinates
 * on a Three.js PlaneGeometry with origin (0,0) at center and extent [-0.5..0.5, -0.5..0.5].
 */
export function mapViewportTo3DPlane(
  box: BoundingBox2D,
  viewportWidth: number,
  viewportHeight: number,
  paperWidth: number,
  paperHeight: number
): PlaneBox3D {
  // Center of box in viewport pixels (0,0 at top-left)
  const centerX = box.x + box.width / 2;
  const centerY = box.y + box.height / 2;

  // Convert to Three.js Plane coordinates:
  // X: from -paperWidth/2 (left) to +paperWidth/2 (right)
  // Y: from +paperHeight/2 (top) to -paperHeight/2 (bottom)
  const normX = (centerX / viewportWidth) - 0.5;
  const normY = 0.5 - (centerY / viewportHeight);

  const localX = normX * paperWidth;
  const localY = normY * paperHeight;
  const localW = (box.width / viewportWidth) * paperWidth;
  const localH = (box.height / viewportHeight) * paperHeight;

  return {
    center: [localX, localY, 0.005], // slight z-offset to float just above paper surface
    size: [localW, localH],
  };
}
