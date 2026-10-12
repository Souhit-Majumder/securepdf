# Attack Model: Secure PDF Fingerprinting (Phase II Step 3)

## Attacker Levels

### Level 1 — Casual Sharing
*   **Profile**: A student who simply uploads or shares their personalized PDF without attempting to modify it.
*   **Goal**: Traceability of the shared document back to the student.
*   **Outcome**: The embedded fingerprint survives standard file sharing (e.g., uploading to Telegram or a file host). The system successfully extracts the payload, verifies the HMAC, and identifies the student.

### Level 2 — Accidental Transformation
*   **Profile**: A student who unintentionally modifies the PDF structure through everyday use.
*   **Actions**:
    *   Opening and re-saving the PDF.
    *   Compressing the PDF to reduce file size.
    *   Removing standard metadata (Author, Title) for privacy.
    *   Extracting or rearranging pages for study purposes.
*   **Goal**: Determine which operations preserve the attribution payload. The system aims for robust survivability against non-malicious transformations.

### Level 3 — Active Attacker
*   **Profile**: A student or third party deliberately attempting to subvert the fingerprinting mechanism.
*   **Actions**:
    *   Locating and deleting the hidden payload to evade detection.
    *   Modifying the embedded `document_uid` or `nonce` to confuse the system.
    *   Attempting to forge a new, cryptographically valid fingerprint to frame another student.
*   **Primary Security Property**: Without the master key, an attacker must not be able to modify the embedded identity and produce a cryptographically valid fingerprint.

## Cryptographic Security Properties
*   **Unforgeability**: Even if an active attacker extracts the `document_uid`, `nonce`, and `fingerprint`, they cannot generate a valid fingerprint for a different student or document without the `master_key`. This relies on the collision resistance and unforgeability properties of the HMAC-SHA256 construction.
*   **Verification Before Trust**: Any data extracted from a leaked PDF is considered untrusted attacker-controlled data. The system uses the extracted claims (`document_uid`, `nonce`) to locate a candidate record in the database, but it **never** trusts this attribution until the HMAC-SHA256 verification algorithm successfully cryptographically proves the payload's authenticity.

## The Dual-Layer Architecture

To combat both malicious and accidental transformations (Level 2 and 3 attackers), the system embeds cryptographically identical payloads using two complementary carrier methods:

### Layer 1: Structural Carrier (Catalog)
*   **Method**: Payload embedded in the PDF Root Catalog dictionary (`/SPDFPayload`).
*   **Properties**: Extremely fast to extract, easy to verify, and does not alter the content streams.
*   **Weakness**: PyMuPDF and many PDF editors drop unrecognized dictionary keys when extracting pages or rewriting the document structure.

### Layer 2: Content Carrier (Redundant Annotations)
*   **Method**: Payload encoded compactly (Base64) and embedded across multiple invisible, non-rendering annotations (`Hidden`, `Invisible`, `NoView`).
*   **Properties**: By residing in the `/Annots` array of specific pages, the payload survives page reordering, page extraction, and aggressive structural modifications. The redundant copies protect against targeted deletion.

These layers are **complementary**, not just a backup. Layer 1 defends the document as a holistic object, while Layer 2 defends the individual pages from being extracted and redistributed.

## The Verification Pipeline

The verification pipeline explicitly separates three distinct concepts:

1.  **Extraction**: The mechanical process of parsing the PDF to find potential payload strings (from Layer 1 and Layer 2). *Extracted data is fundamentally untrusted.*
2.  **Authentication**: The cryptographic process of validating the payload (verifying the HMAC-SHA256 signature). *Only payloads that pass this check are considered VALID.*
3.  **Attribution**: The final step of mapping the mathematically verified `document_uid` and `nonce` to a student identity via the authoritative database.

### Conflict Policy (Fail-Closed)
Because extraction yields independent candidates from Layer 1 and Layer 2, conflict handling is strictly enforced:
*   If Layer 1 and Layer 2 are both valid but point to **different authenticated identities** (e.g., an attacker spliced a valid Layer 2 annotation from Alice into Bob's valid document), the system flags a **`SECURITY_CONFLICT`** and fails closed. It does not guess which layer is correct.
*   If one layer is missing or tampered with (fails HMAC), it is safely discarded. The verification succeeds if the remaining layer successfully authenticates.
