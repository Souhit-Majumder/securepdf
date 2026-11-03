import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  X,
  Clock,
  Users,
  Plus,
  Trash2,
  AlertCircle,
  CheckCircle2,
  Loader2,
  FileText,
  Send,
  HelpCircle,
  RefreshCw,
  Sparkles,
  AlertTriangle,
  Download,
  Copy,
  Check,
  Upload,
  FileSpreadsheet,
  Search,
  Info,
} from "lucide-react";
import {
  RecipientInput,
  CsvParseResult,
  parseAndValidateRecipients,
  getStegoStatusExplanation,
  getBatchStatusExplanation,
  calculateBatchSummaryMetrics,
  formatActiveLinksText,
  exportBatchRecipientsCsv,
  BatchRecipientItem,
  BatchSummaryMetrics,
} from "../utils/distributionUtils";

interface DistributionModalProps {
  isOpen: boolean;
  onClose: () => void;
  documentUid: string;
  documentTitle: string;
}

const EXPIRY_OPTIONS = [
  { label: "2 minutes (Default Testing)", value: 120 },
  { label: "15 minutes", value: 900 },
  { label: "1 hour", value: 3600 },
  { label: "24 hours", value: 86400 },
  { label: "7 days", value: 604800 },
  { label: "Custom Duration", value: -1 },
];

