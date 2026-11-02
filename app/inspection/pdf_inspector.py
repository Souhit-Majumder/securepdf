"""
Read-Only Structural Inspector for SecurePDF.

Mandatory Guarantees:
- Strictly read-only: no clean_contents(), update_stream(), PDF saves,
  database access, worker subprocesses, or mutations of the source PDF.
- Reuses shared production functions from app.pdf.stego:
  - extract_bits_from_stream
  - parse_stego_bitstream
  - count_available_word_gaps
- Classifies arbitrary kerning as OBSERVED_SYNTAX; classifies as
  STRUCTURALLY_DECODED only when parse_stego_bitstream validates SPDF frame and CRC.
- Static inspection NEVER reports AUTHENTICATED.
- get_page_modulations() clearly labels telemetry_source="STRUCTURAL_RESCAN"
  and reports uncompressed in-memory stream offsets (not physical file offsets).
"""
from __future__ import annotations

import datetime
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
import fitz

from app.inspection.models import (
    CatalogLocation,
    AnnotationLocation,
    ContentStreamLocation,
    ModulationSample,
    CarrierVerificationStatus,
    CarrierInspectionResult,
    SubjectEvidence,
    CrossLayerEvidence,
    EvidenceReport,
    AuthorizationContext,
    create_subject_ref,
    create_evidence_ref,
    redact_subject_evidence,
)
from app.pdf.payload_redundancy import decode_compact_payload
from app.pdf.stego.embed import count_available_word_gaps
from app.pdf.stego.extract import extract_bits_from_stream, MIN_KERNING_THRESHOLD
from app.pdf.stego.framing import parse_stego_bitstream, StegoPayload


