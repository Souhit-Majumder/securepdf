import React, { useState, useEffect, useRef } from "react";
import {
  Shield,
  Upload,
  Box,
  Layers,
  Type,
  RotateCcw,
  Move,
  Rotate3d,
  ZoomIn,
  ZoomOut,
  ChevronDown,
  Lock,
  Users,
  Loader2,
  AlertCircle,
  X,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import {
  InspectionResponseDTO,
  ActiveVerificationResponseDTO,
  WebGLDiagnosticInfo,
} from "./types/inspection";
import { probeWebGLSupport } from "./utils/webglCheck";
import { UploadZone } from "./components/UploadZone";
import { Viewport3D } from "./components/Viewport3D";
import { EvidencePanel } from "./components/EvidencePanel";
import { WebGLErrorFallback } from "./components/WebGLErrorFallback";
import { UserDTO } from "./types/auth";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { DistributionModal } from "./components/DistributionModal";
import { UserMenu } from "./components/UserMenu";
import { getSafeRedirect } from "./utils/safeRedirect";

export const App: React.FC = () => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [inspectionReport, setInspectionReport] = useState<InspectionResponseDTO | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Phase B verification state
  const [verificationResult, setVerificationResult] = useState<ActiveVerificationResponseDTO | null>(null);
  const [isVerifying, setIsVerifying] = useState(false);
  const [verificationError, setVerificationError] = useState<string | null>(null);
  const [forensicKey, setForensicKey] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Layer selection state (0 = Catalog, 1 = Annotations, 2 = Text Stream)
  const [activeLayer, setActiveLayer] = useState<number>(0);

  // Layer visibility toggles
  const [visibleLayers, setVisibleLayers] = useState({
    catalog: true,
    annotations: true,
    textStream: true,
  });

  // Spatial camera controls
  const [spatialTool, setSpatialTool] = useState<"orbit" | "pan">("orbit");
  const [zoomLevel, setZoomLevel] = useState<number>(100);
  const [cameraResetTrigger, setCameraResetTrigger] = useState<number>(0);

  // Multi-page navigation state
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(1);

  // Layer 2 annotation localization state
  const [selectedAnnotationXref, setSelectedAnnotationXref] = useState<number | null>(null);

  // WebGL diagnostic probe state
  const [webglDiagnostic, setWebglDiagnostic] = useState<WebGLDiagnosticInfo | null>(null);

  // Authentication & routing state
  const [currentUser, setCurrentUser] = useState<UserDTO | null>(null);
  const [isAuthLoading, setIsAuthLoading] = useState<boolean>(true);
  const [currentPath, setCurrentPath] = useState<string>(() => window.location.pathname || "/");

  // Distribution batch state
  const [isDistributionModalOpen, setIsDistributionModalOpen] = useState(false);
  const [activeDocumentUid, setActiveDocumentUid] = useState<string | null>(null);
  const [isDistributing, setIsDistributing] = useState(false);
  const [distributionError, setDistributionError] = useState<string | null>(null);

  // Check existing session on mount
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const res = await fetch("/api/auth/me", { credentials: "include" });
        if (res.ok) {
          const user: UserDTO = await res.json();
          setCurrentUser(user);
        } else {
          setCurrentUser(null);
        }
      } catch {
        setCurrentUser(null);
      } finally {
        setIsAuthLoading(false);
      }
    };
    checkAuth();
  }, []);

  // Listen to browser Back/Forward navigation
  useEffect(() => {
    const handlePopState = () => {
      setCurrentPath(window.location.pathname || "/");
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = (path: string) => {
    window.history.pushState({}, "", path);
    const url = new URL(path, window.location.origin);
    setCurrentPath(url.pathname);
  };

  // Route protection and safe redirection guard
  useEffect(() => {
    if (!isAuthLoading) {
      if (!currentUser && currentPath !== "/login" && currentPath !== "/register") {
        const redirectParam = currentPath !== "/" ? `?redirect=${encodeURIComponent(currentPath)}` : "";
        window.history.replaceState({}, "", `/login${redirectParam}`);
        setCurrentPath("/login");
      } else if (currentUser && (currentPath === "/login" || currentPath === "/register")) {
        const safe = getSafeRedirect(new URLSearchParams(window.location.search).get("redirect"));
        window.history.replaceState({}, "", safe);
        setCurrentPath(safe);
      }
    }
  }, [isAuthLoading, currentUser, currentPath]);

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } catch (err) {
      console.error("Logout request error:", err);
    } finally {
      setCurrentUser(null);
      navigate("/login");
    }
  };

  // Execute WebGL probe on mount
  useEffect(() => {
    const diagnostic = probeWebGLSupport();
    setWebglDiagnostic(diagnostic);
  }, []);

  const handleFileSelected = async (file: File) => {
    // Abort in-flight verification if running
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setVerificationResult(null);
    setIsVerifying(false);
    setVerificationError(null);
    setDistributionError(null);
    setActiveDocumentUid(null);
    setCurrentPage(1);
    setTotalPages(1);
    setSelectedAnnotationXref(null);

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
      if (report.document_uid) {
        setActiveDocumentUid(report.document_uid);
      }
    } catch (err: any) {
      console.error("Inspection request error:", err);
      setError(err.message || "Failed to inspect document structure.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpenDistribution = async () => {
    if (!currentUser) {
      navigate(`/login?redirect=${encodeURIComponent(window.location.pathname)}`);
      return;
    }
    if (!selectedFile) return;

    if (activeDocumentUid) {
      setDistributionError(null);
      setIsDistributionModalOpen(true);
      return;
    }

    setIsDistributing(true);
    setDistributionError(null);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("title", selectedFile.name);
      const res = await fetch("/documents/", {
        method: "POST",
        credentials: "include",
        body: formData,
      });

      if (!res.ok) {
        if (res.status === 401) {
          setCurrentUser(null);
          navigate(`/login?redirect=${encodeURIComponent(window.location.pathname)}`);
          return;
        }
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || `Document registration failed (HTTP ${res.status})`);
      }

      const data = await res.json();
      setActiveDocumentUid(data.document_uid);
      setIsDistributionModalOpen(true);
    } catch (err: any) {
      console.error("Document registration for distribution failed:", err);
      if (inspectionReport?.document_uid) {
        setActiveDocumentUid(inspectionReport.document_uid);
        setIsDistributionModalOpen(true);
      } else {
        setDistributionError(err.message || "Failed to register document for distribution.");
      }
    } finally {
      setIsDistributing(false);
    }
  };

  const handleStartVerification = async (key: string) => {
    if (!selectedFile) return;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    setIsVerifying(true);
    setVerificationError(null);

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const response = await fetch("/api/inspection/verify", {
        method: "POST",
        headers: {
          "X-SecurePDF-Audit-Key": key,
        },
        body: formData,
        signal: abortController.signal,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        if (response.status === 401 || response.status === 403) {
          setForensicKey(null); // Clear invalid key to re-prompt
        }
        throw new Error(errorData.detail || `Verification failed (HTTP ${response.status})`);
      }

      const result: ActiveVerificationResponseDTO = await response.json();
      setVerificationResult(result);
    } catch (err: any) {
      if (err.name === "AbortError") {
        console.info("Verification aborted by user or file switch.");
        return;
      }
      console.error("Verification error:", err);
      setVerificationError(err.message || "Failed to perform active verification.");
    } finally {
      setIsVerifying(false);
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
    }
  };

  const handleCancelVerification = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsVerifying(false);
  };

  const handleClearVerification = () => {
    setVerificationResult(null);
    setVerificationError(null);
  };

  if (isAuthLoading) {
    return (
      <div className="flex h-screen w-screen spatial-bg items-center justify-center font-sans">
        <div className="flex flex-col items-center gap-3 p-6 rounded-3xl glass-top-island border border-white/95 shadow-xl animate-in fade-in duration-150">
          <div className="w-10 h-10 rounded-2xl bg-sky-500/15 border border-sky-400/40 flex items-center justify-center text-sky-600 shadow-xs">
            <Shield className="w-5 h-5 animate-pulse" />
          </div>
          <span className="text-xs font-medium text-slate-500">Verifying session...</span>
        </div>
      </div>
    );
  }

  if (currentPath === "/login") {
    return (
      <LoginPage
        currentUser={currentUser}
        onLoginSuccess={(user) => {
          setCurrentUser(user);
        }}
        onNavigate={navigate}
      />
    );
  }

  if (currentPath === "/register") {
    return (
      <RegisterPage
        currentUser={currentUser}
        onRegisterSuccess={(user) => {
          setCurrentUser(user);
        }}
        onNavigate={navigate}
      />
    );
  }

  const isWebglAvailable =
    webglDiagnostic && (webglDiagnostic.webgl1_supported || webglDiagnostic.webgl2_supported);

  return (
    <div className="flex flex-col h-screen w-screen spatial-bg text-slate-800 overflow-hidden relative font-sans">
      {/* ---------------- Floating Top Glass Island Header (Matches Design Reference) ---------------- */}
      <header className="absolute top-4 left-1/2 -translate-x-1/2 z-30 h-11 px-5 rounded-2xl glass-top-island flex items-center gap-4 shadow-xl pointer-events-auto">
        {/* Brand Logo & Name */}
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md bg-sky-500/10 border border-sky-400/30 flex items-center justify-center text-sky-600 shadow-xs">
            <Shield className="w-3.5 h-3.5" />
          </div>
          <span className="font-semibold tracking-tight text-xs text-slate-900">
            SecurePDF
          </span>
        </div>

        {/* Center File Pill */}
        {selectedFile && (
          <div className="hidden sm:flex items-center gap-1.5 px-3 py-1 rounded-xl bg-white/70 border border-white/90 text-xs text-slate-800 shadow-xs">
            <Lock className="w-3 h-3 text-sky-600" />
            <span className="truncate max-w-[170px] font-medium text-[11px]">
              {selectedFile.name}
            </span>
            <ChevronDown className="w-2.5 h-2.5 text-slate-400" />
          </div>
        )}


        <div className="w-px h-3.5 bg-slate-300/60" />

        {/* Right Action Controls */}
        <div className="flex items-center gap-2">
          {selectedFile && (
            <button
              onClick={handleOpenDistribution}
              disabled={isDistributing}
              title="Create personalized watermarked distribution batch"
              className="h-7 px-3 rounded-full bg-sky-500/15 hover:bg-sky-500/25 border border-sky-400/40 text-sky-700 text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer shadow-xs disabled:opacity-60 disabled:cursor-wait"
            >
              {isDistributing ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Preparing...</span>
                </>
              ) : (
                <>
                  <Users className="w-3.5 h-3.5" />
                  <span>Distribute</span>
                </>
              )}
            </button>
          )}

          <label className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl glass-btn text-xs font-medium text-slate-700 cursor-pointer">
            <Upload className="w-3 h-3 text-sky-600" />
            <span className="text-[11px]">{selectedFile ? "Inspect Another" : "Open PDF"}</span>
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

          {currentUser && (
            <UserMenu
              user={currentUser}
              onLogout={handleLogout}
            />
          )}
        </div>
      </header>

      {/* Distribution Error Alert */}
      {distributionError && (
        <div className="absolute top-18 left-1/2 -translate-x-1/2 z-40 max-w-md px-4 py-2.5 rounded-2xl bg-rose-50/95 border border-rose-300 text-rose-800 text-xs shadow-xl flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <AlertCircle className="w-4 h-4 text-rose-500 shrink-0" />
          <span className="font-medium flex-1">{distributionError}</span>
          <button
            onClick={() => setDistributionError(null)}
            className="p-1 text-rose-400 hover:text-rose-700 rounded-lg hover:bg-rose-100/50 cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* ---------------- Main Forensic Workspace ---------------- */}
      <main className="flex-1 w-full h-full relative overflow-hidden flex items-center justify-center">
        {/* Left: Floating Dark-Slate Frosted Glass Layer Selector Dock (Matches Reference Image) */}
        {inspectionReport && isWebglAvailable && (
          <aside className="absolute top-24 left-8 z-20 w-44 glass-dock-dark rounded-2xl p-2.5 flex flex-col gap-1.5 shadow-2xl">
            <div className="text-[8.5px] font-bold uppercase tracking-wider text-slate-400 px-2 py-0.5">
              Layers
            </div>

            {/* Layer 01: Catalog */}
            <button
              onClick={() => setActiveLayer(0)}
              className={`w-full flex items-center gap-2.5 p-2 rounded-xl text-left transition-all duration-200 relative ${
                activeLayer === 0
                  ? "glass-dock-item-active text-white font-semibold"
                  : "hover:bg-white/10 text-slate-300 hover:text-white"
              }`}
            >
              <div
                className={`w-5 h-5 rounded-lg flex items-center justify-center shrink-0 ${
                  activeLayer === 0
                    ? "bg-white/20 text-sky-300"
                    : "bg-white/5 text-slate-400"
                }`}
              >
                <Box className="w-3.5 h-3.5" />
              </div>
              <div className="min-w-0">
                <div className="text-[11px] font-medium truncate">01 Catalog</div>
                <div className="text-[8.5px] text-slate-400 truncate">Object references</div>
              </div>
            </button>

            {/* Layer 02: Annotations */}
            <button
              onClick={() => setActiveLayer(1)}
              className={`w-full flex items-center gap-2.5 p-2 rounded-xl text-left transition-all duration-200 relative ${
                activeLayer === 1
                  ? "glass-dock-item-active text-white font-semibold"
                  : "hover:bg-white/10 text-slate-300 hover:text-white"
              }`}
            >
              <div
                className={`w-5 h-5 rounded-lg flex items-center justify-center shrink-0 ${
                  activeLayer === 1
                    ? "bg-white/20 text-cyan-300"
                    : "bg-white/5 text-slate-400"
                }`}
              >
                <Layers className="w-3.5 h-3.5" />
              </div>
              <div className="min-w-0">
                <div className="text-[11px] font-medium truncate">02 Annotations</div>
                <div className="text-[8.5px] text-slate-400 truncate">Page annotations</div>
              </div>
            </button>

            {/* Layer 03: Text Stream */}
            <button
              onClick={() => setActiveLayer(2)}
              className={`w-full flex items-center gap-2.5 p-2 rounded-xl text-left transition-all duration-200 relative ${
                activeLayer === 2
                  ? "glass-dock-item-active text-white font-semibold"
                  : "hover:bg-white/10 text-slate-300 hover:text-white"
              }`}
            >
              <div
                className={`w-5 h-5 rounded-lg flex items-center justify-center shrink-0 ${
                  activeLayer === 2
                    ? "bg-white/20 text-indigo-300"
                    : "bg-white/5 text-slate-400"
                }`}
              >
                <Type className="w-3.5 h-3.5" />
              </div>
              <div className="min-w-0">
                <div className="text-[11px] font-medium truncate">03 Text Stream</div>
                <div className="text-[8.5px] text-slate-400 truncate">Kerning modulation</div>
              </div>
            </button>
          </aside>
        )}

        {/* Inner Box: Large Translucent Frosted Glass Sheet & 3D Stage (Matches Reference Image) */}
        <div className="w-[82%] max-w-[1240px] h-[76%] max-h-[720px] spatial-backdrop-sheet rounded-[32px] relative overflow-hidden shadow-2xl z-10 flex items-center justify-center">
          <div className="w-full h-full relative">
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
                spatialTool={spatialTool}
                currentPage={currentPage}
                onTotalPagesChange={setTotalPages}
                selectedAnnotationXref={selectedAnnotationXref}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-slate-500">
                <div className="flex items-center gap-2.5">
                  <div className="w-4 h-4 border-2 border-sky-500 border-t-transparent rounded-full animate-spin" />
                  <span className="text-xs font-medium tracking-wide">Inspecting Document Structure...</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right: Floating Frosted Glass Evidence Instrument Panel (Aligned with Left Dock) */}
        {inspectionReport && isWebglAvailable && (
          <aside className="absolute top-24 right-8 z-20">
            <EvidencePanel
              report={inspectionReport}
              activeLayer={activeLayer}
              onSelectLayer={setActiveLayer}
              verificationResult={verificationResult}
              isVerifying={isVerifying}
              verificationError={verificationError}
              onVerify={handleStartVerification}
              onCancelVerify={handleCancelVerification}
              onClearVerify={handleClearVerification}
              forensicKey={forensicKey}
              onSetForensicKey={setForensicKey}
              selectedAnnotationXref={selectedAnnotationXref}
              onSelectAnnotation={setSelectedAnnotationXref}
              onPageChange={setCurrentPage}
              currentPage={currentPage}
            />
          </aside>
        )}

        {/* ---------------- Bottom Floating Compact Optical-Glass Control Strip ---------------- */}
        {inspectionReport && isWebglAvailable && (
          <div className="absolute bottom-7 left-1/2 -translate-x-1/2 z-20 flex items-center gap-1.5 px-3 py-1.5 rounded-full glass-toolbar shadow-xl pointer-events-auto">
            {/* Spatial Mode Buttons */}
            <button
              title="Pan View"
              onClick={() => setSpatialTool("pan")}
              className={`p-1.5 rounded-full transition ${
                spatialTool === "pan"
                  ? "text-sky-800 bg-sky-500/20 border border-sky-400/40"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white/40"
              }`}
            >
              <Move className="w-3.5 h-3.5" />
            </button>

            <button
              title="Orbit Perspective Tilt"
              onClick={() => setSpatialTool("orbit")}
              className={`p-1.5 rounded-full transition ${
                spatialTool === "orbit"
                  ? "text-sky-800 bg-sky-500/20 border border-sky-400/40"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white/40"
              }`}
            >
              <Rotate3d className="w-3.5 h-3.5" />
            </button>

            <button
              title="Reset View"
              onClick={() => {
                setZoomLevel(100);
                setCameraResetTrigger((c) => c + 1);
              }}
              className="p-1.5 rounded-full text-slate-600 hover:text-slate-900 hover:bg-white/40 transition"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>

            <div className="w-px h-3.5 bg-slate-300/60 mx-0.5" />

            {/* Zoom Controls */}
            <div className="flex items-center gap-0.5 text-[9.5px] text-slate-800 font-mono px-0.5">
              <button
                title="Zoom Out"
                onClick={() => setZoomLevel((z) => Math.max(50, z - 10))}
                className="p-0.5 rounded-full hover:bg-white/40 transition"
              >
                <ZoomOut className="w-3 h-3" />
              </button>
              <span className="min-w-[32px] text-center font-semibold">{zoomLevel}%</span>
              <button
                title="Zoom In"
                onClick={() => setZoomLevel((z) => Math.min(200, z + 10))}
                className="p-0.5 rounded-full hover:bg-white/40 transition"
              >
                <ZoomIn className="w-3 h-3" />
              </button>
            </div>

            <div className="w-px h-3.5 bg-slate-300/60 mx-0.5" />

            {/* Page Navigation Controls */}
            <div className="flex items-center gap-0.5 text-[9.5px] text-slate-800 font-mono px-0.5">
              <button
                title="Previous Page"
                disabled={currentPage <= 1}
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                className="p-1 rounded-full text-slate-600 hover:text-slate-900 hover:bg-white/40 disabled:opacity-30 disabled:hover:bg-transparent transition cursor-pointer disabled:cursor-not-allowed"
              >
                <ChevronLeft className="w-3 h-3" />
              </button>
              <span className="min-w-[42px] text-center font-semibold text-[9px] px-1 select-none">
                {currentPage} / {totalPages}
              </span>
              <button
                title="Next Page"
                disabled={currentPage >= totalPages}
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                className="p-1 rounded-full text-slate-600 hover:text-slate-900 hover:bg-white/40 disabled:opacity-30 disabled:hover:bg-transparent transition cursor-pointer disabled:cursor-not-allowed"
              >
                <ChevronRight className="w-3 h-3" />
              </button>
            </div>

            <div className="w-px h-3.5 bg-slate-300/60 mx-0.5" />

            {/* Layer Visibility Toggles */}
            <button
              title="Toggle Layer 1 (Catalog)"
              onClick={() =>
                setVisibleLayers((v) => ({ ...v, catalog: !v.catalog }))
              }
              className={`px-2 py-0.5 rounded-full text-[9.5px] font-mono transition ${
                visibleLayers.catalog
                  ? "text-sky-800 bg-sky-500/20 border border-sky-400/40 font-bold"
                  : "text-slate-400 hover:text-slate-700 hover:bg-white/30"
              }`}
            >
              01
            </button>

            <button
              title="Toggle Layer 2 (Annotations)"
              onClick={() =>
                setVisibleLayers((v) => ({ ...v, annotations: !v.annotations }))
              }
              className={`px-2 py-0.5 rounded-full text-[9.5px] font-mono transition ${
                visibleLayers.annotations
                  ? "text-cyan-800 bg-cyan-500/20 border border-cyan-400/40 font-bold"
                  : "text-slate-400 hover:text-slate-700 hover:bg-white/30"
              }`}
            >
              02
            </button>

            <button
              title="Toggle Layer 3 (Text Stream)"
              onClick={() =>
                setVisibleLayers((v) => ({ ...v, textStream: !v.textStream }))
              }
              className={`px-2 py-0.5 rounded-full text-[9.5px] font-mono transition ${
                visibleLayers.textStream
                  ? "text-indigo-800 bg-indigo-500/20 border border-indigo-400/40 font-bold"
                  : "text-slate-400 hover:text-slate-700 hover:bg-white/30"
              }`}
            >
              03
            </button>
          </div>
        )}
      </main>

      {/* Distribution Modal */}
      {selectedFile && (
        <DistributionModal
          isOpen={isDistributionModalOpen}
          onClose={() => setIsDistributionModalOpen(false)}
          documentUid={activeDocumentUid || inspectionReport?.document_uid || ""}
          documentTitle={selectedFile.name}
        />
      )}
    </div>
  );
};
