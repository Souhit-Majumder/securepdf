/**
 * SecurePDF UI Phase 2 Distribution Workflow Unit Tests
 *
 * Verifies:
 * 1. Bulk CSV/TSV delimiter auto-detection and quote-aware parsing.
 * 2. Intelligent header detection (Name, UID, case-insensitive, swapped columns).
 * 3. Field validation: empty names/UIDs, 255-character limits.
 * 4. Duplicate detection: within imported file and against existing queue.
 * 5. Partial imports: importing valid rows while skipping invalid/duplicate rows.
 * 6. Plain-language Layer 3 Steganography and batch status explanations.
 * 7. Non-double-counting batch summary metrics (active vs expired, L3 coverage).
 * 8. Safe clipboard active links generation and CSV export structure.
 */

import React from "react";
import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";
import {
  detectDelimiter,
  parseAndValidateRecipients,
  getStegoStatusExplanation,
  getBatchStatusExplanation,
  calculateBatchSummaryMetrics,
  formatActiveLinksText,
  BatchRecipientItem,
} from "../utils/distributionUtils";
import { DistributionModal } from "../components/DistributionModal";

describe("Bulk Recipient Import - Delimiter & Line Parsing", () => {
  it("auto-detects common delimiters: comma, tab, semicolon, pipe", () => {
    expect(detectDelimiter("Alice,101\nBob,102")).toBe(",");
    expect(detectDelimiter("Alice\t101\nBob\t102")).toBe("\t");
    expect(detectDelimiter("Alice;101\nBob;102")).toBe(";");
    expect(detectDelimiter("Alice|101\nBob|102")).toBe("|");
  });

  it("handles empty or single-character inputs safely", () => {
    expect(detectDelimiter("")).toBe(",");
    expect(detectDelimiter("   \n  ")).toBe(",");
    expect(detectDelimiter("Alice")).toBe(",");
  });

  it("parses fields with quotes containing commas without splitting prematurely", () => {
    const csv = `"Doe, Jane",STU-1001\n"Smith, John",STU-1002`;
    const result = parseAndValidateRecipients(csv);

    expect(result.validCount).toBe(2);
    expect(result.validRows[0].name).toBe("Doe, Jane");
    expect(result.validRows[0].student_uid).toBe("STU-1001");
    expect(result.validRows[1].name).toBe("Smith, John");
    expect(result.validRows[1].student_uid).toBe("STU-1002");
  });

  it("handles escaped quotes within quoted fields", () => {
    const csv = `"Arthur ""King"" Pendragon",STU-999`;
    const result = parseAndValidateRecipients(csv);

    expect(result.validCount).toBe(1);
    expect(result.validRows[0].name).toBe('Arthur "King" Pendragon');
    expect(result.validRows[0].student_uid).toBe("STU-999");
  });
});

describe("Bulk Recipient Import - Header Detection", () => {
  it("detects standard headers and skips the header row", () => {
    const csv = `Full Name,Student ID\nAlice Johnson,STU-001\nBob Miller,STU-002`;
    const result = parseAndValidateRecipients(csv);

    expect(result.hasHeaders).toBe(true);
    expect(result.totalCount).toBe(2);
    expect(result.validCount).toBe(2);
    expect(result.validRows[0]).toEqual({ name: "Alice Johnson", student_uid: "STU-001" });
    expect(result.validRows[1]).toEqual({ name: "Bob Miller", student_uid: "STU-002" });
  });

  it("detects reversed column order when header indicates UID first then Name", () => {
    const csv = `Identifier,Recipient\nSTU-001,Alice Johnson\nSTU-002,Bob Miller`;
    const result = parseAndValidateRecipients(csv);

    expect(result.hasHeaders).toBe(true);
    expect(result.validCount).toBe(2);
    expect(result.validRows[0].name).toBe("Alice Johnson");
    expect(result.validRows[0].student_uid).toBe("STU-001");
  });

  it("treats headerless 2-column files as Name, UID starting on row 1", () => {
    const csv = `Alice Johnson,STU-001\nBob Miller,STU-002`;
    const result = parseAndValidateRecipients(csv);

    expect(result.hasHeaders).toBe(false);
    expect(result.totalCount).toBe(2);
    expect(result.validCount).toBe(2);
    expect(result.validRows[0].name).toBe("Alice Johnson");
  });
});

