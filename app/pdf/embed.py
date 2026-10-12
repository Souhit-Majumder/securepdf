import fitz

from app.pdf.payload_redundancy import encode_compact_payload, embed_redundant_annotations

def embed_payload(doc: fitz.Document, document_uid: str, nonce: str, fingerprint: str) -> bool:
    """
    Embeds the SPDF payload into the PDF at two layers.
    Layer 1: Structural (Catalog dictionary)
    Layer 2: Content (Redundant invisible annotations)
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
        
    return True