export const DistributionModal: React.FC<DistributionModalProps> = ({
  isOpen,
  onClose,
  documentUid,
  documentTitle,
}) => {
  // Expiry state
  const [selectedDuration, setSelectedDuration] = useState<number>(120); // Default 2 minutes
  const [customSeconds, setCustomSeconds] = useState<string>("300");

  // Mode state: 'manual' vs 'import'
  const [inputMode, setInputMode] = useState<"manual" | "import">("manual");

  // Manual recipient input state
  const [recipientName, setRecipientName] = useState("");
  const [recipientUid, setRecipientUid] = useState("");
  const [recipients, setRecipients] = useState<RecipientInput[]>([]);

  // CSV/TSV Import state
  const [importText, setImportText] = useState("");
  const [importParseResult, setImportParseResult] = useState<CsvParseResult | null>(null);
  const [importFilter, setImportFilter] = useState<"ALL" | "VALID" | "DUPLICATES" | "INVALID">("ALL");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Queue search & confirmation
  const [queueSearch, setQueueSearch] = useState("");
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  // Form & submission state
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [enableStage1, setEnableStage1] = useState<boolean>(true);
  const [enableStage2, setEnableStage2] = useState<boolean>(true);
  const [enableStage3, setEnableStage3] = useState<boolean>(false);
  const [successBatch, setSuccessBatch] = useState<{
    batch_uid: string;
    total_recipients: number;
    expiry_duration_seconds: number;
    status: string;
    enable_stage1?: boolean;
    enable_stage2?: boolean;
    enable_stage3?: boolean;
    stego_status?: "PENDING" | "SKIPPED" | "SUCCESS" | "FAILED" | "PARTIAL";
    recipients?: BatchRecipientItem[];
  } | null>(null);

  // Results screen search and filter
  const [resultsSearch, setResultsSearch] = useState("");
  const [resultsFilter, setResultsFilter] = useState<"ALL" | "ACTIVE" | "EXPIRED" | "FAILED">("ALL");
  const [copiedIdentifier, setCopiedIdentifier] = useState<string | null>(null);
  const [copiedAllFeedback, setCopiedAllFeedback] = useState(false);

  // Live timer for second-by-second countdown
  const [nowMs, setNowMs] = useState<number>(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !isLoading && !isGenerating) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isLoading, isGenerating, onClose]);

  // Polling for generation progress
  useEffect(() => {
    let intervalId: any = null;

    if (successBatch && (successBatch.status === "PROCESSING" || isGenerating)) {
      intervalId = setInterval(async () => {
        try {
          const res = await fetch(`/api/documents/batches/${successBatch.batch_uid}`, {
            credentials: "include",
          });
          if (res.ok) {
            const data = await res.json();
            setSuccessBatch({
              batch_uid: data.batch_uid,
              total_recipients: data.total_recipients,
              expiry_duration_seconds: data.expiry_duration_seconds,
              status: data.status,
              enable_stage1: data.enable_stage1,
              enable_stage2: data.enable_stage2,
              enable_stage3: data.enable_stage3,
              stego_status: data.stego_status,
              recipients: data.recipients,
            });
            if (["COMPLETED", "PARTIALLY_FAILED", "FAILED"].includes(data.status)) {
              setIsGenerating(false);
            }
          }
        } catch {
          // Ignore transient network errors during polling
        }
      }, 1500);
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [successBatch?.batch_uid, successBatch?.status, isGenerating]);

  // Parse imported text whenever importText or existing queue changes
  useEffect(() => {
    if (importText.trim()) {
      const parsed = parseAndValidateRecipients(importText, recipients);
      setImportParseResult(parsed);
    } else {
      setImportParseResult(null);
    }
  }, [importText, recipients]);

  const effectiveDuration =
    selectedDuration === -1 ? parseInt(customSeconds, 10) || 120 : selectedDuration;

  // Manual recipient submission handler
  const handleAddRecipient = (e: React.FormEvent) => {
    e.preventDefault();
    setInputError(null);

    const trimmedName = recipientName.trim();
    const trimmedUid = recipientUid.trim();

    if (!trimmedName) {
      setInputError("Recipient name is required.");
      return;
    }
    if (!trimmedUid) {
      setInputError("Recipient identifier (e.g. Student UID) is required.");
      return;
    }

    if (trimmedName.length > 255 || trimmedUid.length > 255) {
      setInputError("Name or identifier exceeds 255 characters maximum limit.");
      return;
    }

    if (recipients.length >= 1000) {
      setInputError("Maximum batch capacity of 1,000 recipients reached.");
      return;
    }

    // Check duplicate identifier within this batch queue (case-insensitive)
    const exists = recipients.some(
      (r) => r.student_uid.toLowerCase() === trimmedUid.toLowerCase()
    );
    if (exists) {
      setInputError(`Recipient identifier "${trimmedUid}" is already in this batch queue.`);
      return;
    }

    setRecipients([...recipients, { name: trimmedName, student_uid: trimmedUid }]);
    setRecipientName("");
    setRecipientUid("");
  };

  const handleRemoveRecipient = (indexToRemove: number) => {
    setRecipients(recipients.filter((_, idx) => idx !== indexToRemove));
  };

  const handleClearQueue = () => {
    setRecipients([]);
    setShowClearConfirm(false);
  };

  // CSV/TSV file picker handler
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      if (content) {
        setImportText(content);
      }
    };
    reader.readAsText(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // Commit valid imported rows into the queue
  const handleCommitImport = () => {
    if (!importParseResult || importParseResult.validRows.length === 0) return;

    const remainingCapacity = 1000 - recipients.length;
    const rowsToAdd = importParseResult.validRows.slice(0, remainingCapacity);

    setRecipients([...recipients, ...rowsToAdd]);
    setImportText("");
    setImportParseResult(null);
    setInputMode("manual");
  };

  // Batch registration submission
  const handleSubmitBatch = async () => {
    setApiError(null);

    if (recipients.length === 0) {
      setApiError("Please add at least one recipient to the batch.");
      return;
    }

    if (!enableStage1 && !enableStage2 && !enableStage3) {
      setApiError("At least one security stage must be selected.");
      return;
    }

    if (effectiveDuration < 30 || effectiveDuration > 2592000) {
      setApiError("Duration must be between 30 seconds and 30 days (2,592,000 seconds).");
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch(`/api/documents/${documentUid}/batches`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          expiry_duration_seconds: effectiveDuration,
          enable_stage1: enableStage1,
          enable_stage2: enableStage2,
          enable_stage3: enableStage3,
          recipients: recipients,
        }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to create distribution batch.");
      }

      setSuccessBatch({
        batch_uid: data.batch_uid,
        total_recipients: data.total_recipients,
        expiry_duration_seconds: data.expiry_duration_seconds,
        status: data.status,
        enable_stage1: data.enable_stage1,
        enable_stage2: data.enable_stage2,
        enable_stage3: data.enable_stage3,
        stego_status: data.stego_status,
        recipients: data.recipients,
      });
    } catch (err: any) {
      setApiError(err.message || "An unexpected error occurred during batch creation.");
    } finally {
      setIsLoading(false);
    }
  };

  // Start personalized PDF watermarking & carrier embedding
  const handleStartGeneration = async () => {
    if (!successBatch) return;
    setIsGenerating(true);
    setGenerationError(null);

    try {
      const response = await fetch(`/api/documents/batches/${successBatch.batch_uid}/generate`, {
        method: "POST",
        credentials: "include",
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to initiate PDF generation.");
      }

      setSuccessBatch({
        batch_uid: data.batch_uid,
        total_recipients: data.total_recipients,
        expiry_duration_seconds: data.expiry_duration_seconds,
        status: data.status,
        enable_stage1: data.enable_stage1,
        enable_stage2: data.enable_stage2,
        enable_stage3: data.enable_stage3,
        stego_status: data.stego_status,
        recipients: data.recipients,
      });

      if (["COMPLETED", "PARTIALLY_FAILED", "FAILED"].includes(data.status)) {
        setIsGenerating(false);
      }
    } catch (err: any) {
      setGenerationError(err.message || "Failed to trigger generation.");
      setIsGenerating(false);
    }
  };

  const handleReset = () => {
    setSuccessBatch(null);
    setRecipients([]);
    setRecipientName("");
    setRecipientUid("");
    setEnableStage1(true);
    setEnableStage2(true);
    setEnableStage3(false);
    setSelectedDuration(120);
    setCustomSeconds("300");
    setApiError(null);
    setInputError(null);
    setGenerationError(null);
    setIsGenerating(false);
    setResultsSearch("");
    setResultsFilter("ALL");
  };

  const handleCopyLink = async (recipientIdentifier: string, downloadUrl: string) => {
    try {
      const fullUrl = `${window.location.origin}${downloadUrl}`;
      await navigator.clipboard.writeText(fullUrl);
      setCopiedIdentifier(recipientIdentifier);
      setTimeout(() => {
        setCopiedIdentifier((prev) => (prev === recipientIdentifier ? null : prev));
      }, 2000);
    } catch (err) {
      console.error("Failed to copy link:", err);
    }
  };

  const handleCopyAllActive = async () => {
    if (!successBatch?.recipients) return;
    const text = formatActiveLinksText(
      documentTitle,
      successBatch.batch_uid,
      successBatch.recipients,
      window.location.origin,
      nowMs
    );
    try {
      await navigator.clipboard.writeText(text);
      setCopiedAllFeedback(true);
      setTimeout(() => setCopiedAllFeedback(false), 2200);
    } catch (err) {
      console.error("Failed to copy links block:", err);
    }
  };

  const handleExportCsv = () => {
    if (!successBatch?.recipients) return;
    exportBatchRecipientsCsv(
      documentTitle,
      successBatch.batch_uid,
      successBatch.recipients,
      window.location.origin,
      nowMs
    );
  };

  const getRemainingSeconds = (expiresAtStr?: string | null): number => {
    if (!expiresAtStr) return 0;
    const expTime = new Date(expiresAtStr).getTime();
    return Math.max(0, Math.floor((expTime - nowMs) / 1000));
  };

  const formatCountdown = (seconds: number): string => {
    if (seconds <= 0) return "Expired";
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    if (m >= 60) {
      const h = Math.floor(m / 60);
      const remM = m % 60;
      return `${h}h ${remM}m`;
    }
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  // Filtered queue items
  const filteredQueue = useMemo(() => {
    if (!queueSearch.trim()) return recipients;
    const q = queueSearch.toLowerCase().trim();
    return recipients.filter(
      (r) => r.name.toLowerCase().includes(q) || r.student_uid.toLowerCase().includes(q)
    );
  }, [recipients, queueSearch]);

  // Filtered import preview rows
  const previewRows = useMemo(() => {
    if (!importParseResult) return [];
    if (importFilter === "VALID") {
      return importParseResult.allRows.filter((r) => r.status === "VALID");
    }
    if (importFilter === "DUPLICATES") {
      return importParseResult.allRows.filter(
        (r) => r.status === "DUPLICATE_INTERNAL" || r.status === "DUPLICATE_QUEUE"
      );
    }
    if (importFilter === "INVALID") {
      return importParseResult.allRows.filter(
        (r) =>
          r.status === "INVALID_NAME" ||
          r.status === "INVALID_UID" ||
          r.status === "TOO_LONG"
      );
    }
    return importParseResult.allRows;
  }, [importParseResult, importFilter]);

  // Derived batch metrics
  const summaryMetrics: BatchSummaryMetrics = useMemo(() => {
    return calculateBatchSummaryMetrics(
      successBatch?.recipients || [],
      successBatch?.total_recipients || 0,
      nowMs
    );
  }, [successBatch?.recipients, successBatch?.total_recipients, nowMs]);

  // Filtered generated recipient list
  const filteredResults = useMemo(() => {
    if (!successBatch?.recipients) return [];
    let list = successBatch.recipients;

    // Search filter
    if (resultsSearch.trim()) {
      const q = resultsSearch.toLowerCase().trim();
      list = list.filter(
        (r) =>
          r.recipient_name.toLowerCase().includes(q) ||
          r.recipient_identifier.toLowerCase().includes(q)
      );
    }

    // Status filter
    if (resultsFilter === "ACTIVE") {
      list = list.filter((r) => {
        if (r.status !== "GENERATED" || !r.download_url) return false;
        if (!r.expires_at) return true;
        return new Date(r.expires_at).getTime() > nowMs;
      });
    } else if (resultsFilter === "EXPIRED") {
      list = list.filter((r) => {
        if (r.status === "EXPIRED") return true;
        if (r.expires_at && new Date(r.expires_at).getTime() <= nowMs) return true;
        return false;
      });
    } else if (resultsFilter === "FAILED") {
      list = list.filter((r) => r.status === "FAILED");
    }

    return list;
  }, [successBatch?.recipients, resultsSearch, resultsFilter, nowMs]);

  // Status explanations
  const batchExplanation = getBatchStatusExplanation(successBatch?.status || "PENDING");
  const stegoExplanation = getStegoStatusExplanation(
    successBatch?.stego_status,
    successBatch?.enable_stage3
  );

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Daylight Frosted Backdrop */}
      <div
        className="absolute inset-0 bg-slate-900/30 backdrop-blur-md transition-opacity"
        onClick={!isLoading && !isGenerating ? onClose : undefined}
      />

      {/* Apple Liquid Glass Dialog Card */}
      <div className="relative w-full max-w-2xl rounded-3xl glass-top-island p-6 border border-white/95 shadow-2xl space-y-4 animate-in fade-in zoom-in-95 duration-150 z-10 max-h-[92vh] flex flex-col backdrop-blur-2xl">
        {/* Modal Header */}
        <div className="flex items-start justify-between border-b border-slate-200/60 pb-3 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-sky-500/15 border border-sky-400/35 flex items-center justify-center text-sky-600 shadow-xs">
              <Users className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-900 tracking-tight">
                {successBatch ? "Personalized Batch Distribution" : "Create Distribution Batch"}
              </h2>
              <div className="flex items-center gap-1.5 text-xs text-slate-500 truncate max-w-md mt-0.5">
                <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                <span className="font-medium text-slate-700 truncate">{documentTitle}</span>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isLoading || isGenerating}
            className="p-1.5 rounded-full hover:bg-slate-200/50 text-slate-400 hover:text-slate-700 transition cursor-pointer disabled:opacity-40"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* -------------------- Results & Generation State -------------------- */}
        {successBatch ? (
          <div className="space-y-4 overflow-y-auto pr-1 flex-1 animate-in fade-in">
            {/* Status Header & Plain-Language Explanation */}
            <div className="p-4 rounded-2xl bg-white/70 border border-slate-200/80 backdrop-blur-xl shadow-xs space-y-2.5">
              <div className="flex items-start gap-3">
                <div
                  className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 border transition-all ${
                    batchExplanation.variant === "success"
                      ? "bg-emerald-500/15 border-emerald-400/40 text-emerald-600"
                      : batchExplanation.variant === "info"
                      ? "bg-sky-500/15 border-sky-400/40 text-sky-600 animate-pulse"
                      : batchExplanation.variant === "warning"
                      ? "bg-amber-500/15 border-amber-400/40 text-amber-600"
                      : batchExplanation.variant === "error"
                      ? "bg-rose-500/15 border-rose-400/40 text-rose-600"
                      : "bg-slate-500/10 border-slate-300 text-slate-600"
                  }`}
                >
                  {batchExplanation.variant === "success" && <CheckCircle2 className="w-5 h-5" />}
                  {batchExplanation.variant === "info" && <Loader2 className="w-5 h-5 animate-spin" />}
                  {batchExplanation.variant === "warning" && <AlertTriangle className="w-5 h-5" />}
                  {batchExplanation.variant === "error" && <AlertCircle className="w-5 h-5" />}
                  {batchExplanation.variant === "neutral" && <Sparkles className="w-5 h-5" />}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="text-sm font-bold text-slate-900 tracking-tight">
                      {batchExplanation.title}
                    </h3>
                    <span
                      className={`px-2 py-0.5 rounded-md font-semibold text-[10px] ${
                        successBatch.status === "COMPLETED"
                          ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
                          : successBatch.status === "PROCESSING"
                          ? "bg-sky-100 text-sky-800 border border-sky-200"
                          : successBatch.status === "PARTIALLY_FAILED"
                          ? "bg-amber-100 text-amber-800 border border-amber-200"
                          : successBatch.status === "FAILED"
                          ? "bg-rose-100 text-rose-800 border border-rose-200"
                          : "bg-slate-100 text-slate-700 border border-slate-200"
                      }`}
                    >
                      {successBatch.status}
                    </span>
                    <span
                      data-testid="batch-stego-status"
                      className={`px-2 py-0.5 rounded-md font-semibold text-[10px] ${
                        stegoExplanation.variant === "success"
                          ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
                          : stegoExplanation.variant === "warning"
                          ? "bg-amber-100 text-amber-800 border border-amber-200"
                          : stegoExplanation.variant === "error"
                          ? "bg-rose-100 text-rose-800 border border-rose-200"
                          : stegoExplanation.variant === "info"
                          ? "bg-sky-100 text-sky-800 border border-sky-200"
                          : "bg-slate-100 text-slate-700 border border-slate-200"
                      }`}
                    >
                      {successBatch.stego_status || "PENDING"}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
                    {batchExplanation.subtitle}
                  </p>
                  {/* Applied Carrier Stages Badges */}
                  <div className="flex items-center gap-1.5 flex-wrap pt-1.5" data-testid="applied-stages-container">
                    <span className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">Stages:</span>
                    {successBatch.enable_stage1 && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-sky-100 text-sky-800 border border-sky-200">
                        Stage 1 (Catalog)
                      </span>
                    )}
                    {successBatch.enable_stage2 && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-sky-100 text-sky-800 border border-sky-200">
                        Stage 2 (Annotations)
                      </span>
                    )}
                    {successBatch.enable_stage3 && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-indigo-100 text-indigo-800 border border-indigo-200">
                        Stage 3 (Stego)
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Layer 3 Plain-Language Explanation Note */}
              <div className="pt-2 border-t border-slate-100 flex items-start gap-2 text-[11px] text-slate-600">
                <Info className="w-3.5 h-3.5 text-sky-600 shrink-0 mt-0.5" />
                <span className="leading-normal">{stegoExplanation.description}</span>
              </div>
            </div>

            {/* Compact Batch Summary Cards (Apple Liquid Glass) */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              {/* Stat 1: Total Enrolled */}
              <div className="p-2.5 rounded-2xl bg-white/70 border border-white/90 shadow-xs flex flex-col justify-between">
                <span className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Total</span>
                <div className="mt-1 flex items-baseline gap-1">
                  <span className="text-lg font-bold text-slate-900">{summaryMetrics.totalEnrolled}</span>
                  <span className="text-[10px] text-slate-500">recipients</span>
                </div>
              </div>

              {/* Stat 2: Generated */}
              <div className="p-2.5 rounded-2xl bg-white/70 border border-white/90 shadow-xs flex flex-col justify-between">
                <span className="text-[10px] uppercase font-bold tracking-wider text-emerald-600">Generated</span>
                <div className="mt-1 flex items-baseline gap-1">
                  <span className="text-lg font-bold text-emerald-700">{summaryMetrics.generatedCount}</span>
                  <span className="text-[10px] text-slate-400">({summaryMetrics.generationPercent}%)</span>
                </div>
              </div>

              {/* Stat 3: Active Links */}
              <div className="p-2.5 rounded-2xl bg-white/70 border border-white/90 shadow-xs flex flex-col justify-between">
                <span className="text-[10px] uppercase font-bold tracking-wider text-sky-600">Active Links</span>
                <div className="mt-1 flex items-baseline gap-1">
                  <span className="text-lg font-bold text-sky-700">{summaryMetrics.activeCount}</span>
                  <span className="text-[10px] text-slate-400">live</span>
                </div>
              </div>

              {/* Stat 4: Expired Links */}
              <div className="p-2.5 rounded-2xl bg-white/70 border border-white/90 shadow-xs flex flex-col justify-between">
                <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500">Expired</span>
                <div className="mt-1 flex items-baseline gap-1">
                  <span className="text-lg font-bold text-slate-700">{summaryMetrics.expiredCount}</span>
                  <span className="text-[10px] text-slate-400">timed out</span>
                </div>
              </div>

              {/* Stat 5: L3 Stego Coverage */}
              <div className="p-2.5 rounded-2xl bg-white/70 border border-white/90 shadow-xs flex flex-col justify-between col-span-2 sm:col-span-1">
                <span className="text-[10px] uppercase font-bold tracking-wider text-indigo-600">L3 Coverage</span>
                <div className="mt-1 flex items-baseline gap-1">
                  <span className="text-lg font-bold text-indigo-700">
                    {summaryMetrics.l3SuccessCount}/{summaryMetrics.totalEnrolled}
                  </span>
                  <span className="text-[10px] text-slate-400">({summaryMetrics.l3CoveragePercent}%)</span>
                </div>
              </div>
            </div>

            {/* Generation Progress Bar (during PROCESSING or partially completed) */}
            {(successBatch.status === "PROCESSING" ||
              successBatch.status === "COMPLETED" ||
              successBatch.status === "PARTIALLY_FAILED") && (
              <div className="p-3 rounded-2xl bg-white/60 border border-white/90 space-y-1.5 shadow-xs">
                <div className="flex justify-between text-xs text-slate-600 font-medium">
                  <span>Generation Progress</span>
                  <span>
                    {summaryMetrics.generatedCount} of {summaryMetrics.totalEnrolled} completed
                    {summaryMetrics.failedCount > 0 && ` (${summaryMetrics.failedCount} failed)`}
                  </span>
                </div>
                <div className="w-full h-2 rounded-full bg-slate-200/80 overflow-hidden">
                  <div
                    className={`h-full transition-all duration-300 ${
                      successBatch.status === "COMPLETED"
                        ? "bg-emerald-500"
                        : successBatch.status === "PARTIALLY_FAILED"
                        ? "bg-amber-500"
                        : "bg-sky-500"
                    }`}
                    style={{ width: `${summaryMetrics.generationPercent}%` }}
                  />
                </div>
              </div>
            )}

            {/* Generation Error Alert */}
            {generationError && (
              <div className="flex items-start gap-2 p-3 rounded-2xl bg-rose-50 border border-rose-200 text-rose-700 text-xs">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-rose-500" />
                <div className="flex-1 font-medium">{generationError}</div>
              </div>
            )}

            {/* Generated Recipients List Toolbar */}
            <div className="space-y-2 pt-1">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
                {/* Status Segmented Filters */}
                <div className="inline-flex p-0.5 rounded-xl bg-slate-200/60 border border-white/80 text-[10px] font-medium text-slate-600">
                  <button
                    type="button"
                    onClick={() => setResultsFilter("ALL")}
                    className={`px-2.5 py-1 rounded-lg transition ${
                      resultsFilter === "ALL" ? "bg-white text-slate-900 font-semibold shadow-xs" : "hover:text-slate-900"
                    }`}
                  >
                    All ({successBatch.recipients?.length || 0})
                  </button>
                  <button
                    type="button"
                    onClick={() => setResultsFilter("ACTIVE")}
                    className={`px-2.5 py-1 rounded-lg transition ${
                      resultsFilter === "ACTIVE" ? "bg-white text-emerald-800 font-semibold shadow-xs" : "hover:text-slate-900"
                    }`}
                  >
                    Active ({summaryMetrics.activeCount})
                  </button>
                  <button
                    type="button"
                    onClick={() => setResultsFilter("EXPIRED")}
                    className={`px-2.5 py-1 rounded-lg transition ${
                      resultsFilter === "EXPIRED" ? "bg-white text-slate-800 font-semibold shadow-xs" : "hover:text-slate-900"
                    }`}
                  >
                    Expired ({summaryMetrics.expiredCount})
                  </button>
                  {summaryMetrics.failedCount > 0 && (
                    <button
                      type="button"
                      onClick={() => setResultsFilter("FAILED")}
                      className={`px-2.5 py-1 rounded-lg transition ${
                        resultsFilter === "FAILED" ? "bg-white text-rose-700 font-semibold shadow-xs" : "hover:text-slate-900"
                      }`}
                    >
                      Failed ({summaryMetrics.failedCount})
                    </button>
                  )}
                </div>

                {/* Bulk Actions */}
                <div className="flex items-center gap-1.5 self-end sm:self-auto">
                  <button
                    type="button"
                    onClick={handleExportCsv}
                    title="Export personalized distribution report as CSV"
                    className="py-1 px-2.5 rounded-xl bg-white hover:bg-slate-50 border border-slate-200/90 text-slate-700 text-[11px] font-medium flex items-center gap-1 transition shadow-xs cursor-pointer"
                  >
                    <Download className="w-3 h-3 text-sky-600" />
                    <span>Export CSV</span>
                  </button>

                  <button
                    type="button"
                    onClick={handleCopyAllActive}
                    title="Copy all active download links to clipboard"
                    className="py-1 px-2.5 rounded-xl bg-sky-50 hover:bg-sky-100 border border-sky-200/90 text-sky-700 text-[11px] font-medium flex items-center gap-1 transition shadow-xs cursor-pointer"
                  >
                    {copiedAllFeedback ? (
                      <>
                        <Check className="w-3 h-3 text-emerald-600" />
                        <span className="text-emerald-700 font-semibold">Copied!</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3 h-3 text-sky-600" />
                        <span>Copy Active Links</span>
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Recipient Search Filter */}
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                <input
                  type="text"
                  placeholder="Filter recipients by name or identifier..."
                  value={resultsSearch}
                  onChange={(e) => setResultsSearch(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 rounded-xl border border-slate-200/90 bg-white/80 text-xs placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-sky-500 shadow-xs"
                />
              </div>

              {/* Generated Recipients List (macOS Tahoe Clean Styling) */}
              <div className="max-h-60 overflow-y-auto rounded-2xl border border-slate-200/80 bg-white/70 divide-y divide-slate-100 shadow-xs">
                {filteredResults.length === 0 ? (
                  <div className="p-6 text-center text-xs text-slate-400">
                    No recipients match the active search or filter.
                  </div>
                ) : (
                  filteredResults.map((r, idx) => {
                    const remaining = getRemainingSeconds(r.expires_at);
                    const isExpired = r.status === "EXPIRED" || (r.expires_at ? remaining <= 0 : false);
                    const canDownload = r.status === "GENERATED" && !isExpired && !!r.download_url;

                    return (
                      <div
                        key={idx}
                        className="px-3.5 py-2.5 flex items-center justify-between text-xs gap-2 hover:bg-white/90 transition"
                      >
                        {/* Recipient Identity & Dynamic Expiry Countdown */}
                        <div className="flex flex-col min-w-0 pr-2">
                          <div className="flex items-center gap-1.5 truncate">
                            <span className="font-semibold text-slate-800 truncate">{r.recipient_name}</span>
                            <span className="font-mono text-[10px] text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200/60">
                              {r.recipient_identifier}
                            </span>
                          </div>

                          {r.status === "GENERATED" && r.expires_at && (
                            <div className="flex items-center gap-1 text-[10px] mt-0.5">
                              <Clock
                                className={`w-3 h-3 shrink-0 ${
                                  isExpired
                                    ? "text-slate-400"
                                    : remaining <= 60
                                    ? "text-rose-600 animate-pulse"
                                    : remaining <= 300
                                    ? "text-amber-600"
                                    : "text-sky-600"
                                }`}
                              />
                              {isExpired ? (
                                <span className="text-slate-400 font-medium">Link expired</span>
                              ) : (
                                <span
                                  className={`font-mono ${
                                    remaining <= 60
                                      ? "text-rose-600 font-bold animate-pulse"
                                      : remaining <= 300
                                      ? "text-amber-700 font-semibold"
                                      : "text-slate-600"
                                  }`}
                                >
                                  Expires in <strong>{formatCountdown(remaining)}</strong>
                                </span>
                              )}
                            </div>
                          )}
                        </div>

                        {/* Status Badges & Action Buttons */}
                        <div className="flex items-center gap-2 shrink-0">
                          {/* Layer 3 Stego Status Pill */}
                          {r.stego_status && (
                            <span
                              data-testid={`recipient-stego-${r.recipient_identifier}`}
                              title={getStegoStatusExplanation(r.stego_status, successBatch.enable_stage3).description}
                              className={`text-[9.5px] font-mono px-1.5 py-0.5 rounded-md font-medium cursor-help ${
                                r.stego_status === "SUCCESS"
                                  ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                  : r.stego_status === "FAILED"
                                  ? "bg-rose-50 text-rose-700 border border-rose-200"
                                  : r.stego_status === "PENDING"
                                  ? "bg-sky-50 text-sky-700 border border-sky-200"
                                  : "bg-slate-50 text-slate-500 border border-slate-200"
                              }`}
                            >
                              L3: {r.stego_status}
                            </span>
                          )}

                          {/* Overall Status Badge */}
                          <span
                            className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                              isExpired || r.status === "EXPIRED"
                                ? "bg-slate-100 text-slate-500 border border-slate-200"
                                : r.status === "GENERATED"
                                ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
                                : r.status === "FAILED"
                                ? "bg-rose-100 text-rose-700 border border-rose-200"
                                : successBatch.status === "PROCESSING"
                                ? "bg-sky-100 text-sky-700 animate-pulse border border-sky-200"
                                : "bg-slate-100 text-slate-600"
                            }`}
                          >
                            {isExpired ? "Expired" : r.status}
                          </span>

                          {/* Action Controls */}
                          <div className="flex items-center gap-1">
                            {/* Download Action */}
                            {canDownload ? (
                              <a
                                href={r.download_url!}
                                download
                                title="Download personalized PDF"
                                className="p-1.5 rounded-lg bg-sky-50 text-sky-700 hover:bg-sky-100 border border-sky-200/80 transition cursor-pointer flex items-center gap-1 text-[11px] font-medium"
                              >
                                <Download className="w-3.5 h-3.5" />
                                <span className="hidden sm:inline">Download</span>
                              </a>
                            ) : (
                              <button
                                disabled
                                title={isExpired ? "Link expired" : "PDF not yet generated"}
                                className="p-1.5 rounded-lg bg-slate-50 text-slate-300 border border-slate-200/50 cursor-not-allowed flex items-center gap-1 text-[11px]"
                              >
                                <Download className="w-3.5 h-3.5" />
                                <span className="hidden sm:inline">Download</span>
                              </button>
                            )}

                            {/* Copy Link Action */}
                            {canDownload ? (
                              <button
                                type="button"
                                onClick={() => handleCopyLink(r.recipient_identifier, r.download_url!)}
                                title="Copy temporary download link"
                                className="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/80 text-slate-700 border border-slate-200 transition cursor-pointer flex items-center gap-1 text-[11px] font-medium"
                              >
                                {copiedIdentifier === r.recipient_identifier ? (
                                  <>
                                    <Check className="w-3.5 h-3.5 text-emerald-600" />
                                    <span className="text-emerald-700 font-semibold text-[10px]">Copied!</span>
                                  </>
                                ) : (
                                  <>
                                    <Copy className="w-3.5 h-3.5 text-slate-600" />
                                    <span className="hidden sm:inline">Copy Link</span>
                                  </>
                                )}
                              </button>
                            ) : (
                              <button
                                disabled
                                title={isExpired ? "Link expired" : "PDF not yet generated"}
                                className="p-1.5 rounded-lg bg-slate-50 text-slate-300 border border-slate-200/50 cursor-not-allowed flex items-center gap-1 text-[11px]"
                              >
                                <Copy className="w-3.5 h-3.5" />
                                <span className="hidden sm:inline">Copy Link</span>
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {/* Bottom Modal Actions */}
            <div className="flex gap-2 justify-end pt-3 border-t border-slate-200/60 shrink-0">
              {successBatch.status === "PENDING" && (
                <>
                  <button
                    onClick={onClose}
                    className="py-2 px-3.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-medium text-xs transition cursor-pointer"
                  >
                    Close
                  </button>
                  <button
                    onClick={handleStartGeneration}
                    disabled={isGenerating}
                    className="py-2 px-4 rounded-xl bg-sky-600 hover:bg-sky-500 text-white font-medium text-xs transition shadow-md flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>Generate Personalized PDFs</span>
                  </button>
                </>
              )}

              {successBatch.status === "PROCESSING" && (
                <button
                  disabled
                  className="py-2 px-4 rounded-xl bg-slate-900 text-white font-medium text-xs transition flex items-center gap-2 opacity-80 cursor-wait"
                >
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Generating ({summaryMetrics.generatedCount}/{summaryMetrics.totalEnrolled})...</span>
                </button>
              )}

              {successBatch.status === "PARTIALLY_FAILED" && (
                <>
                  <button
                    onClick={onClose}
                    className="py-2 px-3.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-medium text-xs transition cursor-pointer"
                  >
                    Close
                  </button>
                  <button
                    onClick={handleStartGeneration}
                    disabled={isGenerating}
                    className="py-2 px-4 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-medium text-xs transition shadow-md flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span>Retry Failed Recipients</span>
                  </button>
                </>
              )}

              {successBatch.status === "FAILED" && (
                <>
                  <button
                    onClick={onClose}
                    className="py-2 px-3.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-medium text-xs transition cursor-pointer"
                  >
                    Close
                  </button>
                  <button
                    onClick={handleStartGeneration}
                    disabled={isGenerating}
                    className="py-2 px-4 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-medium text-xs transition shadow-md flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span>Retry Generation</span>
                  </button>
                </>
              )}

              {successBatch.status === "COMPLETED" && (
                <>
                  <button
                    onClick={handleReset}
                    className="py-2 px-3.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-medium text-xs transition cursor-pointer"
                  >
                    Create Another Batch
                  </button>
                  <button
                    onClick={onClose}
                    className="py-2 px-4 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-medium text-xs transition shadow-md cursor-pointer"
                  >
                    Done
                  </button>
                </>
              )}
            </div>
          </div>
        ) : (
          /* -------------------- Configuration & Entry State -------------------- */
          <div className="space-y-4 overflow-y-auto pr-1 flex-1">
            {/* API Error Alert */}
            {apiError && (
              <div className="flex items-start gap-2 p-3 rounded-2xl bg-rose-50 border border-rose-200 text-rose-700 text-xs">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-rose-500" />
                <div className="flex-1 font-medium">{apiError}</div>
              </div>
            )}

            {/* Section 1: Uploader-Configurable Expiry Duration */}
            <div className="space-y-1.5 p-3.5 rounded-2xl bg-white/70 border border-slate-200/80 backdrop-blur-xl shadow-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
                  <Clock className="w-3.5 h-3.5 text-sky-600" />
                  <span>Download-Link Validity Duration</span>
                </div>
                <div
                  className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-slate-600 cursor-help"
                  title="Validity period activates individually as each personalized document completes generation."
                >
                  <HelpCircle className="w-3 h-3" />
                  <span>Generation-based</span>
                </div>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 pt-1">
                {EXPIRY_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setSelectedDuration(opt.value)}
                    className={`py-1.5 px-2.5 rounded-xl text-[11px] font-medium border transition text-left cursor-pointer ${
                      selectedDuration === opt.value
                        ? "bg-sky-500 text-white border-sky-500 shadow-xs"
                        : "bg-white/80 border-slate-200 text-slate-700 hover:bg-white"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>

              {/* Custom Seconds Input */}
              {selectedDuration === -1 && (
                <div className="pt-2 flex items-center gap-2">
                  <label className="text-[11px] text-slate-600 font-medium">Custom duration (seconds):</label>
                  <input
                    type="number"
                    min="30"
                    max="2592000"
                    value={customSeconds}
                    onChange={(e) => setCustomSeconds(e.target.value)}
                    className="w-28 px-2.5 py-1 text-xs rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-1 focus:ring-sky-500"
                  />
                  <span className="text-[10px] text-slate-400">(30s - 30 days)</span>
                </div>
              )}

              <p className="text-[10px] text-slate-500 italic pt-1">
                Note: Each recipient's link receives its full selected validity period, counted from the moment that PDF completes generation.
              </p>
            </div>

            {/* Section 2: Security Carrier Stages (Liquid Glass Selectors) */}
            <div className="space-y-2.5 p-3.5 rounded-2xl bg-white/70 border border-slate-200/80 backdrop-blur-xl shadow-xs">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-xs font-bold text-slate-900 tracking-tight">Security Carrier Stages</h3>
                  <p className="text-[11px] text-slate-500">
                    Select one or more cryptographic attribution carriers to embed into each generated PDF.
                  </p>
                </div>
                <span
                  data-testid="selected-stages-badge"
                  className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border transition-colors ${
                    enableStage1 || enableStage2 || enableStage3
                      ? "bg-sky-50 text-sky-700 border-sky-200"
                      : "bg-rose-50 text-rose-700 border-rose-200 animate-pulse"
                  }`}
                >
                  {[enableStage1, enableStage2, enableStage3].filter(Boolean).length} of 3 active
                </span>
              </div>

              {/* 3 Liquid Glass Toggle Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                {/* Stage 1 */}
                <label
                  data-testid="stage1-toggle-card"
                  className={`p-2.5 rounded-xl border transition-all cursor-pointer flex flex-col justify-between ${
                    enableStage1
                      ? "bg-sky-50/80 border-sky-300 shadow-xs ring-1 ring-sky-400/20"
                      : "bg-white/60 border-slate-200 hover:border-slate-300 opacity-75"
                  }`}
                >
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-slate-900">Stage 1</span>
                      <input
                        type="checkbox"
                        data-testid="stage1-checkbox"
                        checked={enableStage1}
                        onChange={(e) => setEnableStage1(e.target.checked)}
                        className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500 cursor-pointer"
                      />
                    </div>
                    <div className="text-[11px] font-semibold text-slate-700">Catalog Carrier</div>
                    <p className="text-[10px] text-slate-500 leading-tight">
                      Document-level PDF catalog dictionary watermark. Primary baseline carrier.
                    </p>
                  </div>
                  <div className="pt-2 flex items-center gap-1 text-[10px] text-slate-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                    <span>HMAC-SHA256</span>
                  </div>
                </label>

                {/* Stage 2 */}
                <label
                  data-testid="stage2-toggle-card"
                  className={`p-2.5 rounded-xl border transition-all cursor-pointer flex flex-col justify-between ${
                    enableStage2
                      ? "bg-sky-50/80 border-sky-300 shadow-xs ring-1 ring-sky-400/20"
                      : "bg-white/60 border-slate-200 hover:border-slate-300 opacity-75"
                  }`}
                >
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-slate-900">Stage 2</span>
                      <input
                        type="checkbox"
                        data-testid="stage2-checkbox"
                        checked={enableStage2}
                        onChange={(e) => setEnableStage2(e.target.checked)}
                        className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500 cursor-pointer"
                      />
                    </div>
                    <div className="text-[11px] font-semibold text-slate-700">Annotations</div>
                    <p className="text-[10px] text-slate-500 leading-tight">
                      Page-level redundant visual and metadata annotation carriers across pages.
                    </p>
                  </div>
                  <div className="pt-2 flex items-center gap-1 text-[10px] text-slate-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                    <span>Multi-Page Redundant</span>
                  </div>
                </label>

                {/* Stage 3 */}
                <label
                  data-testid="stage3-toggle-card"
                  className={`p-2.5 rounded-xl border transition-all cursor-pointer flex flex-col justify-between ${
                    enableStage3
                      ? "bg-sky-50/80 border-sky-300 shadow-xs ring-1 ring-sky-400/20"
                      : "bg-white/60 border-slate-200 hover:border-slate-300 opacity-75"
                  }`}
                >
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-slate-900">Stage 3</span>
                      <input
                        type="checkbox"
                        data-testid="stage3-checkbox"
                        checked={enableStage3}
                        onChange={(e) => setEnableStage3(e.target.checked)}
                        className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500 cursor-pointer"
                      />
                    </div>
                    <div className="text-[11px] font-semibold text-slate-700">Steganography</div>
                    <p className="text-[10px] text-slate-500 leading-tight">
                      Typesetting-level word gap kerning shift carrier. Imperceptible in text.
                    </p>
                  </div>
                  <div className="pt-2 flex items-center gap-1 text-[10px] text-slate-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-500"></span>
                    <span>Passive Kerning</span>
                  </div>
                </label>
              </div>

              {/* Inline Validation Warning when all 3 stages are disabled */}
              {!enableStage1 && !enableStage2 && !enableStage3 && (
                <div
                  data-testid="stages-validation-warning"
                  className="p-2.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-center gap-2 animate-in fade-in"
                >
                  <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />
                  <span className="font-medium">
                    At least one security stage must be selected to proceed with distribution.
                  </span>
                </div>
              )}
            </div>

            {/* Section 3: Dual-Mode Recipient Enrolment (Apple Liquid Glass) */}
            <div className="space-y-3 p-3.5 rounded-2xl bg-white/70 border border-slate-200/80 backdrop-blur-xl shadow-xs">
              {/* Header with Segmented Control Pills */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-slate-900">Enrol Recipients</span>
                  {/* Capacity Badge */}
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-sky-50 text-sky-700 border border-sky-200">
                    {recipients.length} / 1,000 queued
                  </span>
                </div>

                {/* macOS Tahoe-style Segmented Switch */}
                <div className="inline-flex p-0.5 rounded-xl bg-slate-200/60 border border-white/80 text-[11px] font-medium text-slate-600">
                  <button
                    type="button"
                    onClick={() => setInputMode("manual")}
                    className={`px-3 py-1 rounded-lg transition flex items-center gap-1.5 ${
                      inputMode === "manual"
                        ? "bg-white text-slate-900 font-semibold shadow-xs"
                        : "hover:text-slate-900"
                    }`}
                  >
                    <Plus className="w-3 h-3 text-sky-600" />
                    <span>Manual Entry</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setInputMode("import")}
                    className={`px-3 py-1 rounded-lg transition flex items-center gap-1.5 ${
                      inputMode === "import"
                        ? "bg-white text-slate-900 font-semibold shadow-xs"
                        : "hover:text-slate-900"
                    }`}
                  >
                    <FileSpreadsheet className="w-3 h-3 text-sky-600" />
                    <span>Import CSV / TSV</span>
                  </button>
                </div>
              </div>

              {/* Mode A: Manual Form */}
              {inputMode === "manual" ? (
                <div className="space-y-2">
                  {inputError && (
                    <div className="p-2 rounded-xl bg-amber-50 border border-amber-200 text-amber-800 text-[11px] flex items-center gap-1.5">
                      <AlertCircle className="w-3.5 h-3.5 shrink-0 text-amber-600" />
                      <span>{inputError}</span>
                    </div>
                  )}

                  <form onSubmit={handleAddRecipient} className="grid grid-cols-1 sm:grid-cols-5 gap-2 pt-0.5">
                    <div className="sm:col-span-2">
                      <input
                        type="text"
                        placeholder="Recipient Full Name"
                        value={recipientName}
                        onChange={(e) => setRecipientName(e.target.value)}
                        className="w-full px-3 py-1.5 rounded-xl border border-slate-200 bg-white text-xs placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-sky-500 shadow-xs"
                      />
                    </div>
                    <div className="sm:col-span-2">
                      <input
                        type="text"
                        placeholder="Identifier (e.g. Student UID)"
                        value={recipientUid}
                        onChange={(e) => setRecipientUid(e.target.value)}
                        className="w-full px-3 py-1.5 rounded-xl border border-slate-200 bg-white text-xs placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-sky-500 shadow-xs"
                      />
                    </div>
                    <div className="sm:col-span-1">
                      <button
                        type="submit"
                        disabled={recipients.length >= 1000}
                        className="w-full py-1.5 px-3 rounded-xl bg-sky-500 hover:bg-sky-600 text-white font-medium text-xs transition flex items-center justify-center gap-1 shadow-xs cursor-pointer disabled:opacity-50"
                      >
                        <Plus className="w-3.5 h-3.5" />
                        <span>Add</span>
                      </button>
                    </div>
                  </form>
                </div>
              ) : (
                /* Mode B: CSV / TSV Import Zone */
                <div className="space-y-3">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {/* File Dropzone */}
                    <div
                      onClick={() => fileInputRef.current?.click()}
                      className="p-3.5 rounded-xl border-2 border-dashed border-sky-300 hover:border-sky-400 bg-sky-50/40 hover:bg-sky-50/70 transition flex flex-col items-center justify-center text-center cursor-pointer group"
                    >
                      <Upload className="w-5 h-5 text-sky-600 mb-1 group-hover:scale-110 transition-transform" />
                      <span className="text-xs font-semibold text-slate-800">Upload CSV or TSV File</span>
                      <span className="text-[10px] text-slate-500 mt-0.5">Click or drag .csv, .tsv, .txt</span>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain"
                        onChange={handleFileUpload}
                        className="hidden"
                      />
                    </div>

                    {/* Direct Paste Area */}
                    <div className="flex flex-col">
                      <textarea
                        rows={3}
                        placeholder="Or paste tabular data here...&#10;Alice Smith, STU-101&#10;Bob Jones, STU-102"
                        value={importText}
                        onChange={(e) => setImportText(e.target.value)}
                        className="w-full p-2.5 rounded-xl border border-slate-200 bg-white text-xs placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-sky-500 font-mono text-[11px] resize-none shadow-xs"
                      />
                    </div>
                  </div>

                  {/* Parse Preview & De-duplication Drawer */}
                  {importParseResult && (
                    <div className="space-y-2 p-3 rounded-xl bg-slate-50 border border-slate-200 text-xs animate-in fade-in">
                      {/* Summary Metrics Strip */}
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-semibold text-slate-800 text-[11px] mr-1">Preview:</span>
                          <button
                            type="button"
                            onClick={() => setImportFilter("ALL")}
                            className={`px-2 py-0.5 rounded-md font-semibold text-[10px] transition cursor-pointer ${
                              importFilter === "ALL"
                                ? "bg-slate-800 text-white shadow-xs"
                                : "bg-slate-200/70 text-slate-700 hover:bg-slate-200"
                            }`}
                          >
                            All ({importParseResult.totalCount})
                          </button>
                          <button
                            type="button"
                            onClick={() => setImportFilter("VALID")}
                            className={`px-2 py-0.5 rounded-md font-semibold text-[10px] transition cursor-pointer ${
                              importFilter === "VALID"
                                ? "bg-emerald-600 text-white shadow-xs"
                                : "bg-emerald-100 text-emerald-800 hover:bg-emerald-200"
                            }`}
                          >
                            {importParseResult.validCount} Valid
                          </button>
                          {importParseResult.duplicateCount > 0 && (
                            <button
                              type="button"
                              onClick={() => setImportFilter("DUPLICATES")}
                              className={`px-2 py-0.5 rounded-md font-semibold text-[10px] transition cursor-pointer ${
                                importFilter === "DUPLICATES"
                                  ? "bg-amber-600 text-white shadow-xs"
                                  : "bg-amber-100 text-amber-800 hover:bg-amber-200"
                              }`}
                            >
                              {importParseResult.duplicateCount} Duplicates
                            </button>
                          )}
                          {importParseResult.invalidCount > 0 && (
                            <button
                              type="button"
                              onClick={() => setImportFilter("INVALID")}
                              className={`px-2 py-0.5 rounded-md font-semibold text-[10px] transition cursor-pointer ${
                                importFilter === "INVALID"
                                  ? "bg-rose-600 text-white shadow-xs"
                                  : "bg-rose-100 text-rose-800 hover:bg-rose-200"
                              }`}
                            >
                              {importParseResult.invalidCount} Invalid
                            </button>
                          )}
                        </div>

                        {/* Import Commit Action */}
                        <button
                          type="button"
                          onClick={handleCommitImport}
                          disabled={importParseResult.validCount === 0}
                          className="py-1 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs transition shadow-xs flex items-center gap-1 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <Check className="w-3.5 h-3.5" />
                          <span>Import {importParseResult.validCount} Valid Recipients</span>
                        </button>
                      </div>

                      {/* Header Detection Indicator */}
                      <div className="flex items-center justify-between text-[10px] text-slate-500">
                        <span>
                          Delimiter: <strong className="font-mono text-slate-700">{importParseResult.detectedDelimiter === "\t" ? "Tab (TSV)" : "Comma (CSV)"}</strong>
                        </span>
                        <span>{importParseResult.hasHeaders ? "Headers detected (Name & UID)" : "No headers detected (Column 1=Name, Column 2=UID)"}</span>
                      </div>

                      {/* Preview Table (Scrollable) */}
                      <div className="max-h-32 overflow-y-auto rounded-lg border border-slate-200 bg-white divide-y divide-slate-100 text-[11px]">
                        {previewRows.slice(0, 50).map((row, idx) => (
                          <div key={idx} className="px-2.5 py-1.5 flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 truncate">
                              <span className="font-mono text-[9px] text-slate-400 w-5">#{row.originalRowNumber}</span>
                              <span className="font-medium text-slate-800 truncate">{row.name || "<empty name>"}</span>
                              <span className="font-mono text-[10px] text-slate-500 bg-slate-100 px-1 rounded">
                                {row.student_uid || "<empty uid>"}
                              </span>
                            </div>
                            <div>
                              {row.status === "VALID" ? (
                                <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                                  Valid
                                </span>
                              ) : row.status === "DUPLICATE_INTERNAL" ? (
                                <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-amber-50 text-amber-700 border border-amber-200" title={row.errorMessage}>
                                  Duplicate (File)
                                </span>
                              ) : row.status === "DUPLICATE_QUEUE" ? (
                                <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-amber-50 text-amber-700 border border-amber-200" title={row.errorMessage}>
                                  Duplicate (Queue)
                                </span>
                              ) : (
                                <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-rose-50 text-rose-700 border border-rose-200" title={row.errorMessage}>
                                  {row.status === "TOO_LONG" ? ">255 chars" : "Invalid"}
                                </span>
                              )}
                            </div>
                          </div>
                        ))}
                        {previewRows.length > 50 && (
                          <div className="p-1.5 text-center text-[10px] text-slate-400 italic">
                            ... and {previewRows.length - 50} more rows
                          </div>
                        )}
                        {previewRows.length === 0 && (
                          <div className="p-3 text-center text-[11px] text-slate-400 italic">
                            No rows match the selected filter ({importFilter}).
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Recipient Queue Management & Search Filter */}
              {recipients.length > 0 && (
                <div className="space-y-1.5 pt-2 border-t border-slate-100">
                  <div className="flex items-center justify-between gap-2">
                    {/* Search inside queue */}
                    <div className="relative flex-1">
                      <Search className="w-3 h-3 absolute left-2.5 top-2 text-slate-400" />
                      <input
                        type="text"
                        placeholder="Search queued recipients..."
                        value={queueSearch}
                        onChange={(e) => setQueueSearch(e.target.value)}
                        className="w-full pl-7 pr-3 py-1 rounded-lg border border-slate-200 bg-white text-[11px] placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-sky-500"
                      />
                    </div>

                    {/* Clear All Confirmation Button */}
                    {showClearConfirm ? (
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={handleClearQueue}
                          className="px-2 py-1 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-medium text-[10px] transition cursor-pointer"
                        >
                          Confirm Clear
                        </button>
                        <button
                          type="button"
                          onClick={() => setShowClearConfirm(false)}
                          className="px-2 py-1 rounded-lg bg-slate-200 hover:bg-slate-300 text-slate-700 font-medium text-[10px] transition cursor-pointer"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setShowClearConfirm(true)}
                        className="px-2.5 py-1 rounded-lg text-slate-500 hover:text-rose-600 hover:bg-rose-50 text-[11px] font-medium transition cursor-pointer flex items-center gap-1"
                      >
                        <Trash2 className="w-3 h-3" />
                        <span>Clear Queue ({recipients.length})</span>
                      </button>
                    )}
                  </div>

                  {/* Queued Recipients Table */}
                  <div className="max-h-36 overflow-y-auto border border-slate-200/80 rounded-xl bg-white/80 divide-y divide-slate-100 shadow-xs">
                    {filteredQueue.length === 0 ? (
                      <div className="p-3 text-center text-xs text-slate-400">
                        {queueSearch ? "No queued recipients match search." : "No recipients queued."}
                      </div>
                    ) : (
                      filteredQueue.map((r, idx) => (
                        <div
                          key={idx}
                          className="px-3 py-1.5 flex items-center justify-between text-xs hover:bg-slate-50 transition"
                        >
                          <div className="flex items-center gap-3 truncate">
                            <span className="font-semibold text-slate-800 truncate">{r.name}</span>
                            <span className="font-mono text-[11px] text-slate-500 px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200">
                              {r.student_uid}
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={() => handleRemoveRecipient(idx)}
                            className="text-slate-400 hover:text-rose-500 p-1 transition cursor-pointer"
                            title="Remove recipient"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Modal Bottom Actions */}
            <div className="flex items-center justify-between pt-2 border-t border-slate-200/60 shrink-0">
              <span className="text-[11px] text-slate-400">
                Selected validity: <span className="font-semibold text-slate-700">{effectiveDuration}s</span>
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={isLoading}
                  className="py-2 px-3.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-medium text-xs transition cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  data-testid="create-batch-button"
                  onClick={handleSubmitBatch}
                  disabled={isLoading || recipients.length === 0 || (!enableStage1 && !enableStage2 && !enableStage3)}
                  className="py-2 px-4 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-medium text-xs transition shadow-md flex items-center gap-1.5 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Creating Batch...</span>
                    </>
                  ) : (
                    <>
                      <Send className="w-3.5 h-3.5" />
                      <span>Create Batch ({recipients.length})</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
