# SecurePDF — Professor Live Demonstration

A self-contained, reproducible demonstration suite for **SecurePDF**: Cryptographic Document Fingerprinting, Recipient Attribution, Dual-Carrier Redundancy, and Advisory Forensic Machine Learning.

---

## 1. Quick Start

Run the entire demonstration pipeline non-interactively:

```bash
python demo/run_demo.py --all
```

Or launch the interactive menu:

```bash
python demo/run_demo.py
```

### Resetting Generated Artifacts
To clean all generated PDFs, reports, charts, and demo databases while preserving your input PDFs and `students.json`:

```bash
python demo/run_demo.py --reset
```

---

## 2. Directory Structure

All demonstration inputs, outputs, databases, keys, and visual reports remain strictly isolated within `demo/`:

```text
demo/
├── README.md               # This technical guide and presentation runbook
├── run_demo.py             # Main interactive and non-interactive demo CLI runner
├── students.json           # Editable student recipient registry
├── pdfs/                   # Input folder for source PDF documents
│   ├── README.md
│   ├── cs101_syllabus.pdf
│   └── crypto_lecture.pdf
├── issued/                 # Personalized, cryptographically fingerprinted PDFs
│   └── issuance_manifest.json
├── tampered/               # Controlled transformation and attack scenario PDFs
├── reports/                # Forensic analysis reports and visual evidence
│   ├── tamper_report.json
│   ├── tamper_report.csv
│   ├── ml_evaluation.json
│   ├── findings.md
│   ├── discovered_pdfs.json
│   └── visual/             # Side-by-side pixel diffs and structural cards
├── charts/                 # High-resolution presentation figures (Matplotlib / Seaborn)
│   ├── 01_issuance_distribution.png
│   ├── 02_tamper_crypto_outcomes.png
│   ├── 03_carrier_survival.png
│   ├── 04_confusion_matrix.png
│   ├── 05_class_metrics.png
│   ├── 06_model_vs_baseline.png
│   ├── 07_feature_importances.png
│   └── 08_dataset_split_distribution.png
├── dataset/                # Demo ML dataset, baselines, and manifests
│   ├── manifests/
│   ├── baselines/
│   └── variants/
├── working/                # Isolated demo SQLite database and demo master key
│   ├── securepdf_demo.db
│   ├── demo_master.key
│   └── demo_model.joblib
├── logs/                   # Execution and processing logs
└── results/                # Synthesized summary outputs
```

> **Isolation Guarantee**: The demo writes exclusively to `demo/working/` and `demo/issued/`. The production database (`data/securepdf.db`) and production master key (`data/master.key`) are **never modified**.

---

## 3. Individual Stage Execution

You can run individual demonstration stages directly:

| Command | Stage Description |
| :--- | :--- |
| `python demo/run_demo.py --stage pdfs` | **Stage 1**: Discovers and validates `%PDF` headers, page count, and SHA-256 digests in `demo/pdfs/`. |
| `python demo/run_demo.py --stage students` | **Stage 2**: Validates `demo/students.json` schema, student IDs, and non-empty records. |
| `python demo/run_demo.py --stage issue` | **Stage 3**: Cryptographically fingerprints and issues personalized PDFs to `demo/issued/`. |
| `python demo/run_demo.py --stage ml` | **Stage 6**: Generates source-grouped ML dataset, trains Random Forest model, and evaluates test split. |
| `python demo/run_demo.py --stage tamper` | **Stage 4**: Executes 13 multi-vector attack scenarios and runs dual-track forensic analysis. |
| `python demo/run_demo.py --stage visual` | **Stage 5**: Renders side-by-side visual difference heatmaps and structural carrier comparison cards. |
| `python demo/run_demo.py --stage charts` | **Stage 7**: Generates 8 presentation charts in `demo/charts/` and creates `reports/findings.md`. |

---

## 4. The 13 Attack Scenarios & Cryptographic Semantics

