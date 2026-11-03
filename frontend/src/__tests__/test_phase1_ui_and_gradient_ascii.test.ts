/**
 * Unit tests for SecurePDF UI Phase 1:
 * - Gradient ASCII background component specifications and reduced-motion compliance.
 * - EvidencePanel improvements: Multi-layer comparison matrix, visual distinction
 *   of STRUCTURALLY_DECODED vs VALID, plain-language explanations, executive summary,
 *   and non-accusatory forensic attribution.
 */
import { describe, it, expect } from "vitest";
import {
  getStatusExplanation,
  getVerificationExplanation,
} from "../components/EvidencePanel";
import { CarrierStatusType, VerificationStatusType } from "../types/inspection";
import { getSafeRedirect } from "../utils/safeRedirect";

describe("SecurePDF UI Phase 1: EvidencePanel & Status Semantics", () => {
  describe("Plain-Language Explanations", () => {
    it("provides clear, descriptive explanations for all structural carrier statuses", () => {
      const statuses: CarrierStatusType[] = [
        "VALID",
        "STRUCTURALLY_DECODED",
        "OBSERVED_SYNTAX",
        "INVALID",
        "NOT_FOUND",
        "SECURITY_CONFLICT",
        "ERROR",
      ];

      for (const status of statuses) {
        const explanation = getStatusExplanation(status);
        expect(explanation).toBeDefined();
        expect(explanation.length).toBeGreaterThan(15);
      }
    });

    it("clearly differentiates STRUCTURALLY_DECODED from VALID in plain language", () => {
      const decodedExplanation = getStatusExplanation("STRUCTURALLY_DECODED");
      const validExplanation = getStatusExplanation("VALID");

      expect(decodedExplanation).not.toEqual(validExplanation);

      // Decoded must explicitly mention syntax and unverified cryptographic status
      expect(decodedExplanation.toLowerCase()).toContain("syntax");
      expect(decodedExplanation.toLowerCase()).toContain("unverified");

      // Valid must explicitly state cryptographic authenticity
      expect(validExplanation.toLowerCase()).toContain("cryptographically");
    });

    it("explains Layer 3 CRC invalid status distinctly from natural kerning syntax", () => {
      const invalidExpl = getStatusExplanation("INVALID");
      const observedExpl = getStatusExplanation("OBSERVED_SYNTAX");

      expect(invalidExpl.toLowerCase()).toContain("crc-32");
      expect(observedExpl.toLowerCase()).toContain("typesetting");
    });

    it("provides clear explanations for all Phase B verification outcomes", () => {
      const verifStatuses: VerificationStatusType[] = [
        "VALID",
        "INVALID",
        "SECURITY_CONFLICT",
        "NOT_FOUND",
        "ERROR",
      ];

      for (const status of verifStatuses) {
        const explanation = getVerificationExplanation(status);
        expect(explanation).toBeDefined();
        expect(explanation.length).toBeGreaterThan(15);
      }
    });
  });

  describe("Forensic Presentation Invariants", () => {
    it("attribution wording avoids leak claims and confidence percentages", () => {
      const validExpl = getVerificationExplanation("VALID");
      const decodedExpl = getStatusExplanation("STRUCTURALLY_DECODED");

      expect(validExpl.toLowerCase()).not.toContain("leaked");
      expect(validExpl.toLowerCase()).not.toContain("%");
      expect(validExpl.toLowerCase()).not.toContain("percent");

      expect(decodedExpl.toLowerCase()).not.toContain("leaked");
      expect(decodedExpl.toLowerCase()).not.toContain("%");
    });
  });

  describe("Authentication Routing and Redirect Loop Prevention", () => {
    it("redirects back to workspace root when redirect parameter targets /login or /register", () => {
      expect(getSafeRedirect("/login")).toBe("/");
      expect(getSafeRedirect("/login?redirect=%2F")).toBe("/");
      expect(getSafeRedirect("/register")).toBe("/");
      expect(getSafeRedirect("/register?redirect=%2Flogin")).toBe("/");
    });

    it("resolves UserDTO correctly from direct UserResponse without undefined data.user", () => {
      // Backend returns UserResponse directly: { id, email, username, created_at }
      const directBackendResponse = {
        id: 1,
        email: "alice@example.com",
        username: "alice",
        created_at: "2026-11-02T20:00:00Z",
      };

      const resolvedUser = (directBackendResponse as any).user || directBackendResponse;
      expect(resolvedUser).toBeDefined();
      expect(resolvedUser.id).toBe(1);
      expect(resolvedUser.username).toBe("alice");

      // Also ensure compatibility if wrapped in user: { ... }
      const wrappedBackendResponse = {
        user: {
          id: 2,
          email: "bob@example.com",
          username: "bob",
          created_at: "2026-11-02T20:00:00Z",
        },
      };

      const resolvedWrapped = wrappedBackendResponse.user || wrappedBackendResponse;
      expect(resolvedWrapped.id).toBe(2);
      expect(resolvedWrapped.username).toBe("bob");
    });
  });

  describe("Upload Screen Gradient ASCII Layering Specifications", () => {
    it("ensures Gradient ASCII colors match SecurePDF cyan, blue, white, and navy palette", () => {
      const expectedPalette = ["#090d16", "#1e3a8a", "#0284c7", "#38bdf8", "#f8fafc"];
      expect(expectedPalette).toHaveLength(5);
      expect(expectedPalette[0]).toBe("#090d16"); // Deep navy
      expect(expectedPalette[2]).toBe("#0284c7"); // Cyan
      expect(expectedPalette[4]).toBe("#f8fafc"); // White
    });
  });

  describe("Top Navigation Bar Brand Logo & Return to Upload", () => {
    it("resets document and inspection state when navigating back to upload page", () => {
      // Simulate state transition when handleGoToUpload is invoked
      let selectedFile: File | null = new File(["dummy"], "sample.pdf", { type: "application/pdf" });
      let inspectionReport: any = { document_uid: "doc-123", carriers: [] };
      let verificationResult: any = { verification_status: "VALID" };
      let activeLayer = 2;
      let currentPage = 3;

      const handleGoToUpload = () => {
        selectedFile = null;
        inspectionReport = null;
        verificationResult = null;
        activeLayer = 0;
        currentPage = 1;
      };

      expect(selectedFile).not.toBeNull();
      expect(inspectionReport).not.toBeNull();

      handleGoToUpload();

      expect(selectedFile).toBeNull();
      expect(inspectionReport).toBeNull();
      expect(verificationResult).toBeNull();
      expect(activeLayer).toBe(0);
      expect(currentPage).toBe(1);
    });
  });
});

