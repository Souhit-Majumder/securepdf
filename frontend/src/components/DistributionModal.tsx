import React, { useState, useEffect } from "react";
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
} from "lucide-react";

interface RecipientInput {
  name: string;
  student_uid: string;
}

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

  // Recipient input state
  const [recipientName, setRecipientName] = useState("");
  const [recipientUid, setRecipientUid] = useState("");
  const [recipients, setRecipients] = useState<RecipientInput[]>([]);

  // Form & submission state
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [successBatch, setSuccessBatch] = useState<{
    batch_uid: string;
    total_recipients: number;
    expiry_duration_seconds: number;
    status: string;
    recipients?: Array<{
      recipient_name: string;
      recipient_identifier: string;
      status: string;
      generated_at?: string | null;
      expires_at?: string | null;
      download_url?: string | null;
      created_at: string;
    }>;
  } | null>(null);

  // Live timer for second-by-second expiry countdown
  const [nowMs, setNowMs] = useState<number>(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Feedback state for copied download link
  const [copiedIdentifier, setCopiedIdentifier] = useState<string | null>(null);

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

  if (!isOpen) return null;

  const effectiveDuration =
    selectedDuration === -1 ? parseInt(customSeconds, 10) || 120 : selectedDuration;

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

    // Check duplicate identifier within this batch queue
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

  const handleRemoveRecipient = (index: number) => {
    setRecipients(recipients.filter((_, idx) => idx !== index));
  };

  const handleSubmitBatch = async () => {
    setApiError(null);

    if (recipients.length === 0) {
      setApiError("Please add at least one recipient to the batch.");
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
        recipients: data.recipients,
      });
    } catch (err: any) {
      setApiError(err.message || "An unexpected error occurred during batch creation.");
    } finally {
      setIsLoading(false);
    }
  };

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
    setSelectedDuration(120);
    setCustomSeconds("300");
    setApiError(null);
    setInputError(null);
    setGenerationError(null);
    setIsGenerating(false);
  };

  // Recipient stats for progress display
  const completedCount = successBatch?.recipients?.filter((r) => r.status === "GENERATED").length || 0;
  const failedCount = successBatch?.recipients?.filter((r) => r.status === "FAILED").length || 0;
  const totalCount = successBatch?.total_recipients || 1;
  const progressPercent = Math.min(100, Math.round((completedCount / totalCount) * 100));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Daylight Frosted Backdrop */}
      <div
        className="absolute inset-0 bg-slate-900/25 backdrop-blur-md transition-opacity"
        onClick={!isLoading ? onClose : undefined}
      />

      {/* Modal Dialog Card */}
      <div className="relative w-full max-w-xl rounded-3xl glass-top-island p-6 border border-white/95 shadow-2xl space-y-5 animate-in fade-in zoom-in-95 duration-150 z-10 max-h-[90vh] flex flex-col">
        {/* Modal Header */}
        <div className="flex items-start justify-between border-b border-slate-200/60 pb-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-sky-500/15 border border-sky-400/35 flex items-center justify-center text-sky-600 shadow-xs">
              <Users className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-900 tracking-tight">Create Distribution Batch</h2>
              <div className="flex items-center gap-1.5 text-xs text-slate-500 truncate max-w-md">
                <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                <span className="font-medium text-slate-700 truncate">{documentTitle}</span>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isLoading}
            className="p-1.5 rounded-full hover:bg-slate-200/50 text-slate-400 hover:text-slate-700 transition cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Success Confirmation & Generation Workflow State */}
        {successBatch ? (
          <div className="space-y-4 overflow-y-auto pr-1 flex-1 animate-in fade-in">
            {/* Status Header */}
            <div className="py-2 text-center space-y-2">
              <div
                className={`w-12 h-12 mx-auto rounded-2xl flex items-center justify-center border transition-all ${
                  successBatch.status === "COMPLETED"
                    ? "bg-emerald-500/15 border-emerald-400/40 text-emerald-600"
                    : successBatch.status === "PROCESSING"
                    ? "bg-sky-500/15 border-sky-400/40 text-sky-600 animate-pulse"
                    : successBatch.status === "PARTIALLY_FAILED"
                    ? "bg-amber-500/15 border-amber-400/40 text-amber-600"
                    : successBatch.status === "FAILED"
                    ? "bg-rose-500/15 border-rose-400/40 text-rose-600"
                    : "bg-sky-500/15 border-sky-400/40 text-sky-600"
                }`}
              >
                {successBatch.status === "COMPLETED" && <CheckCircle2 className="w-6 h-6" />}
                {successBatch.status === "PROCESSING" && <Loader2 className="w-6 h-6 animate-spin" />}
                {successBatch.status === "PARTIALLY_FAILED" && <AlertTriangle className="w-6 h-6" />}
                {successBatch.status === "FAILED" && <AlertCircle className="w-6 h-6" />}
                {successBatch.status === "PENDING" && <Sparkles className="w-6 h-6" />}
              </div>

              <div>
                <h3 className="text-base font-semibold text-slate-900">
                  {successBatch.status === "COMPLETED" && "Personalized PDFs Generated"}
                  {successBatch.status === "PROCESSING" && "Generating Watermarked PDFs..."}
                  {successBatch.status === "PARTIALLY_FAILED" && "Generation Partially Completed"}
                  {successBatch.status === "FAILED" && "Generation Failed"}
                  {successBatch.status === "PENDING" && "Batch Created Successfully"}
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  {successBatch.status === "COMPLETED" &&
                    "All recipient watermarked PDFs have been generated and safely stored server-side."}
                  {successBatch.status === "PROCESSING" &&
                    `Generating watermarked PDF for recipient ${completedCount + 1} of ${totalCount}...`}
                  {successBatch.status === "PARTIALLY_FAILED" &&
                    `${completedCount} generated successfully, ${failedCount} failed. You can retry failed recipients.`}
                  {successBatch.status === "FAILED" &&
                    "Failed to complete personalized PDF watermarking. Please retry."}
                  {successBatch.status === "PENDING" &&
                    "Your batch is registered. Click below to begin personalized PDF generation."}
                </p>
              </div>
            </div>

            {/* Generation Error Alert */}
            {generationError && (
              <div className="flex items-start gap-2 p-3 rounded-2xl bg-rose-50 border border-rose-200 text-rose-700 text-xs">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-rose-500" />
                <div className="flex-1 font-medium">{generationError}</div>
              </div>
            )}

            {/* Batch Metadata Card */}
            <div className="p-3.5 rounded-2xl bg-white/70 border border-slate-200/80 text-xs space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Batch UID:</span>
                <span className="font-mono font-semibold text-slate-800">{successBatch.batch_uid}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Per-Recipient Validity:</span>
                <span className="font-semibold text-sky-700">{successBatch.expiry_duration_seconds}s</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Batch Status:</span>
                <span
                  className={`px-2 py-0.5 rounded-md font-semibold text-[11px] ${
                    successBatch.status === "COMPLETED"
                      ? "bg-emerald-100 text-emerald-800"
                      : successBatch.status === "PROCESSING"
                      ? "bg-sky-100 text-sky-800"
                      : successBatch.status === "PARTIALLY_FAILED"
                      ? "bg-amber-100 text-amber-800"
                      : successBatch.status === "FAILED"
                      ? "bg-rose-100 text-rose-800"
                      : "bg-slate-100 text-slate-700"
                  }`}
                >
                  {successBatch.status}
                </span>
              </div>

              {/* Progress Bar (during or after processing) */}
              {(successBatch.status === "PROCESSING" ||
                successBatch.status === "COMPLETED" ||
                successBatch.status === "PARTIALLY_FAILED") && (
                <div className="pt-2 space-y-1">
                  <div className="flex justify-between text-[11px] text-slate-600 font-medium">
                    <span>Generation Progress</span>
                    <span>
                      {completedCount} / {totalCount} completed
                      {failedCount > 0 && ` (${failedCount} failed)`}
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
                      style={{ width: `${progressPercent}%` }}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Recipient Status Breakdown */}
            {successBatch.recipients && successBatch.recipients.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[11px] font-semibold text-slate-700 flex justify-between">
                  <span>Recipients & Temporary Links</span>
                  <span className="text-slate-400 font-normal">{successBatch.recipients.length} total</span>
                </div>
                <div className="max-h-56 overflow-y-auto rounded-xl border border-slate-200/80 bg-white/70 divide-y divide-slate-100 shadow-xs">
                  {successBatch.recipients.map((r, idx) => {
                    const remaining = getRemainingSeconds(r.expires_at);
                    const isExpired = r.status === "EXPIRED" || (r.expires_at ? remaining <= 0 : false);
                    const canDownload = r.status === "GENERATED" && !isExpired && !!r.download_url;

                    return (
                      <div key={idx} className="px-3.5 py-2.5 flex items-center justify-between text-xs gap-2">
                        {/* Recipient Details & Countdown */}
                        <div className="flex flex-col min-w-0 pr-2">
                          <div className="flex items-center gap-1.5 truncate">
                            <span className="font-semibold text-slate-800 truncate">{r.recipient_name}</span>
                            <span className="font-mono text-[10px] text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200/60">
                              {r.recipient_identifier}
                            </span>
                          </div>
                          {r.status === "GENERATED" && r.expires_at && (
                            <div className="flex items-center gap-1 text-[10px] text-slate-500 mt-0.5">
                              <Clock className="w-3 h-3 text-sky-600 shrink-0" />
                              {isExpired ? (
                                <span className="text-rose-600 font-medium">Link expired</span>
                              ) : (
                                <span className="font-mono text-slate-600">
                                  Expires in <strong className="text-slate-800">{formatCountdown(remaining)}</strong>
                                </span>
                              )}
                            </div>
                          )}
                        </div>

                        {/* Status Badge & Action Buttons */}
                        <div className="flex items-center gap-2 shrink-0">
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
                  })}
                </div>
              </div>
            )}

            {/* Bottom Actions */}
            <div className="flex gap-2 justify-end pt-3 border-t border-slate-200/60">
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
                  <span>Generating ({completedCount}/{totalCount})...</span>
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
          /* Form Content Body (Scrollable) */
          <div className="space-y-4 overflow-y-auto pr-1 flex-1">
            {/* API Error Alert */}
            {apiError && (
              <div className="flex items-start gap-2 p-3 rounded-2xl bg-rose-50 border border-rose-200 text-rose-700 text-xs">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-rose-500" />
                <div className="flex-1 font-medium">{apiError}</div>
              </div>
            )}

            {/* Section 1: Uploader-Configurable Expiry Duration */}
            <div className="space-y-1.5 p-3 rounded-2xl bg-white/60 border border-white/90">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
                  <Clock className="w-3.5 h-3.5 text-sky-600" />
                  <span>Download-Link Validity Duration</span>
                </div>
                <div
                  className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-slate-600 cursor-help"
                  title="Expiry timing begins immediately when each personalized recipient PDF is generated in Phase 2."
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

            {/* Section 2: Recipient Ingestion Form */}
            <div className="space-y-2 p-3 rounded-2xl bg-white/60 border border-white/90">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-800">Add Recipients</span>
                <span className="text-[11px] font-medium text-slate-500">
                  {recipients.length} queued
                </span>
              </div>

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
                    className="w-full px-3 py-1.5 rounded-xl border border-slate-200 bg-white text-xs placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-sky-500"
                  />
                </div>
                <div className="sm:col-span-2">
                  <input
                    type="text"
                    placeholder="Identifier (e.g. Student UID)"
                    value={recipientUid}
                    onChange={(e) => setRecipientUid(e.target.value)}
                    className="w-full px-3 py-1.5 rounded-xl border border-slate-200 bg-white text-xs placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-sky-500"
                  />
                </div>
                <div className="sm:col-span-1">
                  <button
                    type="submit"
                    className="w-full py-1.5 px-3 rounded-xl bg-sky-500 hover:bg-sky-600 text-white font-medium text-xs transition flex items-center justify-center gap-1 shadow-xs cursor-pointer"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Add</span>
                  </button>
                </div>
              </form>

              {/* Recipient Queue Table */}
              {recipients.length > 0 && (
                <div className="mt-2 max-h-36 overflow-y-auto border border-slate-200/80 rounded-xl bg-white/80 divide-y divide-slate-100">
                  {recipients.map((r, idx) => (
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
                  ))}
                </div>
              )}
            </div>

            {/* Bottom Actions */}
            <div className="flex items-center justify-between pt-2 border-t border-slate-200/60">
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
                  onClick={handleSubmitBatch}
                  disabled={isLoading || recipients.length === 0}
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
