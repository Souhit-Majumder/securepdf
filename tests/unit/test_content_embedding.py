import pytest
import fitz
import os
from app.pdf.content_embed import embed_in_page_dict, embed_as_invisible_annotation
from app.pdf.content_extract import extract_from_page_dict, extract_from_invisible_annotation

@pytest.fixture
def test_payload():
    return "SPDF-V1|DOC-001|nonce123|d9d5925cafc74f338e530ea4808d3ef7fba959b4c30d039619f41e590e7a8c32"

@pytest.fixture
def original_pdf(tmp_path):
    path = str(tmp_path / "original.pdf")
    doc = fitz.open()
    
    # Page 1
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 50), "Page 1 Content")
    
    # Page 2
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 50), "Page 2 Content")
    
    doc.save(path)
    doc.close()
    return path

def run_carrier_tests(embed_func, extract_func, original_pdf, test_payload, tmp_path, carrier_name):
    print(f"\n--- Testing Carrier: {carrier_name} ---")
    
    # 1. Embed
    embedded_path = str(tmp_path / f"embedded_{carrier_name}.pdf")
    doc = fitz.open(original_pdf)
    # Embed on page 0
    embed_func(doc[0], test_payload)
    doc.save(embedded_path)
    doc.close()
    
    # Test 1: Visually null and rendered output unchanged
    doc_orig = fitz.open(original_pdf)
    doc_embed = fitz.open(embedded_path)
    
    pix_orig = doc_orig[0].get_pixmap()
    pix_embed = doc_embed[0].get_pixmap()
    assert pix_orig.samples == pix_embed.samples, f"{carrier_name}: Visual output changed!"
    
    # Test 2 & 6: Reliable extraction
    extracted = extract_func(doc_embed[0])
    assert extracted == test_payload, f"{carrier_name}: Failed to extract!"
    doc_orig.close()
    doc_embed.close()
    print(f"[+] {carrier_name}: Visual integrity and extraction passed")
    
    # Test 3: PyMuPDF save (re-save + garbage collection)
    resaved_path = str(tmp_path / f"resaved_{carrier_name}.pdf")
    doc_resave = fitz.open(embedded_path)
    doc_resave.save(resaved_path, garbage=4, deflate=True)
    doc_resave.close()
    
    doc_resave = fitz.open(resaved_path)
    assert extract_func(doc_resave[0]) == test_payload, f"{carrier_name}: Failed after resave/optimization!"
    doc_resave.close()
    print(f"[+] {carrier_name}: Optimization/Re-save passed")
    
    # Test 4: Page extraction -> new PDF
    extracted_path = str(tmp_path / f"extracted_{carrier_name}.pdf")
    doc_src = fitz.open(embedded_path)
    doc_dest = fitz.open()
    doc_dest.insert_pdf(doc_src, from_page=0, to_page=0) # extract page 1
    doc_dest.save(extracted_path)
    doc_src.close()
    doc_dest.close()
    
    doc_extr = fitz.open(extracted_path)
    if carrier_name == "Page Dictionary":
        assert extract_func(doc_extr[0]) is None, f"{carrier_name}: Unexpectedly survived extraction!"
    else:
        assert extract_func(doc_extr[0]) == test_payload, f"{carrier_name}: Failed after page extraction!"
    doc_extr.close()
    print(f"[+] {carrier_name}: Page extraction passed")
    
    # Test 5: Page reorder -> new PDF
    reordered_path = str(tmp_path / f"reordered_{carrier_name}.pdf")
    doc_reorder = fitz.open(embedded_path)
    doc_reorder.select([1, 0]) # Swap pages
    doc_reorder.save(reordered_path)
    doc_reorder.close()
    
    doc_reorder_test = fitz.open(reordered_path)
    # The payload was on the original page 0, which is now page 1
    if carrier_name == "Page Dictionary":
        # It actually survives reordering in PyMuPDF!
        assert extract_func(doc_reorder_test[1]) == test_payload
    else:
        assert extract_func(doc_reorder_test[1]) == test_payload, f"{carrier_name}: Failed after page reordering!"
    doc_reorder_test.close()
    print(f"[+] {carrier_name}: Page reordering passed")

def test_page_dict_carrier(original_pdf, test_payload, tmp_path):
    run_carrier_tests(embed_in_page_dict, extract_from_page_dict, original_pdf, test_payload, tmp_path, "Page Dictionary")

def test_invisible_annotation_carrier(original_pdf, test_payload, tmp_path):
    run_carrier_tests(embed_as_invisible_annotation, extract_from_invisible_annotation, original_pdf, test_payload, tmp_path, "Invisible Annotation")