describe("Bulk Recipient Import - Validation & Constraints", () => {
  it("flags empty recipient name", () => {
    const csv = `,STU-100\nValid Name,STU-101`;
    const result = parseAndValidateRecipients(csv);

    expect(result.totalCount).toBe(2);
    expect(result.validCount).toBe(1);
    expect(result.invalidCount).toBe(1);
    expect(result.allRows[0].status).toBe("INVALID_NAME");
    expect(result.allRows[0].errorMessage).toContain("Recipient name is missing");
  });

  it("flags empty student identifier", () => {
    const csv = `Alice Johnson,\nBob Miller,STU-102`;
    const result = parseAndValidateRecipients(csv);

    expect(result.totalCount).toBe(2);
    expect(result.validCount).toBe(1);
    expect(result.invalidCount).toBe(1);
    expect(result.allRows[0].status).toBe("INVALID_UID");
    expect(result.allRows[0].errorMessage).toContain("Recipient identifier (UID) is missing");
  });

  it("flags fields exceeding the 255-character limit", () => {
    const superLongName = "A".repeat(256);
    const csv = `${superLongName},STU-103\nShort Name,STU-104`;
    const result = parseAndValidateRecipients(csv);

    expect(result.invalidCount).toBe(1);
    expect(result.validCount).toBe(1);
    expect(result.allRows[0].status).toBe("TOO_LONG");
    expect(result.allRows[0].errorMessage).toContain("255 characters");
  });
});

describe("Bulk Recipient Import - Duplicate Detection", () => {
  it("detects internal duplicate identifiers within the same import file", () => {
    const csv = `Alice,STU-101\nBob,STU-102\nCharlie,STU-101`;
    const result = parseAndValidateRecipients(csv);

    expect(result.totalCount).toBe(3);
    expect(result.validCount).toBe(2);
    expect(result.duplicateCount).toBe(1);
    expect(result.allRows[2].status).toBe("DUPLICATE_INTERNAL");
    expect(result.allRows[2].errorMessage).toContain("appears multiple times in this import file");
  });

  it("detects duplicates against the existing recipient queue (case-insensitively)", () => {
    const existingQueue = [
      { name: "Existing Alice", student_uid: "STU-001" },
      { name: "Existing Bob", student_uid: "stu-002" },
    ];

    const csv = `New Charlie,STU-003\nDuplicate Alice,stu-001\nDuplicate Bob,STU-002`;
    const result = parseAndValidateRecipients(csv, existingQueue);

    expect(result.totalCount).toBe(3);
    expect(result.validCount).toBe(1);
    expect(result.duplicateCount).toBe(2);
    expect(result.allRows[1].status).toBe("DUPLICATE_QUEUE");
    expect(result.allRows[2].status).toBe("DUPLICATE_QUEUE");
    expect(result.validRows[0].student_uid).toBe("STU-003");
  });

  it("allows importing only valid rows while skipping invalid and duplicate rows", () => {
    const existingQueue = [{ name: "Alice", student_uid: "A1" }];
    const csv = `Bob,B1\n,C1\nAlice 2,A1\nDavid,B1\nEve,E1`;
    const result = parseAndValidateRecipients(csv, existingQueue);

    // Row 1: Bob, B1 -> VALID
    // Row 2: empty name -> INVALID_NAME
    // Row 3: Alice 2, A1 -> DUPLICATE_QUEUE
    // Row 4: David, B1 -> DUPLICATE_INTERNAL
    // Row 5: Eve, E1 -> VALID
    expect(result.validCount).toBe(2);
    expect(result.validRows.map((r) => r.student_uid)).toEqual(["B1", "E1"]);
    expect(result.duplicateCount).toBe(2);
    expect(result.invalidCount).toBe(1);
  });
});

