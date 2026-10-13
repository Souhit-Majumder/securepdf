# SecurePDF

Cryptographic PDF Fingerprinting and Recipient Attribution Engine.

SecurePDF embeds unique, tamper-evident cryptographic fingerprints into PDF documents to enable deterministic tracing of leaked files back to specific recipients (e.g., students), while preserving visual integrity and resisting accidental and active adversarial transformations.

---

## Architecture Overview

SecurePDF separates responsibilities into reusable core libraries, independent client interfaces, and a future GUI boundary:

```text
securepdf/
├── app/
│   ├── config.py             # Centralized path configuration with environment overrides
│   ├── core/                 # Unified core interfaces
│   │   ├── crypto/           # Cryptographic primitives (HMAC-SHA256, master key, nonce)
│   │   └── pdf/              # Dual-layer PDF embedding and extraction engine
│   ├── crypto/               # Cryptography implementation
│   │   ├── keys.py           # 256-bit master key management
│   │   ├── fingerprint.py    # Canonical message formatting and HMAC generation
│   │   └── integrity.py      # Constant-time HMAC verification
│   ├── pdf/                  # PyMuPDF-based manipulation
│   │   ├── processor.py      # Document opening, optimization, and validation
│   │   ├── embed.py          # Dual-layer carrier embedding
│   │   ├── extract.py        # Dual-layer carrier extraction with DoS caps
│   │   └── payload_redundancy.py # Compact Base64 encoding & redundant annotations
│   ├── database/             # SQLite database layer
│   │   ├── database.py       # Connection handling and table schemas
│   │   └── models.py         # Dataclasses: Student, Document, Fingerprint
│   ├── repositories/         # Parameterized data access layer
│   │   └── repository.py     # Parameterized SQL repository
│   ├── services/             # Shared business logic
│   │   ├── fingerprint_service.py   # Document personalization orchestration
│   │   └── verification_service.py  # "Verify Before Trust" attribution pipeline
│   ├── api/                  # FastAPI REST API layer
│   │   ├── routes/           # Endpoints: /documents, /students, /verify
│   │   ├── schemas/          # Pydantic validation schemas
│   │   └── dependencies.py   # Dependency injection providers
│   ├── cli/                  # Independent CLI client
│   │   ├── main.py           # Argument parsing and command dispatch
│   │   ├── __main__.py       # Module entry point (`python -m app.cli`)
│   │   └── commands/         # Modular subcommands: verify, demo, register, distribute
│   └── main.py               # FastAPI application entry point
├── frontend/
│   └── README.md             # Specification for future decoupled GUI client
├── tests/                    # Reorganized regression test suite
│   ├── conftest.py           # Isolated test environment fixture
│   ├── unit/                 # Unit tests (crypto, pdf, database constraints)
│   ├── integration/          # Integration tests (multi-layer, API routes)
│   ├── security/             # Attack simulation and parser robustness tests
│   └── cli/                  # CLI command and smoke tests
├── docs/                     # Threat models, security reviews, and architecture specs
├── scripts/                  # Utility and debugging scripts
├── requirements.txt          # Python dependencies
└── .gitignore
```

---

## Security Model & Dual-Layer Carriers

1. **Root of Trust**:
   - Secured by a local 256-bit master key (`data/master.key`) generated using PyCryptodome's cryptographically secure pseudo-random number generator (`get_random_bytes(32)`).
   - The master key **never** leaves the server and is **never** embedded in documents.
2. **Identity Hiding**:
   - The recipient identifier (`student_uid`) is intentionally omitted from the embedded PDF payload. Recipient identity is derived post-cryptographic verification via authoritative database lookup.
3. **Dual-Layer Embedding**:
   - **Layer 1 (Structural Carrier)**: Embedded directly into the PDF Root Catalog dictionary (`/SPDFPayload`). Rapid extraction and zero visual overhead.
   - **Layer 2 (Content Carrier)**: Embedded across three independent, zero-area invisible annotations (`Hidden`, `Invisible`, `NoView`) using compact Base64 HMAC encoding. Survives page extraction, page reordering, and targeted annotation tampering.
4. **Verify Before Trust Pipeline**:
   - Decoupled into Extraction → Authentication (HMAC-SHA256 check) → Attribution (Database lookup).
   - If Layer 1 and Layer 2 authenticate to distinct recipient identities (e.g., content splicing attacks), the system triggers a **fail-closed** `SECURITY_CONFLICT` state and refuses attribution.

---

## Setup & Installation

### Prerequisites
- Python 3.10+ (tested with Python 3.13)
- Virtual environment recommended

