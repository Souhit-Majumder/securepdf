import logging
from dataclasses import dataclass
from typing import Optional, Literal, TYPE_CHECKING
import fitz

from app.config import config
from app.pdf.payload_redundancy import encode_compact_payload, embed_redundant_annotations
from app.pdf.stego.embed import embed_layer3, count_available_word_gaps
from app.pdf.stego.framing import StegoPayload

if TYPE_CHECKING:
    from app.inspection.collector import EvidenceCollector

logger = logging.getLogger(__name__)

L3EmbeddingStatus = Literal[
    "EMBEDDED",
    "SKIPPED_INSUFFICIENT_CAPACITY",
    "DISABLED",
    "FAILED",
]

@dataclass(frozen=True)
class EmbeddingStageResult:
    success: bool                          # True if baseline (L1 + L2) embedded successfully
    l1_status: str                         # "EMBEDDED" | "FAILED"
    l2_status: str                         # "EMBEDDED" | "FAILED"
    l3_status: L3EmbeddingStatus
    l3_required_bits: Optional[int] = None
    l3_available_bits: Optional[int] = None
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success

def embed_payload(
    doc: fitz.Document,
    document_uid: str,
    nonce: str,
    fingerprint: str,
    enable_stego: Optional[bool] = None,
    student_uid: Optional[str] = None,
    master_key: Optional[bytes] = None,
    collector: Optional["EvidenceCollector"] = None,
) -> EmbeddingStageResult:
    """
    Embeds the SPDF payload into the PDF at two primary layers (Catalog, Annotations),
    and optionally at Layer 3 (steganographic text kerning) when enabled.
    Measures usable Layer 3 capacity on the live document after Layer 1 and Layer 2 processing.
    """
    l1_status = "FAILED"
    l2_status = "FAILED"
    error_msg = None

    try:
        # Layer 1: Catalog Embedding
        payload_l1 = f"SPDF-V1|{document_uid}|{nonce}|{fingerprint}"
        hex_payload = payload_l1.encode('utf-8').hex()
        pdf_string = f"<{hex_payload}>"
        catalog_xref = doc.pdf_catalog()
        doc.xref_set_key(catalog_xref, "SPDFPayload", pdf_string)
        if collector is not None:
            collector.record_layer1_embedding(
                catalog_xref=catalog_xref,
                signature_token=fingerprint,
                nonce_token=nonce,
                status="VALID",
                details={"document_uid": document_uid, "version": "SPDF-V1"},
            )
        l1_status = "EMBEDDED"
    except Exception as e:
        error_msg = f"Layer 1 embedding failed: {str(e)}"
        if collector is not None:
            collector.record_layer1_embedding(catalog_xref=0, status="ERROR", details={"error": str(e)})
        return EmbeddingStageResult(
            success=False,
            l1_status="FAILED",
            l2_status="FAILED",
            l3_status="FAILED",
            error=error_msg,
        )

    try:
        # Layer 2: Redundant Annotation Embedding
        payload_l2 = encode_compact_payload(document_uid, nonce, fingerprint)
        if doc.page_count > 0:
            embed_redundant_annotations(doc[0], payload_l2, copies=3)
            if collector is not None:
                for annot in doc[0].annots():
                    title = annot.info.get("title", "")
                    if title.startswith("SPDF"):
                        collector.record_layer2_annotation(
                            page_index=0,
                            annotation_xref=annot.xref,
                            rect=[annot.rect.x0, annot.rect.y0, annot.rect.x1, annot.rect.y1],
                            title=title,
                            signature_token=fingerprint,
                            nonce_token=nonce,
                            status="VALID",
                            details={"document_uid": document_uid, "version": "SPDF1"},
                        )
        l2_status = "EMBEDDED"
    except Exception as e:
        error_msg = f"Layer 2 embedding failed: {str(e)}"
        return EmbeddingStageResult(
            success=False,
            l1_status=l1_status,
            l2_status="FAILED",
            l3_status="FAILED",
            error=error_msg,
        )

    # Layer 3: Steganographic Content Kerning Embedding
    stego_enabled = enable_stego if enable_stego is not None else getattr(config, "ENABLE_STEGO_CARRIER", False)
    l3_status: L3EmbeddingStatus = "DISABLED"
    req_bits = None
    avail_bits = None

    if stego_enabled:
        if not student_uid or not master_key:
            l3_status = "FAILED"
            error_msg = "Layer 3 enabled but student_uid or master_key not provided"
            logger.warning(error_msg)
        else:
            # Measure actual usable capacity post-L1 and post-L2
            req_bits = StegoPayload.calculate_required_bits(document_uid, student_uid)
            avail_bits = count_available_word_gaps(doc)

            if avail_bits < req_bits:
                l3_status = "SKIPPED_INSUFFICIENT_CAPACITY"
                logger.warning(
                    "Document word gap capacity (%d) insufficient for Layer 3 (%d bits); skipping Layer 3.",
                    avail_bits,
                    req_bits,
                )
                if collector is not None:
                    collector.record_layer3_result(
                        status="NOT_FOUND",
                        details={"error": "insufficient_capacity", "required_bits": req_bits, "available_bits": avail_bits},
                    )
            else:
                try:
                    nonce_bytes = bytes.fromhex(nonce) if isinstance(nonce, str) else nonce
                    stego_ok = embed_layer3(doc, document_uid, student_uid, nonce_bytes, master_key, collector=collector)
                    if stego_ok:
                        l3_status = "EMBEDDED"
                    else:
                        l3_status = "FAILED"
                        error_msg = "Layer 3 content stream modulation failed"
                        logger.warning(error_msg)
                except Exception as e:
                    l3_status = "FAILED"
                    error_msg = f"Layer 3 embedding encountered exception: {str(e)}"
                    logger.warning(error_msg)

    return EmbeddingStageResult(
        success=True,
        l1_status=l1_status,
        l2_status=l2_status,
        l3_status=l3_status,
        l3_required_bits=req_bits,
        l3_available_bits=avail_bits,
        error=error_msg,
    )