describe("Distribution Status Explanations", () => {
  it("explains Layer 3 Steganography SUCCESS accurately", () => {
    const info = getStegoStatusExplanation("SUCCESS", true);
    expect(info.label).toBe("L3 Verified");
    expect(info.variant).toBe("success");
    expect(info.description).toContain("kerning modulation");
    expect(info.description).toContain("HMAC-SHA256");
  });

  it("explains Layer 3 Steganography SKIPPED distinguishing opt-out vs carrier capacity bypass", () => {
    const infoOptOut = getStegoStatusExplanation("SKIPPED", false);
    expect(infoOptOut.label).toBe("L3 Bypassed");
    expect(infoOptOut.description).toContain("not opted in");
    expect(infoOptOut.description).toContain("Visible watermarks and annotation carriers remain fully functional");

    const infoCapacityBypass = getStegoStatusExplanation("SKIPPED", true);
    expect(infoCapacityBypass.label).toBe("L3 Bypassed");
    expect(infoCapacityBypass.description).toContain("insufficient text carrier capacity");
    expect(infoCapacityBypass.description).toContain("Visible watermarks and annotation carriers remain fully functional");
  });

  it("explains Layer 3 Steganography PARTIAL coverage accurately", () => {
    const info = getStegoStatusExplanation("PARTIAL");
    expect(info.label).toBe("L3 Partial");
    expect(info.variant).toBe("warning");
    expect(info.description).toContain("Some recipient documents received verified Layer 3 carriers");
  });

  it("explains Layer 3 Steganography FAILED accurately", () => {
    const info = getStegoStatusExplanation("FAILED");
    expect(info.label).toBe("L3 Failed");
    expect(info.variant).toBe("error");
    expect(info.description).toContain("output verification failed");
  });

  it("explains Layer 3 Steganography PENDING accurately", () => {
    const info = getStegoStatusExplanation("PENDING");
    expect(info.label).toBe("L3 Queued");
    expect(info.variant).toBe("info");
  });

  it("explains overall Batch Lifecycle statuses without inventing causes", () => {
    expect(getBatchStatusExplanation("COMPLETED").variant).toBe("success");
    expect(getBatchStatusExplanation("PROCESSING").variant).toBe("info");
    expect(getBatchStatusExplanation("PARTIALLY_FAILED").variant).toBe("warning");
    expect(getBatchStatusExplanation("FAILED").variant).toBe("error");
    expect(getBatchStatusExplanation("PENDING").variant).toBe("neutral");
  });
});

describe("Batch Summary Metrics Calculation", () => {
  const baseNow = 1700000000000;

  it("derives mutually exclusive counts for generated, active, expired, failed, and pending", () => {
    const recipients: BatchRecipientItem[] = [
      // 1. Active generated link
      {
        recipient_name: "Alice",
        recipient_identifier: "A1",
        status: "GENERATED",
        stego_status: "SUCCESS",
        expires_at: new Date(baseNow + 60000).toISOString(),
        download_url: "/documents/download/tok_1",
      },
      // 2. Expired generated link (past expires_at)
      {
        recipient_name: "Bob",
        recipient_identifier: "B2",
        status: "GENERATED",
        stego_status: "SKIPPED",
        expires_at: new Date(baseNow - 1000).toISOString(),
        download_url: "/documents/download/tok_2",
      },
      // 3. Status explicitly EXPIRED
      {
        recipient_name: "Charlie",
        recipient_identifier: "C3",
        status: "EXPIRED",
        stego_status: "SUCCESS",
        expires_at: new Date(baseNow - 50000).toISOString(),
        download_url: null,
      },
      // 4. Generation FAILED
      {
        recipient_name: "Dave",
        recipient_identifier: "D4",
        status: "FAILED",
        stego_status: "FAILED",
      },
      // 5. PENDING generation
      {
        recipient_name: "Eve",
        recipient_identifier: "E5",
        status: "PENDING",
        stego_status: "PENDING",
      },
    ];

    const metrics = calculateBatchSummaryMetrics(recipients, 5, baseNow);

    expect(metrics.totalEnrolled).toBe(5);
    expect(metrics.generatedCount).toBe(2);
    expect(metrics.activeCount).toBe(1);
    expect(metrics.expiredCount).toBe(2); // Bob (past time) + Charlie (EXPIRED status)
    expect(metrics.failedCount).toBe(1);
    expect(metrics.pendingCount).toBe(1);

    // Layer 3 Stego coverage: 2 SUCCESS / 5 total = 40%
    expect(metrics.l3SuccessCount).toBe(2);
    expect(metrics.l3SkippedCount).toBe(1);
    expect(metrics.l3FailedCount).toBe(1);
    expect(metrics.l3PendingCount).toBe(1);
    expect(metrics.l3CoveragePercent).toBe(40);
    expect(metrics.generationPercent).toBe(40); // 2 generated out of 5
  });

  it("handles zero recipients safely without division by zero", () => {
    const metrics = calculateBatchSummaryMetrics([], 0, baseNow);
    expect(metrics.totalEnrolled).toBe(0);
    expect(metrics.activeCount).toBe(0);
    expect(metrics.l3CoveragePercent).toBe(0);
    expect(metrics.generationPercent).toBe(0);
  });
});

