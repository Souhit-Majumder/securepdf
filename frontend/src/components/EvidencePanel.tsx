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
  ChevronDown,
  ChevronRight,
  Check,
  Eye,
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
  selectedAnnotationXref?: number | null;
  onSelectAnnotation?: (xref: number | null) => void;
  selectedKerningLocationIndex?: number | null;
  onSelectKerningLocation?: (index: number | null) => void;
  onPageChange?: (page: number) => void;
  currentPage?: number;
}

/** Plain-language explanation for structural carrier inspection statuses */
export function getStatusExplanation(status: CarrierStatusType): string {
  switch (status) {
    case "VALID":
      return "Cryptographically authentic. Payload verified against master key and database issuance.";
    case "STRUCTURALLY_DECODED":
      return "Structural carrier parsed from PDF syntax. Cryptographic HMAC is unverified.";
    case "OBSERVED_SYNTAX":
      return "Natural typesetting kerning observed. No steganographic synchronization frame detected.";
    case "INVALID":
      return "Carrier preamble detected, but bitstream failed CRC-32 checksum validation.";
    case "SECURITY_CONFLICT":
      return "Conflicting tracking tokens detected across document layers, indicating carrier splicing.";
    case "NOT_FOUND":
      return "No carrier signature, dictionary entry, or modulation pattern detected in this layer.";
    case "ERROR":
    default:
      return "An unexpected error occurred during carrier inspection.";
  }
}

