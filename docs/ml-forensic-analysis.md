# Machine Learning PDF Forensic Analysis

## 1. Overview & Forensic Objective

SecurePDF integrates an **ML-based PDF forensic analysis subsystem** designed to complement its cryptographic recipient-fingerprinting engine. 

While SecurePDF's cryptographic core provides deterministic, authoritative recipient attribution using HMAC-SHA256 and dual-carrier embedding, it operates as a binary integrity check (fingerprint authentic vs. invalid/missing). In real-world leak investigations, analysts frequently encounter PDF documents that have been re-saved, compressed, converted, edited, or maliciously scrubbed of metadata.

The ML subsystem provides **structural forensic characterization**:
- It analyzes structural, syntactical, and carrier indicators within the PDF container.
- It predicts whether the document exhibits structural characteristics resembling known classes of document modification (e.g., standard re-saving, page manipulation, or deliberate carrier marker tampering).
- **Critical Invariant**: The ML component is **strictly advisory**. It never makes attribution decisions, never replaces HMAC verification, never treats arbitrary modifications as proof of malice, and cannot override cryptographic verification results.

---

## 2. Two Independent Verification Tracks

SecurePDF maintains two completely independent analysis tracks:

| Dimension | Track 1: Cryptographic Verification (Authoritative) | Track 2: ML Forensic Assessment (Advisory) |
| :--- | :--- | :--- |
| **Method** | HMAC-SHA256 signature verification over canonical message `SPDF-V1\|{doc_uid}\|{student_uid}\|{nonce}` | Supervised Random Forest classification on 23 structural features |
| **Output** | `VALID`, `INVALID`, `NOT_FOUND`, or `SECURITY_CONFLICT` | Predicted class: `original`, `benign_transformation`, `modified`, `marker_tampering` |
| **Attribution** | Identifies student recipient name and UID via authoritative database lookup | **None**. Student identity is never predicted or estimated by ML |
| **Authority** | **Authoritative & Legally Actionable** | **Advisory & Diagnostic** |
| **Conflict Behavior** | Fails closed on layer mismatch | Informational indicator only |

---

## 3. Feature Extraction Schema

The feature extractor (`app/ml/feature_extractor.py`) computes a fixed, deterministic 23-dimensional numerical vector. Extraction is strictly passive:
- Never executes embedded JavaScript or PDF action dictionaries (`/Launch`, `/Action`, `/JS`).
- Never trusts file paths, file extensions, or user-supplied names.
- Does not use recipient identities, nonces, secret keys, or cryptographic verification outcomes as predictive features (preventing target leakage).
- Enforces strict input limits (rejecting non-PDFs, empty files, and files exceeding 50 MB).
- Performs read-only analysis without modifying the input PDF.

### Feature Definitions

| Index | Feature Name | Type | Description | Limitations & Caveats |
| :---: | :--- | :---: | :--- | :--- |
| 0 | `file_size_bytes` | float | Total PDF file size in bytes | Highly variable; depends on font embedding and compression. |
| 1 | `page_count` | float | Total number of pages in the document | Baseline metric; susceptible to document length. |
| 2 | `total_text_length` | float | Character count of all extractable page text | Scanned or rasterized PDFs yield zero text. |
| 3 | `avg_text_per_page` | float | Text length divided by page count | Ratio sensitive to sparse introductory/appendix pages. |
| 4 | `annotation_count` | float | Total PDF annotations across all pages | Benign highlights and comments increase this count. |
| 5 | `avg_annotations_per_page` | float | Annotation count divided by page count | Normalized indicator. |
| 6 | `image_count` | float | Total embedded raster images across pages | Dependent on document graphic layout. |
| 7 | `embedded_file_count` | float | Number of file attachments in the PDF Catalog | Most standard academic PDFs have 0 attachments. |
| 8 | `is_encrypted` | float | 1.0 if PDF encryption dictionary exists, else 0.0 | Standard password or permissions encryption indicator. |
| 9 | `has_metadata` | float | 1.0 if document info dictionary contains any fields | Modern editors may wipe metadata on export. |
| 10 | `metadata_field_count` | float | Count of populated standard metadata fields (title, author, etc.) | Indicates metadata stripping depth. |
| 11 | `has_title` | float | 1.0 if title field is present | Standard metadata flag. |
| 12 | `has_author` | float | 1.0 if author field is present | Standard metadata flag. |
| 13 | `has_creation_date` | float | 1.0 if creationDate field is present | Often preserved during superficial edits. |
| 14 | `has_mod_date` | float | 1.0 if modDate field is present | Updated by legitimate PDF viewers upon saving. |
| 15 | `dates_match` | float | 1.0 if creationDate equals modDate | Frequently diverges upon re-saving or annotation. |
| 16 | `javascript_action_count` | float | Passive xref scan for `/JavaScript`, `/JS`, `/Action` tokens | Identifies interactive components without code execution. |
| 17 | `has_catalog_carrier` | float | 1.0 if `/SPDFPayload` exists in PDF Catalog (Layer 1) | Syntactic presence of Layer 1 carrier. |
| 18 | `catalog_carrier_format_valid`| float | 1.0 if Layer 1 payload matches `SPDF-V1\|...` format | Syntactic format check (NOT cryptographic check). |
| 19 | `annotation_carrier_count` | float | Count of annotations matching SecurePDF Layer 2 title prefix | Raw carrier count. |
| 20 | `annotation_carrier_format_valid_count` | float | Count of Layer 2 annotations matching `SPDF1:...` format | Syntactic format check of Layer 2 annotations. |
| 21 | `annotation_carrier_duplicate_count` | float | Maximum duplicate count of identical Layer 2 payloads | Measures redundancy retention. |
| 22 | `carrier_count_total` | float | Sum of catalog and annotation carriers | Aggregate carrier presence indicator. |

