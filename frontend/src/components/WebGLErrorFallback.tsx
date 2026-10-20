import React from "react";
import { AlertTriangle, RefreshCw, Cpu, Monitor, CheckCircle, XCircle } from "lucide-react";
import { WebGLDiagnosticInfo, InspectionResponseDTO } from "../types/inspection";
import { EvidencePanel } from "./EvidencePanel";

interface WebGLErrorFallbackProps {
  diagnostic: WebGLDiagnosticInfo;
  inspectionReport: InspectionResponseDTO | null;
  onRetry: () => void;
}

export const WebGLErrorFallback: React.FC<WebGLErrorFallbackProps> = ({
  diagnostic,
  inspectionReport,
  onRetry,
}) => {
  return (
    <div className="flex flex-col items-center justify-center min-h-[550px] w-full max-w-2xl mx-auto p-6 z-10">
      <div className="w-full rounded-2xl glass-inspector p-8 flex flex-col items-center text-center shadow-xl">
        <div className="w-16 h-16 rounded-2xl bg-amber-50 border border-amber-200 flex items-center justify-center text-amber-600 mb-5 shadow-xs">
          <AlertTriangle className="w-8 h-8" />
        </div>

        <h3 className="text-xl font-semibold tracking-tight text-slate-900 mb-2">
          3D Hardware Acceleration Unavailable
        </h3>
        <p className="text-sm text-slate-600 max-w-md mb-6 leading-relaxed">
          {diagnostic.message} The forensic 3D inspection environment requires an active WebGL context.
        </p>

        {/* Sanitized Hardware Diagnostics Grid */}
        <div className="w-full rounded-xl bg-white/80 border border-slate-200/90 p-4 mb-6 text-left text-xs font-mono shadow-xs">
          <div className="text-[11px] font-sans font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Sanitized Hardware Diagnostics
          </div>

          <div className="grid grid-cols-2 gap-y-2.5 gap-x-4">
            <div className="flex items-center gap-2 text-slate-700">
              <Cpu className="w-4 h-4 text-sky-600 shrink-0" />
              <span className="text-slate-500">Vendor:</span>
              <span className="truncate font-semibold">{diagnostic.sanitized_vendor || "Unavailable"}</span>
            </div>

            <div className="flex items-center gap-2 text-slate-700">
              <Monitor className="w-4 h-4 text-sky-600 shrink-0" />
              <span className="text-slate-500">Renderer:</span>
              <span className="truncate font-semibold">{diagnostic.sanitized_renderer || "Unavailable"}</span>
            </div>

            <div className="flex items-center gap-2 text-slate-700">
              {diagnostic.webgl1_supported ? (
                <CheckCircle className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
              ) : (
                <XCircle className="w-3.5 h-3.5 text-rose-600 shrink-0" />
              )}
              <span className="text-slate-500">WebGL 1.0:</span>
              <span className="font-semibold">{diagnostic.webgl1_supported ? "Supported" : "Disabled"}</span>
            </div>

            <div className="flex items-center gap-2 text-slate-700">
              {diagnostic.webgl2_supported ? (
                <CheckCircle className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
              ) : (
                <XCircle className="w-3.5 h-3.5 text-rose-600 shrink-0" />
              )}
              <span className="text-slate-500">WebGL 2.0:</span>
              <span className="font-semibold">{diagnostic.webgl2_supported ? "Supported" : "Disabled"}</span>
            </div>
          </div>
        </div>

        {/* Troubleshooting guidance */}
        <div className="w-full p-4 rounded-xl bg-slate-50 border border-slate-200 text-left text-xs text-slate-700 mb-6">
          <div className="font-semibold text-slate-800 mb-1.5">Troubleshooting Steps:</div>
          <ul className="list-disc list-inside space-y-1 text-slate-600">
            <li>Enable "Hardware Acceleration" in your browser's system settings.</li>
            <li>Ensure graphics drivers are updated and WebGL is not blocked by enterprise policies.</li>
            <li>Restart your browser if GPU memory was recently exhausted by other applications.</li>
          </ul>
        </div>

        <button
          onClick={onRetry}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl glass-btn text-sm font-medium text-sky-700 hover:text-sky-800 shadow-sm"
        >
          <RefreshCw className="w-4 h-4" />
          Re-probe Graphics Context
        </button>
      </div>

      {/* Preserve inspection evidence report if available */}
      {inspectionReport && (
        <div className="w-full mt-6">
          <div className="text-xs uppercase tracking-wider text-slate-500 mb-2 font-semibold">
            Inspection Evidence Report (Preserved)
          </div>
          <EvidencePanel
            report={inspectionReport}
            activeLayer={0}
            onSelectLayer={() => {}}
            isStandAlone
          />
        </div>
      )}
    </div>
  );
};
