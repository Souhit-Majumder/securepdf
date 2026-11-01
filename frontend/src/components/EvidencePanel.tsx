import React, { useState } from "react";
import {
  Activity,
  Box,
  Layers,
  Type,
  Info,
  ShieldAlert,
  HelpCircle,
  Lock,
  ShieldCheck,
  Key,
  X,
  AlertCircle,
  UserCheck,
  Shield,
} from "lucide-react";
import {
  InspectionResponseDTO,
  CarrierStatusType,
  ActiveVerificationResponseDTO,
  VerificationStatusType,
} from "../types/inspection";

interface EvidencePanelProps {
  report: InspectionResponseDTO;
  activeLayer: number; // 0 = Catalog, 1 = Annotations, 2 = Stego Kerning
  onSelectLayer: (layerIndex: number) => void;
  isStandAlone?: boolean;
  verificationResult?: ActiveVerificationResponseDTO | null;
  isVerifying?: boolean;
  verificationError?: string | null;
  onVerify?: (auditKey: string) => void;
  onCancelVerify?: () => void;
  onClearVerify?: () => void;
  forensicKey?: string | null;
  onSetForensicKey?: (key: string) => void;
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({
  report,
  activeLayer,
  isStandAlone = false,
  verificationResult = null,
  isVerifying = false,
  verificationError = null,
  onVerify,
  onCancelVerify,
  onClearVerify,
  forensicKey = null,
  onSetForensicKey,
}) => {
  const [isPromptOpen, setIsPromptOpen] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const carrier = report.carriers[activeLayer] || report.carriers[0];
  const pageDim = report.page_dimensions[0] || null;

  const renderStatusBadge = (status: CarrierStatusType) => {
    switch (status) {
      case "VALID":
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-400/40 shadow-sm shadow-emerald-500/20 tracking-tight">
            <Lock className="w-2.5 h-2.5" />
            VALID
          </span>
        );
      case "STRUCTURALLY_DECODED":
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-400/40 shadow-sm shadow-emerald-500/20 tracking-tight">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            STRUCTURALLY_DECODED
          </span>
        );
      case "OBSERVED_SYNTAX":
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-400/40 shadow-sm shadow-amber-500/20 tracking-tight">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            OBSERVED_SYNTAX
          </span>
        );
      case "INVALID":
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-400/40 shadow-sm shadow-rose-500/20 tracking-tight">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
            INVALID
          </span>
        );
      case "SECURITY_CONFLICT":
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-0.5 rounded-full text-[10px] font-bold bg-purple-500/20 text-purple-300 border border-purple-400/40 shadow-sm shadow-purple-500/20 tracking-tight">
            <ShieldAlert className="w-2.5 h-2.5" />
            SECURITY_CONFLICT
          </span>
        );
      case "NOT_FOUND":
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-medium bg-white/5 text-slate-400 border border-white/10">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
            NOT_FOUND
          </span>
        );
    }
  };

  const renderVerificationStatusBadge = (status: VerificationStatusType) => {
    switch (status) {
      case "VALID":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[9.5px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-400/40 shadow-sm shadow-emerald-500/20 tracking-tight">
            <Lock className="w-2.5 h-2.5" />
            VALID
          </span>
        );
      case "INVALID":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[9.5px] font-bold bg-rose-500/20 text-rose-300 border border-rose-400/40 shadow-sm shadow-rose-500/20 tracking-tight">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
            INVALID
          </span>
        );
      case "SECURITY_CONFLICT":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[9.5px] font-bold bg-purple-500/20 text-purple-300 border border-purple-400/40 shadow-sm shadow-purple-500/20 tracking-tight">
            <ShieldAlert className="w-2.5 h-2.5" />
            SECURITY_CONFLICT
          </span>
        );
      case "NOT_FOUND":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[9.5px] font-medium bg-white/5 text-slate-400 border border-white/10">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
            NOT_FOUND
          </span>
        );
      case "ERROR":
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[9.5px] font-medium bg-amber-500/20 text-amber-300 border border-amber-400/40">
            <AlertCircle className="w-2.5 h-2.5" />
            ERROR
          </span>
        );
    }
  };

  const getLayerIcon = (index: number) => {
    switch (index) {
      case 0:
        return <Box className="w-4 h-4 text-sky-300" />;
      case 1:
        return <Layers className="w-4 h-4 text-cyan-300" />;
      case 2:
      default:
        return <Type className="w-4 h-4 text-indigo-300" />;
    }
  };

  const getLayerDescription = () => {
    if (!carrier) return "No evidence found for this layer.";
    switch (carrier.carrier_name) {
      case "Layer 1 (Catalog)":
        return carrier.status === "STRUCTURALLY_DECODED"
          ? "Document catalog dictionary contains an embedded metadata reference payload."
          : "No structural SPDFPayload key discovered in PDF catalog dictionary.";
      case "Layer 2 (Annotations)":
        return carrier.status === "STRUCTURALLY_DECODED"
          ? `Page 0 contains ${carrier.annotation_locations.length} invisible annotation carrier(s) with redundant compact payload.`
          : "No invisible SPDF annotation objects discovered on Page 0.";
      case "Layer 3 (Stego Kerning)":
        if (carrier.status === "STRUCTURALLY_DECODED") {
          return "Content streams contain a structurally framed steganographic bitstream with verified CRC-32 integrity.";
        } else if (carrier.status === "OBSERVED_SYNTAX") {
          return "Content streams contain standard typesetting inter-word kerning. No steganographic preamble frame detected.";
        } else if (carrier.status === "INVALID") {
          return "Steganographic preamble detected, but bitstream failed CRC-32 checksum validation.";
        }
        return "No text content streams or inter-word spacing gaps detected.";
    }
  };

  return (
    <div
      className={`glass-inspector rounded-3xl flex flex-col text-slate-100 transition-all duration-300 ${
        isStandAlone ? "w-full p-5" : "w-[300px] p-5 h-[calc(100vh-140px)] max-h-[720px] overflow-y-auto shadow-2xl"
      }`}
    >
      {/* Panel Header */}
      <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-white/10 text-sky-300 border border-white/15">
            <Activity className="w-3.5 h-3.5" />
          </div>
          <h2 className="text-[11px] font-bold tracking-wider text-white uppercase">
            Evidence Inspector
          </h2>
        </div>
        <div className="text-[9px] text-slate-400 font-mono font-bold px-2 py-0.5 rounded-md bg-white/5 border border-white/10">
          PHASE A
        </div>
      </div>

      {carrier ? (
        <div className="space-y-3.5">
          {/* Active Layer Header with Icon and Name */}
          <div className="flex items-center gap-2.5 pb-0.5">
            <div className="p-2 rounded-xl bg-white/10 border border-white/15 shadow-xs shrink-0">
              {getLayerIcon(activeLayer)}
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-xs font-bold text-white truncate">
                {carrier.carrier_name}
              </h3>
              <div className="text-[9px] text-slate-400 font-medium">
                Structural Evidence Detail
              </div>
            </div>
          </div>

          {/* Status Row */}
          <div className="flex items-center justify-between py-1.5 border-t border-white/10">
            <span className="text-slate-400 text-[10px] font-medium">Status</span>
            <div>{renderStatusBadge(carrier.status)}</div>
          </div>

          {/* Observations Section */}
          <div className="pt-2 border-t border-white/10">
            <span className="text-slate-400 text-[8.5px] uppercase tracking-wider block mb-1 font-bold">
              Observations
            </span>
            <p className="text-[10px] text-slate-300 leading-relaxed font-normal">
              {getLayerDescription()}
            </p>
          </div>

          {/* Technical Details Section */}
          <div className="pt-2 border-t border-white/10 space-y-1.5">
            <div className="text-[8.5px] font-bold text-slate-400 uppercase tracking-wider mb-0.5">
              Technical Details
            </div>

            {carrier.carrier_name === "Layer 1 (Catalog)" && (
              <>
                <div className="flex justify-between items-center py-0.5 text-[10px]">
                  <span className="text-slate-400">Object Type</span>
                  <span className="font-mono text-white font-semibold">Catalog Dict</span>
                </div>
                <div className="flex justify-between items-center py-0.5 text-[10px]">
                  <span className="text-slate-400">Payload Key</span>
                  <span className="font-mono text-white font-semibold">/SPDFPayload</span>
                </div>
                {carrier.catalog_location && (
                  <div className="flex justify-between items-center py-0.5 text-[10px]">
                    <span className="text-slate-400">Catalog xref</span>
                    <span className="font-mono text-white font-semibold">{carrier.catalog_location.catalog_xref}</span>
                  </div>
                )}
                {carrier.signature_ref && (
                  <div className="flex justify-between items-center py-0.5 text-[10px]">
                    <span className="text-slate-400">Signature Ref</span>
                    <span className="font-mono text-sky-300 font-bold">{carrier.signature_ref}</span>
                  </div>
                )}
              </>
            )}

            {carrier.carrier_name === "Layer 2 (Annotations)" && (
              <>
                <div className="flex justify-between items-center py-0.5 text-[10px]">
                  <span className="text-slate-400">Annotation Count</span>
                  <span className="font-mono text-white font-semibold">{carrier.annotation_locations.length}</span>
                </div>
                {carrier.annotation_locations.length > 0 && (
                  <div className="flex justify-between items-center py-0.5 text-[10px]">
                    <span className="text-slate-400">Flags</span>
                    <span className="font-mono text-white font-semibold">35 (Hidden, NoView)</span>
                  </div>
                )}
                {carrier.signature_ref && (
                  <div className="flex justify-between items-center py-0.5 text-[10px]">
                    <span className="text-slate-400">Signature Ref</span>
                    <span className="font-mono text-sky-300 font-bold">{carrier.signature_ref}</span>
                  </div>
                )}
              </>
            )}

            {carrier.carrier_name === "Layer 3 (Stego Kerning)" && (
              <>
                <div className="flex justify-between items-center py-0.5 text-[10px]">
                  <span className="text-slate-400">Total Word Gaps</span>
                  <span className="font-mono text-white font-semibold">{carrier.total_word_gaps ?? "0"}</span>
                </div>
                <div className="flex justify-between items-center py-0.5 text-[10px]">
                  <span className="text-slate-400">Modulated Gaps</span>
                  <span className="font-mono text-white font-semibold">{carrier.modulated_word_gaps ?? "0"}</span>
                </div>
                {carrier.bit_1_count !== null && (
                  <div className="flex justify-between items-center py-0.5 text-[10px]">
                    <span className="text-slate-400">Bit '1' / '0' Frequency</span>
                    <span className="font-mono text-white font-semibold">{carrier.bit_1_count} / {carrier.bit_0_count}</span>
                  </div>
                )}
                {carrier.signature_ref && (
                  <div className="flex justify-between items-center py-0.5 text-[10px]">
                    <span className="text-slate-400">Signature Ref</span>
                    <span className="font-mono text-sky-300 font-bold">{carrier.signature_ref}</span>
                  </div>
                )}
              </>
            )}
          </div>

          {pageDim && (
            <div className="pt-2 border-t border-white/10 space-y-1 text-[10px]">
              <div className="text-[8.5px] font-bold text-slate-400 uppercase tracking-wider mb-0.5">
                Page Geometry
              </div>
              <div className="flex justify-between items-center py-0.5">
                <span className="text-slate-400">Page</span>
                <span className="font-mono text-white font-semibold">{pageDim.page_index + 1}</span>
              </div>
              <div className="flex justify-between items-center py-0.5">
                <span className="text-slate-400">Rotation</span>
                <span className="font-mono text-white font-semibold">{pageDim.rotation}°</span>
              </div>
              <div className="flex justify-between items-center py-0.5">
                <span className="text-slate-400">CropBox</span>
                <span className="font-mono text-[9px] text-white font-semibold">
                  {pageDim.cropbox.map((v) => Math.round(v)).join(", ")}
                </span>
              </div>
            </div>
          )}

          {/* Cross-Layer Consistency */}
          <div className="pt-2 border-t border-white/10 space-y-1 text-[10px]">
            <div className="text-[8.5px] font-bold text-slate-400 uppercase tracking-wider mb-0.5">
              Cross-Layer Consistency
            </div>
            <div className="flex items-center justify-between py-0.5">
              <span className="text-slate-400">Carrier Tokens Match</span>
              <span className="font-semibold">
                {report.cross_layer.carrier_tokens_match === true ? (
                  <span className="text-emerald-400">Yes</span>
                ) : report.cross_layer.carrier_tokens_match === false ? (
                  <span className="text-rose-400">Mismatch</span>
                ) : (
                  <span className="text-slate-500">N/A</span>
                )}
              </span>
            </div>
          </div>

          {/* ----------------- Phase B: Cryptographic Verification ----------------- */}
          <div className="pt-3 border-t border-white/10 space-y-2.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <div className="p-1 rounded-md bg-sky-500/20 text-sky-300 border border-sky-400/30">
                  <ShieldCheck className="w-3 h-3" />
                </div>
                <span className="text-[9px] font-bold uppercase tracking-wider text-white">
                  Cryptographic Verification
                </span>
              </div>
              <span className="text-[8px] font-mono text-slate-400 bg-white/5 px-1.5 py-0.5 rounded border border-white/10 font-bold">
                PHASE B
              </span>
            </div>

            {/* State 1: In Progress / Running with Indeterminate Pulse */}
            {isVerifying ? (
              <div className="p-3 rounded-2xl bg-white/5 border border-white/10 space-y-2.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-3.5 h-3.5 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
                    <span className="text-[10px] font-medium text-slate-200">
                      Verifying carriers...
                    </span>
                  </div>
                  {onCancelVerify && (
                    <button
                      onClick={onCancelVerify}
                      className="flex items-center gap-1 px-2 py-0.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-400/30 text-[9px] transition"
                    >
                      <X className="w-2.5 h-2.5" />
                      Cancel
                    </button>
                  )}
                </div>
                <div className="h-1 w-full bg-white/10 rounded-full overflow-hidden">
                  <div className="h-full bg-sky-400 rounded-full animate-pulse w-3/4" />
                </div>
                <p className="text-[8.5px] text-slate-400 leading-tight">
                  Running cryptographic HMAC validation and database issuance binding checks.
                </p>
              </div>
            ) : verificationResult ? (
              /* State 2: Verification Result Available */
              <div className="p-3 rounded-2xl bg-white/5 border border-white/10 space-y-2 text-[10px]">
                <div className="flex items-center justify-between pb-1 border-b border-white/10">
                  <span className="text-slate-400 text-[9px]">Outcome</span>
                  <div>{renderVerificationStatusBadge(verificationResult.verification_status)}</div>
                </div>

                {verificationResult.reason && (
                  <div className="text-[9px] text-amber-300/90 leading-tight py-0.5">
                    {verificationResult.reason}
                  </div>
                )}

                {/* Authenticated Layers */}
                <div className="space-y-1 py-0.5">
                  <span className="text-[8.5px] uppercase tracking-wider text-slate-400 block font-bold">
                    Authenticated Carriers
                  </span>
                  {verificationResult.authenticated_layers.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {verificationResult.authenticated_layers.map((layerName) => (
                        <span
                          key={layerName}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 text-[9px] font-medium"
                        >
                          <Lock className="w-2.5 h-2.5" />
                          {layerName}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className="text-[9px] text-slate-400 italic">
                      No carriers authenticated under master key.
                    </span>
                  )}
                </div>

                {/* Pseudonymized Subject Reference */}
                {verificationResult.subject_ref && (
                  <div className="flex items-center justify-between py-1 border-t border-white/10">
                    <span className="text-slate-400 text-[9px]">Subject Reference</span>
                    <span className="font-mono text-[9px] text-sky-300 font-bold">
                      {verificationResult.subject_ref}
                    </span>
                  </div>
                )}

                {verificationResult.document_uid && (
                  <div className="flex items-center justify-between py-0.5">
                    <span className="text-slate-400 text-[9px]">Document UID</span>
                    <span className="font-mono text-[9px] text-white font-semibold truncate max-w-[150px]">
                      {verificationResult.document_uid}
                    </span>
                  </div>
                )}

                {/* Attributed Recipient (Phase 4) */}
                {verificationResult.recipient_name && verificationResult.recipient_identifier ? (
                  <div className="p-2.5 rounded-xl bg-sky-500/10 border border-sky-400/30 space-y-1 my-1">
                    <div className="flex items-center gap-1.5 text-sky-300 font-bold text-[9px] uppercase tracking-wider">
                      <UserCheck className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                      Attributed Recipient
                    </div>
                    <div className="flex items-baseline justify-between pt-0.5">
                      <span className="text-[11px] font-bold text-white truncate max-w-[140px]">
                        {verificationResult.recipient_name}
                      </span>
                      <span className="text-[9.5px] font-mono font-semibold text-sky-300 bg-sky-950/60 px-1.5 py-0.5 rounded border border-sky-400/20 shrink-0">
                        {verificationResult.recipient_identifier}
                      </span>
                    </div>
                  </div>
                ) : verificationResult.verification_status === "VALID" ? (
                  <div className="p-2 rounded-xl bg-white/5 border border-white/10 text-[9px] text-slate-400 italic my-1 flex items-center gap-1.5">
                    <Shield className="w-3 h-3 text-amber-400/80 shrink-0" />
                    <span>Forensic Audit Mode: Recipient identity redacted</span>
                  </div>
                ) : null}

                {/* Clear Button */}
                {onClearVerify && (
                  <button
                    onClick={onClearVerify}
                    className="w-full mt-1.5 py-1 rounded-xl bg-white/10 hover:bg-white/15 border border-white/15 text-[9.5px] text-slate-300 hover:text-white transition font-medium"
                  >
                    Clear Verification
                  </button>
                )}
              </div>
            ) : (
              /* State 3: Idle / Ready to Verify */
              <div className="space-y-2">
                {verificationError && (
                  <div className="p-2.5 rounded-xl bg-rose-500/15 border border-rose-400/30 text-[9.5px] text-rose-300 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold">
                      <ShieldAlert className="w-3 h-3 text-rose-400 shrink-0" />
                      <span>Verification Failed</span>
                    </div>
                    <p className="text-[8.5px] text-rose-200/90 leading-tight">
                      {verificationError}
                    </p>
                  </div>
                )}

                <button
                  onClick={() => {
                    if (forensicKey && onVerify) {
                      onVerify(forensicKey);
                    } else {
                      setIsPromptOpen(true);
                    }
                  }}
                  className="w-full flex items-center justify-center gap-2 p-2.5 rounded-2xl bg-sky-500/20 hover:bg-sky-500/30 text-sky-200 hover:text-white border border-sky-400/40 shadow-sm transition group"
                >
                  <ShieldCheck className="w-3.5 h-3.5 text-sky-400 group-hover:scale-110 transition-transform" />
                  <span className="text-[10.5px] font-bold tracking-wide">
                    Investigate & Verify
                  </span>
                </button>
                <p className="text-[8.5px] text-slate-400 text-center leading-tight">
                  Cryptographically authenticate carriers against database issuance.
                </p>
              </div>
            )}
          </div>

          {/* Forensic Invariant Footnote */}
          <div className="mt-3 p-3 rounded-xl bg-white/5 border border-white/10 text-[9px] text-slate-300 flex items-start gap-2 leading-relaxed shadow-xs">
            <Info className="w-3.5 h-3.5 shrink-0 text-sky-400 mt-0.5" />
            <span>
              Structural inspection only. Grounded in document syntax; does not establish cryptographic authenticity.
            </span>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-center p-4 text-slate-400 text-xs">
          <HelpCircle className="w-5 h-5 mb-1 opacity-40" />
          Select a carrier layer to inspect structural evidence.
        </div>
      )}

      {/* Forensic Key Prompt Modal */}
      {isPromptOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="w-[320px] glass-dock-dark rounded-3xl p-5 border border-white/20 shadow-2xl text-slate-100 space-y-3.5 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-2 border-b border-white/10">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-sky-500/20 text-sky-300 border border-sky-400/30">
                  <Key className="w-3.5 h-3.5" />
                </div>
                <h3 className="text-xs font-bold text-white">Forensic Audit Key</h3>
              </div>
              <button
                onClick={() => setIsPromptOpen(false)}
                className="p-1 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            <p className="text-[9.5px] text-slate-300 leading-relaxed">
              Enter the operator audit key configured in <code className="text-sky-300 font-mono">SECUREPDF_FORENSIC_KEY</code> to perform active cryptographic verification.
            </p>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (keyInput.trim()) {
                  if (onSetForensicKey) {
                    onSetForensicKey(keyInput.trim());
                  }
                  setIsPromptOpen(false);
                  if (onVerify) {
                    onVerify(keyInput.trim());
                  }
                }
              }}
              className="space-y-3"
            >
              <input
                type="password"
                placeholder="Audit Access Key"
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                autoFocus
                className="w-full px-3 py-2 rounded-xl bg-white/10 border border-white/20 text-xs text-white placeholder-slate-400 focus:outline-hidden focus:border-sky-400 transition font-mono"
              />

              <div className="flex items-center gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setIsPromptOpen(false)}
                  className="flex-1 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 border border-white/15 text-xs text-slate-300 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!keyInput.trim()}
                  className="flex-1 py-1.5 rounded-xl bg-sky-500/30 hover:bg-sky-500/40 border border-sky-400/40 text-xs font-bold text-white transition disabled:opacity-40"
                >
                  Verify
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
