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
    </div>
  );
};
