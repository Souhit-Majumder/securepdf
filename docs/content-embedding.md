# Phase II Step 1: Content-Based Embedding Research

## Objective
Investigate and prototype a PDF page/content-stream based embedding mechanism (Layer 2) that can survive structural operations that destroy Catalog-based (Layer 1) fingerprints, specifically:
- Page Extraction (copying pages to a new PDF)
- Page Reordering

## Methodology
Two candidate carriers were evaluated using `PyMuPDF`:
1. **Page Dictionary (`/SPDFPagePayload`)**: Storing a custom key directly on the Page dictionary (similar to the Catalog method, but page-specific).
2. **Invisible Annotation**: Creating a 0.1x0.1 rectangle annotation at the origin (0,0) with no stroke/fill, configured with standard PDF flags `Hidden`, `Invisible`, and `NoView`. The payload is stored in the annotation's content/title dictionary.

Both mechanisms were subjected to an automated test suite (`tests/test_content_embedding.py`) covering:
1. Rendered visual equivalence (pixel-for-pixel comparison).
2. Reliable extraction.
3. PyMuPDF normal re-save and garbage collection (optimization).
4. Page extraction into a brand new PDF.
5. Page reordering (using `doc.select()`).

## Experimental Results

| Test | Page Dictionary Carrier | Invisible Annotation Carrier |
| :--- | :--- | :--- |
| **Visually null / Render unchanged?** | ✅ Yes | ✅ Yes |
| **Extraction Reliable?** | ✅ Yes | ✅ Yes |
| **Optimization/Re-save Survival** | ✅ Yes | ✅ Yes |
| **Page Extraction Survival** | ❌ No | ✅ Yes |
| **Page Reordering Survival** | ❌ No | ✅ Yes |

### Analysis
*   **Page Dictionary Carrier**: Failed on both page extraction and reordering. PyMuPDF's `insert_pdf` and `select` functions rebuild the page tree and intentionally discard unknown/custom dictionary keys from the Page object, just as they do with the Catalog object.
*   **Invisible Annotation Carrier**: Survived **all** tests. Annotations are standard PDF objects residing in the `/Annots` array of a page. Because they are officially recognized by the PDF specification, PyMuPDF faithfully copies them when a page is extracted or reordered. Furthermore, the `Hidden`, `Invisible`, and `NoView` flags ensure the annotation completely avoids rendering, leaving the visual output mathematically identical.

## Conclusion & Architecture Decision
The **Invisible Annotation** mechanism successfully acts as a "visually-null PDF content operation" capable of carrying our payload and surviving structural rebuilds.

This makes it an ideal candidate for **Layer 2**. In Phase II, we will implement this alongside the existing Catalog mechanism to provide robust redundancy against accidental document transformations.

---

# Phase II Step 2: Content Layer Payload Design and Redundancy

## Payload Design & Compact Encoding
The Layer 2 payload does not need to store the student's name or UID (this is handled post-verification via the database attribution step). It only strictly requires:
- A version identifier
- `document_uid`
- `nonce`
- The `HMAC-SHA256` authenticity tag

To minimize payload size, we convert the 64-character hexadecimal HMAC string into its raw 32 bytes, and then encode it via Base64 (resulting in 44 characters). 
*   **Original Hex Payload Size:** ~92 bytes
*   **Compact Base64 Payload Size:** ~70 bytes

This represents a ~24% reduction in payload size, making the annotation string footprint lighter without compromising any cryptographic properties. The format is explicitly versioned as `SPDF1`.

## Redundancy Strategy
A single annotation can be trivially deleted by a PDF editor or a malicious student. To counter this, we designed a **redundancy strategy** where multiple independent invisible annotations are placed on the page (e.g., slightly offset from each other so they are not merged by PDF optimizers).

The behavior was evaluated in an automated suite (`tests/test_redundancy.py`) with 3 redundant annotations:

| Attack / Scenario | Extracted Payloads | Verification State |
| :--- | :--- | :--- |
| **Delete 1 Annotation** | 2 valid | ✅ **VALID** (2 intact copies remain) |
| **Tamper 1 Annotation** | 2 valid, 1 tampered | ✅ **VALID** (The tampered payload fails HMAC verification and is rejected; the 2 intact copies pass) |
| **Delete ALL Annotations** | 0 | ❌ **ERROR** (No payload found) |
| **Page Reordering** | 2 valid (on reordered page) | ✅ **VALID** |

### Security Behavior
The redundancy logic perfectly complements the **Verify Before Trust** architecture. If an attacker modifies an annotation (e.g., changing the payload string or attempting to splice a different document UID), the system will extract it, reconstruct the canonical message, and run the HMAC check. Because the attacker lacks the `master_key`, the modified annotation will mathematically fail the HMAC check and be discarded as invalid. The system will continue evaluating any remaining redundant annotations until one passes.

If no annotation passes the HMAC check, attribution fails entirely. A partially damaged or modified payload is never accepted.
