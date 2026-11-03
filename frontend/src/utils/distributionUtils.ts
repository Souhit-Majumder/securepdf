/**
 * SecurePDF Distribution Workflow Utilities (Phase 2)
 *
 * Implements client-side CSV/TSV parsing, flexible header detection,
 * duplicate detection, plain-language status explanations, batch summary calculations,
 * and secure link formatting/export without modifying backend APIs or leaking tokens.
 */

export interface RecipientInput {
  name: string;
  student_uid: string;
}

export interface ParsedRecipientRow {
  name: string;
  student_uid: string;
  originalRowNumber: number;
  status:
    | "VALID"
    | "DUPLICATE_INTERNAL"
    | "DUPLICATE_QUEUE"
    | "INVALID_NAME"
    | "INVALID_UID"
    | "TOO_LONG";
  errorMessage?: string;
}

export interface CsvParseResult {
  validRows: RecipientInput[];
  allRows: ParsedRecipientRow[];
  totalCount: number;
  validCount: number;
  duplicateCount: number;
  invalidCount: number;
  detectedDelimiter: string;
  hasHeaders: boolean;
}

export interface BatchRecipientItem {
  recipient_name: string;
  recipient_identifier: string;
  status: string;
  stego_status?: "PENDING" | "SKIPPED" | "SUCCESS" | "FAILED";
  generated_at?: string | null;
  expires_at?: string | null;
  download_url?: string | null;
  created_at?: string;
}

export interface BatchSummaryMetrics {
  totalEnrolled: number;
  generatedCount: number;
  activeCount: number;
  expiredCount: number;
  failedCount: number;
  pendingCount: number;
  l3SuccessCount: number;
  l3SkippedCount: number;
  l3FailedCount: number;
  l3PendingCount: number;
  l3CoveragePercent: number;
  generationPercent: number;
}

/**
 * Normalizes text content by stripping quotes and extra whitespace.
 */
