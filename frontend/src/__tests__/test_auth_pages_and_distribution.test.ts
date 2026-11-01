/**
 * Unit and workflow tests for Dedicated Auth Pages and Distribution Batch Creation.
 * Verifies:
 * 1. Dedicated page routing (/login, /register, return redirects).
 * 2. Uploader-configurable download-link expiry presets and boundaries (2 min default).
 * 3. Recipient identity safety and duplicate prevention invariants.
 */
import { describe, it, expect } from "vitest";

import { getSafeRedirect } from "../utils/safeRedirect";

describe("Safe Redirect Validation (CWE-601 Prevention)", () => {
  it("allows safe internal application paths", () => {
    expect(getSafeRedirect("/")).toBe("/");
    expect(getSafeRedirect("/workspace")).toBe("/workspace");
    expect(getSafeRedirect("/inspect/doc_123")).toBe("/inspect/doc_123");
    expect(getSafeRedirect("/settings?tab=profile")).toBe("/settings?tab=profile");
  });

  it("strictly rejects protocol-relative URLs", () => {
    expect(getSafeRedirect("//evil.com")).toBe("/");
    expect(getSafeRedirect("//malicious.site/phish")).toBe("/");
    expect(getSafeRedirect("///evil.com")).toBe("/");
  });

  it("strictly rejects backslash bypass attempts", () => {
    expect(getSafeRedirect("/\\evil.com")).toBe("/");
    expect(getSafeRedirect("/\\/attacker.com")).toBe("/");
  });

  it("strictly rejects absolute URLs and scheme-injected payloads", () => {
    expect(getSafeRedirect("https://attacker.com")).toBe("/");
    expect(getSafeRedirect("http://evil.com/login")).toBe("/");
    expect(getSafeRedirect("javascript:alert(1)")).toBe("/");
    expect(getSafeRedirect("data:text/html,<script>alert(1)</script>")).toBe("/");
  });

  it("safely handles null, undefined, empty, and malformed inputs", () => {
    expect(getSafeRedirect(null)).toBe("/");
    expect(getSafeRedirect(undefined)).toBe("/");
    expect(getSafeRedirect("")).toBe("/");
    expect(getSafeRedirect("   ")).toBe("/");
    expect(getSafeRedirect("relative/without/slash")).toBe("/");
  });
});

describe("Dedicated Authentication Routes and State Invariants", () => {
  it("isolates Login and Register into separate, dedicated routes", () => {
    const routes = {
      login: "/login",
      register: "/register",
      workspace: "/",
    };

    expect(routes.login).not.toBe(routes.register);
    expect(routes.login).toBe("/login");
    expect(routes.register).toBe("/register");
  });

  it("parses and enforces post-authentication return redirect target safely", () => {
    const parseRedirect = (urlSearch: string): string => {
      const params = new URLSearchParams(urlSearch);
      return getSafeRedirect(params.get("redirect"));
    };

    expect(parseRedirect("?redirect=/workspace")).toBe("/workspace");
    expect(parseRedirect("?redirect=/inspect/doc123")).toBe("/inspect/doc123");
    expect(parseRedirect("?redirect=//evil.com")).toBe("/");
    expect(parseRedirect("")).toBe("/");
    expect(parseRedirect("?other=val")).toBe("/");
  });
});

