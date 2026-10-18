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

        # Sample modulations from page 0 (up to 20 samples)
        samples = self.get_page_modulations(
            doc,
            page_index=0,
            offset=0,
            limit=20,
            is_framed=parse_result.crc_valid,
        )

        if parse_result.crc_valid and parse_result.payload:
            payload = parse_result.payload
            sig_ref = self._get_or_create_ref("sig", payload.hmac_tag)
            nonce_ref = self._get_or_create_ref("nonce", payload.nonce)
            bit_len = payload.total_bits

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
                    locations=[s.location for s in samples],
                    total_word_gaps=total_gaps,
                    modulation_samples=samples,
                    details={
                        "frame_detected": True,
                        "crc_valid": False,
                        "error": parse_result.error,
                    },
                ),
                None,
            )
        else:
            # Preamble not found: arbitrary kerning syntax observed in typesetting
            return (
                CarrierInspectionResult(
                    carrier_name="Layer 3 (Stego Kerning)",
                    status="OBSERVED_SYNTAX",
                    locations=[s.location for s in samples],
                    total_word_gaps=total_gaps,
                    modulation_samples=samples,
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
            )
            all_samples.extend(stream_samples)
            gap_counter += len(stream_samples)

        # Apply deterministic pagination
        return all_samples[offset : offset + limit]

    def _parse_stream_for_samples(
        self,
        stream: bytes,
        page_index: int,
        stream_xref: int,
        start_gap_idx: int,
        is_framed: bool,
    ) -> List[ModulationSample]:
        """
        Parses uncompressed page stream for TJ array inter-word gaps.
        Uses exact tokenization matching extract_bits_from_stream.
        """
        samples: List[ModulationSample] = []
        i = 0
        n = len(stream)
        gap_idx = start_gap_idx
        last_word = ""

        while i < n:
            b = stream[i:i + 1]

            if b in b" \t\r\n\x00\x0c":
                i += 1
            elif b == b"%":
                while i < n and stream[i:i + 1] not in b"\r\n":
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
                        loc = ContentStreamLocation(
                            page_index=page_index,
                            content_stream_xref=stream_xref,
                            gap_index=gap_idx,
                            content_stream_offset=space_offset,
                            preceding_word=prec_word,
                            displacement=0,
                            bit_value=None,
                        )
                        samples.append(
                            ModulationSample(
                                location=loc,
                                is_intentional_modulation=False,
                                source="STRUCTURAL_RESCAN",
                            )
                        )
                        gap_idx += 1
                        curr_offset = space_offset + 1
            elif b == b"<":
                if stream[i:i + 2] == b"<<":
                    i += 2
                else:
                    i += 1
                    while i < n and stream[i:i + 1] != b">":
                        i += 1
                    if i < n:
                        i += 1
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
                            # Inter-word space gap
                            disp = last_number if last_number is not None else 0
                            offset = last_num_offset if last_num_offset is not None else s_start
                            bit_val: Optional[Literal["0", "1"]] = None
                            if is_framed:
                                bit_val = "1" if disp <= MIN_KERNING_THRESHOLD else "0"

                            loc = ContentStreamLocation(
                                page_index=page_index,
                                content_stream_xref=stream_xref,
                                gap_index=gap_idx,
                                content_stream_offset=offset,
                                preceding_word=last_word,
                                displacement=disp,
                                bit_value=bit_val,
                            )
                            samples.append(
                                ModulationSample(
                                    location=loc,
                                    is_intentional_modulation=is_framed,
                                    source="STRUCTURAL_RESCAN",
                                )
                            )
                            gap_idx += 1
                        elif b" " in inner:
                            parts = inner.split(b" ")
                            curr_offset = s_start + 1
                            for p_idx, part in enumerate(parts[:-1]):
                                space_offset = curr_offset + len(part)
                                prec_word = part.decode("latin-1", errors="replace")
                                loc = ContentStreamLocation(
                                    page_index=page_index,
                                    content_stream_xref=stream_xref,
                                    gap_index=gap_idx,
                                    content_stream_offset=space_offset,
                                    preceding_word=prec_word,
                                    displacement=0,
                                    bit_value=None,
                                )
                                samples.append(
                                    ModulationSample(
                                        location=loc,
                                        is_intentional_modulation=False,
                                        source="STRUCTURAL_RESCAN",
                                    )
                                )
                                gap_idx += 1
                                curr_offset = space_offset + 1
                            last_word = parts[-1].decode("latin-1", errors="replace")
                        else:
                            last_word = inner.decode("latin-1", errors="replace")

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
                                    loc = ContentStreamLocation(
                                        page_index=page_index,
                                        content_stream_xref=stream_xref,
                                        gap_index=gap_idx,
                                        content_stream_offset=h_start,
                                        preceding_word=prec_word,
                                        displacement=0,
                                        bit_value=None,
                                    )
                                    samples.append(
                                        ModulationSample(
                                            location=loc,
                                            is_intentional_modulation=False,
                                            source="STRUCTURAL_RESCAN",
                                        )
                                    )
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
                        except ValueError:
                            try:
                                last_number = int(float(token))
                                last_num_offset = t_start
                            except ValueError:
                                last_number = None
                                last_num_offset = None

                if i < n and stream[i:i + 1] == b"]":
                    i += 1
            else:
                i += 1

        return samples
