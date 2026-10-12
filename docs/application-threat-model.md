# Application Threat Model: Phase IV Step 1

## 1. Overview and Trust Boundaries

The application layer exposes the frozen PDF fingerprinting core via network APIs. This introduces new attack surfaces primarily related to parameter tampering, unauthorized access, and malicious file uploads.

**Trusted Zone:**
*   Master Key (`data/master.key`) - Never leaves the server.
*   Database Records (`securepdf.db`) - Validated and parameterized.
*   Server-Side Fingerprinting Logic - Executes cryptographically secure operations.

**Untrusted Zone:**
*   Uploaded PDFs (Suspected leaks or new documents).
*   API Request Parameters (`document_uid`, `student_uid`, filenames).
*   Client-controlled data (JSON bodies, multi-part form data).

---

## 2. Security Invariants
*   **No Client-Side Fingerprinting**: A client must never choose its own fingerprint or HMAC. All cryptographic operations are strictly server-side.
*   **Server-Side Identity**: Student identity must be derived exclusively from authenticated server-side database records, never directly from untrusted PDF payload extraction.
*   **Verification is Read-Only**: Verification endpoints (`/verify`) must never mutate the database, generate new fingerprints, or register missing documents.
*   **Zero-Trust PDFs**: Uploaded PDFs are entirely untrusted and must be parsed safely using robust limits (e.g., maximum annotation limits).
*   **Authorization Enforcement**: Only authorized users (Teachers/Administrators) will eventually be permitted to trigger distributions or view attribution results.

---

## 3. Threat Assessment

### Unauthorized Document / Student Registration
*   **Risk**: An attacker registers arbitrary documents or students to pollute the database or prepare for forgery.
*   **Mitigation**: Endpoints (e.g., `POST /documents`, `POST /students`) will require Teacher authorization. (Authorization deferred to Phase IV Step 2).

### Unauthorized Fingerprint Generation
*   **Risk**: An attacker triggers PDF distribution to generate valid fingerprints for unauthorized use.
*   **Mitigation**: `POST /documents/{id}/distribute` will require Teacher authorization. The system strictly generates the `nonce` and `HMAC` internally.

### Student Enumeration & IDOR / BOLA
*   **Risk**: An attacker manipulates `student_uid` or `document_uid` in API requests to access other users' data (Insecure Direct Object Reference).
*   **Mitigation**: All API endpoints must enforce authorization checks on the requested resource. The system currently avoids predictable sequential IDs by utilizing UUIDs (`_uid` fields) for external references.

### Attribution Disclosure
*   **Risk**: An attacker uploads a PDF to `/verify` to discover which student leaked it.
*   **Mitigation**: The `/verify` endpoint will require Teacher authorization. The core engine is mathematically protected against offline attribution (student identities are not in the PDF), so the API is the only oracle.

### Malicious PDF Upload (Parser Exploitation)
*   **Risk**: An attacker uploads a crafted PDF containing malicious structures, oversized payloads, or exploits targeting PyMuPDF.
*   **Mitigation**: The core engine was hardened in Phase III (Layer 2 extraction capped at 100). The API layer must additionally enforce maximum file size limits (e.g., 20MB) and strictly handle multi-part form parsing.

### Replay Attacks
*   **Risk**: An attacker resubmits a valid distribution request to overwrite or duplicate fingerprints.
*   **Mitigation**: The database strictly enforces `UNIQUE(document_id, nonce)` and `UNIQUE(fingerprint)`. The API will generate a fresh nonce per request.

### Parameter Tampering & SQL Injection
*   **Risk**: Manipulated JSON fields (`name`, `filename`) used to execute SQL injection or path traversal.
*   **Mitigation**: The frozen database layer strictly uses parameterized queries (`(?, ?)`). API validation must sanitize filenames (e.g., using `werkzeug.utils.secure_filename`).

### Privilege Escalation
*   **Risk**: A student gains Teacher access.
*   **Mitigation**: Future authentication implementation must enforce Role-Based Access Control (RBAC).

### Denial of Service (DoS)
*   **Risk**: An attacker floods `/documents/{id}/distribute` or `/verify`, consuming high CPU/Memory via HMAC generation or PyMuPDF processing.
*   **Mitigation**: Rate-limiting on sensitive endpoints and maximum file size restrictions on PDF uploads.