| Scenario | Modification Description | Surviving Carriers | Cryptographic Verdict | Recipient Attribution | ML Forensic Assessment |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `01_untouched` | Pristine distributed copy | Layer 1, Layer 2 | `VALID` | Alice Johnson | `AVAILABLE` (benign_transformation) |
| `02_benign_resave` | PyMuPDF re-save (deflate & garbage collect) | Layer 1, Layer 2 | `VALID` | Alice Johnson | `AVAILABLE` (benign_transformation) |
| `03_metadata_mod` | Title and Author altered in catalog | Layer 1, Layer 2 | `VALID` | Alice Johnson | `AVAILABLE` (benign_transformation) |
| `04_page_added` | Extraneous student notes page appended | Layer 1, Layer 2 | `VALID` | Alice Johnson | `AVAILABLE` (modified) |
| `05_page_deleted` | Final page deleted | Layer 1, Layer 2 | `VALID` | Alice Johnson | `AVAILABLE` (benign_transformation) |
| `06_page_reordered` | Reverse page order | Layer 2 | `VALID` | Alice Johnson | `AVAILABLE` (modified) |
| `07_text_modified` | Prominent red banner drawn across content | Layer 1, Layer 2 | `VALID`* | Alice Johnson | `AVAILABLE` (modified) |
| `08_catalog_corrupt` | Junk hex written to Catalog `/SPDFPayload` | Layer 2 (Annotation) | `VALID` | Alice Johnson | `AVAILABLE` (marker_tampering) |
| `09_catalog_deleted` | `/SPDFPayload` set to `null` | Layer 2 (Annotation) | `VALID` | Alice Johnson | `AVAILABLE` (modified) |
| `10_annot_corrupt` | Layer 2 Annotation content overwritten | Layer 1 (Catalog) | `VALID` | Alice Johnson | `AVAILABLE` (marker_tampering) |
| `11_annot_deleted` | Layer 2 Annotations stripped from all pages | Layer 1 (Catalog) | `VALID` | Alice Johnson | `AVAILABLE` (marker_tampering) |
| `12_both_removed` | Adversarial stripping of both carriers | None | `NOT_FOUND` | None | `UNSUPPORTED` (Scope Gated) |
| `13_security_conflict` | Carrier 1 = Alice, Carrier 2 = Bob | Conflicting | `SECURITY_CONFLICT` | None (Fail-Closed) | `AVAILABLE` (Advisory) |

### Key Theoretical Points for Presentation:
1. **`VALID` Does Not Prove Visual Immutability (`07_text_modified`)**:
   - The cryptographic HMAC binds `document_uid`, `student_uid`, and `nonce` under the secret master key.
   - It proves *who received this personalized copy*, not that every pixel stream is unmodified.
2. **Dual-Carrier Redundancy (`08`–`11`)**:
   - If an adversary corrupts or strips Layer 1 (Catalog), Layer 2 (Invisible Annotation) survives and recovers the leaker's identity.
   - If an adversary strips annotations, Layer 1 survives.
3. **Anti-Framing Security Conflict (`13_security_conflict`)**:
   - If a malicious student attempts to splice carrier payloads from two different students to frame a peer, the system detects conflicting signatures and flags `SECURITY_CONFLICT`, failing closed.
4. **Scope Gating on Carrier Removal (`12_both_removed`)**:
   - Stripping both carriers leaves no carrier markings. The system reports `NOT_FOUND` cryptographically, and the ML predictor reports `UNSUPPORTED` with `predicted_class: None`. The model does not hallucinate a classification class for an unrecognized PDF.

---

## 5. Live Presentation Sequence (Runbook for Professor)

When presenting to your professor tomorrow, follow this concise sequence:

1. **Step 1 — Show Input Documents & Student Registry**:
   - Show `demo/pdfs/` (e.g. `cs101_syllabus.pdf`, `crypto_lecture.pdf`).
   - Show `demo/students.json` (Alice, Bob, Charlie, Diana).
2. **Step 2 — Execute Issuance (`Stage 3`)**:
   - Run: `python demo/run_demo.py --stage issue`
   - Explain: Each copy receives an unforgeable HMAC-SHA256 fingerprint embedded redundantly in the Catalog Dictionary and invisible page annotations. No student names or roll numbers are exposed in the PDF.
3. **Step 3 — Run Tampering & Forensic Analysis (`Stage 4`)**:
   - Run: `python demo/run_demo.py --stage tamper`
   - Point out scenario `08` (Catalog corrupted): Layer 2 survives $\rightarrow$ Alice is still attributed!
   - Point out scenario `13` (Spliced carriers): Fails closed as `SECURITY_CONFLICT` to prevent framing attacks.
   - Point out scenario `12` (Both carriers stripped): Returns `NOT_FOUND` and ML returns `UNSUPPORTED` (no false claims).
4. **Step 4 — Present Visual Difference Heatmaps**:
   - Open `demo/reports/visual/visual_diff_text_modified.png`.
   - Explain how PyMuPDF renders the pixel difference heatmap showing exact content alterations while cryptographic identity attribution remains intact.
5. **Step 5 — Present High-Resolution Charts**:
   - Open `demo/charts/02_tamper_crypto_outcomes.png` (Cryptographic verification breakdown).
   - Open `demo/charts/03_carrier_survival.png` (Carrier redundancy survival rates).
   - Open `demo/charts/04_confusion_matrix.png` and `06_model_vs_baseline.png` (ML forensic classification vs dummy baseline).
6. **Step 6 — Review `demo/reports/findings.md`**:
   - Conclude with the synthesized findings report, highlighting the clear separation between cryptographic authority and advisory machine learning.
