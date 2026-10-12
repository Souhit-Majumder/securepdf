import fitz
doc = fitz.open()
page = doc.new_page()
doc.save("test.pdf")
doc.close()

doc = fitz.open("test.pdf")
hex_payload = b"SPDF-V1|DOC-001|nonce123|fingerprint123".hex()
doc.xref_set_key(doc.pdf_catalog(), "SPDFPayload", f"<{hex_payload}>")
doc.save("test_out.pdf")
doc.close()

doc = fitz.open("test_out.pdf")
val = doc.xref_get_key(doc.pdf_catalog(), "SPDFPayload")
print("EXTRACTED:", val)
