import fitz
import base64

def encode_compact_payload(document_uid: str, nonce: str, hmac_hex: str) -> str:
    """
    Encodes the payload compactly.
    Instead of 64 hex chars, uses 44 base64 chars for the HMAC.
    """
    hmac_bytes = bytes.fromhex(hmac_hex)
    hmac_b64 = base64.b64encode(hmac_bytes).decode('ascii')
    # Use SPDF1 as compact version identifier
    return f"SPDF1|{document_uid}|{nonce}|{hmac_b64}"

def decode_compact_payload(payload: str) -> tuple[str, str, str, str]:
    """
    Returns (version, document_uid, nonce, hmac_hex)
    """
    parts = payload.split('|')
    if len(parts) != 4:
        raise ValueError("Invalid compact payload structure")
    version, doc_uid, nonce, hmac_b64 = parts
    hmac_bytes = base64.b64decode(hmac_b64)
    hmac_hex = hmac_bytes.hex()
    return version, doc_uid, nonce, hmac_hex

def embed_redundant_annotations(page: fitz.Page, payload: str, copies: int = 3):
    """
    Embeds the payload redundantly across multiple invisible annotations.
    """
    for i in range(copies):
        # Offset them slightly so they aren't exactly on top of each other, 
        # which might be merged or flagged by aggressive optimization tools.
        offset = i * 1.0
        rect = fitz.Rect(offset, offset, offset + 0.1, offset + 0.1)
        annot = page.add_rect_annot(rect)
        
        annot.set_colors(stroke=None, fill=None)
        annot.set_opacity(0.0)
        
        info = annot.info
        info["title"] = f"SPDF{i}"
        info["content"] = payload
        annot.set_info(info)
        
        # 1: Invisible, 2: Hidden, 32: NoView (Total: 35)
        annot.set_flags(35)
        annot.update()

def extract_redundant_annotations(page: fitz.Page) -> list[str]:
    """
    Extracts all SPDF payloads found in annotations on the page.
    """
    payloads = []
    for annot in page.annots():
        info = annot.info
        if info.get("title", "").startswith("SPDF") and "content" in info:
            payloads.append(info["content"])
    return payloads
