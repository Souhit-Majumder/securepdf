import React, { useState, useRef } from "react";
import { FileText, AlertCircle, ShieldCheck } from "lucide-react";

interface UploadZoneProps {
  onFileSelected: (file: File) => void;
  isLoading: boolean;
  error: string | null;
}

export const UploadZone: React.FC<UploadZoneProps> = ({
  onFileSelected,
  isLoading,
  error,
}) => {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndProcess(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      validateAndProcess(e.target.files[0]);
    }
  };

  const validateAndProcess = (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      alert("Only PDF documents are supported.");
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      alert("Document exceeds maximum size limit of 20MB.");
      return;
    }
    onFileSelected(file);
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-[500px] w-full max-w-xl mx-auto p-6">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`w-full relative cursor-pointer group rounded-2xl p-10 flex flex-col items-center justify-center text-center transition-all duration-300 ${
          isDragOver
            ? "glass-panel-bright scale-[1.02] border-sky-400"
            : "glass-panel hover:border-slate-500/50"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={handleFileChange}
        />

        {/* Ambient glow icon */}
        <div className="relative mb-6">
          <div className="absolute inset-0 bg-sky-500/20 blur-xl rounded-full scale-150 animate-pulse" />
          <div className="relative w-20 h-20 rounded-2xl glass-panel-bright flex items-center justify-center text-sky-400 group-hover:scale-105 transition-transform">
            {isLoading ? (
              <div className="w-8 h-8 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
            ) : (
              <FileText className="w-10 h-10" />
            )}
          </div>
        </div>

        <h3 className="text-xl font-medium tracking-tight text-slate-100 mb-2">
          {isLoading ? "Inspecting Document Structure..." : "Drop PDF for Forensic Inspection"}
        </h3>
        <p className="text-sm text-slate-400 max-w-sm mb-6 leading-relaxed">
          {isLoading
            ? "Analyzing Catalog dictionaries, invisible annotations, and TJ stream kerning modulations..."
            : "Drag and drop your cold PDF document or browse from your filesystem. Strictly read-only analysis."}
        </p>

        <div className="flex items-center gap-3 text-xs text-slate-400">
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-full glass-pill">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            Read-Only Isolation
          </span>
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-full glass-pill">
            Max 20 MB
          </span>
        </div>
      </div>

      {error && (
        <div className="mt-4 w-full p-4 rounded-xl glass-panel border-rose-500/30 text-rose-300 text-xs flex items-center gap-3">
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
};
