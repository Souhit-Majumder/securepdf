# Experimental Steganographic Watermarking for SecurePDF

This directory contains an isolated, modular research prototype exploring **covert text-level steganographic watermarking** in PDF documents via inter-word micro-kerning modulation.

> **Design Principle & Isolation**:
> This experimental prototype is strictly decoupled from the core SecurePDF production codebase (`app/`), the demonstration suite (`demo/`), and existing database/model assets. It maintains its own cryptographic key (`experimental/working/exp_master.key`), tests (`tests/experimental/`), sample documents (`experimental/pdfs/`), and evaluation reports (`experimental/reports/`).

---

## 1. Steganographic Mechanism: TJ Micro-Kerning Modulation

### Why Micro-Kerning over Zero-Width Unicode Characters?
Early prototypes of text steganography often rely on zero-width Unicode characters (such as `\u200b` ZERO WIDTH SPACE or `\u200c` ZERO WIDTH NON-JOINER). However, when evaluated against standard standard Type 1 PostScript PDF fonts (e.g., standard Helvetica `helv` or Times-Roman), PDF viewers and rasterizers map unsupported zero-width code points to visible black replacement glyphs or middle dots (`···`), creating glaring visual defects.

Instead, this prototype operates directly on the PDF vector text stream using the **`TJ` operator**:
- In PDF content streams, text is positioned using alternating strings and glyph displacement numbers:
  ```pdf
  [(Chapter) -25 ( ) (4:) -25 ( ) (Principles)] TJ
  ```
- Kerning values are measured in **thousandths of an em** ($1/1000$ em).
- A negative displacement shifts subsequent text to the right, subtly expanding the inter-word gap by approximately $0.24\text{ to }0.30\text{ pt}$ (at 10–12 pt font size).
- **Encoding Scheme**:
  - Binary `0`: Natural inter-word spacing (`0 ( )`).
  - Binary `1`: Modulated micro-kerning displacement (`-25 ( )`).

### Verification Before Saving
Embedding validates two strict invariants before writing to disk:
1. **Text Equivalence**: Exact text extraction (`page.get_text()`) must be identical before and after embedding.
2. **Rendering Integrity**: Every page must render error-free through the PDF engine (`get_pixmap()`). If either check fails, the operation aborts and rolls back.

---

## 2. Cryptographic Framing & Capacity Budget

### Untruncated 256-Bit HMAC-SHA256
In accordance with Kerckhoffs' principle, steganographic security cannot rely on concealment alone. An adversary who discovers the kerning modulation must still be unable to forge or tamper with recipient attributions. 

Rather than truncating the HMAC tag to 64 bits to artificially reduce payload size, the prototype embeds a **full 256-bit HMAC-SHA256 authentication tag**:

```
[SYNC 4B][VERSION 1B][DOC_LEN 1B][DOC_BYTES][REC_LEN 1B][REC_BYTES][NONCE 16B][HMAC-SHA256 32B][CRC-32 4B]
```

- **Sync Preamble (`SPDF`)**: 32 bits (enables framing synchronization even if text is prepended).
- **Protocol Version**: 8 bits (`0x01`).
- **Document UID**: Variable length ($8 \times L_{\text{doc}}$ bits, e.g., 96 bits for `DOC-BENCH-01`).
- **Recipient UID**: Variable length ($8 \times L_{\text{rec}}$ bits, e.g., 104 bits for `STU-EXP-ALICE`).
- **Cryptographic Nonce**: 128 bits (16 bytes fresh entropy, preventing replay and tag collision).
- **HMAC-SHA256 Tag**: 256 bits (32 bytes under isolated master key).
- **CRC-32 Checksum**: 32 bits (integrity validation before cryptographic verification).

### Capacity Calculation & Low-Capacity Handling
The complete frame requires approximately **664 to 700 bits** (word gaps):
$$\text{Required Bits} = (4 + 1 + 1 + L_{\text{doc}} + 1 + L_{\text{rec}} + 16 + 32 + 4) \times 8$$

When a document has fewer word boundaries than required bits, the system **fails closed** by raising `InsufficientCapacityError`, reporting the exact deficit rather than truncating security margins:
```
InsufficientCapacityError: Document capacity insufficient: requires 688 word gaps, 
but document only has 39 word gaps (deficit: 649 bits).
```

---

## 3. Command-Line Interface (CLI)

The CLI (`experimental/cli.py`) provides standalone commands without touching application databases:

### 1. Embed Watermark
```bash
python experimental/cli.py embed \
  --input experimental/pdfs/sample_lecture.pdf \
  --output experimental/output/watermarked_lecture.pdf \
  --doc-uid DOC-BENCH-01 \
  --recipient-uid STU-EXP-ALICE
```

