import fitz

from app.pdf.payload_redundancy import extract_redundant_annotations

def extract_layer1(doc: fitz.Document) -> str | None:
    """
    Extracts the SPDF Layer 1 payload from the PDF Catalog dictionary.
    Returns the string or None.
    """
    catalog_xref = doc.pdf_catalog()
    key_val = doc.xref_get_key(catalog_xref, "SPDFPayload")
    
    if key_val[0] == "null":
        return None
    
    val_str = key_val[1]
    if key_val[0] == "string":
        if val_str.startswith("SPDF-V1"):
            return val_str
    return None

def extract_layer2(doc: fitz.Document) -> list[str]:
    """
    Extracts all SPDF Layer 2 payloads from invisible annotations across all pages.
    """
    payloads = []
    for page in doc:
        page_payloads = extract_redundant_annotations(page)
        payloads.extend(page_payloads)
        if len(payloads) >= 100:
            return payloads[:100]
    return payloads
