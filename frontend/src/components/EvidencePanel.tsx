import React from "react";
import {
  Activity,
  Box,
  Layers,
  Type,
  Info,
  ShieldAlert,
  HelpCircle,
} from "lucide-react";
import {
  InspectionResponseDTO,
  CarrierStatusType,
} from "../types/inspection";

interface EvidencePanelProps {
  report: InspectionResponseDTO;
  activeLayer: number; // 0 = Catalog, 1 = Annotations, 2 = Stego Kerning
  onSelectLayer: (layerIndex: number) => void;
  isStandAlone?: boolean;
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({
  report,
  activeLayer,
  isStandAlone = false,
}) => {
  const carrier = report.carriers[activeLayer] || report.carriers[0];
  const pageDim = report.page_dimensions[0] || null;

  const renderStatusBadge = (status: CarrierStatusType) => {
    switch (status) {
      case "STRUCTURALLY_DECODED":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            STRUCTURALLY_DECODED
          </span>
        );
      case "OBSERVED_SYNTAX":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            OBSERVED_SYNTAX
          </span>
        );
      case "INVALID":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
            INVALID
          </span>
        );
      case "SECURITY_CONFLICT":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <ShieldAlert className="w-3 h-3" />
            SECURITY_CONFLICT
          </span>
        );
      case "NOT_FOUND":
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
            NOT_FOUND
          </span>
        );
    }
  };

  const getLayerIcon = (index: number) => {
    switch (index) {
      case 0:
        return <Box className="w-5 h-5 text-sky-400" />;
      case 1:
        return <Layers className="w-5 h-5 text-cyan-400" />;
      case 2:
      default:
        return <Type className="w-5 h-5 text-indigo-400" />;
    }
  };

  const getLayerDescription = () => {
    if (!carrier) return "No evidence found for this layer.";
    switch (carrier.carrier_name) {
      case "Layer 1 (Catalog)":
        return carrier.status === "STRUCTURALLY_DECODED"
          ? "Document catalog dictionary contains an embedded metadata reference payload."
          : "No structural SPDFPayload dictionary key detected in PDF root catalog.";
      case "Layer 2 (Annotations)":
        return carrier.status === "STRUCTURALLY_DECODED"
          ? `Page 0 contains ${carrier.annotation_locations.length} invisible annotation carrier(s) with redundant compact payload.`
          : "No invisible SPDF annotation objects discovered on Page 0.";
      case "Layer 3 (Stego Kerning)":
        if (carrier.status === "STRUCTURALLY_DECODED") {
          return "Content streams contain a structurally framed steganographic bitstream with valid CRC-32 integrity.";
        } else if (carrier.status === "OBSERVED_SYNTAX") {
          return "Content streams contain standard typesetting inter-word kerning syntax. No steganographic preamble frame detected.";
        } else if (carrier.status === "INVALID") {
          return "Steganographic synchronization frame detected, but payload failed CRC-32 checksum validation.";
        }
        return "No text content streams or inter-word spacing gaps detected.";
    }
  };

  return (
    <div
      className={`glass-panel rounded-2xl flex flex-col text-slate-200 transition-all duration-300 ${
        isStandAlone ? "w-full p-6" : "w-[360px] p-5 shadow-2xl h-[calc(100vh-120px)] max-h-[820px] overflow-y-auto"
      }`}
    >
      {/* Header */}
      <div className="flex items-center gap-2.5 pb-4 mb-4 border-b border-white/[0.08]">
        <div className="p-1.5 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/20">
          <Activity className="w-4 h-4" />
        </div>
        <h2 className="text-sm font-semibold tracking-tight text-slate-100 uppercase">
          Evidence Inspector
        </h2>
      </div>

      {carrier ? (
        <div className="space-y-5">
          {/* Active Layer Header Card */}
          <div className="flex items-start gap-3 p-3.5 rounded-xl glass-panel-subtle">
            <div className="p-2 rounded-lg bg-slate-800/80 border border-white/10 shrink-0">
              {getLayerIcon(activeLayer)}
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-semibold text-slate-100 truncate">
                {carrier.carrier_name}
              </h3>
              <div className="text-[11px] text-slate-400 mt-0.5">
                Structural Evidence Detail
              </div>
            </div>
          </div>

          {/* Status Row */}
          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between py-1">
              <span className="text-slate-400 font-medium">Status</span>
              <div>{renderStatusBadge(carrier.status)}</div>
            </div>

            {carrier.catalog_location && (
              <div className="flex items-center justify-between py-1 border-t border-white/[0.04]">
                <span className="text-slate-400 font-medium">Catalog xref</span>
                <span className="font-mono text-slate-200">{carrier.catalog_location.catalog_xref}</span>
              </div>
            )}

            {carrier.signature_ref && (
              <div className="flex items-center justify-between py-1 border-t border-white/[0.04]">
                <span className="text-slate-400 font-medium">Signature Ref</span>
                <span className="font-mono text-sky-300 font-semibold">{carrier.signature_ref}</span>
              </div>
            )}

            <div className="pt-2 border-t border-white/[0.04]">
              <span className="text-slate-400 font-medium block mb-1">Description</span>
              <p className="text-xs text-slate-300 leading-relaxed">
                {getLayerDescription()}
              </p>
            </div>
          </div>

          {/* Technical Details Section */}
          <div className="pt-4 border-t border-white/[0.08] space-y-2.5">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
              Technical Details
            </div>

            {carrier.carrier_name === "Layer 1 (Catalog)" && (
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between text-slate-300">
                  <span className="text-slate-400">Object Type:</span>
                  <span className="font-mono">Catalog Dictionary</span>
                </div>
                <div className="flex justify-between text-slate-300">
                  <span className="text-slate-400">Payload Key:</span>
                  <span className="font-mono">/SPDFPayload</span>
                </div>
              </div>
            )}

            {carrier.carrier_name === "Layer 2 (Annotations)" && (
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between text-slate-300">
                  <span className="text-slate-400">Annotation Count:</span>
                  <span className="font-mono">{carrier.annotation_locations.length}</span>
                </div>
                <div className="flex justify-between text-slate-300">
                  <span className="text-slate-400">Flags:</span>
                  <span className="font-mono">35 (Hidden, NoView)</span>
                </div>
              </div>
            )}

            {carrier.carrier_name === "Layer 3 (Stego Kerning)" && (
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between text-slate-300">
                  <span className="text-slate-400">Total Word Gaps:</span>
                  <span className="font-mono">{carrier.total_word_gaps ?? "None"}</span>
                </div>
                <div className="flex justify-between text-slate-300">
                  <span className="text-slate-400">Modulated Gaps:</span>
                  <span className="font-mono">{carrier.modulated_word_gaps ?? "0"}</span>
                </div>
                {carrier.bit_1_count !== null && (
                  <div className="flex justify-between text-slate-300">
                    <span className="text-slate-400">Bit '1' / '0' Frequency:</span>
                    <span className="font-mono">{carrier.bit_1_count} / {carrier.bit_0_count}</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Page Location Geometry */}
          {pageDim && (
            <div className="pt-4 border-t border-white/[0.08] space-y-2 text-xs">
              <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
                Page Location
              </div>
              <div className="flex justify-between text-slate-300">
                <span className="text-slate-400">Page Number:</span>
                <span className="font-mono">{pageDim.page_index + 1}</span>
              </div>
              <div className="flex justify-between text-slate-300">
                <span className="text-slate-400">Rotation:</span>
                <span className="font-mono">{pageDim.rotation}°</span>
              </div>
              <div className="flex justify-between text-slate-300">
                <span className="text-slate-400">CropBox:</span>
                <span className="font-mono text-[11px]">
                  {pageDim.cropbox.map((v) => Math.round(v)).join(", ")}
                </span>
              </div>
              <div className="flex justify-between text-slate-300">
                <span className="text-slate-400">MediaBox:</span>
                <span className="font-mono text-[11px]">
                  {pageDim.mediabox.map((v) => Math.round(v)).join(", ")}
                </span>
              </div>
            </div>
          )}

          {/* Cross Layer Summary */}
          <div className="pt-4 border-t border-white/[0.08] space-y-2 text-xs">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
              Cross-Layer Consistency
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Carrier Tokens Match:</span>
              <span className="font-medium text-slate-200">
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

          {/* Forensic Invariant Footnote */}
          <div className="mt-4 p-3 rounded-xl bg-sky-950/20 border border-sky-500/20 text-[11px] text-sky-300/80 flex items-start gap-2.5 leading-relaxed">
            <Info className="w-4 h-4 shrink-0 text-sky-400 mt-0.5" />
            <span>
              Catalog and structural evidence references internal document syntax only. This does not indicate cryptographic authenticity.
            </span>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-center p-6 text-slate-500 text-xs">
          <HelpCircle className="w-8 h-8 mb-2 opacity-40" />
          Select a carrier layer to inspect structural evidence.
        </div>
      )}
    </div>
  );
};
