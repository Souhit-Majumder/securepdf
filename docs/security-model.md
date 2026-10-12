# Security Model: Secure PDF Fingerprinting (Phase I)

## Entities

*   **Teacher/System**: The authorized entity that possesses the master cryptographic key and generates personalized PDFs. This entity is fully trusted.
*   **Student (Recipient)**: The intended recipient of the fingerprinted PDF. They are not trusted and might act maliciously (e.g., share the PDF, attempt to frame others).
*   **Document**: The educational material (PDF) being distributed.
*   **Fingerprint**: The cryptographic payload embedded in the Document, which uniquely binds the Document to the Student.
*   **Secret Key**: The master cryptographic key (`master.key`). It is the root of trust. It **never** leaves the server and is **never** embedded in the PDF.
*   **Investigator**: An authorized entity (could be the Teacher or System) attempting to trace the origin of a leaked PDF.
*   **Attacker**: Any entity (including a malicious Student) trying to forge a fingerprint, tamper with an existing fingerprint, or frame another student.

## Core Trust Relationship

```text
                 SECRET KEY
                     │
                     ▼
Teacher/System ──→ Fingerprint
                     │
                     ▼
                  PDF copy
                     │
                     ▼
                  Student
```

The Secret Key is the cornerstone of the system. The Fingerprint is mathematically derived from the Document UID, Student UID, and a random nonce, secured by the Secret Key.

## Cryptographic Construction: HMAC-SHA256

The system uses HMAC-SHA256 instead of plain SHA-256 hashing.

### Why HMAC-SHA256?
A plain hash `SHA256(student_uid + document_uid + nonce)` relies on obscurity (hiding the nonce). An attacker who can guess or extract the nonce can generate valid-looking fingerprints for any student, enabling framing.

By using `HMAC(secret_key, data)`, the generation of a mathematically valid fingerprint requires possession of the Secret Key. Without the key, an attacker cannot forge a valid fingerprint, even if they know the `document_uid`, `student_uid`, and `nonce`.

### Canonical Message
To prevent ambiguity and concatenation vulnerabilities (e.g., `DOC` + `123` vs `DO` + `C123`), the HMAC input uses a canonical, versioned message format:
`SPDF-V1|document_uid|student_uid|nonce`
