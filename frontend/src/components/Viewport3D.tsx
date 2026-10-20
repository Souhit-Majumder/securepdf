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
}

export const Viewport3D: React.FC<Viewport3DProps> = ({
  report,
  pdfFile,
  activeLayer,
  visibleLayers,
  onSelectLayer,
  zoomLevel,
  cameraResetTrigger,
  spatialTool = "orbit",
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const paperMeshRef = useRef<THREE.Mesh | null>(null);
  const annotationGroupRef = useRef<THREE.Group | null>(null);

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

  // 4. Client-side PDF.js rendering to Three.js Canvas Texture (Crisp, flat, matte paper)
  useEffect(() => {
    if (!pdfFile || !paperMeshRef.current) return;

    let isCancelled = false;

    const renderPdfToTexture = async () => {
      try {
        const fileBuffer = await pdfFile.arrayBuffer();
        const loadingTask = pdfjsLib.getDocument({ data: fileBuffer });
        const pdfDoc = await loadingTask.promise;
        const page = await pdfDoc.getPage(1);

        // High resolution rendering for sharp document text legibility
        const renderScale = 2.4;
        const viewport = page.getViewport({ scale: renderScale, rotation: page.rotate });

        const canvas = document.createElement("canvas");
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        const ctx = canvas.getContext("2d");

        if (ctx) {
          // Fill canvas with pure white background before PDF page render
          ctx.fillStyle = "#ffffff";
          ctx.fillRect(0, 0, canvas.width, canvas.height);

          await page.render({ canvasContext: ctx, viewport }).promise;
          if (isCancelled) return;

          const texture = new THREE.CanvasTexture(canvas);
          texture.colorSpace = THREE.SRGBColorSpace;
          texture.minFilter = THREE.LinearFilter;
          texture.magFilter = THREE.LinearFilter;

          if (paperMeshRef.current) {
            // Unlit MeshBasicMaterial: strictly preserves original PDF colors, contrast,
            // with zero artificial gradients, specular highlights, or diagonal shading
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
        console.warn("Local PDF.js preview rendering failed; using default paper mesh:", err);
      }
    };

    renderPdfToTexture();

    return () => {
      isCancelled = true;
    };
  }, [pdfFile]);

  // 5. Build Layer 2 Holographic Annotation Overlays on the 3D Paper
  useEffect(() => {
    if (!annotationGroupRef.current) return;
    const group = annotationGroupRef.current;
    group.clear();

    if (!visibleLayers.annotations) return;

    const l2Carrier = report.carriers.find((c) => c.carrier_name === "Layer 2 (Annotations)");
    const pageDim = report.page_dimensions[0];
    if (!l2Carrier || !l2Carrier.annotation_locations.length || !pageDim) return;

    const paperWidth = 2.65;
    const paperHeight = 3.55;

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

    l2Carrier.annotation_locations.forEach((annot) => {
      const mapped = mapPyMuPdfToPdfJs(annot.rect, pageDim.cropbox, mockViewport);
      const planeBox = mapViewportTo3DPlane(mapped, pageDim.width, pageDim.height, paperWidth, paperHeight);

      const boxWidth = Math.max(planeBox.size[0], 0.35);
      const boxHeight = Math.max(planeBox.size[1], 0.15);

      const boxGeo = new THREE.PlaneGeometry(boxWidth, boxHeight);
      const boxMat = new THREE.MeshBasicMaterial({
        color: 0x0284c7, // sky-600 for clear visibility on white paper
        transparent: true,
        opacity: activeLayer === 1 ? 0.16 : 0.08,
        side: THREE.DoubleSide,
        depthWrite: false,
      });

      const boxMesh = new THREE.Mesh(boxGeo, boxMat);
      boxMesh.position.set(planeBox.center[0], planeBox.center[1], 0.012);
      group.add(boxMesh);

      // Fine cyan outline
      const edges = new THREE.EdgesGeometry(boxGeo);
      const lineMat = new THREE.LineBasicMaterial({
        color: 0x0284c7,
        linewidth: 1.5,
        transparent: true,
        opacity: activeLayer === 1 ? 0.88 : 0.55,
      });
      const wireframe = new THREE.LineSegments(edges, lineMat);
      boxMesh.add(wireframe);
    });
  }, [report, visibleLayers.annotations, activeLayer]);

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

  // Carrier data references
  const l1Carrier = report.carriers.find((c) => c.carrier_name === "Layer 1 (Catalog)");
  const l3Carrier = report.carriers.find((c) => c.carrier_name === "Layer 3 (Stego Kerning)");
  const l3Sample = l3Carrier?.content_stream_locations[0] || null;

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

      {/* SVG Leader Lines for Spatial Grounding (Clean, non-decorative, restrained) */}
      <svg className="absolute inset-0 w-full h-full pointer-events-none z-10">
        {/* Layer 1 Leader line from Catalog Capsule to Document Header */}
        {visibleLayers.catalog && (
          <g className="transition-opacity duration-300">
            <line
              x1="30%"
              y1="22%"
              x2="41%"
              y2="25%"
              stroke="rgba(2, 132, 199, 0.45)"
              strokeWidth="1.2"
              strokeDasharray="3 3"
            />
            <circle cx="41%" cy="25%" r="2.5" fill="#0284c7" />
            <circle cx="41%" cy="25%" r="5" fill="none" stroke="rgba(2, 132, 199, 0.25)" strokeWidth="1" />
          </g>
        )}

        {/* Layer 3 Leader line from Optical Lens to Word Gap (Only if evidence exists) */}
        {visibleLayers.textStream && (
          <g className="transition-opacity duration-300">
            <line
              x1="29%"
              y1="66%"
              x2="42%"
              y2="54%"
              stroke={l3Sample ? "rgba(2, 132, 199, 0.45)" : "rgba(148, 163, 184, 0.35)"}
              strokeWidth="1.2"
              strokeDasharray="3 3"
            />
            <circle
              cx="42%"
              cy="54%"
              r="2.5"
              fill={l3Sample ? "#0284c7" : "#94a3b8"}
            />
          </g>
        )}
      </svg>

      {/* ---------------- Layer 1: Floating Suspended Catalog Capsule (Matches Reference Image) ---------------- */}
      {visibleLayers.catalog && (
        <div
          onClick={(e) => {
            e.stopPropagation();
            onSelectLayer(0);
          }}
          className={`absolute top-[16%] left-[24%] z-20 cursor-pointer group transition-all duration-200 ${
            activeLayer === 0 ? "scale-[1.02]" : "hover:scale-[1.01]"
          }`}
        >
          <div
            className={`px-4 py-2 rounded-full transition-all duration-200 shadow-md ${
              activeLayer === 0 ? "glass-dock-item-active" : "glass-catalog-node"
            }`}
          >
            <div className="flex items-center gap-2">
              <span className="text-[11.5px] font-medium text-slate-800 tracking-tight">
                Capsule for <span className="font-mono font-semibold text-sky-900">/SPDFPayload</span>
              </span>
              {l1Carrier?.status === "STRUCTURALLY_DECODED" && (
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse ml-0.5" />
              )}
            </div>
          </div>
        </div>
      )}

      {/* ---------------- Layer 3: True Optical Glass Inspection Lens (Matches Reference Image) ---------------- */}
      {visibleLayers.textStream && (
        <div
          onClick={(e) => {
            e.stopPropagation();
            onSelectLayer(2);
          }}
          className={`absolute bottom-[18%] left-[28%] z-20 cursor-pointer group transition-all duration-200 ${
            activeLayer === 2 ? "scale-[1.02]" : "hover:scale-[1.01]"
          }`}
        >
          {/* Circular Optical Glass Lens */}
          <div className="relative w-36 h-36 rounded-full optical-glass-lens p-1 flex items-center justify-center">
            {/* Delicate inner concentric measurement ring */}
            <div className="absolute inset-2.5 rounded-full border border-sky-500/20 pointer-events-none" />

            {/* Specular reflection highlight crescent (Matching Reference Image) */}
            <div className="absolute top-2 left-5 right-5 h-7 rounded-full bg-gradient-to-b from-white/95 via-white/35 to-transparent pointer-events-none" />

            {/* Central Precision Crosshair Caliper (Matching Reference Image) */}
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="w-10 h-10 relative flex items-center justify-center">
                <div className="absolute w-full h-[1.2px] bg-slate-600/60" />
                <div className="absolute h-full w-[1.2px] bg-slate-600/60" />
              </div>
            </div>

            {/* Honest Telemetry Overlay */}
            <div className="absolute bottom-2.5 inset-x-2 text-center pointer-events-none">
              {l3Sample ? (
                <div className="text-[9.5px] font-mono font-bold text-sky-950 bg-white/70 backdrop-blur-xs rounded-full px-2 py-0.5 inline-block shadow-xs border border-white/80">
                  {l3Sample.displacement} pt • bit {l3Sample.bit_value ?? "0"}
                </div>
              ) : l3Carrier?.status === "OBSERVED_SYNTAX" ? (
                <div className="text-[9px] font-medium text-amber-950 bg-amber-500/15 backdrop-blur-xs rounded-full px-2 py-0.5 inline-block border border-amber-400/30">
                  Typesetting TJ
                </div>
              ) : (
                <div className="text-[9px] font-medium text-slate-700 bg-white/60 backdrop-blur-xs rounded-full px-2 py-0.5 inline-block border border-white/80">
                  No Stego Preamble
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