/** Plain-language explanation for Phase B active cryptographic verification statuses */
export function getVerificationExplanation(status: VerificationStatusType): string {
  switch (status) {
    case "VALID":
      return "Cryptographically verified under master key. Document copy authentic to issuance record.";
    case "INVALID":
      return "HMAC cryptographic signature invalid or document payload does not match issuance record.";
    case "SECURITY_CONFLICT":
      return "Security conflict: cross-carrier payload tokens do not match or carrier has been tampered with.";
    case "NOT_FOUND":
      return "No verifiable carrier payloads discovered in document structure.";
    case "ERROR":
    default:
      return "Cryptographic verification service encountered an unrecoverable error.";
  }
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({
  report,
  activeLayer,
  onSelectLayer,
  isStandAlone = false,
  verificationResult = null,
  isVerifying = false,
  verificationError = null,
  onVerify,
  onCancelVerify,
  onClearVerify,
  forensicKey = null,
  onSetForensicKey,
  selectedAnnotationXref = null,
  onSelectAnnotation,
  selectedKerningLocationIndex = null,
  onSelectKerningLocation,
  onPageChange,
  currentPage = 1,
}) => {
  const [isPromptOpen, setIsPromptOpen] = useState(false);
  const [keyInput, setKeyInput] = useState("");

  // Expandable section states for progressive disclosure
  const [isOverviewExpanded, setIsOverviewExpanded] = useState(true);
  const [isTechDetailsExpanded, setIsTechDetailsExpanded] = useState(true);
  const [isLocationsExpanded, setIsLocationsExpanded] = useState(true);
  const [isGeometryExpanded, setIsGeometryExpanded] = useState(false);

  const carrier = report.carriers[activeLayer] || report.carriers[0];
  const pageDim = report.page_dimensions[0] || null;

  // Visual status label rendering with clear differentiation between STRUCTURALLY_DECODED (cyan) and VALID (emerald)
  const renderStatusBadge = (status: CarrierStatusType) => {
    switch (status) {
      case "VALID":
        return (
          <span
            title="Cryptographically authenticated"
            className="inline-flex items-center gap-1.5 text-[9.5px] font-bold text-emerald-400 tracking-tight"
          >
            <ShieldCheck className="w-3 h-3 text-emerald-400" />
            VALID
          </span>
        );
      case "STRUCTURALLY_DECODED":
        return (
          <span
            title="Syntax parsed from PDF structure; cryptographically unverified"
            className="inline-flex items-center gap-1.5 text-[9.5px] font-bold text-cyan-300 tracking-tight"
          >
            <Eye className="w-3 h-3 text-cyan-400 animate-pulse" />
            STRUCTURALLY_DECODED
          </span>
        );
      case "OBSERVED_SYNTAX":
        return (
          <span
            title="Typesetting inter-word spacing observed without carrier preamble"
            className="inline-flex items-center gap-1.5 text-[9.5px] font-bold text-amber-300 tracking-tight"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            OBSERVED_SYNTAX
          </span>
        );
      case "INVALID":
        return (
          <span
            title="Preamble detected but CRC checksum or framing failed"
            className="inline-flex items-center gap-1.5 text-[9.5px] font-bold text-rose-400 tracking-tight"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
            INVALID
          </span>
        );
      case "SECURITY_CONFLICT":
        return (
          <span
            title="Cross-carrier token mismatch or carrier splicing"
            className="inline-flex items-center gap-1.5 text-[9.5px] font-bold text-purple-300 tracking-tight"
          >
            <ShieldAlert className="w-3 h-3 text-purple-400" />
            SECURITY_CONFLICT
          </span>
        );
      case "NOT_FOUND":
      default:
        return (
          <span
            title="No carrier structure discovered"
            className="inline-flex items-center gap-1.5 text-[9.5px] font-medium text-slate-400 tracking-tight"
          >
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
          <span className="inline-flex items-center gap-1.5 text-[9.5px] font-bold text-emerald-400 tracking-tight">
            <Lock className="w-3 h-3 text-emerald-400" />
            VALID
          </span>
        );
      case "INVALID":
        return (
          <span className="inline-flex items-center gap-1.5 text-[9.5px] font-bold text-rose-400 tracking-tight">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
            INVALID
          </span>
        );
      case "SECURITY_CONFLICT":
        return (
          <span className="inline-flex items-center gap-1.5 text-[9.5px] font-bold text-purple-300 tracking-tight">
            <ShieldAlert className="w-3 h-3 text-purple-400" />
            SECURITY_CONFLICT
          </span>
        );
      case "NOT_FOUND":
        return (
          <span className="inline-flex items-center gap-1.5 text-[9.5px] font-medium text-slate-400 tracking-tight">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
            NOT_FOUND
          </span>
        );
      case "ERROR":
      default:
        return (
          <span className="inline-flex items-center gap-1.5 text-[9.5px] font-medium text-amber-300 tracking-tight">
            <AlertCircle className="w-3 h-3 text-amber-400" />
            ERROR
          </span>
        );
    }
  };

  const getLayerIcon = (index: number) => {
    switch (index) {
      case 0:
        return <Box className="w-3.5 h-3.5 text-sky-300" />;
      case 1:
        return <Layers className="w-3.5 h-3.5 text-cyan-300" />;
      case 2:
      default:
        return <Type className="w-3.5 h-3.5 text-indigo-300" />;
    }
  };

  const getLayerDescription = () => {
    if (!carrier) return "No evidence found for this layer.";
    switch (carrier.carrier_name) {
      case "Layer 1 (Catalog)":
        return carrier.status === "STRUCTURALLY_DECODED"
          ? "Document catalog dictionary contains an embedded metadata reference payload (/SPDFPayload)."
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

  // Compute stats for Executive Security Summary
  const detectedCarriersCount = report.carriers.filter(
    (c) => c.status === "STRUCTURALLY_DECODED" || c.status === "VALID"
  ).length;

  const isLayerAuthenticated = (layerNameOrIndex: string | number) => {
    if (!verificationResult) return false;
    const nameMatch =
      typeof layerNameOrIndex === "number"
        ? layerNameOrIndex === 0
          ? ["Layer 1", "Catalog"]
          : layerNameOrIndex === 1
          ? ["Layer 2", "Annotation"]
          : ["Layer 3", "Kerning", "Stego", "Text"]
        : [layerNameOrIndex];

    return verificationResult.authenticated_layers.some((authLayer) =>
      nameMatch.some((m) => authLayer.toLowerCase().includes(m.toLowerCase()))
    );
  };

  return (
    <div
      className={`glass-inspector rounded-3xl flex flex-col text-slate-100 transition-all duration-300 ${
        isStandAlone
          ? "w-full p-5"
          : "w-[340px] p-4 sm:p-5 h-[calc(100vh-140px)] max-h-[720px] overflow-y-auto shadow-2xl"
      }`}
    >
      {/* ---------------- Panel Header ---------------- */}
      <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-white/10 text-sky-300 border border-white/15">
            <Activity className="w-3.5 h-3.5" />
          </div>
          <h2 className="text-[11px] font-bold tracking-wider text-white uppercase">
            Forensic Inspector
          </h2>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[8.5px] text-slate-400 font-mono font-bold px-2 py-0.5 rounded-md bg-white/5 border border-white/10">
            {verificationResult ? "PHASE B VERIFIED" : "PHASE A INSPECTION"}
          </span>
        </div>
      </div>

      {/* ---------------- Executive Security Summary Banner ---------------- */}
      <div className="mb-3.5">
        {verificationResult ? (
          verificationResult.verification_status === "VALID" ? (
            <div className="p-3 rounded-2xl bg-emerald-950/40 border border-emerald-400/35 space-y-1.5 shadow-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-emerald-300 font-bold text-[10px] uppercase tracking-wide">
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span>Cryptographic Match Authenticated</span>
                </div>
                <span className="px-1.5 py-0.2 rounded text-[8px] font-mono font-bold bg-emerald-500/20 text-emerald-200 border border-emerald-400/30">
                  {verificationResult.authenticated_layers.length}/3 LAYERS
                </span>
              </div>
              <p className="text-[9.5px] text-emerald-100/90 leading-relaxed font-normal">
                {verificationResult.recipient_name
                  ? `Authenticated under master key and attributed to recipient ${verificationResult.recipient_name}.`
                  : "Cryptographic HMAC verified under master key. Recipient identity redacted."}
              </p>
            </div>
          ) : verificationResult.verification_status === "SECURITY_CONFLICT" ? (
            <div className="p-3 rounded-2xl bg-purple-950/40 border border-purple-400/35 space-y-1.5 shadow-sm">
              <div className="flex items-center gap-1.5 text-purple-300 font-bold text-[10px] uppercase tracking-wide">
                <ShieldAlert className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                <span>Security Conflict Detected</span>
              </div>
              <p className="text-[9.5px] text-purple-100/90 leading-relaxed font-normal">
                Cross-layer tracking tokens do not match. Multiple carrier payloads may have been spliced or manipulated.
              </p>
            </div>
          ) : (
            <div className="p-3 rounded-2xl bg-rose-950/40 border border-rose-400/35 space-y-1.5 shadow-sm">
              <div className="flex items-center gap-1.5 text-rose-300 font-bold text-[10px] uppercase tracking-wide">
                <AlertCircle className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                <span>Verification Not Authenticated</span>
              </div>
              <p className="text-[9.5px] text-rose-100/90 leading-relaxed font-normal">
                Cryptographic HMAC signature could not be verified under the supplied master key or database issuance records.
              </p>
            </div>
          )
        ) : (
          <div className="p-3 rounded-2xl bg-sky-950/40 border border-sky-400/30 space-y-1.5 shadow-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-sky-300 font-bold text-[10px] uppercase tracking-wide">
                <Eye className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                <span>Structural Carrier Discovery</span>
              </div>
              <span className="px-1.5 py-0.2 rounded text-[8px] font-mono font-bold bg-sky-500/20 text-sky-200 border border-sky-400/30">
                {detectedCarriersCount}/3 DETECTED
              </span>
            </div>
            <p className="text-[9.5px] text-sky-100/80 leading-relaxed font-normal">
              {detectedCarriersCount > 0
                ? `${detectedCarriersCount} of 3 forensic carrier layer(s) detected in PDF syntax. Cryptographic verification is required to establish authenticity and recipient attribution.`
                : "No forensic carrier layers detected in document syntax. Standard PDF document."}
            </p>
          </div>
        )}
      </div>

      {/* ---------------- Unified Multi-Layer Comparison Overview ---------------- */}
      <div className="mb-3.5 rounded-2xl bg-white/5 border border-white/10 overflow-hidden">
        <button
          onClick={() => setIsOverviewExpanded(!isOverviewExpanded)}
          className="w-full flex items-center justify-between p-2.5 text-left hover:bg-white/5 transition"
        >
          <div className="flex items-center gap-2">
            <span className="text-[9px] font-bold uppercase tracking-wider text-slate-300">
              Unified Carrier Comparison Matrix
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-slate-400 text-[8px]">
            <span>Layers 1-3</span>
            {isOverviewExpanded ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
          </div>
        </button>

        {isOverviewExpanded && (
          <div className="p-2.5 pt-0 space-y-1.5 border-t border-white/10">
            {/* Matrix Table */}
            <div className="w-full text-[8.5px]">
              {/* Table Header */}
              <div className="grid grid-cols-12 gap-1 py-1 font-bold text-slate-400 border-b border-white/10 uppercase tracking-wider text-[7.5px]">
                <div className="col-span-4">Layer</div>
                <div className="col-span-2 text-center">Detect</div>
                <div className="col-span-2 text-center">Structure</div>
                <div className="col-span-2 text-center">CRC</div>
                <div className="col-span-2 text-center">Auth</div>
              </div>

              {/* Rows */}
              {report.carriers.map((c, idx) => {
                const isActive = activeLayer === idx;
                const isDetected = c.status !== "NOT_FOUND";
                const isDecoded =
                  c.status === "STRUCTURALLY_DECODED" || c.status === "VALID";
                const isObserved = c.status === "OBSERVED_SYNTAX";

                // Layer 3 has explicit CRC validation
                const crcStatus =
                  idx === 2
                    ? isDecoded
                      ? "PASS"
                      : c.status === "INVALID"
                      ? "FAIL"
                      : "—"
                    : "—";

                const isAuth = isLayerAuthenticated(idx);

                return (
                  <div
                    key={c.carrier_name}
                    onClick={() => onSelectLayer(idx)}
                    className={`grid grid-cols-12 gap-1 py-1.5 px-1 rounded-lg items-center cursor-pointer transition ${
                      isActive
                        ? "bg-sky-500/20 text-white font-semibold ring-1 ring-sky-400/40"
                        : "hover:bg-white/5 text-slate-300"
                    }`}
                  >
                    {/* Layer Name & Icon */}
                    <div className="col-span-4 flex items-center gap-1 truncate">
                      {getLayerIcon(idx)}
                      <span className="truncate">
                        {idx === 0
                          ? "01 Catalog"
                          : idx === 1
                          ? "02 Annots"
                          : "03 Kerning"}
                      </span>
                    </div>

                    {/* Detection */}
                    <div className="col-span-2 text-center">
                      {isDetected ? (
                        <span className="px-1 py-0.2 rounded bg-cyan-500/20 text-cyan-300 font-mono text-[7px] font-bold">
                          FOUND
                        </span>
                      ) : isObserved ? (
                        <span className="px-1 py-0.2 rounded bg-amber-500/20 text-amber-300 font-mono text-[7px] font-bold">
                          OBSVD
                        </span>
                      ) : (
                        <span className="px-1 py-0.2 rounded bg-white/5 text-slate-500 font-mono text-[7px]">
                          NONE
                        </span>
                      )}
                    </div>

                    {/* Structural Decoding */}
                    <div className="col-span-2 text-center">
                      {isDecoded ? (
                        <span className="px-1 py-0.2 rounded bg-cyan-500/20 text-cyan-300 font-mono text-[7px] font-bold">
                          DECODED
                        </span>
                      ) : isObserved ? (
                        <span className="px-1 py-0.2 rounded bg-amber-500/20 text-amber-300 font-mono text-[7px]">
                          SYNTAX
                        </span>
                      ) : (
                        <span className="px-1 py-0.2 rounded bg-white/5 text-slate-500 font-mono text-[7px]">
                          —
                        </span>
                      )}
                    </div>

                    {/* CRC Checksum */}
                    <div className="col-span-2 text-center">
                      {crcStatus === "PASS" ? (
                        <span className="px-1 py-0.2 rounded bg-emerald-500/20 text-emerald-300 font-mono text-[7px] font-bold">
                          PASS
                        </span>
                      ) : crcStatus === "FAIL" ? (
                        <span className="px-1 py-0.2 rounded bg-rose-500/20 text-rose-300 font-mono text-[7px] font-bold">
                          FAIL
                        </span>
                      ) : (
                        <span className="text-slate-500 font-mono text-[7px]">
                          {crcStatus}
                        </span>
                      )}
                    </div>

                    {/* Cryptographic Authentication */}
                    <div className="col-span-2 text-center">
                      {isAuth ? (
                        <span className="px-1 py-0.2 rounded bg-emerald-500/25 text-emerald-300 border border-emerald-400/30 font-mono text-[7px] font-bold">
                          VALID
                        </span>
                      ) : verificationResult ? (
                        <span className="px-1 py-0.2 rounded bg-white/5 text-slate-400 font-mono text-[7px]">
                          UNVERIF
                        </span>
                      ) : (
                        <span className="px-1 py-0.2 rounded bg-white/5 text-slate-500 font-mono text-[7px]">
                          PEND
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="pt-1 text-[7.5px] text-slate-400 flex items-center justify-between">
              <span>Click a layer row to inspect structural details</span>
              <span className="text-sky-300/80">Active: 0{activeLayer + 1}</span>
            </div>
          </div>
        )}
      </div>

      {carrier ? (
        <div className="space-y-3">
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

          {/* Status Row with Distinct Badges */}
          <div className="flex items-center justify-between py-1.5 border-t border-white/10">
            <span className="text-slate-400 text-[10px] font-medium">
              Inspection Status
            </span>
            <div>{renderStatusBadge(carrier.status)}</div>
          </div>

          {/* Plain-Language Status Explanation */}
          <div className="p-2.5 rounded-xl bg-white/5 border border-white/10 space-y-1">
            <span className="text-[8px] font-bold text-slate-400 uppercase tracking-wider block">
              Plain Language Status
            </span>
            <p className="text-[9.5px] text-slate-200 leading-relaxed font-normal">
              {getStatusExplanation(carrier.status)}
            </p>
          </div>

          {/* Observations Section */}
          <div className="pt-2 border-t border-white/10">
            <span className="text-slate-400 text-[8.5px] uppercase tracking-wider block mb-1 font-bold">
              Syntactic Observations
            </span>
            <p className="text-[10px] text-slate-300 leading-relaxed font-normal">
              {getLayerDescription()}
            </p>
          </div>

          {/* ---------------- Technical Details (Progressive Disclosure) ---------------- */}
          <div className="pt-2 border-t border-white/10">
            <button
              onClick={() => setIsTechDetailsExpanded(!isTechDetailsExpanded)}
              className="w-full flex items-center justify-between py-1 text-left text-slate-400 hover:text-white transition"
            >
              <span className="text-[8.5px] font-bold uppercase tracking-wider">
                Technical Details & Identifiers
              </span>
              {isTechDetailsExpanded ? (
                <ChevronDown className="w-3 h-3" />
              ) : (
                <ChevronRight className="w-3 h-3" />
              )}
            </button>

            {isTechDetailsExpanded && (
              <div className="mt-1.5 space-y-1.5 text-[9.5px] bg-black/20 p-2.5 rounded-xl border border-white/5">
                {carrier.carrier_name === "Layer 1 (Catalog)" && (
                  <>
                    <div className="flex justify-between items-center py-0.5">
                      <span className="text-slate-400">Object Type</span>
                      <span className="font-mono text-white font-semibold">Catalog Dict</span>
                    </div>
                    <div className="flex justify-between items-center py-0.5">
                      <span className="text-slate-400">Payload Key</span>
                      <span className="font-mono text-white font-semibold">/SPDFPayload</span>
                    </div>
                    {carrier.catalog_location && (
                      <div className="flex justify-between items-center py-0.5">
                        <span className="text-slate-400">Catalog xref</span>
                        <span className="font-mono text-white font-semibold">
                          #{carrier.catalog_location.catalog_xref}
                        </span>
                      </div>
                    )}
                    {carrier.signature_ref && (
                      <div className="flex justify-between items-center py-0.5">
                        <span className="text-slate-400">Signature Ref</span>
                        <span className="font-mono text-sky-300 font-bold">
                          {carrier.signature_ref}
                        </span>
                      </div>
                    )}
                  </>
                )}

                {carrier.carrier_name === "Layer 2 (Annotations)" && (
                  <>
                    <div className="flex justify-between items-center py-0.5">
                      <span className="text-slate-400">Annotation Count</span>
                      <span className="font-mono text-white font-semibold">
                        {carrier.annotation_locations.length}
                      </span>
                    </div>
                    {carrier.annotation_locations.length > 0 && (
                      <div className="flex justify-between items-center py-0.5">
                        <span className="text-slate-400">Flags</span>
                        <span className="font-mono text-white font-semibold">
                          35 (Hidden, NoView)
                        </span>
                      </div>
                    )}
                    {carrier.signature_ref && (
                      <div className="flex justify-between items-center py-0.5">
                        <span className="text-slate-400">Signature Ref</span>
                        <span className="font-mono text-sky-300 font-bold">
                          {carrier.signature_ref}
                        </span>
                      </div>
                    )}
                  </>
                )}

                {carrier.carrier_name === "Layer 3 (Stego Kerning)" && (
                  <>
                    <div className="flex justify-between items-center py-0.5">
                      <span className="text-slate-400">Total Word Gaps</span>
                      <span className="font-mono text-white font-semibold">
                        {carrier.total_word_gaps ?? "0"}
                      </span>
                    </div>
                    <div className="flex justify-between items-center py-0.5">
                      <span className="text-slate-400">Modulated Gaps</span>
                      <span className="font-mono text-white font-semibold">
                        {carrier.modulated_word_gaps ?? "0"}
                      </span>
                    </div>
                    {carrier.bit_1_count !== null && (
                      <div className="flex justify-between items-center py-0.5">
                        <span className="text-slate-400">Bit '1' / '0' Frequency</span>
                        <span className="font-mono text-white font-semibold">
                          {carrier.bit_1_count} / {carrier.bit_0_count}
                        </span>
                      </div>
                    )}
                    {carrier.signature_ref && (
                      <div className="flex justify-between items-center py-0.5">
                        <span className="text-slate-400">Signature Ref</span>
                        <span className="font-mono text-sky-300 font-bold">
                          {carrier.signature_ref}
                        </span>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>

          {/* ---------------- Detected Instances / Modulation Locations (Expandable) ---------------- */}
          {carrier.carrier_name === "Layer 2 (Annotations)" &&
            carrier.annotation_locations.length > 0 && (
              <div className="pt-2 border-t border-white/10">
                <button
                  onClick={() => setIsLocationsExpanded(!isLocationsExpanded)}
                  className="w-full flex items-center justify-between py-1 text-left text-slate-400 hover:text-white transition"
                >
                  <span className="text-[8.5px] font-bold uppercase tracking-wider flex items-center gap-1.5">
                    <Layers className="w-3 h-3 text-cyan-400" />
                    Detected Annotations ({carrier.annotation_locations.length})
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[7.5px] text-slate-400">Click to locate</span>
                    {isLocationsExpanded ? (
                      <ChevronDown className="w-3 h-3" />
                    ) : (
                      <ChevronRight className="w-3 h-3" />
                    )}
                  </div>
                </button>

                {isLocationsExpanded && (
                  <div className="space-y-1.5 max-h-48 overflow-y-auto pr-0.5 mt-1.5">
                    {carrier.annotation_locations.map((annot, idx) => {
                      const isSelected = selectedAnnotationXref === annot.annotation_xref;
                      const nativeWidth = (annot.rect[2] - annot.rect[0]).toFixed(2);
                      const nativeHeight = (annot.rect[3] - annot.rect[1]).toFixed(2);

                      return (
                        <div
                          key={annot.annotation_xref || idx}
                          data-testid={`annotation-entry-${annot.annotation_xref}`}
                          onClick={() => {
                            if (onSelectAnnotation) {
                              onSelectAnnotation(isSelected ? null : annot.annotation_xref);
                            }
                            if (onPageChange && annot.page_index !== (currentPage || 1) - 1) {
                              onPageChange(annot.page_index + 1);
                            }
                          }}
                          className={`p-2 rounded-xl border transition-all text-[9.5px] cursor-pointer ${
                            isSelected
                              ? "bg-sky-500/20 border-sky-400/80 ring-1 ring-sky-400/50 text-white shadow-sm"
                              : "bg-white/5 border-white/10 hover:bg-white/10 text-slate-300"
                          }`}
                        >
                          <div className="flex items-center justify-between mb-1">
                            <span className="font-mono font-bold text-sky-300 flex items-center gap-1.5">
                              <span
                                className={`w-1.5 h-1.5 rounded-full ${
                                  isSelected ? "bg-sky-400 animate-pulse" : "bg-slate-400"
                                }`}
                              />
                              {annot.title || `SPDF${idx}`}
                            </span>
                            <div className="flex items-center gap-1.5">
                              <span className="px-1.5 py-0.2 rounded bg-white/10 text-[8px] font-mono text-slate-300">
                                Page {annot.page_index + 1}
                              </span>
                              <span className="font-mono text-[8px] text-slate-400">
                                xref #{annot.annotation_xref}
                              </span>
                            </div>
                          </div>

                          <div className="space-y-0.5 text-[8.5px] font-mono text-slate-300 bg-black/20 p-1.5 rounded-lg border border-white/5">
                            <div className="flex justify-between text-slate-400">
                              <span>Native Rect:</span>
                              <span className="text-slate-400">Points (pt)</span>
                            </div>
                            <div className="text-sky-200 truncate">
                              [{annot.rect.map((v) => v.toFixed(2)).join(", ")}]
                            </div>
                            <div className="flex justify-between text-[8px] text-slate-400 pt-0.5 border-t border-white/5">
                              <span>
                                Dimensions: {nativeWidth} × {nativeHeight} pt
                              </span>
                              <span className="text-[7.5px] text-sky-300/80 italic">
                                Enlarged in 3D
                              </span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

          {carrier.carrier_name === "Layer 3 (Stego Kerning)" &&
            carrier.content_stream_locations &&
            carrier.content_stream_locations.length > 0 && (
              <div className="pt-2 border-t border-white/10">
                <button
                  onClick={() => setIsLocationsExpanded(!isLocationsExpanded)}
                  className="w-full flex items-center justify-between py-1 text-left text-slate-400 hover:text-white transition"
                >
                  <span className="text-[8.5px] font-bold uppercase tracking-wider flex items-center gap-1.5">
                    <Type className="w-3 h-3 text-sky-400" />
                    Modulation Locations ({carrier.content_stream_locations.length})
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[7.5px] text-slate-400">Click to locate</span>
                    {isLocationsExpanded ? (
                      <ChevronDown className="w-3 h-3" />
                    ) : (
                      <ChevronRight className="w-3 h-3" />
                    )}
                  </div>
                </button>

                {isLocationsExpanded && (
                  <div className="space-y-1.5 max-h-48 overflow-y-auto pr-0.5 mt-1.5">
                    {carrier.content_stream_locations.map((loc, idx) => {
                      const isSelected = selectedKerningLocationIndex === loc.location_index;
                      const isExact = loc.localization_status === "EXACT";
                      const isApprox = loc.localization_status === "APPROXIMATE";
                      const isUnavail = loc.localization_status === "UNAVAILABLE";

                      return (
                        <div
                          key={loc.location_index ?? idx}
                          data-testid={`carrier-location-entry-${loc.location_index}`}
                          onClick={() => {
                            if (onSelectKerningLocation) {
                              onSelectKerningLocation(isSelected ? null : loc.location_index);
                            }
                            if (onPageChange && loc.page_index !== (currentPage || 1) - 1) {
                              onPageChange(loc.page_index + 1);
                            }
                          }}
                          className={`p-2 rounded-xl border transition-all text-[9.5px] cursor-pointer ${
                            isSelected
                              ? "bg-sky-500/20 border-sky-400/80 ring-1 ring-sky-400/50 text-white shadow-sm"
                              : "bg-white/5 border-white/10 hover:bg-white/10 text-slate-300"
                          }`}
                        >
                          <div className="flex items-center justify-between mb-1">
                            <span className="font-mono font-bold text-sky-300 flex items-center gap-1.5">
                              <span
                                className={`w-1.5 h-1.5 rounded-full ${
                                  isSelected ? "bg-sky-400 animate-pulse" : "bg-slate-400"
                                }`}
                              />
                              Modulation #{loc.location_index + 1}
                            </span>
                            <div className="flex items-center gap-1.5">
                              <span className="px-1.5 py-0.2 rounded bg-white/10 text-[8px] font-mono text-slate-300">
                                Page {loc.page_index + 1}
                              </span>
                              <span
                                className={`px-1.5 py-0.2 rounded text-[7.5px] font-mono font-bold ${
                                  isExact
                                    ? "bg-sky-500/20 text-sky-300 border border-sky-400/30"
                                    : isApprox
                                    ? "bg-amber-500/20 text-amber-300 border border-amber-400/30"
                                    : "bg-slate-500/20 text-slate-400 border border-slate-400/30"
                                }`}
                              >
                                {isExact ? "EXACT" : isApprox ? "APPROXIMATE" : "UNAVAILABLE"}
                              </span>
                            </div>
                          </div>

                          <div className="space-y-0.5 text-[8.5px] font-mono text-slate-300 bg-black/20 p-1.5 rounded-lg border border-white/5">
                            {isUnavail || !loc.rect ? (
                              <div className="text-slate-400 italic">
                                Coordinates not reliably available
                              </div>
                            ) : (
                              <>
                                <div className="flex justify-between text-slate-400">
                                  <span>{isApprox ? "~ Approx Coordinates:" : "Native Coordinates:"}</span>
                                  <span className="text-slate-400">Points (pt)</span>
                                </div>
                                <div className={`${isApprox ? "text-amber-200" : "text-sky-200"} truncate`}>
                                  [{loc.rect.map((v) => v.toFixed(2)).join(", ")}]
                                </div>
                                <div className="flex justify-between text-[8px] text-slate-400 pt-0.5 border-t border-white/5">
                                  <span>
                                    Dimensions: {(loc.rect[2] - loc.rect[0]).toFixed(2)} ×{" "}
                                    {(loc.rect[3] - loc.rect[1]).toFixed(2)} pt
                                  </span>
                                  <span className="text-[7.5px] text-sky-300/80 italic">Caliper Marker</span>
                                </div>
                              </>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

          {/* ---------------- Page Geometry & Cross-Layer (Collapsible) ---------------- */}
          <div className="pt-2 border-t border-white/10">
            <button
              onClick={() => setIsGeometryExpanded(!isGeometryExpanded)}
              className="w-full flex items-center justify-between py-1 text-left text-slate-400 hover:text-white transition"
            >
              <span className="text-[8.5px] font-bold uppercase tracking-wider">
                Geometry & Cross-Layer Diagnostics
              </span>
              {isGeometryExpanded ? (
                <ChevronDown className="w-3 h-3" />
              ) : (
                <ChevronRight className="w-3 h-3" />
              )}
            </button>

            {isGeometryExpanded && (
              <div className="mt-1.5 space-y-2 bg-black/20 p-2.5 rounded-xl border border-white/5 text-[9.5px]">
                {pageDim && (
                  <div className="space-y-1">
                    <div className="text-[8px] font-bold text-slate-400 uppercase tracking-wider">
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

                <div className="pt-1.5 border-t border-white/10 space-y-1">
                  <div className="text-[8px] font-bold text-slate-400 uppercase tracking-wider">
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
              </div>
            )}
          </div>

          {/* ---------------- Phase B: Cryptographic Verification ---------------- */}
          <div className="pt-3 border-t border-white/10 space-y-2.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <div className="p-1 rounded-md bg-sky-500/20 text-sky-300 border border-sky-400/30">
                  <ShieldCheck className="w-3 h-3" />
                </div>
                <span className="text-[9.5px] font-bold uppercase tracking-wider text-white">
                  Cryptographic Verification
                </span>
              </div>
              <span className="text-[8px] font-mono text-slate-400 bg-white/5 px-1.5 py-0.5 rounded border border-white/10 font-bold">
                PHASE B
              </span>
            </div>

            {/* State 1: In Progress */}
            {isVerifying ? (
              <div className="p-3 rounded-2xl bg-white/5 border border-white/10 space-y-2.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-3.5 h-3.5 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
                    <span className="text-[10px] font-medium text-slate-200">
                      Verifying cryptographic HMAC...
                    </span>
                  </div>
                  {onCancelVerify && (
                    <button
                      onClick={onCancelVerify}
                      className="flex items-center gap-1 px-2 py-0.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-400/30 text-[9px] transition cursor-pointer"
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
                  Validating master HMAC and looking up document issuance records in secure database.
                </p>
              </div>
            ) : verificationResult ? (
              /* State 2: Verification Result Available */
              <div className="p-3 rounded-2xl bg-white/5 border border-white/10 space-y-2.5 text-[10px]">
                {/* Result Outcome Header */}
                <div className="flex items-center justify-between pb-1.5 border-b border-white/10">
                  <span className="text-slate-400 text-[9px]">Verification Result</span>
                  <div>{renderVerificationStatusBadge(verificationResult.verification_status)}</div>
                </div>

                {/* Plain-Language Verification Explanation */}
                <p className="text-[9px] text-slate-300 leading-relaxed font-normal">
                  {getVerificationExplanation(verificationResult.verification_status)}
                </p>

                {verificationResult.reason && (
                  <div className="p-2 rounded-xl bg-amber-500/10 border border-amber-400/20 text-[9px] text-amber-300 leading-tight">
                    {verificationResult.reason}
                  </div>
                )}

                {/* Attributed Recipient Prominent Display (Phase 4 / Phase B) */}
                {verificationResult.recipient_name && verificationResult.recipient_identifier ? (
                  <div className="p-3 rounded-xl bg-gradient-to-br from-sky-500/15 to-sky-900/30 border border-sky-400/40 space-y-1.5 my-1.5 shadow-sm">
                    <div className="flex items-center gap-1.5 text-sky-300 font-bold text-[9px] uppercase tracking-wider">
                      <UserCheck className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                      <span>Attributed Recipient</span>
                    </div>
                    <div className="flex items-baseline justify-between pt-0.5">
                      <span className="text-xs font-bold text-white truncate max-w-[170px]">
                        {verificationResult.recipient_name}
                      </span>
                      <span className="text-[9.5px] font-mono font-bold text-sky-300 bg-sky-950/80 px-2 py-0.5 rounded-md border border-sky-400/30 shrink-0">
                        {verificationResult.recipient_identifier}
                      </span>
                    </div>
                    <p className="text-[8px] text-sky-200/80 leading-tight">
                      Document copy cryptographically issued to this recipient.
                    </p>
                  </div>
                ) : verificationResult.verification_status === "VALID" ? (
                  <div className="p-2 rounded-xl bg-white/5 border border-white/10 text-[9px] text-slate-400 italic my-1 flex items-center gap-1.5">
                    <Shield className="w-3 h-3 text-amber-400/80 shrink-0" />
                    <span>Forensic Audit Mode: Recipient identity redacted</span>
                  </div>
                ) : null}

                {/* Authenticated Layers Card */}
                <div className="space-y-1.5 py-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[8.5px] uppercase tracking-wider text-slate-300 font-bold">
                      Authenticated Carriers
                    </span>
                    <span className="text-[8px] font-mono text-emerald-400 font-semibold">
                      {verificationResult.authenticated_layers.length} Verified
                    </span>
                  </div>
                  {verificationResult.authenticated_layers.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {verificationResult.authenticated_layers.map((layerName) => (
                        <span
                          key={layerName}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 text-[9px] font-medium"
                        >
                          <Check className="w-2.5 h-2.5 text-emerald-400" />
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

                {/* Distinguish Authentication vs Structural Detection */}
                <div className="p-2 rounded-xl bg-white/5 border border-white/10 text-[8px] space-y-1 text-slate-400">
                  <div className="flex items-center gap-1.5 text-slate-300 font-medium">
                    <ShieldCheck className="w-3 h-3 text-emerald-400 shrink-0" />
                    <span>Authentication: HMAC verified against master secret</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-slate-300 font-medium">
                    <Eye className="w-3 h-3 text-cyan-400 shrink-0" />
                    <span>Detection: Carrier syntax parsed from PDF stream</span>
                  </div>
                </div>

                {/* Pseudonymized Subject Reference & Document UID */}
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
                    <span className="font-mono text-[9px] text-white font-semibold truncate max-w-[170px]">
                      {verificationResult.document_uid}
                    </span>
                  </div>
                )}

                {/* Clear Verification Button */}
                {onClearVerify && (
                  <button
                    onClick={onClearVerify}
                    className="w-full mt-1.5 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 border border-white/15 text-[9.5px] text-slate-300 hover:text-white transition font-medium cursor-pointer"
                  >
                    Clear Verification
                  </button>
                )}
              </div>
            ) : (
              /* State 3: Ready to Verify */
              <div className="space-y-2">
                {verificationError && (
                  <div className="p-2.5 rounded-xl bg-rose-500/15 border border-rose-400/30 text-[9.5px] text-rose-300 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold">
                      <ShieldAlert className="w-3 h-3 text-rose-400 shrink-0" />
                      <span>Verification Error</span>
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
                  className="w-full flex items-center justify-center gap-2 p-2.5 rounded-2xl bg-sky-500/20 hover:bg-sky-500/30 text-sky-200 hover:text-white border border-sky-400/40 shadow-sm transition group cursor-pointer"
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
          <div className="mt-3 p-2.5 rounded-xl bg-white/5 border border-white/10 text-[8.5px] text-slate-300 flex items-start gap-2 leading-relaxed shadow-xs">
            <Info className="w-3.5 h-3.5 shrink-0 text-sky-400 mt-0.5" />
            <span>
              Structural inspection is grounded in document syntax. Cryptographic verification establishes origin authenticity without proving leak causation.
            </span>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-center p-4 text-slate-400 text-xs">
          <HelpCircle className="w-5 h-5 mb-1 opacity-40" />
          Select a carrier layer to inspect structural evidence.
        </div>
      )}

      {/* ---------------- Forensic Key Prompt Modal ---------------- */}
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
                className="p-1 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition cursor-pointer"
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
                  className="flex-1 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 border border-white/15 text-xs text-slate-300 transition cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!keyInput.trim()}
                  className="flex-1 py-1.5 rounded-xl bg-sky-500/30 hover:bg-sky-500/40 border border-sky-400/40 text-xs font-bold text-white transition disabled:opacity-40 cursor-pointer"
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
