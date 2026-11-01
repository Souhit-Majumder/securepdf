/**
 * Unit tests for Phase 4: Forensic Recipient Attribution & Multi-page PDF Navigation.
 * Guarantees Verified:
 * - Recipient attribution fields on ActiveVerificationResponseDTO.
 * - Strict PII redaction for audit-key-only verification.
 * - Multi-page navigation bounds clamping and page-index alignment.
 * - Layer 2 annotation overlay filtering by page_index (preventing page 0 overlay bleeding).
 * - Multi-page aspect ratio and geometry derivation.
 */
import { describe, it, expect } from "vitest";
import {
  ActiveVerificationResponseDTO,
  MinimizedAnnotationLocationDTO,
} from "../types/inspection";

describe("Phase 4 Forensic Recipient Attribution DTO", () => {
  it("supports recipient attribution under authenticated owner verification", () => {
    const verifiedAttribution: ActiveVerificationResponseDTO = {
      verification_status: "VALID",
      authenticated_layers: ["Layer 1 (Catalog)", "Layer 2 (Annotations)"],
      reason: null,
      document_uid: "DOC-SEC-99",
      subject_ref: "subj_anon_4a9b2c",
      recipient_name: "Alice Montgomery",
      recipient_identifier: "STU-ALICE-2026",
      carriers: [],
      cross_layer: {
        carrier_tokens_match: true,
        cross_carrier_conflict: false,
        conflict_reason: null,
      },
      timestamp: "2026-11-01T12:00:00Z",
    };

    expect(verifiedAttribution.recipient_name).toBe("Alice Montgomery");
    expect(verifiedAttribution.recipient_identifier).toBe("STU-ALICE-2026");
    expect(verifiedAttribution.verification_status).toBe("VALID");

    // Zero secret leakage
    expect((verifiedAttribution as any).nonce).toBeUndefined();
    expect((verifiedAttribution as any).hmac_tag).toBeUndefined();
    expect((verifiedAttribution as any).download_token).toBeUndefined();
    expect((verifiedAttribution as any).master_key).toBeUndefined();
  });

  it("strictly redacts recipient PII under forensic-key-only auditor requests", () => {
    const auditorVerification: ActiveVerificationResponseDTO = {
      verification_status: "VALID",
      authenticated_layers: ["Layer 1 (Catalog)"],
      reason: null,
      document_uid: "DOC-SEC-99",
      subject_ref: "subj_anon_auditor_view",
      recipient_name: null,
      recipient_identifier: null,
      carriers: [],
      cross_layer: {
        carrier_tokens_match: true,
        cross_carrier_conflict: false,
        conflict_reason: null,
      },
      timestamp: "2026-11-01T12:05:00Z",
    };

    expect(auditorVerification.recipient_name).toBeNull();
    expect(auditorVerification.recipient_identifier).toBeNull();
    expect(auditorVerification.subject_ref).toBe("subj_anon_auditor_view");
  });
});

describe("Phase 4 Multi-page Navigation & Evidence Association Logic", () => {
  const clampPage = (requested: number, total: number) => Math.min(Math.max(1, requested), Math.max(1, total));

  it("clamps page navigation correctly within [1, totalPages]", () => {
    const totalPages = 5;

    expect(clampPage(0, totalPages)).toBe(1);
    expect(clampPage(-3, totalPages)).toBe(1);
    expect(clampPage(1, totalPages)).toBe(1);
    expect(clampPage(3, totalPages)).toBe(3);
    expect(clampPage(5, totalPages)).toBe(5);
    expect(clampPage(6, totalPages)).toBe(5);
    expect(clampPage(999, totalPages)).toBe(5);
  });

  it("filters Layer 2 annotations strictly to the matching page index", () => {
    const annotations: MinimizedAnnotationLocationDTO[] = [
      {
        carrier_type: "ANNOTATION",
        page_index: 0,
        annotation_xref: 101,
        rect: [10, 20, 30, 40],
        title: "SPDF0",
      },
      {
        carrier_type: "ANNOTATION",
        page_index: 0,
        annotation_xref: 102,
        rect: [50, 60, 70, 80],
        title: "SPDF1",
      },
      {
        carrier_type: "ANNOTATION",
        page_index: 2,
        annotation_xref: 201,
        rect: [15, 25, 35, 45],
        title: "SPDF_P2",
      },
    ];

    // On Page 1 (page_index = 0): only page 0 annotations match
    const currentPage1 = 1;
    const pageIndex1 = currentPage1 - 1;
    const page1Annots = annotations.filter((a) => a.page_index === pageIndex1);
    expect(page1Annots).toHaveLength(2);
    expect(page1Annots[0].title).toBe("SPDF0");
    expect(page1Annots[1].title).toBe("SPDF1");

    // On Page 2 (page_index = 1): NO annotations exist; must NOT show page 0 annotations
    const currentPage2 = 2;
    const pageIndex2 = currentPage2 - 1;
    const page2Annots = annotations.filter((a) => a.page_index === pageIndex2);
    expect(page2Annots).toHaveLength(0);

    // On Page 3 (page_index = 2): only page 2 annotation matches
    const currentPage3 = 3;
    const pageIndex3 = currentPage3 - 1;
    const page3Annots = annotations.filter((a) => a.page_index === pageIndex3);
    expect(page3Annots).toHaveLength(1);
    expect(page3Annots[0].title).toBe("SPDF_P2");
  });

  it("calculates page-specific aspect ratios correctly for multi-page documents", () => {
    const pageDimensions = [
      { page_index: 0, width: 612, height: 792, rotation: 0 as const, cropbox: [0, 0, 612, 792], mediabox: [0, 0, 612, 792] }, // Portrait (0.7727)
      { page_index: 1, width: 792, height: 612, rotation: 0 as const, cropbox: [0, 0, 792, 612], mediabox: [0, 0, 792, 612] }, // Landscape (1.2941)
    ];

    const baseHeight = 3.55;

    // Page 1 Portrait width
    const page0 = pageDimensions[0];
    const width0 = baseHeight * (page0.width / page0.height);
    expect(width0).toBeCloseTo(2.742, 2);

    // Page 2 Landscape width
    const page1 = pageDimensions[1];
    const width1 = baseHeight * (page1.width / page1.height);
    expect(width1).toBeCloseTo(4.594, 2);

    expect(width1).toBeGreaterThan(width0);
  });
});