---

## 4. Controlled Dataset Generation Pipeline

The dataset generation module (`app/ml/dataset.py`) generates balanced, labeled training datasets from original source PDFs using controlled, reproducible transformations.

### Target Classes

1. `original`:
   - Clean, untransformed PDFs carrying legitimate SecurePDF dual-layer carriers.
2. `benign_transformation`:
   - Common non-malicious operations: PDF re-saving with stream compression (`deflate=True`), linearization, font re-encoding, and metadata clearing/editing.
3. `modified`:
   - Structural content alterations: Page insertion, page deletion, page reordering, content annotation injection, and visible text block modifications.
4. `marker_tampering`:
   - Targeted attacks against fingerprint carriers: Catalog payload stripping, annotation carrier wiping, carrier payload corruption, and cross-document splicing attempts.

### Source-Grouped Split Policy

**Critical Methodological Invariant**:
- Variants generated from the same source PDF **never** span across train and test splits.
- Splitting occurs strictly at the **source document level** (`source_document_id`).
- For example, if `Source_A.pdf` is assigned to `train`, all 12 variants of `Source_A` (`Source_A_resave`, `Source_A_del_page`, etc.) are placed in the training partition.
- This prevents structural feature leakage and ensures the model evaluates generalization to unseen document layouts rather than memorizing source-specific layout quirks.

### Manifest Security

The dataset manifest (`manifest.json`) records:
- `source_document_id` and `variant_id`.
- `transformation` applied and assigned `label`.
- `relative_path` within the dataset directory.
- `split` (`train` or `test`).
- Extracted 23-feature vector.

No absolute local paths, user personal information, student names, nonces, or master keys are ever written to the manifest.

---

## 5. Model Architecture & Training

The training module (`app/ml/train.py`) trains a `RandomForestClassifier` (100 estimators, max depth 8, balanced class weights) alongside a `DummyClassifier` (majority class baseline).

### Artifact Serialization & Integrity

Trained models are persisted via `joblib` as versioned artifact bundles containing:
- `artifact_version`: e.g. `"1.0.0"`.
- `model_type`: `"RandomForestClassifier"`.
- `feature_schema`: Exact list of 23 feature names in deterministic sequence.
- `classes`: List of class labels known to the model.
- `model`: Trained Random Forest instance.
- `baseline_model`: Trained Dummy classifier instance.
- `training_metadata`: Split statistics, source IDs, train/test accuracy, and top feature importances.

The runtime predictor rejects incompatible versions or schema mismatches with fail-safe error handling.

---

## 6. Evaluation Protocol & Baseline Comparison

The evaluation module (`app/ml/evaluate.py`) computes:
- Overall test accuracy compared to the majority-class baseline.
- Macro-averaged precision, recall, and F1-score.
- Per-class precision, recall, F1-score, and support count.
- Multi-class confusion matrix.
- Gini feature importances (reported with strict non-causal disclosures).

### Experimental Limitations & Risk Disclosures

1. **Synthetic Training Domain**: The model is trained on controlled, programmatically generated transformations. It may exhibit degraded performance when confronted with proprietary enterprise PDF manipulation suites, obscure print drivers, or novel anti-forensic tools.
2. **Advisory Nature**: A prediction of `modified` indicates structural divergence from typical originals, which may arise from completely benign workflows (e.g. printing to PDF, adding lecturer annotations, or running accessibility OCR).
3. **Uncalibrated Confidence**: Confidence scores reflect the empirical fraction of Random Forest decision trees voting for a given class. They are **not** Bayesian probabilities.
4. **Attribution Independence**: ML assessment must never be cited as evidence of recipient identity. Cryptographic verification (HMAC-SHA256) is the only legally defensible attribution mechanism.

---

## 7. CLI Usage Guide

### 1. Generate Dataset
```bash
python -m app.cli ml dataset --generate-synthetic-sources 10 --seed 42
```
Options:
- `--source-dir`: Path to directory containing source PDFs (defaults to `data/ml/dataset/sources`).
- `--output-dir`: Path to output directory (defaults to `data/ml/dataset`).
- `--generate-synthetic-sources N`: Generates N multi-page fingerprinted source PDFs if no real originals exist.
- `--split-ratio`: Source-grouped train ratio (default: 0.7).

### 2. Train Model
```bash
python -m app.cli ml train --seed 42 --n-estimators 100
```
Options:
- `--manifest`: Path to `manifest.json`.
- `--output`: Path to output model artifact (defaults to `data/ml/forensic_model.joblib`).
- `--n-estimators`: Number of decision trees.

### 3. Evaluate Model
```bash
python -m app.cli ml evaluate
```
Options:
- `--manifest`: Path to `manifest.json`.
- `--model`: Path to model artifact.
- `--eval-all`: Evaluates across all available samples if test set is small.

### 4. Forensic Analysis Command
```bash
python -m app.cli analyze path/to/suspected_leak.pdf
```
Produces a comprehensive report detailing:
1. File validation and byte size.
2. Authoritative cryptographic verification status and recipient attribution (if valid).
3. Selected structural indicators (page count, annotations, carrier presence).
4. Advisory ML classification, model version, and uncalibrated tree vote proportion.
5. Explicit advisory disclaimer.