### 2. Extract and Authenticate
```bash
python experimental/cli.py extract \
  --input experimental/output/watermarked_lecture.pdf
```
*Output:*
```
Extraction Status : AUTHENTICATED
Extraction Method : stream_parsing
Bits Recovered    : 800
Document UID      : DOC-BENCH-01
Recipient UID     : STU-EXP-ALICE
HMAC-SHA256 Valid : True
Diagnostic Reason : Valid HMAC-SHA256 authentication.
```

### 3. Visual Comparison & Difference Heatmap
```bash
python experimental/cli.py compare \
  --original experimental/pdfs/sample_lecture.pdf \
  --watermarked experimental/output/watermarked_lecture.pdf \
  --diff-image experimental/reports/visual_diff.png
```

### 4. Multi-Vector Attack Benchmark & Chart Generation
```bash
python experimental/cli.py evaluate \
  --input experimental/pdfs/sample_lecture.pdf \
  --doc-uid DOC-BENCH-01 \
  --recipient-uid STU-EXP-ALICE
```

---

## 4. Empirical Evaluation Results

The evaluation suite subjects watermarked documents to 8 controlled scenarios. Results are saved in `experimental/reports/stego_benchmark_results.json` and plotted in `experimental/charts/`.

| Scenario | Description | Status | HMAC Valid | Bit Error Rate (BER) | Rendered PSNR |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **00 Baseline** | Plain un-watermarked PDF (false-positive test) | `NO_WATERMARK` | False | 1.00 | $\infty$ (999.0 dB) |
| **01 Untouched** | Pristine watermarked document | `AUTHENTICATED` | **True** | **0.00** | 18.03 dB |
| **02 Benign Re-Save** | PyMuPDF save with garbage collection & deflate | `AUTHENTICATED` | **True** | **0.00** | $\infty$ (999.0 dB) |
| **03 Metadata Mod** | Title and Author altered in catalog dictionary | `AUTHENTICATED` | **True** | **0.00** | 18.03 dB |
| **04 Appended Text** | Extraneous text banner added to page | `AUTHENTICATED` | **True** | **0.00** | 34.21 dB |
| **05 Page Reorder** | Pages reversed `[N..1]` | `NO_WATERMARK` | False | 1.00 | 18.03 dB |
| **06 Margin Crop** | 10 pt margins cropped on all pages | `AUTHENTICATED` | **True** | **0.00** | 18.03 dB |
| **07 Rasterization** | Print-scan / bitmap rasterization (150 DPI) | `NO_WATERMARK` | False | 1.00 | 42.50 dB |

### Visual Distortion Analysis
- **Changed Pixels Ratio**: Approximately **$3.8\% \text{ to } 4.9\%$** of pixels differ when compared at 150 DPI due to sub-pixel glyph rasterization shifts across modulated lines.
- **PSNR**: Average PSNR is **$\approx 18.0\text{ to }23.3\text{ dB}$** when computed against un-watermarked text. While casual human readers do not notice the $0.24\text{ pt}$ space adjustment, pixel-level automated comparators easily detect the shift.
- **Imperceptibility Claim Boundary**: The watermark is **not steganographically invisible to automated pixel difference comparators**, although it preserves typography, line layout, and copy-paste text extraction without human-visible defects.

---

## 5. Security Boundaries & Failure Modes

1. **Carrier Inherent Limitation (Rasterization & Print-Scan)**:
   - Text-kerning watermarks exist exclusively as vector operators inside PDF content streams (`TJ`).
   - Rasterizing pages to bitmaps (or printing and scanning) destroys the vector carrier entirely. Extraction reports `NO_WATERMARK` with $100\%$ Bit Error Rate.
2. **Page Permutation Vulnerability**:
   - Because the 672-bit payload is distributed sequentially across pages, page order disruption breaks the bit framing, causing authentication to fail.
3. **Dual-Track Extraction**:
   - Stream parsing is the primary, reliable decoding mechanism.
   - Geometric bounding-box gap extraction is an experimental alternative sensitive to font metrics and sub-pixel rounding.
4. **Content Integrity**:
   - A valid watermark proves **recipient attribution**, not entire document content immutability. An attacker can append external content without invalidating the embedded kerning watermark.

---

## 6. Generated Artifacts

- **Reports**:
  - `experimental/reports/stego_benchmark_results.json`: Machine-readable benchmark metrics.
  - `experimental/reports/stego_benchmark_results.csv`: Tabular scenario summary.
  - `experimental/reports/visual_diff.png`: 3-panel figure showing original, watermarked, and difference heatmap.
- **Charts**:
  - `experimental/charts/01_watermark_survival_by_attack.png`: Authentication survival across attack scenarios.
  - `experimental/charts/02_bit_error_rate_by_attack.png`: Bit Error Rate (BER) by attack vector.
  - `experimental/charts/03_visual_distortion_psnr_mse.png`: PSNR and visual distortion distribution.
  - `experimental/charts/04_capacity_and_payload_breakdown.png`: Full HMAC-SHA256 capacity budget breakdown.