def _matrix_mult(m1: Tuple[float, ...], m2: Tuple[float, ...]) -> Tuple[float, float, float, float, float, float]:
    """Row-vector 3x3 matrix multiplication: [x, y, 1] * m1 * m2."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _transform_point(p: Tuple[float, float], m: Tuple[float, float, float, float, float, float]) -> Tuple[float, float]:
    x, y = p
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def _is_valid_orthogonal(m: Tuple[float, float, float, float, float, float]) -> bool:
    """Checks if composite matrix is non-singular and has no shear (orthogonal rotation/scale)."""
    a, b, c, d, _, _ = m
    det = a * d - b * c
    if abs(det) < 1e-6:
        return False
    dot = a * c + b * d
    if abs(dot) > 1e-3:
        return False
    return True


BASEFONT_ALIASES: Dict[str, str] = {
    "TimesNewRomanPSMT": "times-roman",
    "TimesNewRomanPS-BoldMT": "times-bold",
    "TimesNewRomanPS-ItalicMT": "times-italic",
    "TimesNewRomanPS-BoldItalicMT": "times-bolditalic",
    "ArialMT": "helv",
    "Arial-BoldMT": "helv",
    "Arial-ItalicMT": "helv",
    "Arial-BoldItalicMT": "helv",
    "CourierNewPSMT": "couri",
    "CourierNewPS-BoldMT": "couri",
    "SymbolMT": "symb",
}


class FontMetricsCache:
    """Read-only font metrics resolver for a specific page."""

    def __init__(self, doc: fitz.Document, page: fitz.Page):
        self.doc = doc
        self.page = page
        self._fonts: Dict[str, Dict[str, Any]] = {}
        self._build_cache()

    def _build_cache(self):
        try:
            for font_item in self.page.get_fonts(full=True):
                xref, ext, ftype, basefont, name, enc, _ = font_item
                fname = name.lstrip("/") if name else ""

                is_type3 = (ftype == "Type3")
                type3_reliable = False
                widths_map: Dict[int, float] = {}
                first_char = 0
                ascender = 1.075
                descender = -0.299

                # 1. Resolve FontDescriptor for ascent and descent metrics
                try:
                    fd_val = self.doc.xref_get_key(xref, "FontDescriptor")
                    if fd_val[0] == "xref":
                        fd_xref = int(fd_val[1].split()[0])
                        asc_val = self.doc.xref_get_key(fd_xref, "Ascent")
                        desc_val = self.doc.xref_get_key(fd_xref, "Descent")
                        if asc_val[0] == "int":
                            ascender = float(asc_val[1]) / 1000.0
                        if desc_val[0] == "int":
                            descender = float(desc_val[1]) / 1000.0
                except Exception:
                    pass

                # 2. Resolve /Widths array (handles direct array and indirect xref)
                try:
                    fc_val = self.doc.xref_get_key(xref, "FirstChar")
                    w_val = self.doc.xref_get_key(xref, "Widths")
                    first_char = int(fc_val[1]) if fc_val[0] == "int" else 0
                    raw_w_str = ""
                    if w_val[0] == "array":
                        raw_w_str = w_val[1]
                    elif w_val[0] == "xref":
                        w_xref = int(w_val[1].split()[0])
                        raw_w_str = self.doc.xref_object(w_xref)

                    if raw_w_str:
                        raw_w = raw_w_str.strip("[] ").split()
                        for c_off, w_entry in enumerate(raw_w):
                            if w_entry:
                                try:
                                    widths_map[first_char + c_off] = float(w_entry)
                                except ValueError:
                                    pass
                        if is_type3 and widths_map:
                            type3_reliable = True
                except Exception:
                    pass

                # 3. Instantiate fitz.Font for advance width calculation
                fitz_font = None
                if not is_type3:
                    if basefont:
                        try:
                            fitz_font = fitz.Font(fontname=basefont)
                        except Exception:
                            clean_name = basefont.split("+")[-1]
                            alias = BASEFONT_ALIASES.get(clean_name) or BASEFONT_ALIASES.get(basefont)
                            if alias:
                                try:
                                    fitz_font = fitz.Font(fontname=alias)
                                except Exception:
                                    fitz_font = None

                    if fitz_font is None and xref > 0:
                        try:
                            f_info = self.doc.extract_font(xref)
                            if f_info and len(f_info) >= 4 and f_info[3]:
                                fitz_font = fitz.Font(fontbuffer=f_info[3])
                        except Exception:
                            fitz_font = None

                    if fitz_font and (ascender == 1.075 or descender == -0.299):
                        try:
                            if hasattr(fitz_font, "ascender") and fitz_font.ascender:
                                ascender = float(fitz_font.ascender)
                            if hasattr(fitz_font, "descender") and fitz_font.descender:
                                descender = float(fitz_font.descender)
                        except Exception:
                            pass

                self._fonts[fname] = {
                    "type": ftype,
                    "is_type3": is_type3,
                    "type3_reliable": type3_reliable,
                    "fitz_font": fitz_font,
                    "widths_map": widths_map,
                    "first_char": first_char,
                    "ascender": ascender,
                    "descender": descender,
                }
        except Exception:
            pass

    def get_font_entry(self, font_name: str) -> Optional[Dict[str, Any]]:
        fname = font_name.lstrip("/")
        return self._fonts.get(fname)

    def get_space_width(self, font_entry: Optional[Dict[str, Any]], font_size: float) -> Optional[float]:
        if font_entry and font_entry.get("is_type3") and not font_entry.get("type3_reliable"):
            return None
        if font_entry:
            widths_map = font_entry.get("widths_map", {})
            if 32 in widths_map:
                return (widths_map[32] / 1000.0) * font_size
            fitz_font = font_entry.get("fitz_font")
            if fitz_font:
                try:
                    return float(fitz_font.text_length(" ", fontsize=font_size))
                except Exception:
                    pass
        return 0.278 * font_size

    def get_string_width(self, font_entry: Optional[Dict[str, Any]], s_bytes: bytes, font_size: float) -> Optional[float]:
        if font_entry and font_entry.get("is_type3") and not font_entry.get("type3_reliable"):
            return None
        if font_entry:
            widths_map = font_entry.get("widths_map", {})
            if widths_map:
                total_w = 0.0
                for b in s_bytes:
                    w0 = widths_map.get(b, 500.0)
                    total_w += (w0 / 1000.0) * font_size
                return total_w
            fitz_font = font_entry.get("fitz_font")
            if fitz_font:
                try:
                    return float(fitz_font.text_length(s_bytes.decode("latin-1", errors="replace"), fontsize=font_size))
                except Exception:
                    pass
        return len(s_bytes) * 0.5 * font_size


class PageLayoutCorroborator:
    """Corroborates operator-calculated space positions against rendered rawdict layout."""

    def __init__(self, page: fitz.Page):
        self.page = page
        self.spaces: List[Dict[str, Any]] = []
        self._load_rendered_spaces()

    def _load_rendered_spaces(self):
        try:
            raw = self.page.get_text("rawdict")
            for block in raw.get("blocks", []):
                for line in block.get("lines", []):
                    line_chars = []
                    for span in line.get("spans", []):
                        line_chars.extend(span.get("chars", []))

                    for i, ch in enumerate(line_chars):
                        if ch.get("c") == " ":
                            prec_chars = "".join([c.get("c", "") for c in line_chars[max(0, i - 12):i]]).split()
                            foll_chars = "".join([c.get("c", "") for c in line_chars[i + 1:min(len(line_chars), i + 13)]]).split()
                            bbox = ch.get("bbox", [0, 0, 0, 0])
                            self.spaces.append({
                                "bbox": [float(v) for v in bbox],
                                "prec": prec_chars[-1] if prec_chars else "",
                                "foll": foll_chars[0] if foll_chars else "",
                            })
        except Exception:
            pass

    def corroborate(
        self,
        pred_rect: List[float],
        prec_word: str,
        foll_word: str = "",
        tolerance_pt: float = 1.5,
    ) -> Tuple[Literal["EXACT", "APPROXIMATE", "UNAVAILABLE"], Optional[List[float]]]:
        if not self.spaces:
            return "UNAVAILABLE", None

        pcx = (pred_rect[0] + pred_rect[2]) / 2.0
        pcy = (pred_rect[1] + pred_rect[3]) / 2.0
        pw = pred_rect[2] - pred_rect[0]
        ph = pred_rect[3] - pred_rect[1]

        matches = []
        for s in self.spaces:
            rx0, ry0, rx1, ry1 = s["bbox"]
            rcx = (rx0 + rx1) / 2.0
            rcy = (ry0 + ry1) / 2.0
            rw = rx1 - rx0
            rh = ry1 - ry0

            dx = abs(pcx - rcx)
            dy = abs(pcy - rcy)
            dw = abs(pw - rw)
            dh = abs(ph - rh)

            if dx <= tolerance_pt and dy <= tolerance_pt and dw <= tolerance_pt and dh <= 2.5:
                context_match = False
                if prec_word and s["prec"]:
                    if prec_word.endswith(s["prec"]) or s["prec"].endswith(prec_word):
                        context_match = True
                matches.append((s["bbox"], context_match))

        # Require both geometric proximity and matching preceding-word context for EXACT
        ctx_matches = [m for m in matches if m[1]]
        if len(ctx_matches) == 1:
            return "EXACT", [round(v, 2) for v in ctx_matches[0][0]]
        elif matches:
            # Candidate(s) within geometric tolerance, but context not established or ambiguous
            return "APPROXIMATE", [round(v, 2) for v in pred_rect]

        # Check for plausible correspondence (within reasonable neighborhood of a rendered space)
        for s in self.spaces:
            rcx = (s["bbox"][0] + s["bbox"][2]) / 2.0
            rcy = (s["bbox"][1] + s["bbox"][3]) / 2.0
            if abs(pcx - rcx) <= 10.0 and abs(pcy - rcy) <= 10.0:
                return "APPROXIMATE", [round(v, 2) for v in pred_rect]

        return "UNAVAILABLE", None


class PdfStructuralInspector:
    """
    Performs purely read-only structural analysis on cold PDFs.
    Zero side-effects: never modifies, cleans, compresses, or writes PDFs,
    and never queries or writes to SQLite databases.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or hashlib.sha256(str(id(self)).encode()).hexdigest()[:12]
        self._ref_map: Dict[str, str] = {}
        self._ref_counters: Dict[str, int] = {}

    def _get_or_create_ref(self, prefix: str, secret_or_token: str | bytes) -> str:
        """Maps a sensitive token to an opaque reference token without storing raw values."""
        if isinstance(secret_or_token, bytes):
            token_bytes = secret_or_token
        else:
            token_bytes = str(secret_or_token).encode("utf-8")

        lookup_key = f"{prefix}:{hashlib.sha256(self.session_id.encode() + token_bytes).hexdigest()}"
        if lookup_key in self._ref_map:
            return self._ref_map[lookup_key]

        count = self._ref_counters.get(prefix, 0) + 1
        self._ref_counters[prefix] = count
        ref = create_evidence_ref(prefix, count)
        self._ref_map[lookup_key] = ref
        return ref

    def inspect_pdf(
        self,
        pdf_input: str | Path | fitz.Document,
        auth_ctx: Optional[AuthorizationContext] = None,
    ) -> EvidenceReport:
        """
        Performs read-only inspection of Catalog, Annotations, and TJ Kerning.
        Never calls clean_contents(), update_stream(), or save().
        """
        auth = auth_ctx or AuthorizationContext(principal="read_only_inspector", has_pii_clearance=False)
        should_close = False

        if isinstance(pdf_input, (str, Path)):
            doc = fitz.open(str(pdf_input))
            should_close = True
        else:
            doc = pdf_input

        try:
            return self._inspect_doc(doc, auth)
        finally:
            if should_close:
                doc.close()

    def _inspect_doc(self, doc: fitz.Document, auth_ctx: AuthorizationContext) -> EvidenceReport:
        doc_uid = "UNKNOWN"
        subject_ref = "subj_anon_unknown"
        extracted_student_uid: Optional[str] = None

        # -------------------------------------------------------------
        # 1. Layer 1: Catalog Inspection (Read-Only)
        # -------------------------------------------------------------
        l1_result = self._inspect_layer1(doc)
        if l1_result.details.get("document_uid"):
            doc_uid = l1_result.details["document_uid"]

        # -------------------------------------------------------------
        # 2. Layer 2: Annotation Inspection (Read-Only)
        # -------------------------------------------------------------
        l2_result = self._inspect_layer2(doc)
        if doc_uid == "UNKNOWN" and l2_result.details.get("document_uid"):
            doc_uid = l2_result.details["document_uid"]

        # -------------------------------------------------------------
        # 3. Layer 3: Steganographic Content Stream Inspection (Read-Only)
        # -------------------------------------------------------------
        l3_result, l3_payload = self._inspect_layer3(doc)
        if l3_payload:
            if doc_uid == "UNKNOWN":
                doc_uid = l3_payload.document_uid
            extracted_student_uid = l3_payload.recipient_uid
            subject_ref = create_subject_ref(l3_payload.recipient_uid, session_salt=self.session_id)

        # -------------------------------------------------------------
        # 4. Cross-Layer Analysis
        # -------------------------------------------------------------
        sig_pool = [s for s in [l1_result.signature_ref, l2_result.signature_ref, l3_result.signature_ref] if s]
        unique_sigs = set(sig_pool)
        sigs_match = (len(unique_sigs) == 1) if len(sig_pool) >= 2 else None
        cross_conflict = (len(unique_sigs) > 1) or (l2_result.status == "SECURITY_CONFLICT")

        conflict_reason = None
        if cross_conflict:
            conflict_reason = "Cross-carrier signature reference mismatch" if len(unique_sigs) > 1 else "Internal carrier conflict"

        cross_layer = CrossLayerEvidence(
            l1_signature_ref=l1_result.signature_ref,
            l2_signature_refs=[l2_result.signature_ref] if l2_result.signature_ref else [],
            l3_signature_ref=l3_result.signature_ref,
            signatures_match=sigs_match,
            cross_carrier_conflict=cross_conflict,
            conflict_reason=conflict_reason,
        )

        # Determine overall structural status (never AUTHENTICATED)
        if cross_conflict:
            overall_status = "SECURITY_CONFLICT"
        elif any(c.status == "STRUCTURALLY_DECODED" for c in [l1_result, l2_result, l3_result]):
            overall_status = "STRUCTURALLY_DECODED"
        elif any(c.status == "OBSERVED_SYNTAX" for c in [l1_result, l2_result, l3_result]):
            overall_status = "OBSERVED_SYNTAX"
        elif all(c.status == "NOT_FOUND" for c in [l1_result, l2_result, l3_result]):
            overall_status = "NOT_FOUND"
        else:
            overall_status = "INVALID"

        # Apply trusted PII redaction
        subject = SubjectEvidence(
            subject_ref=subject_ref,
            student_uid=extracted_student_uid,
            student_name=None,  # Static inspection has no DB access; name is never available
        )
        safe_subject = redact_subject_evidence(subject, auth_ctx)

        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        return EvidenceReport(
            document_uid=doc_uid,
            overall_status=overall_status,
            subject=safe_subject,
            carriers=[l1_result, l2_result, l3_result],
            cross_layer=cross_layer,
            telemetry_source="READ_ONLY_INSPECTION",
            timestamp=timestamp,
        )

    def _inspect_layer1(self, doc: fitz.Document) -> CarrierInspectionResult:
        """Inspects PDF Catalog dictionary for /SPDFPayload key."""
        catalog_xref = doc.pdf_catalog()
        key_val = doc.xref_get_key(catalog_xref, "SPDFPayload")

        if key_val[0] == "null":
            return CarrierInspectionResult(
                carrier_name="Layer 1 (Catalog)",
                status="NOT_FOUND",
            )

        val_str = key_val[1]
        if key_val[0] == "string" and val_str.startswith("SPDF-V1"):
            parts = val_str.split("|")
            if len(parts) == 4:
                _, doc_uid, nonce_hex, fp_hex = parts
                sig_ref = self._get_or_create_ref("sig", fp_hex)
                nonce_ref = self._get_or_create_ref("nonce", nonce_hex)
                loc = CatalogLocation(catalog_xref=catalog_xref)
                return CarrierInspectionResult(
                    carrier_name="Layer 1 (Catalog)",
                    status="STRUCTURALLY_DECODED",
                    locations=[loc],
                    signature_ref=sig_ref,
                    nonce_ref=nonce_ref,
                    details={"document_uid": doc_uid, "version": "SPDF-V1"},
                )

        return CarrierInspectionResult(
            carrier_name="Layer 1 (Catalog)",
            status="OBSERVED_SYNTAX",
            locations=[CatalogLocation(catalog_xref=catalog_xref)],
            details={"raw_type": key_val[0]},
        )

    def _inspect_layer2(self, doc: fitz.Document) -> CarrierInspectionResult:
        """Inspects Page 0 invisible annotations for SPDF* payloads."""
        if doc.page_count == 0:
            return CarrierInspectionResult(
                carrier_name="Layer 2 (Annotations)",
                status="NOT_FOUND",
            )

        page = doc[0]
        locations: List[AnnotationLocation] = []
        decoded_payloads: List[Tuple[str, str, str, str]] = []

        for annot in page.annots():
            info = annot.info
            title = info.get("title", "")
            if title.startswith("SPDF") and "content" in info:
                rect = [annot.rect.x0, annot.rect.y0, annot.rect.x1, annot.rect.y1]
                loc = AnnotationLocation(
                    page_index=0,
                    annotation_xref=annot.xref,
                    rect=rect,
                    flags=annot.flags,
                    opacity=annot.opacity,
                    title=title,
                )
                locations.append(loc)
                try:
                    ver, d_uid, nonce_str, hmac_hex = decode_compact_payload(info["content"])
                    decoded_payloads.append((ver, d_uid, nonce_str, hmac_hex))
                except Exception:
                    pass

        if not locations:
            return CarrierInspectionResult(
                carrier_name="Layer 2 (Annotations)",
                status="NOT_FOUND",
            )

        if not decoded_payloads:
            return CarrierInspectionResult(
                carrier_name="Layer 2 (Annotations)",
                status="OBSERVED_SYNTAX",
                locations=locations,
                details={"annotation_count": len(locations)},
            )

        # Check for internal consistency across redundant copies
        first_ver, first_doc, first_nonce, first_hmac = decoded_payloads[0]
        internal_conflict = False
        for _, d_uid, n_str, h_hex in decoded_payloads[1:]:
            if (d_uid, n_str, h_hex) != (first_doc, first_nonce, first_hmac):
                internal_conflict = True
                break

        primary_sig_ref = self._get_or_create_ref("sig", first_hmac)
        primary_nonce_ref = self._get_or_create_ref("nonce", first_nonce)

        return CarrierInspectionResult(
            carrier_name="Layer 2 (Annotations)",
            status="SECURITY_CONFLICT" if internal_conflict else "STRUCTURALLY_DECODED",
            locations=locations,
            signature_ref=primary_sig_ref,
            nonce_ref=primary_nonce_ref,
            details={
                "document_uid": first_doc,
                "version": first_ver,
                "copies_found": len(locations),
                "internal_conflict": internal_conflict,
            },
        )

    def _inspect_layer3(
        self,
        doc: fitz.Document,
    ) -> Tuple[CarrierInspectionResult, Optional[StegoPayload]]:
        """
        Inspects content streams for steganographic TJ kerning using shared production logic.
        Reuses extract_bits_from_stream, parse_stego_bitstream, and count_available_word_gaps.
        """
        total_gaps = count_available_word_gaps(doc)

        # Extract bits from all page streams without calling clean_contents()
        all_bits: List[str] = []
        for page in doc:
            c_xrefs = page.get_contents()
            for xref in c_xrefs:
                stream_bytes = doc.xref_stream(xref)
                if stream_bytes:
                    bits = extract_bits_from_stream(stream_bytes, threshold=MIN_KERNING_THRESHOLD)
                    all_bits.append(bits)

        combined_bits = "".join(all_bits)

        if not combined_bits or total_gaps == 0:
            return (
                CarrierInspectionResult(
                    carrier_name="Layer 3 (Stego Kerning)",
                    status="NOT_FOUND",
                    total_word_gaps=total_gaps,
                ),
                None,
            )

        # Parse using shared production framing logic
        parse_result = parse_stego_bitstream(combined_bits)

        if parse_result.crc_valid and parse_result.payload:
            payload = parse_result.payload
            sig_ref = self._get_or_create_ref("sig", payload.hmac_tag)
            nonce_ref = self._get_or_create_ref("nonce", payload.nonce)
            bit_len = payload.total_bits

            # Multi-page sampling: sample up to 8 modulations per carrier-bearing page, max 40 across document
            samples: List[ModulationSample] = []
            loc_counter = 0
            bits_remaining = bit_len

            for p_idx in range(doc.page_count):
                if bits_remaining <= 0 or len(samples) >= 40:
                    break
                page = doc[p_idx]
                c_xrefs = page.get_contents()
                page_carrier_gaps = 0
                for xref in c_xrefs:
                    st = doc.xref_stream(xref)
                    if st:
                        page_carrier_gaps += len(extract_bits_from_stream(st, threshold=MIN_KERNING_THRESHOLD))
                if page_carrier_gaps == 0:
                    continue

                page_carrier_bits = min(page_carrier_gaps, bits_remaining)
                page_sample_limit = min(8, 40 - len(samples), page_carrier_bits)
                page_samples = self.get_page_modulations(
                    doc,
                    page_index=p_idx,
                    offset=0,
                    limit=page_sample_limit,
                    is_framed=True,
                    start_location_idx=loc_counter,
                    max_carrier_bits=page_carrier_bits,
                )
                samples.extend(page_samples)
                loc_counter += len(page_samples)
                bits_remaining -= page_carrier_bits

            return (
                CarrierInspectionResult(
                    carrier_name="Layer 3 (Stego Kerning)",
                    status="STRUCTURALLY_DECODED",
                    locations=[s.location for s in samples],
                    signature_ref=sig_ref,
                    nonce_ref=nonce_ref,
                    total_word_gaps=total_gaps,
                    modulated_word_gaps=bit_len,
                    bit_1_count=combined_bits[:bit_len].count("1") if len(combined_bits) >= bit_len else None,
                    bit_0_count=combined_bits[:bit_len].count("0") if len(combined_bits) >= bit_len else None,
                    modulation_samples=samples,
                    details={
                        "document_uid": payload.document_uid,
                        "recipient_uid": payload.recipient_uid,
                        "frame_detected": True,
                        "crc_valid": True,
                    },
                ),
                payload,
            )
        elif parse_result.frame_detected:
            # Sync preamble found, but CRC-32 failed
            return (
                CarrierInspectionResult(
                    carrier_name="Layer 3 (Stego Kerning)",
                    status="INVALID",
                    locations=[],
                    total_word_gaps=total_gaps,
                    modulation_samples=[],
                    details={
                        "frame_detected": True,
                        "crc_valid": False,
                        "error": parse_result.error,
                    },
                ),
                None,
            )
        else:
            # Preamble not found: arbitrary kerning syntax observed in typesetting (zero carrier locations)
            return (
                CarrierInspectionResult(
                    carrier_name="Layer 3 (Stego Kerning)",
                    status="OBSERVED_SYNTAX",
                    locations=[],
                    total_word_gaps=total_gaps,
                    modulation_samples=[],
                    details={
                        "frame_detected": False,
                        "crc_valid": False,
                        "extracted_bit_count": len(combined_bits),
                    },
                ),
                None,
            )

    def get_page_modulations(
        self,
        doc: fitz.Document,
        page_index: int,
        offset: int = 0,
        limit: int = 50,
        is_framed: bool = False,
        start_location_idx: int = 0,
        max_carrier_bits: Optional[int] = None,
    ) -> List[ModulationSample]:
        """
        On-demand structural re-scan of a specific page's content streams.
        Returns paginated ModulationSample items with telemetry_source="STRUCTURAL_RESCAN".
        Offset refers strictly to the uncompressed, in-memory stream byte offset.
        """
        if not (0 <= page_index < doc.page_count):
            return []

        page = doc[page_index]
        c_xrefs = page.get_contents()
        all_samples: List[ModulationSample] = []
        gap_counter = 0

        # Build font cache and layout corroborator once per page
        font_cache = FontMetricsCache(doc, page)
        corroborator = PageLayoutCorroborator(page)

        remaining_carrier_bits = max_carrier_bits
        for xref in c_xrefs:
            stream = doc.xref_stream(xref)
            if not stream:
                continue

            stream_samples = self._parse_stream_for_samples(
                stream=stream,
                page_index=page_index,
                stream_xref=xref,
                start_gap_idx=gap_counter,
                is_framed=is_framed,
                page=page,
                font_cache=font_cache,
                corroborator=corroborator,
                start_location_idx=start_location_idx + len(all_samples),
                max_carrier_bits=remaining_carrier_bits,
            )
            all_samples.extend(stream_samples)
            gap_counter += len(stream_samples)
            if remaining_carrier_bits is not None:
                remaining_carrier_bits = max(0, remaining_carrier_bits - len(stream_samples))

        # Apply deterministic pagination
        return all_samples[offset : offset + limit]

    def _parse_stream_for_samples(
        self,
        stream: bytes,
        page_index: int,
        stream_xref: int,
        start_gap_idx: int,
        is_framed: bool,
        page: Optional[fitz.Page] = None,
        font_cache: Optional[FontMetricsCache] = None,
        corroborator: Optional[PageLayoutCorroborator] = None,
        start_location_idx: int = 0,
        max_carrier_bits: Optional[int] = None,
    ) -> List[ModulationSample]:
        """
        Parses uncompressed page stream for TJ array inter-word gaps using operator-level text-state tracking.
        Derives space positions in PyMuPDF page coordinates and corroborates against rendered page geometry.
        """
        samples: List[ModulationSample] = []
        i = 0
        n = len(stream)
        gap_idx = start_gap_idx
        sample_loc_counter = start_location_idx
        carrier_samples_count = 0
        last_word = ""

        # CropBox geometry
        if page:
            cb = page.cropbox
            cx0, cy0, cx1, cy1 = float(cb.x0), float(cb.y0), float(cb.x1), float(cb.y1)
        else:
            cx0, cy0, cx1, cy1 = 0.0, 0.0, 595.0, 842.0

        # PDF Graphics and Text State tracking
        ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        gs_stack: List[Tuple[float, float, float, float, float, float]] = []
        Tm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        Tlm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        x_text = 0.0
        current_font_name = ""
        current_font_entry: Optional[Dict[str, Any]] = None
        font_size = 11.0
        T_c = 0.0
        T_w = 0.0
        T_h = 100.0
        T_l = 0.0
        T_rise = 0.0
        operands: List[str] = []

        while i < n:
            b = stream[i:i + 1]

            if b in b" \t\r\n\x00\x0c":
                i += 1
            elif b == b"%":
                while i < n and stream[i:i + 1] not in b"\r\n":
                    i += 1
            elif b == b"q":
                gs_stack.append(ctm)
                operands.clear()
                i += 1
            elif b == b"Q":
                if gs_stack:
                    ctm = gs_stack.pop()
                operands.clear()
                i += 1
            elif b == b"(":
                # Literal string outside array (e.g. standard Tj operator)
                s_start = i
                i += 1
                depth = 1
                while i < n and depth > 0:
                    if stream[i:i + 1] == b"\\" and i + 1 < n:
                        i += 2
                        continue
                    elif stream[i:i + 1] == b"(":
                        depth += 1
                    elif stream[i:i + 1] == b")":
                        depth -= 1
                    i += 1
                raw_str = stream[s_start:i]
                inner = raw_str[1:-1]
                parts = inner.split(b" ")
                if len(parts) > 1:
                    curr_offset = s_start + 1
                    for p_idx, part in enumerate(parts[:-1]):
                        space_offset = curr_offset + len(part)
                        prec_word = part.decode("latin-1", errors="replace")
                        if not is_framed:
                            loc = ContentStreamLocation(
                                page_index=page_index,
                                content_stream_xref=stream_xref,
                                gap_index=gap_idx,
                                content_stream_offset=space_offset,
                                preceding_word=prec_word,
                                displacement=0,
                                bit_value=None,
                                location_index=sample_loc_counter,
                                localization_status="UNAVAILABLE",
                                is_carrier_sample=False,
                                rect=None,
                            )
                            samples.append(
                                ModulationSample(
                                    location=loc,
                                    is_intentional_modulation=False,
                                    source="STRUCTURAL_RESCAN",
                                )
                            )
                            sample_loc_counter += 1
                        gap_idx += 1
                        curr_offset = space_offset + 1
                    last_word = parts[-1].decode("latin-1", errors="replace")
                else:
                    last_word = inner.decode("latin-1", errors="replace")
                if font_cache:
                    w_adv = font_cache.get_string_width(current_font_entry, inner, font_size)
                    if w_adv is not None:
                        x_text += w_adv * (T_h / 100.0)
            elif b == b"<":
                if stream[i:i + 2] == b"<<":
                    i += 2
                else:
                    h_start = i
                    i += 1
                    while i < n and stream[i:i + 1] != b">":
                        i += 1
                    if i < n:
                        i += 1
                    raw_hex = stream[h_start:i]
                    try:
                        decoded_bytes = bytes.fromhex(raw_hex[1:-1].decode("ascii", errors="replace"))
                        if b" " in decoded_bytes:
                            parts = decoded_bytes.split(b" ")
                            for p_idx, part in enumerate(parts[:-1]):
                                prec_word = part.decode("latin-1", errors="replace")
                                if not is_framed:
                                    loc = ContentStreamLocation(
                                        page_index=page_index,
                                        content_stream_xref=stream_xref,
                                        gap_index=gap_idx,
                                        content_stream_offset=h_start,
                                        preceding_word=prec_word,
                                        displacement=0,
                                        bit_value=None,
                                        location_index=sample_loc_counter,
                                        localization_status="UNAVAILABLE",
                                        is_carrier_sample=False,
                                        rect=None,
                                    )
                                    samples.append(
                                        ModulationSample(
                                            location=loc,
                                            is_intentional_modulation=False,
                                            source="STRUCTURAL_RESCAN",
                                        )
                                    )
                                    sample_loc_counter += 1
                                gap_idx += 1
                            last_word = parts[-1].decode("latin-1", errors="replace")
                        else:
                            last_word = decoded_bytes.decode("latin-1", errors="replace")
                    except Exception:
                        pass
            elif b == b"[":
                # Array containing TJ elements
                i += 1
                last_number: Optional[int] = None
                last_num_offset: Optional[int] = None

                while i < n and stream[i:i + 1] != b"]":
                    while i < n and stream[i:i + 1] in b" \t\r\n\x00\x0c":
                        i += 1
                    if i >= n or stream[i:i + 1] == b"]":
                        break

                    sb = stream[i:i + 1]

                    if sb == b"(":
                        s_start = i
                        i += 1
                        depth = 1
                        while i < n and depth > 0:
                            if stream[i:i + 1] == b"\\" and i + 1 < n:
                                i += 2
                                continue
                            elif stream[i:i + 1] == b"(":
                                depth += 1
                            elif stream[i:i + 1] == b")":
                                depth -= 1
                            i += 1
                        raw_str = stream[s_start:i]
                        inner = raw_str[1:-1]

                        if inner == b" ":
                            # Inter-word space gap carrying steganographic kerning modulation
                            disp = last_number if last_number is not None else 0
                            offset = last_num_offset if last_num_offset is not None else s_start
                            bit_val: Optional[Literal["0", "1"]] = None
                            if is_framed:
                                bit_val = "1" if disp <= MIN_KERNING_THRESHOLD else "0"

                            # Calculate operator-level geometry
                            x_start = x_text
                            sp_w_raw = font_cache.get_space_width(current_font_entry, font_size) if font_cache else (0.278 * font_size)

                            status: Literal["EXACT", "APPROXIMATE", "UNAVAILABLE"] = "UNAVAILABLE"
                            rect: Optional[List[float]] = None

                            if sp_w_raw is not None and font_size > 0:
                                sp_w = (sp_w_raw + T_c + T_w) * (T_h / 100.0)
                                x_end = x_start + sp_w
                                x_text = x_end

                                M_comp = _matrix_mult(Tm, ctm)
                                if _is_valid_orthogonal(M_comp):
                                    asc = current_font_entry.get("ascender", 1.075) if current_font_entry else 1.075
                                    desc = current_font_entry.get("descender", -0.299) if current_font_entry else -0.299
                                    y_bot = desc * font_size + T_rise
                                    y_top = asc * font_size + T_rise

                                    p0 = _transform_point((x_start, y_bot), M_comp)
                                    p1 = _transform_point((x_end, y_bot), M_comp)
                                    p2 = _transform_point((x_end, y_top), M_comp)
                                    p3 = _transform_point((x_start, y_top), M_comp)

                                    xs = [p[0] - cx0 for p in [p0, p1, p2, p3]]
                                    ys = [cy1 - p[1] for p in [p0, p1, p2, p3]]
                                    pred_rect = [min(xs), min(ys), max(xs), max(ys)]

                                    if corroborator is not None:
                                        status, rect = corroborator.corroborate(pred_rect, prec_word=last_word)
                                    else:
                                        status = "APPROXIMATE"
                                        rect = [round(v, 2) for v in pred_rect]

                            should_record = True
                            if is_framed and max_carrier_bits is not None and carrier_samples_count >= max_carrier_bits:
                                should_record = False

                            if should_record:
                                loc = ContentStreamLocation(
                                    page_index=page_index,
                                    content_stream_xref=stream_xref,
                                    gap_index=gap_idx,
                                    content_stream_offset=offset,
                                    preceding_word=last_word,
                                    displacement=disp,
                                    bit_value=bit_val,
                                    location_index=sample_loc_counter,
                                    localization_status=status,
                                    is_carrier_sample=is_framed,
                                    rect=rect,
                                )
                                samples.append(
                                    ModulationSample(
                                        location=loc,
                                        is_intentional_modulation=is_framed,
                                        source="STRUCTURAL_RESCAN",
                                    )
                                )
                                sample_loc_counter += 1
                                if is_framed:
                                    carrier_samples_count += 1
                            gap_idx += 1

                        elif b" " in inner:
                            parts = inner.split(b" ")
                            curr_offset = s_start + 1
                            for p_idx, part in enumerate(parts[:-1]):
                                space_offset = curr_offset + len(part)
                                prec_word = part.decode("latin-1", errors="replace")
                                if not is_framed:
                                    loc = ContentStreamLocation(
                                        page_index=page_index,
                                        content_stream_xref=stream_xref,
                                        gap_index=gap_idx,
                                        content_stream_offset=space_offset,
                                        preceding_word=prec_word,
                                        displacement=0,
                                        bit_value=None,
                                        location_index=sample_loc_counter,
                                        localization_status="UNAVAILABLE",
                                        is_carrier_sample=False,
                                        rect=None,
                                    )
                                    samples.append(
                                        ModulationSample(
                                            location=loc,
                                            is_intentional_modulation=False,
                                            source="STRUCTURAL_RESCAN",
                                        )
                                    )
                                    sample_loc_counter += 1
                                gap_idx += 1
                                curr_offset = space_offset + 1
                            last_word = parts[-1].decode("latin-1", errors="replace")
                            if font_cache:
                                w_adv = font_cache.get_string_width(current_font_entry, inner, font_size)
                                if w_adv is not None:
                                    x_text += w_adv * (T_h / 100.0)
                        else:
                            last_word = inner.decode("latin-1", errors="replace")
                            if font_cache:
                                w_adv = font_cache.get_string_width(current_font_entry, inner, font_size)
                                if w_adv is not None:
                                    x_text += w_adv * (T_h / 100.0)

                        last_number = None
                        last_num_offset = None

                    elif sb == b"<":
                        h_start = i
                        i += 1
                        while i < n and stream[i:i + 1] != b">":
                            i += 1
                        if i < n:
                            i += 1
                        raw_hex = stream[h_start:i]
                        try:
                            decoded_bytes = bytes.fromhex(raw_hex[1:-1].decode("ascii", errors="replace"))
                            if b" " in decoded_bytes:
                                parts = decoded_bytes.split(b" ")
                                for p_idx, part in enumerate(parts[:-1]):
                                    prec_word = part.decode("latin-1", errors="replace")
                                    if not is_framed:
                                        loc = ContentStreamLocation(
                                            page_index=page_index,
                                            content_stream_xref=stream_xref,
                                            gap_index=gap_idx,
                                            content_stream_offset=h_start,
                                            preceding_word=prec_word,
                                            displacement=0,
                                            bit_value=None,
                                            location_index=sample_loc_counter,
                                            localization_status="UNAVAILABLE",
                                            is_carrier_sample=False,
                                            rect=None,
                                        )
                                        samples.append(
                                            ModulationSample(
                                                location=loc,
                                                is_intentional_modulation=False,
                                                source="STRUCTURAL_RESCAN",
                                            )
                                        )
                                        sample_loc_counter += 1
                                    gap_idx += 1
                                last_word = parts[-1].decode("latin-1", errors="replace")
                            else:
                                last_word = decoded_bytes.decode("latin-1", errors="replace")
                        except Exception:
                            pass
                        last_number = None
                        last_num_offset = None

                    elif sb in b"()<>[]":
                        i += 1
                        last_number = None
                        last_num_offset = None

                    else:
                        t_start = i
                        while i < n and stream[i:i + 1] not in b" \t\r\n\x00\x0c[]()<>":
                            i += 1
                        if i == t_start:
                            i += 1
                        token = stream[t_start:i]
                        try:
                            last_number = int(token)
                            last_num_offset = t_start
                            dx = -(float(last_number) / 1000.0 * font_size) * (T_h / 100.0)
                            x_text += dx
                        except ValueError:
                            try:
                                last_number = int(float(token))
                                last_num_offset = t_start
                                dx = -(float(last_number) / 1000.0 * font_size) * (T_h / 100.0)
                                x_text += dx
                            except ValueError:
                                last_number = None
                                last_num_offset = None

                if i < n and stream[i:i + 1] == b"]":
                    i += 1

            elif b in b"()<>[]":
                i += 1
                operands.clear()

            else:
                t_start = i
                while i < n and stream[i:i + 1] not in b" \t\r\n\x00\x0c[]()<>/%":
                    i += 1
                if i == t_start:
                    i += 1
                tok = stream[t_start:i].decode("latin-1", errors="replace")

                if tok == "BT":
                    Tm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
                    Tlm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
                    x_text = 0.0
                    operands.clear()
                elif tok == "ET":
                    operands.clear()
                elif tok == "Tm":
                    if len(operands) >= 6:
                        try:
                            Tm = tuple(float(x) for x in operands[-6:])
                            Tlm = Tm
                            x_text = 0.0
                        except Exception:
                            pass
                    operands.clear()
                elif tok == "Td":
                    if len(operands) >= 2:
                        try:
                            tx, ty = float(operands[-2]), float(operands[-1])
                            Tlm = _matrix_mult((1.0, 0.0, 0.0, 1.0, tx, ty), Tlm)
                            Tm = Tlm
                            x_text = 0.0
                        except Exception:
                            pass
                    operands.clear()
                elif tok == "TD":
                    if len(operands) >= 2:
                        try:
                            tx, ty = float(operands[-2]), float(operands[-1])
                            T_l = -ty
                            Tlm = _matrix_mult((1.0, 0.0, 0.0, 1.0, tx, ty), Tlm)
                            Tm = Tlm
                            x_text = 0.0
                        except Exception:
                            pass
                    operands.clear()
                elif tok == "T*":
                    Tlm = _matrix_mult((1.0, 0.0, 0.0, 1.0, 0.0, -T_l), Tlm)
                    Tm = Tlm
                    x_text = 0.0
                    operands.clear()
                elif tok == "Tf":
                    if len(operands) >= 2:
                        current_font_name = operands[-2].lstrip("/")
                        if font_cache:
                            current_font_entry = font_cache.get_font_entry(current_font_name)
                        try:
                            font_size = float(operands[-1])
                        except Exception:
                            pass
                    operands.clear()
                elif tok == "Tc":
                    if operands:
                        try:
                            T_c = float(operands[-1])
                        except Exception:
                            pass
                    operands.clear()
                elif tok == "Tw":
                    if operands:
                        try:
                            T_w = float(operands[-1])
                        except Exception:
                            pass
                    operands.clear()
                elif tok == "Tz":
                    if operands:
                        try:
                            T_h = float(operands[-1])
                        except Exception:
                            pass
                    operands.clear()
                elif tok == "TL":
                    if operands:
                        try:
                            T_l = float(operands[-1])
                        except Exception:
                            pass
                    operands.clear()
                elif tok == "Ts":
                    if operands:
                        try:
                            T_rise = float(operands[-1])
                        except Exception:
                            pass
                    operands.clear()
                elif tok == "cm":
                    if len(operands) >= 6:
                        try:
                            cm_m = tuple(float(x) for x in operands[-6:])
                            ctm = _matrix_mult(cm_m, ctm)
                        except Exception:
                            pass
                    operands.clear()
                elif tok == "TJ":
                    operands.clear()
                else:
                    operands.append(tok)

        return samples
