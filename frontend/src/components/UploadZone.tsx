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
            ? "glass-dock scale-[1.01] border-sky-400 shadow-xl"
            : "glass-dock hover:border-slate-300 shadow-lg"
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
          <div className="absolute inset-0 bg-sky-400/20 blur-xl rounded-full scale-150 animate-pulse" />
          <div className="relative w-20 h-20 rounded-2xl bg-white border border-slate-200/90 shadow-sm flex items-center justify-center text-sky-600 group-hover:scale-105 transition-transform">
            {isLoading ? (
              <div className="w-8 h-8 border-2 border-sky-600 border-t-transparent rounded-full animate-spin" />
            ) : (
              <FileText className="w-10 h-10" />
            )}
          </div>
        </div>

        <h3 className="text-xl font-semibold tracking-tight text-slate-900 mb-2">
          {isLoading ? "Inspecting Document Structure..." : "Drop PDF for Forensic Inspection"}
        </h3>
        <p className="text-sm text-slate-500 max-w-sm mb-6 leading-relaxed">
          {isLoading
            ? "Analyzing Catalog dictionaries, invisible annotations, and TJ stream kerning modulations..."
            : "Drag and drop your cold PDF document or browse from your filesystem. Strictly read-only analysis."}
        </p>

        <div className="flex items-center gap-3 text-xs text-slate-600">
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/80 border border-slate-200 shadow-xs">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
            Read-Only Isolation
          </span>
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/80 border border-slate-200 shadow-xs">
            Max 20 MB
          </span>
        </div>
      </div>

      {error && (
        <div className="mt-4 w-full p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center gap-3 shadow-xs">
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
};
