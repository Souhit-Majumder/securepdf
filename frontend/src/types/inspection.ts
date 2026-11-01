/**
 * TypeScript interfaces matching SecurePDF Phase A backend DTO schemas.
 * Guarantees:
 * - Strict typing matching Pydantic DTO models.
 * - rotation is strictly 0 | 90 | 180 | 270.
 * - Optional references are string | null.
 */

export type CarrierStatusType =
  | "VALID"
  | "STRUCTURALLY_DECODED"
  | "OBSERVED_SYNTAX"
  | "INVALID"
  | "NOT_FOUND"
  | "SECURITY_CONFLICT"
  | "ERROR";

export type VerificationStatusType =
  | "VALID"
  | "INVALID"
  | "NOT_FOUND"
  | "SECURITY_CONFLICT"
  | "ERROR";

export interface PageDimensionDTO {
  page_index: number;
  width: number;
  height: number;
  rotation: 0 | 90 | 180 | 270;
  cropbox: [number, number, number, number];
  mediabox: [number, number, number, number];
}

export interface MinimizedCatalogLocationDTO {
  carrier_type: "CATALOG";
  catalog_xref: number;
}

export interface MinimizedAnnotationLocationDTO {
  carrier_type: "ANNOTATION";
  page_index: number;
  annotation_xref: number;
  rect: [number, number, number, number]; // [x0, y0, x1, y1] in PyMuPDF points
  title: string;
}

export interface MinimizedContentStreamLocationDTO {
  carrier_type: "CONTENT_STREAM";
  page_index: number;
  content_stream_xref: number;
  gap_index: number;
  displacement: number;
  bit_value: "0" | "1" | null;
  is_intentional: boolean;
}

export interface MinimizedCarrierDTO {
  carrier_name:
    | "Layer 1 (Catalog)"
    | "Layer 2 (Annotations)"
    | "Layer 3 (Stego Kerning)";
  status: CarrierStatusType;
  signature_ref: string | null;
  total_word_gaps: number | null;
  modulated_word_gaps: number | null;
  bit_1_count: number | null;
  bit_0_count: number | null;
  catalog_location?: MinimizedCatalogLocationDTO | null;
  annotation_locations: MinimizedAnnotationLocationDTO[];
  content_stream_locations: MinimizedContentStreamLocationDTO[];
}

export interface MinimizedCrossLayerDTO {
  carrier_tokens_match: boolean | null;
  cross_carrier_conflict: boolean;
  conflict_reason: string | null;
}

export interface InspectionResponseDTO {
  document_uid: string | null;
  overall_status: CarrierStatusType;
  subject_ref: string | null;
  page_dimensions: PageDimensionDTO[];
  carriers: MinimizedCarrierDTO[];
  cross_layer: MinimizedCrossLayerDTO;
  timestamp: string;
}

export interface ActiveVerificationResponseDTO {
  verification_status: VerificationStatusType;
  authenticated_layers: string[];
  reason: string | null;
  document_uid: string | null;
  subject_ref: string | null;
  carriers: MinimizedCarrierDTO[];
  cross_layer: MinimizedCrossLayerDTO;
  timestamp: string;
}

export interface WebGLDiagnosticInfo {
  status: "unsupported" | "context_lost" | "init_failed";
  webgl1_supported: boolean;
  webgl2_supported: boolean;
  sanitized_vendor: string | null;
  sanitized_renderer: string | null;
  error_code: string;
  message: string;
}