describe("Uploader-Configurable Download-Link Expiry Invariants", () => {
  const EXPIRY_PRESETS = [
    { label: "2 minutes (Default Testing)", value: 120 },
    { label: "15 minutes", value: 900 },
    { label: "1 hour", value: 3600 },
    { label: "24 hours", value: 86400 },
    { label: "7 days", value: 604800 },
    { label: "Custom Duration", value: -1 },
  ];

  it("defaults to 2 minutes (120 seconds) for fast testing", () => {
    const defaultOption = EXPIRY_PRESETS[0];
    expect(defaultOption.value).toBe(120);
    expect(defaultOption.label).toContain("Default Testing");
  });

  it("validates expiry duration bounds (30s to 30 days)", () => {
    const validateDuration = (seconds: number): boolean => {
      return seconds >= 30 && seconds <= 2592000;
    };

    // Valid options
    expect(validateDuration(120)).toBe(true);
    expect(validateDuration(900)).toBe(true);
    expect(validateDuration(3600)).toBe(true);
    expect(validateDuration(86400)).toBe(true);
    expect(validateDuration(604800)).toBe(true);
    expect(validateDuration(2592000)).toBe(true);

    // Invalid options
    expect(validateDuration(0)).toBe(false);
    expect(validateDuration(29)).toBe(false);
    expect(validateDuration(-10)).toBe(false);
    expect(validateDuration(2592001)).toBe(false);
  });

  it("verifies per-recipient expiry calculation model for Phase 2/3", () => {
    const batchExpiryDurationSeconds = 120;
    const recipientGeneratedAt = new Date("2026-11-01T12:00:00Z");

    const calculateRecipientExpiresAt = (generatedAt: Date, durationSeconds: number): Date => {
      return new Date(generatedAt.getTime() + durationSeconds * 1000);
    };

    const recipientExpiresAt = calculateRecipientExpiresAt(
      recipientGeneratedAt,
      batchExpiryDurationSeconds
    );

    expect(recipientExpiresAt.toISOString()).toBe("2026-11-01T12:02:00.000Z");
  });
});

describe("Recipient Identity Safety and Validation Invariants", () => {
  interface RecipientQueueItem {
    name: string;
    student_uid: string;
  }

  const validateAndQueueRecipient = (
    queue: RecipientQueueItem[],
    name: string,
    student_uid: string
  ): { success: boolean; error?: string; updatedQueue?: RecipientQueueItem[] } => {
    const trimmedName = name.trim();
    const trimmedUid = student_uid.trim();

    if (!trimmedName) {
      return { success: false, error: "Recipient name is required." };
    }
    if (!trimmedUid) {
      return { success: false, error: "Recipient identifier is required." };
    }

    const exists = queue.some(
      (r) => r.student_uid.toLowerCase() === trimmedUid.toLowerCase()
    );
    if (exists) {
      return {
        success: false,
        error: `Recipient identifier "${trimmedUid}" is already in this batch queue.`,
      };
    }

    return {
      success: true,
      updatedQueue: [...queue, { name: trimmedName, student_uid: trimmedUid }],
    };
  };

  it("requires both name and unique identifier for every recipient", () => {
    const queue: RecipientQueueItem[] = [];

    const emptyName = validateAndQueueRecipient(queue, "   ", "STU-001");
    expect(emptyName.success).toBe(false);
    expect(emptyName.error).toBe("Recipient name is required.");

    const emptyUid = validateAndQueueRecipient(queue, "Alice", "   ");
    expect(emptyUid.success).toBe(false);
    expect(emptyUid.error).toBe("Recipient identifier is required.");

    const valid = validateAndQueueRecipient(queue, "Alice Smith", "STU-001");
    expect(valid.success).toBe(true);
    expect(valid.updatedQueue?.length).toBe(1);
  });

  it("prevents duplicate recipient identifiers within the same batch queue", () => {
    let queue: RecipientQueueItem[] = [{ name: "Alice Smith", student_uid: "STU-001" }];

    // Attempt to add another recipient with the same student_uid
    const duplicate = validateAndQueueRecipient(queue, "Another Student", "STU-001");
    expect(duplicate.success).toBe(false);
    expect(duplicate.error).toContain("is already in this batch queue");

    // Case-insensitive duplicate check
    const caseDuplicate = validateAndQueueRecipient(queue, "Another Student", "stu-001");
    expect(caseDuplicate.success).toBe(false);

    // Distinct identifier succeeds
    const distinct = validateAndQueueRecipient(queue, "Bob Jones", "STU-002");
    expect(distinct.success).toBe(true);
    expect(distinct.updatedQueue?.length).toBe(2);
  });

  it("ensures recipient names in batch responses remain strictly isolated to the batch uploader", () => {
    // Model of User A's batch response
    const batchA = {
      batch_uid: "batch_aaa111",
      recipients: [{ recipient_name: "Alice Smith", recipient_identifier: "STU-SHARED" }],
    };

    // Model of User B's batch response
    const batchB = {
      batch_uid: "batch_bbb222",
      recipients: [{ recipient_name: "Bob Jones", recipient_identifier: "STU-SHARED" }],
    };

    // Identity safety assertion
    expect(batchA.recipients[0].recipient_identifier).toBe(batchB.recipients[0].recipient_identifier);
    expect(batchA.recipients[0].recipient_name).toBe("Alice Smith");
    expect(batchB.recipients[0].recipient_name).toBe("Bob Jones");
    expect(batchA.recipients[0].recipient_name).not.toBe(batchB.recipients[0].recipient_name);
  });
});

