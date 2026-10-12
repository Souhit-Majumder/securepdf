# Security Review: Secure PDF Fingerprinting Core (Phase III Step 1)

## Overview
This document summarizes the security review of the integrated dual-layer PDF fingerprinting core. The design strictly adheres to a "Verify Before Trust" architecture where extraction, cryptographic authentication, and database attribution are completely decoupled.

## Threat Model & Trust Boundaries
*   **Assets**: Student identities, document authenticity, system master key.
*   **Trust Boundaries**: 
    *   Any uploaded/leaked PDF is assumed **malicious/untrusted**.
    *   The Database (`data/securepdf.db`) and Key File (`data/master.key`) are **trusted** and must be kept secure.
*   **Attack Surfaces**:
    *   PDF Parser (PyMuPDF) and payload extraction logic.
    *   Cryptographic verification logic.
    *   Database queries.

## 1. Cryptographic Assumptions & Review
*   **Algorithm**: `HMAC-SHA256` is consistently applied.
*   **Key Generation**: The `master.key` is securely generated using PyCryptodome's `get_random_bytes(32)`, providing 256 bits of entropy. It is dynamically created if missing, avoiding hard-coded keys.
*   **Constant-Time Verification**: Uses `hmac.verify(provided_mac_bytes)` which executes a constant-time comparison, preventing timing side-channel attacks.
*   **Canonical Message**: Safely enforced via `build_canonical_message()` generating `SPDF-V1|{document_uid}|{student_uid}|{nonce}`.
*   **Identity Hiding**: The `student_uid` and student name are correctly **excluded** from the PDF payloads, acting purely as a hidden verification factor.

## 2. Key-Management Assumptions
*   The `master.key` resides in the local `data/` directory.
*   **Loss of Key**: Irrecoverable. If lost, all previously fingerprinted PDFs cannot be cryptographically verified.
*   **Compromise of Key**: Total system compromise. An attacker could forge valid fingerprints for any student.
*   **Mitigation**: Added `.gitignore` to prevent accidental commits of the `data/` directory.

## 3. PDF Parsing Risks & Mitigations
*   **Parser Robustness**: The extraction code is wrapped in strict try/except blocks. Malformed payloads (invalid Hex, invalid Base64, incorrect SPDF versions, missing delimiters) correctly trigger a safe `INVALID` or `NOT_FOUND` state without crashing the service.
*   **Resource Exhaustion (DoS)**: An active attacker could flood the PDF with millions of fake Layer 2 annotations to exhaust memory or CPU during extraction.
    *   *Mitigation Implemented*: Layer 2 extraction now hard-caps at 100 payloads. The system will gracefully process the first 100 and exit. If a valid payload is displaced by garbage, it fails safely (closed).

## 4. Database Risks & Mitigations
*   **SQL Injection**: All database queries strictly use parameterized `sqlite3` execution (`(?, ?)`). No string concatenation is used.
*   **Uniqueness Invariant**: The database schema explicitly enforces `UNIQUE(document_id, nonce)` at the table level, mathematically ensuring two generation states cannot collide and preventing application-level race conditions.
*   **Side-Effects**: Identified and fixed a vulnerability where the `VerificationService` was using `get_or_create_document` to look up the candidate document. A malformed PDF with a fake `document_uid` would cause the system to spawn "ghost" document records in the database during verification.
    *   *Mitigation Implemented*: Replaced with a strictly read-only `get_document_by_uid`.

## 5. Conflict Handling
The dual-layer architecture has an explicit, tested conflict policy:
*   **L1 Valid + L2 Valid (Identical)**: `VALID`
*   **L1 Missing/Invalid + L2 Valid**: `VALID`
*   **L1 Valid + L2 Missing/Invalid**: `VALID`
*   **L1 Valid + L2 Valid (Different)**: `SECURITY_CONFLICT` (Fails closed, does not guess)
*   **L1 Invalid + L2 Invalid**: `INVALID`

## Known Limitations
*   **No Key Rotation**: If the master key is compromised, there is no built-in mechanism to gracefully rotate the key while supporting older documents.
*   **Annotation Discovery**: While invisible, Layer 2 annotations can still be discovered using specialized PDF diagnostic tools.

## Summary of Findings

| Severity | Description | Status |
| :--- | :--- | :--- |
| **MEDIUM** | `VerificationService` performed a database write (`get_or_create_document`) when extracting unverified candidate claims, allowing database pollution. | ✅ FIXED |
| **LOW** | `extract_layer2` could theoretically consume excessive memory parsing millions of fake annotations. | ✅ FIXED (Capped at 100) |
| **LOW** | `fingerprints` table lacked a strict `UNIQUE(document_id, nonce)` constraint, theoretically allowing duplicate generation states. | ✅ FIXED |
| **INFORMATIONAL** | Key rotation is not supported. Loss of `master.key` is irrecoverable. | ⚠️ DEFERRED |
| **INFORMATIONAL** | `.gitignore` was missing, risking `data/` directory leak. | ✅ FIXED |
