import React, { useState, useEffect } from "react";
import {
  Shield,
  FileText,
  Upload,
  User,
  Box,
  Layers,
  Type,
  RotateCcw,
  Move,
  Rotate3d,
  ZoomIn,
  ZoomOut,
  ChevronDown,
} from "lucide-react";
import { InspectionResponseDTO, WebGLDiagnosticInfo } from "./types/inspection";
import { probeWebGLSupport } from "./utils/webglCheck";
import { UploadZone } from "./components/UploadZone";
import { Viewport3D } from "./components/Viewport3D";
import { EvidencePanel } from "./components/EvidencePanel";
import { WebGLErrorFallback } from "./components/WebGLErrorFallback";

export const App: React.FC = () => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [inspectionReport, setInspectionReport] = useState<InspectionResponseDTO | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Layer selection state (0 = Catalog, 1 = Annotations, 2 = Text Stream)
  const [activeLayer, setActiveLayer] = useState<number>(0);

  // Layer visibility toggles
  const [visibleLayers, setVisibleLayers] = useState({
    catalog: true,
    annotations: true,
    textStream: true,
  });

  // Spatial camera controls
  const [zoomLevel, setZoomLevel] = useState<number>(100);
  const [cameraResetTrigger, setCameraResetTrigger] = useState<number>(0);

  // WebGL diagnostic probe state
  const [webglDiagnostic, setWebglDiagnostic] = useState<WebGLDiagnosticInfo | null>(null);

  // Execute WebGL probe on mount
  useEffect(() => {
    const diagnostic = probeWebGLSupport();
    setWebglDiagnostic(diagnostic);
  }, []);

  const handleFileSelected = async (file: File) => {
    setSelectedFile(file);
    setIsLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("/api/inspection/inspect", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Inspection failed (HTTP ${response.status})`);
      }

      const report: InspectionResponseDTO = await response.json();
      setInspectionReport(report);
    } catch (err: any) {
      console.error("Inspection request error:", err);
      setError(err.message || "Failed to inspect document structure.");
    } finally {
      setIsLoading(false);
    }
  };

  const isWebglAvailable =
    webglDiagnostic && (webglDiagnostic.webgl1_supported || webglDiagnostic.webgl2_supported);

  return (
    <div className="flex flex-col h-screen w-screen bg-[#070b12] text-slate-100 overflow-hidden relative">
      {/* Background radial gradient glow */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] h-[550px] bg-sky-950/20 blur-[140px] pointer-events-none rounded-full" />
      <div className="absolute bottom-1/4 right-1/4 w-[600px] h-[400px] bg-indigo-950/20 blur-[120px] pointer-events-none rounded-full" />

      {/* ---------------- Top Glass Navigation Bar ---------------- */}
      <header className="relative z-30 h-16 px-6 flex items-center justify-between border-b border-white/[0.06] glass-panel-subtle">
        {/* Brand Logo */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl glass-panel-bright flex items-center justify-center text-sky-400 shadow-md shadow-sky-500/10">
            <Shield className="w-5 h-5" />
          </div>
          <span className="font-semibold tracking-tight text-base text-slate-100">
            SecurePDF
          </span>

          {/* Document pill */}
          {selectedFile && (
            <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 ml-3 rounded-lg glass-pill text-xs text-slate-300">
              <FileText className="w-3.5 h-3.5 text-sky-400" />
              <span className="truncate max-w-[200px] font-medium">
                {selectedFile.name}
              </span>
              <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
            </div>
          )}
        </div>

        {/* Status indicator in center */}
        {inspectionReport && (
          <div className="hidden md:flex items-center gap-2 px-3.5 py-1.5 rounded-full glass-pill border-emerald-500/20 text-xs font-medium text-emerald-400">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            Inspection Complete
          </div>
        )}

        {/* Right action controls */}
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 px-4 py-2 rounded-xl glass-btn text-xs font-medium text-slate-200 cursor-pointer">
            <Upload className="w-3.5 h-3.5 text-sky-400" />
            <span>Open PDF</span>
            <input
              type="file"
              accept=".pdf,application/pdf"
              className="hidden"
              onChange={(e) => {
                if (e.target.files && e.target.files[0]) {
                  handleFileSelected(e.target.files[0]);
                }
              }}
            />
          </label>

          <div className="w-8 h-8 rounded-full glass-panel flex items-center justify-center text-slate-400 border border-white/10">
            <User className="w-4 h-4" />
          </div>
        </div>
      </header>

      {/* ---------------- Main Content Workspace ---------------- */}
      <main className="flex-1 relative flex overflow-hidden">
        {/* Left: Compact Layer Selector (Floating Glass Panel) */}
        {inspectionReport && isWebglAvailable && (
          <aside className="absolute top-6 left-6 z-20 w-52 glass-panel rounded-2xl p-3.5 flex flex-col gap-2 shadow-2xl">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 px-2 py-1">
              Layers
            </div>

            {/* Layer 01: Catalog */}
            <button
              onClick={() => setActiveLayer(0)}
              className={`w-full flex items-center gap-3 p-2.5 rounded-xl text-left transition-all duration-200 ${
                activeLayer === 0
                  ? "glass-panel-bright text-slate-100"
                  : "hover:bg-white/[0.04] text-slate-400 hover:text-slate-200"
              }`}
            >
              <div className="w-6 h-6 rounded-lg bg-sky-500/10 border border-sky-500/20 text-sky-400 flex items-center justify-center shrink-0">
                <Box className="w-3.5 h-3.5" />
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium truncate">01 Catalog</div>
                <div className="text-[10px] text-slate-400 truncate">Object references</div>
              </div>
            </button>

            {/* Layer 02: Annotations */}
            <button
              onClick={() => setActiveLayer(1)}
              className={`w-full flex items-center gap-3 p-2.5 rounded-xl text-left transition-all duration-200 ${
                activeLayer === 1
                  ? "glass-panel-bright text-slate-100"
                  : "hover:bg-white/[0.04] text-slate-400 hover:text-slate-200"
              }`}
            >
              <div className="w-6 h-6 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 flex items-center justify-center shrink-0">
                <Layers className="w-3.5 h-3.5" />
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium truncate">02 Annotations</div>
                <div className="text-[10px] text-slate-400 truncate">Page annotations</div>
              </div>
            </button>

            {/* Layer 03: Text Stream */}
            <button
              onClick={() => setActiveLayer(2)}
              className={`w-full flex items-center gap-3 p-2.5 rounded-xl text-left transition-all duration-200 ${
                activeLayer === 2
                  ? "glass-panel-bright text-slate-100"
                  : "hover:bg-white/[0.04] text-slate-400 hover:text-slate-200"
              }`}
            >
              <div className="w-6 h-6 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center shrink-0">
                <Type className="w-3.5 h-3.5" />
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium truncate">03 Text Stream</div>
                <div className="text-[10px] text-slate-400 truncate">Text modulation</div>
              </div>
            </button>
          </aside>
        )}

        {/* Center: 3D Viewport or Fallback */}
        <div className="flex-1 w-full h-full relative">
          {!selectedFile ? (
            <UploadZone
              onFileSelected={handleFileSelected}
              isLoading={isLoading}
              error={error}
            />
          ) : !isWebglAvailable && webglDiagnostic ? (
            <WebGLErrorFallback
              diagnostic={webglDiagnostic}
              inspectionReport={inspectionReport}
              onRetry={() => setWebglDiagnostic(probeWebGLSupport())}
            />
          ) : inspectionReport ? (
            <Viewport3D
              report={inspectionReport}
              pdfFile={selectedFile}
              activeLayer={activeLayer}
              visibleLayers={visibleLayers}
              onSelectLayer={setActiveLayer}
              zoomLevel={zoomLevel}
              cameraResetTrigger={cameraResetTrigger}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-slate-400">
              <div className="flex items-center gap-3">
                <div className="w-6 h-6 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
                <span className="text-sm">Inspecting Document Structure...</span>
              </div>
            </div>
          )}
        </div>

        {/* Right: Floating Evidence Inspector */}
        {inspectionReport && isWebglAvailable && (
          <aside className="absolute top-6 right-6 z-20">
            <EvidencePanel
              report={inspectionReport}
              activeLayer={activeLayer}
              onSelectLayer={setActiveLayer}
            />
          </aside>
        )}

        {/* ---------------- Bottom Floating Spatial Controls ---------------- */}
        {inspectionReport && isWebglAvailable && (
          <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 px-3 py-2 rounded-2xl glass-panel shadow-2xl">
            {/* Spatial Mode Buttons */}
            <button
              title="Pan View"
              className="p-2 rounded-xl text-slate-400 hover:text-slate-100 hover:bg-white/[0.06] transition"
            >
              <Move className="w-4 h-4" />
            </button>

            <button
              title="Orbit Perspective Tilt"
              className="p-2 rounded-xl text-sky-400 bg-sky-500/10 border border-sky-500/20"
            >
              <Rotate3d className="w-4 h-4" />
            </button>

            <button
              title="Reset View"
              onClick={() => setCameraResetTrigger((c) => c + 1)}
              className="p-2 rounded-xl text-slate-400 hover:text-slate-100 hover:bg-white/[0.06] transition"
            >
              <RotateCcw className="w-4 h-4" />
            </button>

            <div className="w-px h-5 bg-white/10 mx-1" />

            {/* Zoom Controls */}
            <div className="flex items-center gap-1 text-xs text-slate-300 font-mono px-1">
              <button
                title="Zoom Out"
                onClick={() => setZoomLevel((z) => Math.max(50, z - 10))}
                className="p-1.5 rounded-lg hover:bg-white/[0.06] transition"
              >
                <ZoomOut className="w-3.5 h-3.5" />
              </button>
              <span className="min-w-[42px] text-center font-medium">{zoomLevel}%</span>
              <button
                title="Zoom In"
                onClick={() => setZoomLevel((z) => Math.min(200, z + 10))}
                className="p-1.5 rounded-lg hover:bg-white/[0.06] transition"
              >
                <ZoomIn className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="w-px h-5 bg-white/10 mx-1" />

            {/* Layer Visibility Toggles */}
            <button
              title="Toggle Catalog Layer Beacon"
              onClick={() =>
                setVisibleLayers((v) => ({ ...v, catalog: !v.catalog }))
              }
              className={`p-2 rounded-xl transition ${
                visibleLayers.catalog
                  ? "text-sky-400 bg-sky-500/10"
                  : "text-slate-500 hover:text-slate-300"
              }`}
            >
              <Box className="w-4 h-4" />
            </button>

            <button
              title="Toggle Annotations Layer Boxes"
              onClick={() =>
                setVisibleLayers((v) => ({ ...v, annotations: !v.annotations }))
              }
              className={`p-2 rounded-xl transition ${
                visibleLayers.annotations
                  ? "text-cyan-400 bg-cyan-500/10"
                  : "text-slate-500 hover:text-slate-300"
              }`}
            >
              <Layers className="w-4 h-4" />
            </button>

            <button
              title="Toggle Stego Kerning Lens"
              onClick={() =>
                setVisibleLayers((v) => ({ ...v, textStream: !v.textStream }))
              }
              className={`p-2 rounded-xl transition ${
                visibleLayers.textStream
                  ? "text-indigo-400 bg-indigo-500/10"
                  : "text-slate-500 hover:text-slate-300"
              }`}
            >
              <Type className="w-4 h-4" />
            </button>
          </div>
        )}
      </main>
    </div>
  );
};