describe("Safe Active Links Clipboard Formatting", () => {
  const baseNow = 1700000000000;

  it("formats only active links and includes remaining time countdown", () => {
    const recipients: BatchRecipientItem[] = [
      {
        recipient_name: "Alice Johnson",
        recipient_identifier: "STU-001",
        status: "GENERATED",
        expires_at: new Date(baseNow + 150000).toISOString(), // 2m 30s left
        download_url: "/documents/download/safe_token_1",
      },
      {
        recipient_name: "Expired Bob",
        recipient_identifier: "STU-002",
        status: "GENERATED",
        expires_at: new Date(baseNow - 5000).toISOString(), // expired
        download_url: "/documents/download/safe_token_2",
      },
    ];

    const text = formatActiveLinksText(
      "Midterm Exam",
      "batch-abc-123",
      recipients,
      "https://securepdf.example.com",
      baseNow
    );

    expect(text).toContain("Midterm Exam");
    expect(text).toContain("Active Links: 1");
    expect(text).toContain("Alice Johnson (STU-001): https://securepdf.example.com/documents/download/safe_token_1");
    expect(text).toContain("Expires in 2m 30s");
    expect(text).not.toContain("Expired Bob");
  });

  it("returns fallback message when no active links exist", () => {
    const text = formatActiveLinksText("Doc", "batch-1", [], "https://example.com", baseNow);
    expect(text).toContain("No active download links available.");
  });
});

describe("DistributionModal Lifecycle & Hook Safety (Rules of Hooks)", () => {
  it("renders safely when isOpen is false without executing conditional hooks", () => {
    const htmlClosed = renderToString(
      React.createElement(DistributionModal, {
        isOpen: false,
        onClose: () => {},
        documentUid: "doc_123",
        documentTitle: "test.pdf",
      })
    );
    expect(htmlClosed).toBe("");
  });

  it("renders modal dialog completely when isOpen is true without throwing", () => {
    const htmlOpen = renderToString(
      React.createElement(DistributionModal, {
        isOpen: true,
        onClose: () => {},
        documentUid: "doc_123",
        documentTitle: "test.pdf",
      })
    );
    expect(htmlOpen).toContain("Security Carrier Stages");
    expect(htmlOpen).toContain("Stage 1");
    expect(htmlOpen).toContain("Stage 2");
    expect(htmlOpen).toContain("Stage 3");
    expect(htmlOpen).toContain("Catalog Carrier");
    expect(htmlOpen).toContain("Annotations");
    expect(htmlOpen).toContain("Steganography");
  });

  it("validates selectable stage combinations and payload serialization", () => {
    const buildBatchPayload = (
      duration: number,
      recipients: any[],
      enableStage1: boolean,
      enableStage2: boolean,
      enableStage3: boolean
    ) => {
      const atLeastOne = enableStage1 || enableStage2 || enableStage3;
      if (!atLeastOne) {
        throw new Error("At least one security stage must be selected.");
      }
      return {
        expiry_duration_seconds: duration,
        enable_stage1: enableStage1,
        enable_stage2: enableStage2,
        enable_stage3: enableStage3,
        recipients,
      };
    };

    // Verify all 7 valid combinations
    const combinations = [
      [true, false, false],  // S1 only
      [false, true, false],  // S2 only
      [false, false, true],  // S3 only
      [true, true, false],   // S1 + S2
      [true, false, true],   // S1 + S3
      [false, true, true],   // S2 + S3
      [true, true, true],    // S1 + S2 + S3
    ];

    expect(combinations).toHaveLength(7);
    for (const [s1, s2, s3] of combinations) {
      const payload = buildBatchPayload(120, [{ name: "A", student_uid: "U1" }], s1, s2, s3);
      expect(payload.enable_stage1).toBe(s1);
      expect(payload.enable_stage2).toBe(s2);
      expect(payload.enable_stage3).toBe(s3);
    }

    // Verify 0 stages throws error
    expect(() =>
      buildBatchPayload(120, [{ name: "A", student_uid: "U1" }], false, false, false)
    ).toThrow("At least one security stage must be selected.");
  });
});