### Installation
```bash
# Clone the repository
git clone https://github.com/Souhit-Majumder/securepdf.git
cd securepdf

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Running the Application

### 1. CLI Usage
The CLI is a standalone client that uses the shared service layer directly without requiring the API server to be running:

```bash
# View all available CLI commands
python -m app.cli --help

# 1. Register an original document
python -m app.cli register-document path/to/original.pdf --title "Lecture Notes" --uid "DOC-001"

# 2. Register a student recipient
python -m app.cli register-student "STU-001" "Alice Smith"

# 3. Generate a personalized copy for a student
python -m app.cli distribute "DOC-001" "STU-001" --output "output/Alice_copy.pdf"

# 4. Investigate a leaked or suspected document
python -m app.cli verify "output/Alice_copy.pdf"

# 5. Perform comprehensive forensic analysis (Cryptographic + Advisory ML)
python -m app.cli analyze "output/Alice_copy.pdf"

# 6. Generate forensic training dataset with source-grouped splits
python -m app.cli ml dataset --generate-synthetic-sources 10

# 7. Train Random Forest forensic classifier
python -m app.cli ml train

# 8. Evaluate model against manifest with baseline comparison
python -m app.cli ml evaluate

# 9. Run an automated 3-student demo workflow
python -m app.cli demo

# 10. Launch interactive menu
python -m app.cli
```

### 2. FastAPI Backend
Launch the REST API server using `uvicorn`:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive API documentation will be available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

#### Primary Endpoints:
- `POST /documents/`: Upload base PDF (validates `%PDF` magic bytes, 20MB stream cap).
- `POST /students/`: Register a recipient identity (`name`, `student_uid`).
- `POST /documents/{document_uid}/distribute`: Generate and download a personalized PDF.
- `POST /verify/`: Submit a suspect PDF for cryptographic verification and attribution.

---

## File Storage & Configurable Paths

Path configuration is centralized in [`app/config.py`](file:///home/souhit/Documents/Research/IS/securepdf/app/config.py) and can be overridden via environment variables:

| Setting | Default Path | Environment Override |
| :--- | :--- | :--- |
| **Data Directory** | `data/` | `SECUREPDF_DATA_DIR` |
| **Database** | `data/securepdf.db` | `SECUREPDF_DB_PATH` |
| **Master Key** | `data/master.key` | `SECUREPDF_KEY_PATH` |
| **Original Documents** | `data/documents/` | `SECUREPDF_DOCUMENTS_DIR` |
| **Generated Copies** | `data/output/` | `SECUREPDF_OUTPUT_DIR` |
| **Temporary Uploads** | `data/temp/` | `SECUREPDF_TEMP_DIR` |
| **ML Artifacts** | `data/ml/` | `SECUREPDF_ML_DIR` |
| **ML Model Path** | `data/ml/forensic_model.joblib` | `SECUREPDF_MODEL_PATH` |
| **ML Dataset** | `data/ml/dataset/` | `SECUREPDF_DATASET_DIR` |

---

## Running the Automated Test Suite

All tests are isolated from production data using temporary directories configured in `tests/conftest.py`:

```bash
# Run the complete test suite
pytest

# Run tests with verbose output
pytest -v

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
pytest tests/security/
pytest tests/cli/
pytest tests/ml/
```

---

## Documentation

- [ML Forensic Analysis Guide](docs/ml-forensic-analysis.md)
- [Architecture Specification](docs/architecture.md)
- [Security Model](docs/security-model.md)
- [Attack Model & Adversarial Testing](docs/attack-model.md)
- [Content Embedding & Carriers](docs/content-embedding.md)
- [API Security Review](docs/api-security-review.md)

---

## Project Status & Roadmap

### Current Features (Implemented)
- Core cryptographic fingerprinting and constant-time HMAC verification (`SPDF-V1|{doc_uid}|{student_uid}|{nonce}`).
- Dual-layer PDF carrier embedding and extraction (Catalog + Annotations).
- Redundant annotation survival against page reordering, extraction, and tampering.
- SQLite parameterized database layer with unique constraints.
- Advisory ML PDF forensic analysis subsystem with 23-feature passive extractor, source-grouped train/test isolation, and Random Forest classifier.
- Fully isolated test suite with 75 passing automated tests.
- Standalone CLI with modular subcommands, comprehensive `analyze` reporting, and interactive console.
- FastAPI REST API with payload size streaming limits and input sanitization.

### Planned Features (Future Milestones)
- **GUI Application**: Decoupled desktop/web interface communicating with FastAPI.
- **Authentication & RBAC**: JWT/Session authentication for Teacher vs. Student roles.
- **Key Rotation**: Cryptographic key lifecycle management and versioned verification.