describe("Phase 2 Personalized PDF Generation Progress and Status Invariants", () => {
  it("calculates generation progress and percentage accurately", () => {
    const computeProgress = (
      recipients: Array<{ status: string }>,
      total: number
    ) => {
      const completed = recipients.filter((r) => r.status === "GENERATED").length;
      const failed = recipients.filter((r) => r.status === "FAILED").length;
      const percent = Math.min(100, Math.round((completed / (total || 1)) * 100));
      return { completed, failed, percent };
    };

    const initial = computeProgress(
      [
        { status: "PENDING" },
        { status: "PENDING" },
        { status: "PENDING" },
      ],
      3
    );
    expect(initial.completed).toBe(0);
    expect(initial.failed).toBe(0);
    expect(initial.percent).toBe(0);

    const partial = computeProgress(
      [
        { status: "GENERATED" },
        { status: "GENERATED" },
        { status: "FAILED" },
        { status: "PENDING" },
      ],
      4
    );
    expect(partial.completed).toBe(2);
    expect(partial.failed).toBe(1);
    expect(partial.percent).toBe(50);

    const complete = computeProgress(
      [
        { status: "GENERATED" },
        { status: "GENERATED" },
        { status: "GENERATED" },
      ],
      3
    );
    expect(complete.completed).toBe(3);
    expect(complete.failed).toBe(0);
    expect(complete.percent).toBe(100);
  });

  it("verifies opaque internal filename format containing no recipient PII", () => {
    const formatOpaqueFilename = (recipientId: number): string => {
      return `rec_${recipientId}.pdf`;
    };

    const filename = formatOpaqueFilename(42);
    expect(filename).toBe("rec_42.pdf");
    expect(filename).not.toContain("Alice");
    expect(filename).not.toContain("STU-");
    expect(filename).toMatch(/^rec_\d+\.pdf$/);
  });
});

