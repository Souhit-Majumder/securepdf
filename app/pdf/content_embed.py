import fitz

def embed_in_page_dict(page: fitz.Page, payload: str):
    """
    Candidate 1: Embed in the Page dictionary.
    Similar to the Catalog method, but attached to the page object itself.
    """
    hex_payload = payload.encode('utf-8').hex()
    page.parent.xref_set_key(page.xref, "SPDFPagePayload", f"<{hex_payload}>")

def embed_as_invisible_annotation(page: fitz.Page, payload: str):
    """
    Candidate 2: Embed as an invisible, zero-area annotation.
    """
    # Create a 0.1x0.1 rectangle at the origin
    rect = fitz.Rect(0, 0, 0.1, 0.1)
    annot = page.add_rect_annot(rect)
    
    # Make it completely invisible (no border, no fill)
    annot.set_colors(stroke=None, fill=None)
    annot.set_opacity(0.0)
    
    # Store payload in the annotation's content/title
    info = annot.info
    info["title"] = "SPDF"
    info["content"] = payload
    annot.set_info(info)
    
    # We can also add a custom flag to prevent printing/viewing
    # PDF specification flags: Invisible=1, Hidden=2, NoView=32. (1 | 2 | 32 = 35)
    annot.set_flags(35)
    annot.update()