function cleanField(raw: string): string {
  if (!raw) return "";
  let trimmed = raw.trim();
  // Strip surrounding double or single quotes if present
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    trimmed = trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

/**
 * Detects the delimiter used in tabular text (comma, tab, semicolon, pipe).
 */
export function detectDelimiter(text: string): string {
  const firstLines = text.split(/\r?\n/).slice(0, 5).filter((l) => l.trim().length > 0);
  if (firstLines.length === 0) return ",";

  const sample = firstLines.join("\n");
  const tabCount = (sample.match(/\t/g) || []).length;
  const commaCount = (sample.match(/,/g) || []).length;
  const semicolonCount = (sample.match(/;/g) || []).length;
  const pipeCount = (sample.match(/\|/g) || []).length;

  if (tabCount > commaCount && tabCount >= semicolonCount) return "\t";
  if (semicolonCount > commaCount && semicolonCount > tabCount) return ";";
  if (pipeCount > commaCount && pipeCount > tabCount) return "|";
  return ",";
}

/**
 * Robust CSV/TSV line splitter that respects quoted fields.
 */
function splitDelimitedLine(line: string, delimiter: string): string[] {
  const result: string[] = [];
  let current = "";
  let inQuotes = false;
  let quoteChar = "";

  for (let i = 0; i < line.length; i++) {
    const char = line[i];

    if (!inQuotes && (char === '"' || char === "'")) {
      inQuotes = true;
      quoteChar = char;
    } else if (inQuotes && char === quoteChar) {
      if (i + 1 < line.length && line[i + 1] === quoteChar) {
        // Escaped quote
        current += quoteChar;
        i++;
      } else {
        inQuotes = false;
        quoteChar = "";
      }
    } else if (!inQuotes && char === delimiter) {
      result.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  result.push(current);
  return result;
}

/**
 * Determines if a row represents header labels and maps column indices.
 */
function detectHeaders(
  firstRowCells: string[]
): { hasHeaders: boolean; nameIndex: number; uidIndex: number } {
  const normalized = firstRowCells.map((c) => cleanField(c).toLowerCase().replace(/[\s_-]+/g, ""));

  const nameKeywords = [
    "name",
    "fullname",
    "studentname",
    "recipient",
    "recipientname",
    "student",
    "person",
    "user",
  ];

  const uidKeywords = [
    "uid",
    "id",
    "studentuid",
    "studentid",
    "identifier",
    "recipientid",
    "matriculation",
    "rollno",
    "rollnumber",
    "email",
    "code",
  ];

  let nameIndex = -1;
  let uidIndex = -1;

  for (let i = 0; i < normalized.length; i++) {
    const cell = normalized[i];
    if (nameIndex === -1 && nameKeywords.includes(cell)) {
      nameIndex = i;
    } else if (uidIndex === -1 && uidKeywords.includes(cell)) {
      uidIndex = i;
    }
  }

  // If both were matched distinctively, we have confident headers
  if (nameIndex !== -1 && uidIndex !== -1 && nameIndex !== uidIndex) {
    return { hasHeaders: true, nameIndex, uidIndex };
  }

  // If one was matched and the other is obvious in a 2-column format
  if (firstRowCells.length === 2) {
    if (nameIndex === 0 && uidIndex === -1) {
      return { hasHeaders: true, nameIndex: 0, uidIndex: 1 };
    }
    if (nameIndex === 1 && uidIndex === -1) {
      return { hasHeaders: true, nameIndex: 1, uidIndex: 0 };
    }
    if (uidIndex === 1 && nameIndex === -1) {
      return { hasHeaders: true, nameIndex: 0, uidIndex: 1 };
    }
    if (uidIndex === 0 && nameIndex === -1) {
      return { hasHeaders: true, nameIndex: 1, uidIndex: 0 };
    }
  }

  // Default fallback: Column 0 = Name, Column 1 = UID, row is NOT a header
  return { hasHeaders: false, nameIndex: 0, uidIndex: 1 };
}

/**
 * Parses raw CSV/TSV text, validates rows against constraints,
 * and performs duplicate detection within the file and against existing queue.
 */
export function parseAndValidateRecipients(
  rawText: string,
  existingQueue: RecipientInput[] = []
): CsvParseResult {
  const trimmed = rawText.trim();
  if (!trimmed) {
    return {
      validRows: [],
      allRows: [],
      totalCount: 0,
      validCount: 0,
      duplicateCount: 0,
      invalidCount: 0,
      detectedDelimiter: ",",
      hasHeaders: false,
    };
  }

  const delimiter = detectDelimiter(trimmed);
  const lines = trimmed.split(/\r?\n/).filter((l) => l.trim().length > 0);

  if (lines.length === 0) {
    return {
      validRows: [],
      allRows: [],
      totalCount: 0,
      validCount: 0,
      duplicateCount: 0,
      invalidCount: 0,
      detectedDelimiter: delimiter,
      hasHeaders: false,
    };
  }

  const firstLineCells = splitDelimitedLine(lines[0], delimiter);
  const { hasHeaders, nameIndex, uidIndex } = detectHeaders(firstLineCells);

  const startLineIdx = hasHeaders ? 1 : 0;
  const existingQueueUids = new Set(existingQueue.map((r) => r.student_uid.toLowerCase().trim()));
  const seenFileUids = new Set<string>();

  const allRows: ParsedRecipientRow[] = [];
  const validRows: RecipientInput[] = [];

  for (let i = startLineIdx; i < lines.length; i++) {
    const rawLine = lines[i];
    const cells = splitDelimitedLine(rawLine, delimiter);

    const name = cleanField(cells[nameIndex] || "");
    const student_uid = cleanField(cells[uidIndex] || "");
    const rowNum = i + 1;

    // Check empty fields
    if (!name) {
      allRows.push({
        name,
        student_uid,
        originalRowNumber: rowNum,
        status: "INVALID_NAME",
        errorMessage: "Recipient name is missing or empty.",
      });
      continue;
    }

    if (!student_uid) {
      allRows.push({
        name,
        student_uid,
        originalRowNumber: rowNum,
        status: "INVALID_UID",
        errorMessage: "Recipient identifier (UID) is missing or empty.",
      });
      continue;
    }

    // Check length limits (backend imposes max 255 chars)
    if (name.length > 255 || student_uid.length > 255) {
      allRows.push({
        name,
        student_uid,
        originalRowNumber: rowNum,
        status: "TOO_LONG",
        errorMessage: "Name or identifier exceeds maximum length limit of 255 characters.",
      });
      continue;
    }

    const lowerUid = student_uid.toLowerCase();

    // Check duplicate within the imported file itself
    if (seenFileUids.has(lowerUid)) {
      allRows.push({
        name,
        student_uid,
        originalRowNumber: rowNum,
        status: "DUPLICATE_INTERNAL",
        errorMessage: `Identifier "${student_uid}" appears multiple times in this import file.`,
      });
      continue;
    }

    // Check duplicate against existing queue
    if (existingQueueUids.has(lowerUid)) {
      allRows.push({
        name,
        student_uid,
        originalRowNumber: rowNum,
        status: "DUPLICATE_QUEUE",
        errorMessage: `Identifier "${student_uid}" is already queued in this distribution batch.`,
      });
      continue;
    }

    // Mark seen and record valid row
    seenFileUids.add(lowerUid);
    validRows.push({ name, student_uid });
    allRows.push({
      name,
      student_uid,
      originalRowNumber: rowNum,
      status: "VALID",
    });
  }

  const validCount = validRows.length;
  const duplicateCount = allRows.filter(
    (r) => r.status === "DUPLICATE_INTERNAL" || r.status === "DUPLICATE_QUEUE"
  ).length;
  const invalidCount = allRows.filter(
    (r) => r.status === "INVALID_NAME" || r.status === "INVALID_UID" || r.status === "TOO_LONG"
  ).length;

  return {
    validRows,
    allRows,
    totalCount: allRows.length,
    validCount,
    duplicateCount,
    invalidCount,
    detectedDelimiter: delimiter,
    hasHeaders,
  };
}

/**
 * Plain-Language Layer 3 Steganography Status Explanations.
 * Strictly adheres to verified backend response schema.
 */
export function getStegoStatusExplanation(
  status?: string | null,
  enableStego: boolean = false
): {
  label: string;
  title: string;
  description: string;
  variant: "success" | "warning" | "error" | "info" | "neutral";
} {
  const norm = (status || "").toUpperCase();

  switch (norm) {
    case "SUCCESS":
      return {
        label: "L3 Verified",
        title: "Layer 3 Active & Cryptographically Verified",
        description:
          "Imperceptible kerning modulation was embedded into text streams and independently authenticated with HMAC-SHA256.",
        variant: "success",
      };
    case "SKIPPED":
      return {
        label: "L3 Bypassed",
        title: "Layer 3 Steganography Bypassed",
        description: enableStego
          ? "Bypassed due to insufficient text carrier capacity in this PDF. Visible watermarks and annotation carriers remain fully functional."
          : "Layer 3 steganography was not opted in for this batch. Visible watermarks and annotation carriers remain fully functional.",
        variant: "neutral",
      };
    case "PARTIAL":
      return {
        label: "L3 Partial",
        title: "Layer 3 Carrier Coverage Partial",
        description:
          "Some recipient documents received verified Layer 3 carriers while others were bypassed due to document capacity constraints.",
        variant: "warning",
      };
    case "FAILED":
      return {
        label: "L3 Failed",
        title: "Carrier Embedding or Verification Failed",
        description:
          "Layer 3 carrier modulation or post-serialization output verification failed for this recipient.",
        variant: "error",
      };
    case "PENDING":
    default:
      return {
        label: "L3 Queued",
        title: "Layer 3 Awaiting Generation",
        description:
          "Steganographic carrier embedding has not yet been processed for this recipient.",
        variant: "info",
      };
  }
}

/**
 * Plain-Language Overall Batch Status Explanations.
 */
export function getBatchStatusExplanation(status: string): {
  title: string;
  subtitle: string;
  variant: "success" | "warning" | "error" | "info" | "neutral";
} {
  switch (status) {
    case "COMPLETED":
      return {
        title: "Personalized Documents Ready",
        subtitle:
          "All recipient watermarked PDFs have been successfully generated and verified on the server.",
        variant: "success",
      };
    case "PROCESSING":
      return {
        title: "Generating Watermarked PDFs...",
        subtitle:
          "Personalizing documents sequentially with unique cryptographic nonces and carriers.",
        variant: "info",
      };
    case "PARTIALLY_FAILED":
      return {
        title: "Generation Partially Completed",
        subtitle:
          "Some recipient documents completed successfully while others encountered errors. Failed items can be retried.",
        variant: "warning",
      };
    case "FAILED":
      return {
        title: "Batch Generation Failed",
        subtitle:
          "Personalized PDF generation encountered an error. You can retry the batch without losing recipient configurations.",
        variant: "error",
      };
    case "PENDING":
    default:
      return {
        title: "Batch Registered Successfully",
        subtitle:
          "Recipient identities and expiration policies are locked. Click below to begin personalized PDF generation.",
        variant: "neutral",
      };
  }
}

/**
 * Computes exact, non-double-counted batch summary metrics from existing recipient data.
 */
export function calculateBatchSummaryMetrics(
  recipients: BatchRecipientItem[] = [],
  totalRecipients: number = 0,
  nowMs: number = Date.now()
): BatchSummaryMetrics {
  const totalEnrolled = Math.max(recipients.length, totalRecipients);

  let generatedCount = 0;
  let activeCount = 0;
  let expiredCount = 0;
  let failedCount = 0;
  let pendingCount = 0;

  let l3SuccessCount = 0;
  let l3SkippedCount = 0;
  let l3FailedCount = 0;
  let l3PendingCount = 0;

  for (const r of recipients) {
    // Check expiry
    let isExpired = false;
    if (r.status === "EXPIRED") {
      isExpired = true;
    } else if (r.expires_at) {
      const expTime = new Date(r.expires_at).getTime();
      if (expTime <= nowMs) {
        isExpired = true;
      }
    }

    if (r.status === "GENERATED") {
      generatedCount++;
      if (!isExpired && r.download_url) {
        activeCount++;
      } else {
        expiredCount++;
      }
    } else if (r.status === "FAILED") {
      failedCount++;
    } else if (r.status === "EXPIRED") {
      expiredCount++;
    } else {
      pendingCount++;
    }

    // Layer 3 Stego breakdown
    const stego = (r.stego_status || "PENDING").toUpperCase();
    if (stego === "SUCCESS") l3SuccessCount++;
    else if (stego === "SKIPPED") l3SkippedCount++;
    else if (stego === "FAILED") l3FailedCount++;
    else l3PendingCount++;
  }

  const l3CoveragePercent =
    totalEnrolled > 0 ? Math.round((l3SuccessCount / totalEnrolled) * 100) : 0;
  const generationPercent =
    totalEnrolled > 0 ? Math.round((generatedCount / totalEnrolled) * 100) : 0;

  return {
    totalEnrolled,
    generatedCount,
    activeCount,
    expiredCount,
    failedCount,
    pendingCount,
    l3SuccessCount,
    l3SkippedCount,
    l3FailedCount,
    l3PendingCount,
    l3CoveragePercent,
    generationPercent,
  };
}

/**
 * Formats all generated recipient download links into a clean plain-text summary for clipboard copying.
 * Does not expose raw database tokens or private server paths.
 */
export function formatActiveLinksText(
  documentTitle: string,
  batchUid: string,
  recipients: BatchRecipientItem[],
  originUrl: string = "",
  nowMs: number = Date.now()
): string {
  const activeItems = recipients.filter((r) => {
    if (r.status !== "GENERATED" || !r.download_url) return false;
    if (!r.expires_at) return true;
    const expTime = new Date(r.expires_at).getTime();
    return expTime > nowMs;
  });

  if (activeItems.length === 0) {
    return `SecurePDF Distribution: ${documentTitle}\nBatch UID: ${batchUid}\nNo active download links available.`;
  }

  const lines: string[] = [
    `SecurePDF Personalized Distribution Links`,
    `Document: ${documentTitle}`,
    `Batch UID: ${batchUid}`,
    `Active Links: ${activeItems.length}`,
    `Generated: ${new Date(nowMs).toUTCString()}`,
    `--------------------------------------------------`,
  ];

  for (const item of activeItems) {
    const fullUrl = originUrl
      ? `${originUrl.replace(/\/$/, "")}${item.download_url}`
      : item.download_url!;

    let remainingStr = "Active";
    if (item.expires_at) {
      const sec = Math.max(0, Math.floor((new Date(item.expires_at).getTime() - nowMs) / 1000));
      const m = Math.floor(sec / 60);
      const s = sec % 60;
      remainingStr = `Expires in ${m}m ${s}s`;
    }

    lines.push(`${item.recipient_name} (${item.recipient_identifier}): ${fullUrl} [${remainingStr}]`);
  }

  return lines.join("\n");
}

/**
 * Generates and triggers browser download of a CSV file containing all recipient distribution records.
 */
export function exportBatchRecipientsCsv(
  documentTitle: string,
  batchUid: string,
  recipients: BatchRecipientItem[],
  originUrl: string = "",
  nowMs: number = Date.now()
): void {
  const csvHeaders = [
    "Recipient Name",
    "Recipient Identifier",
    "PDF Status",
    "Layer 3 Steganography",
    "Generated At (UTC)",
    "Expires At (UTC)",
    "Validity Status",
    "Download URL",
  ];

  const escapeCsv = (val: string | null | undefined): string => {
    if (val === null || val === undefined) return '""';
    const clean = String(val).replace(/"/g, '""');
    return `"${clean}"`;
  };

  const rows: string[] = [csvHeaders.join(",")];

  for (const r of recipients) {
    let isExpired = false;
    let validityStatus = "Pending";

    if (r.expires_at) {
      const expTime = new Date(r.expires_at).getTime();
      isExpired = expTime <= nowMs;
    }

    if (r.status === "GENERATED") {
      validityStatus = isExpired ? "Expired" : "Active";
    } else if (r.status === "FAILED") {
      validityStatus = "Generation Failed";
    }

    const fullUrl =
      r.download_url && !isExpired
        ? originUrl
          ? `${originUrl.replace(/\/$/, "")}${r.download_url}`
          : r.download_url
        : "";

    rows.push(
      [
        escapeCsv(r.recipient_name),
        escapeCsv(r.recipient_identifier),
        escapeCsv(r.status),
        escapeCsv(r.stego_status || "PENDING"),
        escapeCsv(r.generated_at),
        escapeCsv(r.expires_at),
        escapeCsv(validityStatus),
        escapeCsv(fullUrl),
      ].join(",")
    );
  }

  const csvContent = "\uFEFF" + rows.join("\r\n"); // UTF-8 BOM for Excel compatibility
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);

  const safeTitle = documentTitle.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 32);
  const safeBatch = batchUid.slice(0, 12);
  const link = document.createElement("a");
  link.setAttribute("href", url);
  link.setAttribute("download", `distribution_${safeTitle}_${safeBatch}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
