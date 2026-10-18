from typing import Optional
import fitz

from app.config import config
from app.pdf.payload_redundancy import encode_compact_payload, embed_redundant_annotations
from app.pdf.stego.embed import embed_layer3

def embed_payload(
    doc: fitz.Document,
    document_uid: str,
    nonce: str,
    fingerprint: str,
    enable_stego: Optional[bool] = None,
    student_uid: Optional[str] = None,
    master_key: Optional[bytes] = None,
) -> bool:
    """
    Embeds the SPDF payload into the PDF at two primary layers (Catalog, Annotations),
    and optionally at Layer 3 (steganographic text kerning) when enabled.
    """
    # Layer 1: Catalog Embedding
    payload_l1 = f"SPDF-V1|{document_uid}|{nonce}|{fingerprint}"
    hex_payload = payload_l1.encode('utf-8').hex()
    pdf_string = f"<{hex_payload}>"
    catalog_xref = doc.pdf_catalog()
    doc.xref_set_key(catalog_xref, "SPDFPayload", pdf_string)
    
    # Layer 2: Redundant Annotation Embedding
    payload_l2 = encode_compact_payload(document_uid, nonce, fingerprint)
    if doc.page_count > 0:
        embed_redundant_annotations(doc[0], payload_l2, copies=3)

    # Optional Layer 3: Steganographic Content Kerning Embedding
    stego_enabled = enable_stego if enable_stego is not None else getattr(config, "ENABLE_STEGO_CARRIER", False)
    if stego_enabled and student_uid and master_key:
        try:
            nonce_bytes = bytes.fromhex(nonce) if isinstance(nonce, str) else nonce
            embed_layer3(doc, document_uid, student_uid, nonce_bytes, master_key)
        except Exception:
            # Graceful fallback: failure in stego embedding never halts issuance
            pass
        
    return True
