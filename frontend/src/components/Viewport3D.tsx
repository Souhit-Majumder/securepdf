import React, { useEffect, useRef } from "react";
import * as THREE from "three";
import * as pdfjsLib from "pdfjs-dist";
import {
  InspectionResponseDTO,
} from "../types/inspection";
import { mapPyMuPdfToPdfJs, mapViewportTo3DPlane } from "../utils/coordinateMapping";

// Set up local PDF.js worker using workerSrc
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
}

export const Viewport3D: React.FC<Viewport3DProps> = ({
  report,
  pdfFile,
  activeLayer,
  visibleLayers,
  onSelectLayer,
  zoomLevel,
  cameraResetTrigger,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const paperMeshRef = useRef<THREE.Mesh | null>(null);
  const annotationGroupRef = useRef<THREE.Group | null>(null);

  const selectedAnnotationIndex = 0;

  // Mouse interaction state for orbital controls
  const isDragging = useRef(false);
  const previousMousePosition = useRef({ x: 0, y: 0 });
  const targetRotation = useRef({ x: 0.28, y: -0.22 }); // Elegant initial perspective tilt
  const currentRotation = useRef({ x: 0.28, y: -0.22 });

  // 1. Initialize Three.js Scene, Lighting, and Camera
  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    const width = container.clientWidth;
    const height = container.clientHeight;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    // Atmospheric cool-blue ambient environment
    scene.background = new THREE.Color("#070b12");
    scene.fog = new THREE.FogExp2(0x070b12, 0.08);

    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 100);
    camera.position.set(0, 0.2, 5.2);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    rendererRef.current = renderer;

    container.innerHTML = "";
    container.appendChild(renderer.domElement);

    // Premium subtle lighting
    const ambientLight = new THREE.AmbientLight(0xdbeafe, 0.85);
    scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0xffffff, 1.4);
    keyLight.position.set(4, 6, 6);
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.width = 1024;
    keyLight.shadow.mapSize.height = 1024;
    scene.add(keyLight);

    const rimLight = new THREE.PointLight(0x38bdf8, 2.2, 10);
    rimLight.position.set(-4, -2, 2);
    scene.add(rimLight);

    const accentLight = new THREE.PointLight(0x818cf8, 1.8, 8);
    accentLight.position.set(3, 4, 2);
    scene.add(accentLight);

    // Create the centerpiece Paper Sheet
    const paperWidth = 2.2;
    const paperHeight = 2.95; // ~A4 / US Letter aspect ratio
    const paperGeometry = new THREE.BoxGeometry(paperWidth, paperHeight, 0.02);

    const defaultMaterial = new THREE.MeshStandardMaterial({
      color: 0xf8fafc,
      roughness: 0.45,
      metalness: 0.05,
    });

    const paperMesh = new THREE.Mesh(paperGeometry, defaultMaterial);
    paperMesh.castShadow = true;
    paperMesh.receiveShadow = true;
    scene.add(paperMesh);
    paperMeshRef.current = paperMesh;

    // Annotations group anchored directly to the paper mesh
    const annotationGroup = new THREE.Group();
    paperMesh.add(annotationGroup);
    annotationGroupRef.current = annotationGroup;

    // Animation Loop
    let animationFrameId: number;
    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);

      // Smooth damping interpolation for rotation
      currentRotation.current.x += (targetRotation.current.x - currentRotation.current.x) * 0.08;
      currentRotation.current.y += (targetRotation.current.y - currentRotation.current.y) * 0.08;

      if (paperMeshRef.current) {
        paperMeshRef.current.rotation.x = currentRotation.current.x;
        paperMeshRef.current.rotation.y = currentRotation.current.y;
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
      const baseDistance = 5.2;
      const targetZ = baseDistance / (zoomLevel / 100);
      cameraRef.current.position.z = THREE.MathUtils.clamp(targetZ, 2.0, 10.0);
    }
  }, [zoomLevel]);

  // 3. Reset camera view trigger
  useEffect(() => {
    if (cameraResetTrigger > 0) {
      targetRotation.current = { x: 0.28, y: -0.22 };
    }
  }, [cameraResetTrigger]);

  // 4. Client-side PDF.js rendering to Three.js Canvas Texture
  useEffect(() => {
    if (!pdfFile || !paperMeshRef.current) return;

    let isCancelled = false;

    const renderPdfToTexture = async () => {
      try {
        const fileBuffer = await pdfFile.arrayBuffer();
        const loadingTask = pdfjsLib.getDocument({ data: fileBuffer });
        const pdfDoc = await loadingTask.promise;
        const page = await pdfDoc.getPage(1);

        // Render at high resolution for crisp, legible text
        const renderScale = 2.0;
        const viewport = page.getViewport({ scale: renderScale, rotation: page.rotate });

        const canvas = document.createElement("canvas");
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        const ctx = canvas.getContext("2d");

        if (ctx) {
          await page.render({ canvasContext: ctx, viewport }).promise;
          if (isCancelled) return;

          const texture = new THREE.CanvasTexture(canvas);
          texture.colorSpace = THREE.SRGBColorSpace;
          texture.minFilter = THREE.LinearFilter;
          texture.magFilter = THREE.LinearFilter;

          if (paperMeshRef.current) {
            // Apply texture to front face, clean dark material to edges/back
            const materials = [
              new THREE.MeshStandardMaterial({ color: 0xe2e8f0, roughness: 0.8 }),
              new THREE.MeshStandardMaterial({ color: 0xe2e8f0, roughness: 0.8 }),
              new THREE.MeshStandardMaterial({ color: 0xe2e8f0, roughness: 0.8 }),
              new THREE.MeshStandardMaterial({ color: 0xe2e8f0, roughness: 0.8 }),
              new THREE.MeshStandardMaterial({ map: texture, roughness: 0.35, metalness: 0.05 }), // Front
              new THREE.MeshStandardMaterial({ color: 0xf1f5f9, roughness: 0.8 }), // Back
            ];
            paperMeshRef.current.material = materials;
          }
        }
      } catch (err) {
        console.warn("Local PDF.js preview rendering failed; using stylized mesh:", err);
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

    const paperWidth = 2.2;
    const paperHeight = 2.95;

    // Use page dimensions from PDF.js coordinate converter
    const mockViewport = {
      width: pageDim.width,
      height: pageDim.height,
      rotation: pageDim.rotation,
      convertToViewportPoint: (x: number, y: number) => {
        // Standard PDF.js transform emulation for 0 degrees
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

    l2Carrier.annotation_locations.forEach((annot, index) => {
      const mapped = mapPyMuPdfToPdfJs(annot.rect, pageDim.cropbox, mockViewport);
      const planeBox = mapViewportTo3DPlane(mapped, pageDim.width, pageDim.height, paperWidth, paperHeight);

      // Create glowing cyan translucent box
      const boxWidth = Math.max(planeBox.size[0], 0.35);
      const boxHeight = Math.max(planeBox.size[1], 0.15);

      const boxGeo = new THREE.PlaneGeometry(boxWidth, boxHeight);
      const boxMat = new THREE.MeshBasicMaterial({
        color: 0x38bdf8,
        transparent: true,
        opacity: selectedAnnotationIndex === index ? 0.35 : 0.18,
        side: THREE.DoubleSide,
        depthWrite: false,
      });

      const boxMesh = new THREE.Mesh(boxGeo, boxMat);
      boxMesh.position.set(planeBox.center[0], planeBox.center[1], 0.015);
      group.add(boxMesh);

      // Delicate cyan luminous wireframe outline
      const edges = new THREE.EdgesGeometry(boxGeo);
      const lineMat = new THREE.LineBasicMaterial({
        color: 0x38bdf8,
        linewidth: 2,
        transparent: true,
        opacity: 0.9,
      });
      const wireframe = new THREE.LineSegments(edges, lineMat);
      boxMesh.add(wireframe);
    });
  }, [report, visibleLayers.annotations, selectedAnnotationIndex]);

  // Mouse drag handlers for smooth perspective orbit
  const handleMouseDown = (e: React.MouseEvent) => {
    isDragging.current = true;
    previousMousePosition.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging.current) return;
    const deltaX = e.clientX - previousMousePosition.current.x;
    const deltaY = e.clientY - previousMousePosition.current.y;

    targetRotation.current.y += deltaX * 0.006;
    targetRotation.current.x += deltaY * 0.006;

    // Clamp vertical tilt to keep document facing camera
    targetRotation.current.x = THREE.MathUtils.clamp(targetRotation.current.x, -0.6, 0.8);
    targetRotation.current.y = THREE.MathUtils.clamp(targetRotation.current.y, -1.0, 1.0);

    previousMousePosition.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseUp = () => {
    isDragging.current = false;
  };

  // Find sample Layer 3 modulation for the contextual magnification lens
  const l3Carrier = report.carriers.find((c) => c.carrier_name === "Layer 3 (Stego Kerning)");
  const l3Sample = l3Carrier?.content_stream_locations[0] || null;

  return (
    <div
      className="relative w-full h-full cursor-grab active:cursor-grabbing overflow-hidden select-none"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {/* Three.js Canvas Container */}
      <div ref={containerRef} className="w-full h-full" />

      {/* ---------------- Layer 1: Floating Catalog Beacon Callout ---------------- */}
      {visibleLayers.catalog && (
        <div
          onClick={() => onSelectLayer(0)}
          className={`absolute top-[22%] left-[28%] -translate-x-1/2 -translate-y-1/2 z-20 cursor-pointer group transition-all duration-300 hover:scale-105 ${
            activeLayer === 0 ? "scale-105 ring-2 ring-sky-400/50 rounded-xl" : ""
          }`}
        >
          {/* Beacon pill */}
          <div className="relative glass-panel rounded-xl px-4 py-3 flex items-center gap-3 border-sky-400/40 shadow-lg shadow-sky-500/10">
            {/* Number badge */}
            <div className="w-6 h-6 rounded-md bg-sky-500 text-[11px] font-bold text-slate-950 flex items-center justify-center shadow-md shadow-sky-400/30">
              1
            </div>

            <div>
              <div className="text-xs font-semibold text-slate-100 flex items-center gap-1.5 font-mono">
                /SPDFPayload
              </div>
              <div className="text-[11px] text-slate-400">
                Catalog Object Reference
              </div>
              <div className="text-[10px] text-sky-400/90 font-mono mt-0.5">
                xref: {report.carriers[0]?.catalog_location?.catalog_xref ?? 12}
              </div>
            </div>
          </div>

          {/* Glowing connector anchor point */}
          <div className="absolute left-1/2 -bottom-2 -translate-x-1/2 w-2 h-2 rounded-full bg-sky-400 shadow-md shadow-sky-400 animate-ping" />
        </div>
      )}

      {/* ---------------- Layer 3: Contextual Magnification Lens ---------------- */}
      {visibleLayers.textStream && (
        <div
          onClick={() => onSelectLayer(2)}
          className={`absolute bottom-[28%] left-[26%] z-20 cursor-pointer group transition-all duration-300 hover:scale-105 ${
            activeLayer === 2 ? "scale-105 ring-2 ring-indigo-400/50 rounded-full" : ""
          }`}
        >
          {/* Glass Lens Circle with realistic reflection highlights */}
          <div className="relative w-44 h-44 rounded-full p-1 bg-gradient-to-br from-white/25 via-white/5 to-transparent shadow-2xl backdrop-blur-md border border-white/20 flex items-center justify-center">
            {/* Inner refractive glass layer */}
            <div className="w-full h-full rounded-full bg-slate-900/60 border border-sky-400/30 flex flex-col items-center justify-center p-3 text-center overflow-hidden relative shadow-inner">
              <div className="text-[10px] uppercase tracking-wider text-sky-400 font-semibold mb-1">
                Inter-word Kerning
              </div>

              {/* Text gap visualization */}
              <div className="flex items-center gap-1.5 font-serif text-sm text-slate-100 my-1 font-semibold">
                <span>secure</span>
                <span className="inline-block w-4 h-0.5 bg-sky-400 shadow-[0_0_8px_#38bdf8]" />
                <span>comm</span>
              </div>

              {/* Displacement indicator */}
              <div className="mt-1 font-mono text-xs text-sky-300 font-bold">
                {l3Sample ? `${l3Sample.displacement} pt` : "-12.4 pt"}
              </div>

              <div className="text-[10px] text-slate-400 mt-0.5 font-mono">
                bit: {l3Sample?.bit_value ?? (l3Carrier?.status === "STRUCTURALLY_DECODED" ? "1" : "none")}
              </div>
            </div>
          </div>

          {/* Small callout label below lens */}
          <div className="mt-2 glass-panel rounded-lg px-3 py-1.5 text-center text-[11px] text-slate-300 border-indigo-400/30 shadow-md">
            Text Stream Modulation
          </div>
        </div>
      )}
    </div>
  );
};
