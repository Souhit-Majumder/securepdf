import fitz
from typing import Optional

def extract_from_page_dict(page: fitz.Page) -> Optional[str]:
    """Extracts payload from the Page dictionary if present."""
    doc = page.parent
    key_val = doc.xref_get_key(page.xref, "SPDFPagePayload")
    
    if key_val[0] == "null":
        return None
        
    val_str = key_val[1]
    if key_val[0] == "string":
        return val_str
    return None

def extract_from_invisible_annotation(page: fitz.Page) -> Optional[str]:
    """Extracts payload from an invisible SPDF annotation if present."""
    for annot in page.annots():
        info = annot.info
        if info.get("title") == "SPDF" and "content" in info:
            return info["content"]
    return None