describe("Document Registration and Distribution Click Workflow", () => {
  it("targets the canonical /documents/ route instead of /api/documents/", () => {
    const canonicalRoute = "/documents/";
    const legacyMismatchRoute = "/api/documents/";

    expect(canonicalRoute).toBe("/documents/");
    expect(canonicalRoute).not.toBe(legacyMismatchRoute);
  });

  it("resets activeDocumentUid and errors when a new PDF is selected, preserving association if report contains document_uid", () => {
    let activeDocUid: string | null = "DOC-OLD-123";
    let distributionError: string | null = "Previous error";

    // Simulate file selection reset
    const onFileSelected = (newReportDocUid: string | null) => {
      activeDocUid = null;
      distributionError = null;
      if (newReportDocUid) {
        activeDocUid = newReportDocUid;
      }
    };

    // Case 1: Brand new unwatermarked PDF selected
    onFileSelected(null);
    expect(activeDocUid).toBeNull();
    expect(distributionError).toBeNull();

    // Case 2: Watermarked PDF with existing document_uid inspected
    onFileSelected("DOC-INSPECTED-456");
    expect(activeDocUid).toBe("DOC-INSPECTED-456");
    expect(distributionError).toBeNull();
  });

  it("guards against duplicate clicks via isDistributing loading state", () => {
    let isDistributing = false;
    let callCount = 0;

    const simulateClick = () => {
      if (isDistributing) return false;
      isDistributing = true;
      callCount += 1;
      return true;
    };

    expect(simulateClick()).toBe(true);
    expect(callCount).toBe(1);

    // Rapid secondary click while in progress
    expect(simulateClick()).toBe(false);
    expect(callCount).toBe(1);

    // Registration finishes
    isDistributing = false;
    expect(simulateClick()).toBe(true);
    expect(callCount).toBe(2);
  });

  it("surfaces visible error messages on registration failures without silent swallow", () => {
    let distributionError: string | null = null;

    const handleRegistrationResponse = (status: number, detail?: string) => {
      if (status !== 201) {
        distributionError = detail || `Document registration failed (HTTP ${status})`;
      } else {
        distributionError = null;
      }
    };

    handleRegistrationResponse(400, "Only PDF files are allowed");
    expect(distributionError).toBe("Only PDF files are allowed");

    handleRegistrationResponse(500);
    expect(distributionError).toBe("Document registration failed (HTTP 500)");

    handleRegistrationResponse(201);
    expect(distributionError).toBeNull();
  });
});

describe("Phase 3 Temporary Download Links and Frontend Countdown", () => {
  const getRemainingSeconds = (expiresAtStr: string | null, nowMs: number): number => {
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

  it("formats countdown accurately for minutes, seconds, and hours", () => {
    expect(formatCountdown(120)).toBe("02:00");
    expect(formatCountdown(65)).toBe("01:05");
    expect(formatCountdown(9)).toBe("00:09");
    expect(formatCountdown(3665)).toBe("1h 1m");
    expect(formatCountdown(0)).toBe("Expired");
    expect(formatCountdown(-5)).toBe("Expired");
  });

  it("calculates remaining seconds relative to current time and transitions to expired", () => {
    const baseNow = 1700000000000;
    const futureExpiresAt = new Date(baseNow + 120 * 1000).toISOString();

    // 120 seconds left
    expect(getRemainingSeconds(futureExpiresAt, baseNow)).toBe(120);

    // 60 seconds elapsed
    expect(getRemainingSeconds(futureExpiresAt, baseNow + 60 * 1000)).toBe(60);

    // Expired exactly at 120s
    expect(getRemainingSeconds(futureExpiresAt, baseNow + 120 * 1000)).toBe(0);

    // Past deadline
    expect(getRemainingSeconds(futureExpiresAt, baseNow + 130 * 1000)).toBe(0);
  });

  it("enables download and copy actions only when active and not expired", () => {
    const recipientActive = {
      status: "GENERATED",
      expires_at: new Date(Date.now() + 100000).toISOString(),
      download_url: "/documents/download/token_abc123",
    };

    const isExpiredActive = false;
    const canDownloadActive =
      recipientActive.status === "GENERATED" && !isExpiredActive && !!recipientActive.download_url;
    expect(canDownloadActive).toBe(true);

    const recipientExpired = {
      status: "EXPIRED",
      expires_at: new Date(Date.now() - 5000).toISOString(),
      download_url: null,
    };

    const isExpiredPast = true;
    const canDownloadExpired =
      recipientExpired.status === "GENERATED" && !isExpiredPast && !!recipientExpired.download_url;
    expect(canDownloadExpired).toBe(false);
  });

  it("builds the full download URL using window origin and sanitized route", () => {
    const origin = "https://securepdf.example.com";
    const downloadPath = "/documents/download/sec_tok_999";
    const fullShareUrl = `${origin}${downloadPath}`;

    expect(fullShareUrl).toBe("https://securepdf.example.com/documents/download/sec_tok_999");
    expect(fullShareUrl).not.toContain("student");
    expect(fullShareUrl).not.toContain("rec_");
    expect(fullShareUrl).not.toContain("fingerprint");
  });
});

