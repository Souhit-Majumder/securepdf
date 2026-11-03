import React, { useEffect, useRef } from "react";
import * as THREE from "three";
import * as pdfjsLib from "pdfjs-dist";
import {
  InspectionResponseDTO,
} from "../types/inspection";
import { mapPyMuPdfToPdfJs, mapViewportTo3DPlane } from "../utils/coordinateMapping";

// Configure local PDF.js worker
if (typeof window !== "undefined") {
  pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
    "pdfjs-dist/build/pdf.worker.min.mjs",
    import.meta.url
  ).toString();
}

interface Viewport3DProps {
  report: InspectionResponseDTO;
  pdfFile: File | null;
  activeLayer: number;
  visibleLayers: {
    catalog: boolean;
    annotations: boolean;
    textStream: boolean;
  };
  onSelectLayer: (layerIndex: number) => void;
  zoomLevel: number;
  cameraResetTrigger: number;
  spatialTool?: "orbit" | "pan";
  currentPage?: number;
  onTotalPagesChange?: (total: number) => void;
  selectedAnnotationXref?: number | null;
  selectedKerningLocationIndex?: number | null;
  onSelectKerningLocation?: (index: number | null) => void;
}

export const Viewport3D: React.FC<Viewport3DProps> = ({
  report,
  pdfFile,
  activeLayer,
  visibleLayers,
  zoomLevel,
  cameraResetTrigger,
  spatialTool = "orbit",
  currentPage = 1,
  onTotalPagesChange,
  selectedAnnotationXref = null,
  selectedKerningLocationIndex = null,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const paperMeshRef = useRef<THREE.Mesh | null>(null);
  const annotationGroupRef = useRef<THREE.Group | null>(null);
  const kerningGroupRef = useRef<THREE.Group | null>(null);

  // Mouse interaction state for orbital controls (Strictly stable, zero drift)
  const isDragging = useRef(false);
  const previousMousePosition = useRef({ x: 0, y: 0 });
  const targetRotation = useRef({ x: 0.0, y: 0.0 }); // Deterministic upright initial view
  const currentRotation = useRef({ x: 0.0, y: 0.0 });

  // 1. Initialize Three.js Scene, Paper Centerpiece, and Camera
  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    const width = container.clientWidth;
    const height = container.clientHeight;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    // Use transparent background so luminous pearl daylight CSS gradients transmit through canvas
    scene.background = null;

    // Perspective camera positioned slightly to the left (-0.15) to balance between left dock and right inspector
    const camera = new THREE.PerspectiveCamera(36, width / height, 0.1, 100);
    camera.position.set(-0.15, 0.0, 6.8);
    camera.lookAt(-0.15, 0.0, 0.0);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setSize(width, height);
    renderer.setClearColor(0x000000, 0); // Transparent canvas
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = false;
    rendererRef.current = renderer;

    container.innerHTML = "";
    container.appendChild(renderer.domElement);

    // Soft ambient illumination for the general 3D scene
    const ambientLight = new THREE.AmbientLight(0xffffff, 1.0);
    scene.add(ambientLight);

    // Soft studio ambient backdrop plane behind document (z = -0.45)
    // Subtle pale ice-blue / silver halo that adds luminous daylight depth
    const studioCanvas = document.createElement("canvas");
    studioCanvas.width = 512;
    studioCanvas.height = 512;
    const studioCtx = studioCanvas.getContext("2d");
    if (studioCtx) {
      const grad = studioCtx.createRadialGradient(256, 256, 30, 256, 256, 250);
      grad.addColorStop(0, "rgba(224, 242, 254, 0.50)");
      grad.addColorStop(0.5, "rgba(241, 245, 249, 0.25)");
      grad.addColorStop(1, "rgba(255, 255, 255, 0)");
      studioCtx.fillStyle = grad;
      studioCtx.fillRect(0, 0, 512, 512);
    }
    const studioTex = new THREE.CanvasTexture(studioCanvas);
    const studioMat = new THREE.MeshBasicMaterial({
      map: studioTex,
      transparent: true,
      depthWrite: false,
    });
    const studioMesh = new THREE.Mesh(new THREE.PlaneGeometry(10, 8), studioMat);
    studioMesh.position.set(-0.15, 0, -0.45);
    scene.add(studioMesh);

    // Soft daylight contact shadow underneath floating paper
    const shadowCanvas = document.createElement("canvas");
    shadowCanvas.width = 256;
    shadowCanvas.height = 256;
    const sCtx = shadowCanvas.getContext("2d");
    if (sCtx) {
      const grad = sCtx.createRadialGradient(128, 128, 25, 128, 128, 125);
      grad.addColorStop(0, "rgba(15, 23, 42, 0.16)");
      grad.addColorStop(0.4, "rgba(15, 23, 42, 0.05)");
      grad.addColorStop(1, "rgba(15, 23, 42, 0)");
      sCtx.fillStyle = grad;
      sCtx.fillRect(0, 0, 256, 256);
    }
    const shadowTex = new THREE.CanvasTexture(shadowCanvas);
    const shadowMat = new THREE.MeshBasicMaterial({
      map: shadowTex,
      transparent: true,
      opacity: 0.85,
      depthWrite: false,
    });
    const shadowPlane = new THREE.Mesh(new THREE.PlaneGeometry(3.5, 4.4), shadowMat);
    shadowPlane.position.set(-0.15, -0.05, -0.08);
    scene.add(shadowPlane);

    // Centerpiece Paper Sheet
    // Sized to standard aspect ratio, completely flat, opaque matte white
    const paperWidth = 2.65;
    const paperHeight = 3.55;
    const paperThickness = 0.015;
    const paperGeometry = new THREE.BoxGeometry(paperWidth, paperHeight, paperThickness);

    // Default placeholder white matte paper
    const defaultMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff });

    const paperMesh = new THREE.Mesh(paperGeometry, defaultMaterial);
    paperMesh.position.set(-0.15, 0.0, 0.0);
    scene.add(paperMesh);
    paperMeshRef.current = paperMesh;

    // Annotation group anchored directly to the paper face
    const annotationGroup = new THREE.Group();
    paperMesh.add(annotationGroup);
    annotationGroupRef.current = annotationGroup;

    // Layer 3 Kerning Caliper marker group anchored directly to the paper face
    const kerningGroup = new THREE.Group();
    paperMesh.add(kerningGroup);
    kerningGroupRef.current = kerningGroup;

    // Animation Loop with precise convergence (zero drift after reaching target)
    let animationFrameId: number;
    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);

      const diffX = targetRotation.current.x - currentRotation.current.x;
      const diffY = targetRotation.current.y - currentRotation.current.y;

      // Only update rotation when there is active user movement
      if (Math.abs(diffX) > 0.0001 || Math.abs(diffY) > 0.0001) {
        currentRotation.current.x += diffX * 0.12;
        currentRotation.current.y += diffY * 0.12;

        if (paperMeshRef.current) {
          paperMeshRef.current.rotation.x = currentRotation.current.x;
          paperMeshRef.current.rotation.y = currentRotation.current.y;
        }
      }

      renderer.render(scene, camera);
    };
    animate();

    const handleResize = () => {
      if (!containerRef.current) return;
      const w = containerRef.current.clientWidth;
      const h = containerRef.current.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener("resize", handleResize);

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener("resize", handleResize);
      renderer.dispose();
    };
  }, []);

  // 2. Camera zoom handling
  useEffect(() => {
    if (cameraRef.current) {
      const baseDistance = 6.8;
      const targetZ = baseDistance / (zoomLevel / 100);
      cameraRef.current.position.z = THREE.MathUtils.clamp(targetZ, 2.5, 14.0);
    }
  }, [zoomLevel]);

  // 3. Reset camera view trigger (restores exact deterministic upright front-facing view)
  useEffect(() => {
    if (cameraResetTrigger > 0) {
      targetRotation.current = { x: 0.0, y: 0.0 };
      currentRotation.current = { x: 0.0, y: 0.0 };
      if (paperMeshRef.current) {
        paperMeshRef.current.rotation.set(0, 0, 0);
      }
      if (cameraRef.current) {
        cameraRef.current.position.set(-0.15, 0.0, 6.8);
      }
    }
  }, [cameraResetTrigger]);

  const pdfDocRef = useRef<any>(null);

  const renderPageTexture = async (pdfDoc: any, pageNumber: number) => {
    if (!paperMeshRef.current || !pdfDoc) return;
    try {
      const clampedPage = Math.min(Math.max(1, pageNumber), pdfDoc.numPages);
      const page = await pdfDoc.getPage(clampedPage);

      const renderScale = 2.4;
      const viewport = page.getViewport({ scale: renderScale, rotation: page.rotate });

      const canvas = document.createElement("canvas");
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      const ctx = canvas.getContext("2d");

      if (ctx) {
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        await page.render({ canvasContext: ctx, viewport }).promise;

        const texture = new THREE.CanvasTexture(canvas);
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.minFilter = THREE.LinearFilter;
        texture.magFilter = THREE.LinearFilter;

        if (paperMeshRef.current) {
          const pageIndex = clampedPage - 1;
          const pageDim = report.page_dimensions[pageIndex];
          const baseHeight = 3.55;
          const aspect = pageDim ? pageDim.width / pageDim.height : viewport.width / viewport.height;
          const paperWidth = baseHeight * aspect;

          // Update geometry in-place preserving 3D scene and camera
          paperMeshRef.current.geometry.dispose();
          paperMeshRef.current.geometry = new THREE.BoxGeometry(paperWidth, baseHeight, 0.015);

          const edgeMat = new THREE.MeshBasicMaterial({ color: 0xcbd5e1 });
          const backMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
          const frontMat = new THREE.MeshBasicMaterial({
            map: texture,
            toneMapped: false,
          });

          paperMeshRef.current.material = [
            edgeMat, // Right
            edgeMat, // Left
            edgeMat, // Top
            edgeMat, // Bottom
            frontMat, // Front
            backMat,  // Back
          ];
        }
      }
    } catch (err) {
      console.warn("Failed to render page texture:", err);
    }
  };

  // 4. Client-side PDF.js document loading and initial page render
  useEffect(() => {
    if (!pdfFile) {
      pdfDocRef.current = null;
      return;
    }

    let isCancelled = false;

    const loadAndRenderDoc = async () => {
      try {
        const fileBuffer = await pdfFile.arrayBuffer();
        const loadingTask = pdfjsLib.getDocument({ data: fileBuffer });
        const pdfDoc = await loadingTask.promise;
        if (isCancelled) return;
        pdfDocRef.current = pdfDoc;

        if (onTotalPagesChange) {
          onTotalPagesChange(pdfDoc.numPages);
        }

        await renderPageTexture(pdfDoc, currentPage);
      } catch (err) {
        console.warn("Local PDF.js preview rendering failed; using default paper mesh:", err);
      }
    };

    loadAndRenderDoc();

    return () => {
      isCancelled = true;
    };
  }, [pdfFile]);

  // Page turn effect: updates selected page texture and geometry without recreating scene
  useEffect(() => {
    if (!pdfDocRef.current || !paperMeshRef.current) return;
    renderPageTexture(pdfDocRef.current, currentPage);
  }, [currentPage]);

  // 5. Build Layer 2 Holographic Annotation Overlays on the 3D Paper
  useEffect(() => {
    if (!annotationGroupRef.current) return;
    const group = annotationGroupRef.current;
    group.clear();

    if (!visibleLayers.annotations) return;

    const l2Carrier = report.carriers.find((c) => c.carrier_name === "Layer 2 (Annotations)");
    const pageIndex = Math.max(0, (currentPage || 1) - 1);
    const pageDim = report.page_dimensions[pageIndex] || report.page_dimensions[0];
    if (!l2Carrier || !l2Carrier.annotation_locations.length || !pageDim) return;

    // Associate annotations strictly with the currently viewed page
    const pageAnnots = l2Carrier.annotation_locations.filter((annot) => annot.page_index === pageIndex);
    if (!pageAnnots.length) return;

    const paperHeight = 3.55;
    const aspect = pageDim.width / pageDim.height;
    const paperWidth = paperHeight * aspect;

    const mockViewport = {
      width: pageDim.width,
      height: pageDim.height,
      rotation: pageDim.rotation,
      convertToViewportPoint: (x: number, y: number) => {
        return [x - pageDim.cropbox[0], pageDim.cropbox[3] - y] as [number, number];
      },
      convertToViewportRectangle: (rect: [number, number, number, number]) => {
        return [
          rect[0] - pageDim.cropbox[0],
          pageDim.cropbox[3] - rect[3],
          rect[2] - pageDim.cropbox[0],
          pageDim.cropbox[3] - rect[1],
        ] as [number, number, number, number];
      },
    };

    pageAnnots.forEach((annot) => {
      const isSelected = selectedAnnotationXref === annot.annotation_xref;
      const mapped = mapPyMuPdfToPdfJs(annot.rect, pageDim.cropbox, mockViewport);
      const planeBox = mapViewportTo3DPlane(mapped, pageDim.width, pageDim.height, paperWidth, paperHeight);

      // Separate native dimensions from the visual highlight footprint
      const boxWidth = Math.max(planeBox.size[0], 0.35);
      const boxHeight = Math.max(planeBox.size[1], 0.15);

      const boxGeo = new THREE.PlaneGeometry(boxWidth, boxHeight);

      // Distinct highlight material and elevated z-depth for selected annotation
      const boxColor = isSelected ? 0x38bdf8 : 0x0284c7;
      const boxOpacity = isSelected ? 0.38 : (activeLayer === 1 ? 0.16 : 0.08);
      const zOffset = isSelected ? 0.016 : 0.012;

      const boxMat = new THREE.MeshBasicMaterial({
        color: boxColor,
        transparent: true,
        opacity: boxOpacity,
        side: THREE.DoubleSide,
        depthWrite: false,
      });

      const boxMesh = new THREE.Mesh(boxGeo, boxMat);
      boxMesh.position.set(planeBox.center[0], planeBox.center[1], zOffset);
      group.add(boxMesh);

      // Border outline (vibrant electric sky when selected)
      const edges = new THREE.EdgesGeometry(boxGeo);
      const lineMat = new THREE.LineBasicMaterial({
        color: isSelected ? 0x0ea5e9 : 0x0284c7,
        linewidth: isSelected ? 2.5 : 1.5,
        transparent: true,
        opacity: isSelected ? 1.0 : (activeLayer === 1 ? 0.88 : 0.55),
      });
      const wireframe = new THREE.LineSegments(edges, lineMat);
      boxMesh.add(wireframe);

      // Prominent outer reticle bracket when selected
      if (isSelected) {
        const reticleGeo = new THREE.PlaneGeometry(boxWidth + 0.08, boxHeight + 0.06);
        const reticleEdges = new THREE.EdgesGeometry(reticleGeo);
        const reticleLineMat = new THREE.LineBasicMaterial({
          color: 0x38bdf8,
          linewidth: 1.5,
          transparent: true,
          opacity: 0.90,
        });
        const outerReticle = new THREE.LineSegments(reticleEdges, reticleLineMat);
        boxMesh.add(outerReticle);
      }
    });
  }, [report, visibleLayers.annotations, activeLayer, currentPage, selectedAnnotationXref]);

  // 6. Build Layer 3 Subtle Caliper Markers on the 3D Paper
  useEffect(() => {
    if (!kerningGroupRef.current) return;
    const group = kerningGroupRef.current;
    group.clear();

    if (!visibleLayers.textStream) return;

    const l3Carrier = report.carriers.find((c) => c.carrier_name === "Layer 3 (Stego Kerning)");
    const pageIndex = Math.max(0, (currentPage || 1) - 1);
    const pageDim = report.page_dimensions[pageIndex] || report.page_dimensions[0];
    if (!l3Carrier || !l3Carrier.content_stream_locations.length || !pageDim) return;

    const pageLocations = l3Carrier.content_stream_locations.filter(
      (loc) => loc.page_index === pageIndex && loc.rect && loc.localization_status !== "UNAVAILABLE"
    );
    if (!pageLocations.length) return;

    const paperHeight = 3.55;
    const aspect = pageDim.width / pageDim.height;
    const paperWidth = paperHeight * aspect;

    const mockViewport = {
      width: pageDim.width,
      height: pageDim.height,
      rotation: pageDim.rotation,
      convertToViewportPoint: (x: number, y: number) => {
        return [x - pageDim.cropbox[0], pageDim.cropbox[3] - y] as [number, number];
      },
      convertToViewportRectangle: (rect: [number, number, number, number]) => {
        return [
          rect[0] - pageDim.cropbox[0],
          pageDim.cropbox[3] - rect[3],
          rect[2] - pageDim.cropbox[0],
          pageDim.cropbox[3] - rect[1],
        ] as [number, number, number, number];
      },
    };

    pageLocations.forEach((loc) => {
      if (!loc.rect) return;
      const isSelected = selectedKerningLocationIndex === loc.location_index;
      const isApprox = loc.localization_status === "APPROXIMATE";

      const mapped = mapPyMuPdfToPdfJs(loc.rect, pageDim.cropbox, mockViewport);
      const planeBox = mapViewportTo3DPlane(mapped, pageDim.width, pageDim.height, paperWidth, paperHeight);

      // Subtle caliper box dimensions
      const calWidth = Math.max(planeBox.size[0], 0.08);
      const calHeight = Math.max(planeBox.size[1], 0.12);

      const calGeo = new THREE.PlaneGeometry(calWidth, calHeight);

      // Subtle cyan/blue styling: #0ea5e9, selected #38bdf8. Zero violet!
      const calColor = isSelected ? 0x38bdf8 : (isApprox ? 0x0284c7 : 0x0ea5e9);
      const calOpacity = isSelected ? 0.35 : (activeLayer === 2 ? 0.14 : 0.08);
      const zOffset = isSelected ? 0.016 : 0.011;

      const calMat = new THREE.MeshBasicMaterial({
        color: calColor,
        transparent: true,
        opacity: calOpacity,
        side: THREE.DoubleSide,
        depthWrite: false,
      });

      const calMesh = new THREE.Mesh(calGeo, calMat);
      calMesh.position.set(planeBox.center[0], planeBox.center[1], zOffset);
      group.add(calMesh);

      // Outline wireframe
      const edges = new THREE.EdgesGeometry(calGeo);
      const lineMat = new THREE.LineBasicMaterial({
        color: calColor,
        linewidth: isSelected ? 2.0 : 1.0,
        transparent: true,
        opacity: isSelected ? 0.95 : (activeLayer === 2 ? 0.70 : 0.40),
      });
      const wireframe = new THREE.LineSegments(edges, lineMat);
      calMesh.add(wireframe);

      // Distinct reticle when selected
      if (isSelected) {
        const reticleGeo = new THREE.PlaneGeometry(calWidth + 0.04, calHeight + 0.03);
        const reticleEdges = new THREE.EdgesGeometry(reticleGeo);
        const reticleLineMat = new THREE.LineBasicMaterial({
          color: 0x38bdf8,
          linewidth: 1.5,
          transparent: true,
          opacity: 0.90,
        });
        const outerReticle = new THREE.LineSegments(reticleEdges, reticleLineMat);
        calMesh.add(outerReticle);
      }
    });
  }, [report, visibleLayers.textStream, activeLayer, currentPage, selectedKerningLocationIndex]);

  // Deliberate user drag handlers for camera orbit/pan
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    isDragging.current = true;
    previousMousePosition.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging.current) return;
    const deltaX = e.clientX - previousMousePosition.current.x;
    const deltaY = e.clientY - previousMousePosition.current.y;

    if (spatialTool === "orbit") {
      targetRotation.current.y += deltaX * 0.004;
      targetRotation.current.x += deltaY * 0.004;

      // Restrained angle limits to prevent disorienting flip
      targetRotation.current.x = THREE.MathUtils.clamp(targetRotation.current.x, -0.4, 0.55);
      targetRotation.current.y = THREE.MathUtils.clamp(targetRotation.current.y, -0.7, 0.7);
    } else if (spatialTool === "pan" && cameraRef.current) {
      cameraRef.current.position.x -= deltaX * 0.003;
      cameraRef.current.position.y += deltaY * 0.003;
    }

    previousMousePosition.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseUp = () => {
    isDragging.current = false;
  };

  return (
    <div
      className={`relative w-full h-full overflow-hidden select-none ${
        spatialTool === "orbit" ? "cursor-grab active:cursor-grabbing" : "cursor-move"
      }`}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {/* Three.js Canvas Container */}
      <div ref={containerRef} className="w-full h-full" />
    </div>
  );
};
