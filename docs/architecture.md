# Architecture Document: Secure PDF Fingerprinting (Phase I)

## Overview
The Phase I architecture focuses purely on the core security/fingerprinting engine. It takes an original PDF, generates a unique cryptographic fingerprint for a student using PyCryptodome, embeds it invisibly using a PDF manipulation library, and provides a mechanism to later extract and verify this fingerprint.

## Core Principles
1. **Separation of Concerns:** Cryptography, PDF manipulation, and database logic are strictly separated.
2. **Minimalism:** No frontend, no JWT, no complex deployment in Phase I. Only SQLite and a CLI interface.
3. **Cryptographic Integrity:** Fingerprints are generated using HMAC-SHA256, ensuring they cannot be forged without the server's master key.

## Directory Structure
```text
securepdf/
├── app/
│   ├── main.py                     # CLI entry point
│   ├── crypto/                     # Cryptography module
│   │   ├── keys.py                 # Key management (generation/loading)
│   │   ├── fingerprint.py          # HMAC-SHA256 generation
│   │   └── integrity.py            # Fingerprint validation
│   ├── pdf/                        # PDF manipulation module
│   │   ├── embed.py                # Embedding payloads into PDFs
│   │   ├── extract.py              # Extracting payloads from PDFs
│   │   └── processor.py            # High-level PDF orchestration
│   ├── database/                   # SQLite database module
│   │   ├── database.py             # Connection and initialization
│   │   ├── models.py               # Data structures
│   │   └── repository.py           # Database operations
│   └── services/                   # Business logic orchestration
│       ├── fingerprint_service.py  # Orchestrates PDF fingerprinting
│       └── verification_service.py # Orchestrates extraction and verification
├── tests/                          # Automated tests
├── docs/                           # Documentation (Threat Model, Architecture)
├── data/                           # Storage for SQLite DB and keys
├── requirements.txt
├── README.md
└── .gitignore
```

## Database Schema (SQLite)

### 1. `students` Table
Stores information about the intended recipients.
* `id` (INTEGER, PK)
* `student_uid` (TEXT, UNIQUE) - e.g., 'STU-001'
* `name` (TEXT)
* `created_at` (DATETIME)

### 2. `documents` Table
Stores information about the base PDF documents.
* `id` (INTEGER, PK)
* `document_uid` (TEXT, UNIQUE) - e.g., 'DOC-001'
* `original_filename` (TEXT)
* `created_at` (DATETIME)

### 3. `fingerprints` Table
Maps a specific document and student to a generated fingerprint.
* `id` (INTEGER, PK)
* `document_id` (INTEGER, FK to documents)
* `student_id` (INTEGER, FK to students)
* `fingerprint` (TEXT, UNIQUE) - The HMAC-SHA256 hash
* `created_at` (DATETIME)

## Cryptographic Design

### Key Management
* A `master.key` is generated using PyCryptodome's secure random generation.
* The key is stored locally in the `keys/` directory (or `data/`).
* The system loads this key on startup.

### Fingerprint Generation
The fingerprint is an HMAC-SHA256 hash.
* **Key:** `master.key`
* **Message:** `document_uid || student_uid || nonce` (where nonce is a random 128-bit value)

## PDF Embedding Mechanism
* **Library:** `pypdf` (or similar modern PDF library).
* **Location:** The fingerprint payload is embedded as hidden metadata or within a custom PDF dictionary object.
* **Payload Structure:**
  ```json
  {
      "version": 1,
      "document": "DOC-001",
      "nonce": "<random_hex>",
      "fingerprint": "<hmac_hex>"
  }
  ```
* **Constraint:** The `student_uid` is deliberately NOT stored in the PDF. It is derived through a database lookup after the fingerprint's cryptographic integrity is verified.

## CLI Workflows

### 1. Create Student
`python -m app create-student --uid STU-001 --name "Alice"`
* Inserts a record into the `students` table.

### 2. Fingerprint Document
`python -m app fingerprint --document DBMS.pdf --student STU-001`
* Generates/loads `DOC-001`.
* Generates a nonce and the HMAC-SHA256 fingerprint.
* Saves to the `fingerprints` table.
* Embeds the payload into the PDF.
* Saves the output as `output/DBMS_STU-001.pdf`.

### 3. Investigate Document
`python -m app investigate --file leaked.pdf`
* Extracts the embedded payload from the PDF.
* Verifies the HMAC-SHA256 fingerprint using the `master.key`, extracted `document_uid`, derived `student_uid` (from DB), and extracted `nonce`.
* If valid, prints the attribution (Student Name, Student UID). If invalid, prints `INVALID / TAMPERED`.
