# API Security Review (Phase IV Step 3)

## 1. Authentication Boundary & Current State
**Current State:** The API is completely **unauthenticated**. 
Any network client capable of reaching the server can:
*   `POST /documents`: Upload arbitrary PDF files.
*   `POST /students`: Register arbitrary student identities.
*   `POST /documents/{document_uid}/distribute`: Trigger the generation of a personalized PDF.
*   `POST /verify`: Submit a PDF and receive precise attribution details.

**Deferred Controls:** Authentication (e.g., JWT) will be implemented in Phase V. The system must enforce that all the above endpoints are restricted to **Teacher/Administrator** roles only.

## 2. Identified Vulnerabilities & Fixes

### A. Memory Exhaustion via File Upload (High)
*   **Discovery**: The original implementation of `POST /documents` and `POST /verify` read the entire `UploadFile` into memory (`await file.read()`) before checking its size. An attacker could crash the server (Memory DoS) by sending a single massive file (e.g., 2GB).
*   **Fix Implemented**: Switched to a chunked reading approach (`await file.read(1024 * 1024)`). If the accumulated size exceeds 20MB, the stream is aborted, the file is deleted, and a `413 Payload Too Large` error is returned.

### B. Path Traversal in Distribution (Medium)
*   **Discovery**: `POST /documents/{document_uid}/distribute` constructed the output filename directly from user input: `f"{document_uid}_{request.student_uid}.pdf"`. If an attacker registered a `student_uid` containing `../../../`, the output file could overwrite system files or escape the output directory.
*   **Fix Implemented**: Explicitly sanitized `document_uid` and `student_uid` by replacing `/` and `\` with `_` before constructing the output path.

### C. Extension Spoofing (Low)
*   **Discovery**: The upload endpoints validated PDFs solely by checking `filename.endswith(".pdf")`. An attacker could rename a malicious executable to `.pdf` and upload it.
*   **Fix Implemented**: The API now reads the first 4 bytes of the uploaded file to strictly verify the `%PDF` header magic bytes, discarding any mismatched files.

### D. Attribution Disclosure Oracle (Informational / Deferred)
*   **Discovery**: The `POST /verify` endpoint acts as an oracle. An attacker can repeatedly upload PDFs to confirm if a specific student leaked a file, or to enumerate valid fingerprints.
*   **Fix Implemented**: None at this layer. This is an inherent property of the verification API and will be secured by restricting `/verify` to authenticated Teachers only in the next phase.

### E. SQL Injection (Informational)
*   **Discovery**: Tested inputs like `' OR 1=1 --`.
*   **Result**: Safely mitigated by the underlying `sqlite3` parameterized queries in the frozen core's `Repository`. No API changes were necessary.

## 3. Rate Limiting & Resource Abuse
PDF processing (opening, hashing, annotating, and saving via PyMuPDF) is computationally expensive.
*   **Risk**: An attacker flooding `/verify` or `/distribute` will cause significant CPU exhaustion.
*   **Deferred Action**: Once authentication is added, rate-limiting must be applied per-teacher to prevent resource abuse.
