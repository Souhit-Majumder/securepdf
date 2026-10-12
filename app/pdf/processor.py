import fitz

def open_pdf(path: str) -> fitz.Document:
    """Opens a PDF document from the given path."""
    return fitz.open(path)

def save_pdf(doc: fitz.Document, path: str):
    """
    Saves the PDF document.
    We use garbage=3 to clean up unused objects and deflate=True to compress,
    which helps obscure structural modifications slightly.
    """
    doc.save(path, garbage=3, deflate=True)

def validate_pdf(path: str) -> bool:
    """Checks if a file is a valid PDF."""
    try:
        doc = fitz.open(path)
        is_valid = doc.is_pdf
        doc.close()
        return is_valid
    except Exception:
        return False
