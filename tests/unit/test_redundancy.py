import pytest
import fitz
import os
import random
from app.pdf.payload_redundancy import (
    encode_compact_payload, 
    decode_compact_payload, 
    embed_redundant_annotations,
    extract_redundant_annotations
)
from app.crypto.fingerprint import generate_nonce

@pytest.fixture
def mock_data():
    doc_uid = "DOC-123"
    nonce = "abc123nonce"
    hmac_hex = "d9d5925cafc74f338e530ea4808d3ef7fba959b4c30d039619f41e590e7a8c32"
    return doc_uid, nonce, hmac_hex

@pytest.fixture
def original_pdf(tmp_path):
    path = str(tmp_path / "original.pdf")
    doc = fitz.open()
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 50), "Page 1 Content")
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 50), "Page 2 Content")
    doc.save(path)
    doc.close()
    return path

def test_payload_compactness(mock_data):
    doc_uid, nonce, hmac_hex = mock_data
    old_payload = f"SPDF-V1|{doc_uid}|{nonce}|{hmac_hex}"
    new_payload = encode_compact_payload(doc_uid, nonce, hmac_hex)
    
    assert len(new_payload) < len(old_payload)
    print(f"\nOld size: {len(old_payload)} bytes. New size: {len(new_payload)} bytes.")
    
    # Verify decoding works
    ver, d_uid, d_nonce, d_hmac = decode_compact_payload(new_payload)
    assert ver == "SPDF1"
    assert d_uid == doc_uid
    assert d_nonce == nonce
    assert d_hmac == hmac_hex

def test_redundancy_survival(original_pdf, mock_data, tmp_path):
    doc_uid, nonce, hmac_hex = mock_data
    payload = encode_compact_payload(doc_uid, nonce, hmac_hex)
    
    # 1. Embed 3 copies
    embedded_path = str(tmp_path / "embedded.pdf")
    doc = fitz.open(original_pdf)
    embed_redundant_annotations(doc[0], payload, copies=3)
    doc.save(embedded_path)
    doc.close()
    
    # Attack 1: Delete one annotation
    attack1_path = str(tmp_path / "attack1.pdf")
    doc = fitz.open(embedded_path)
    count = 0
    for annot in doc[0].annots():
        if count == 0:
            doc[0].delete_annot(annot)
        count += 1
    assert count == 3
    doc.save(attack1_path)
    doc.close()
    
    doc = fitz.open(attack1_path)
    extracted = extract_redundant_annotations(doc[0])
    assert len(extracted) == 2
    assert extracted[0] == payload
    doc.close()
    
    # Attack 2: Modify one annotation (Tampering)
    attack2_path = str(tmp_path / "attack2.pdf")
    doc = fitz.open(embedded_path)
    count = 0
    for annot in doc[0].annots():
        if count == 1:
            info = annot.info
            info["content"] = "TAMPERED_PAYLOAD"
            annot.set_info(info)
            annot.update()
        count += 1
    doc.save(attack2_path)
    doc.close()
    
    doc = fitz.open(attack2_path)
    extracted = extract_redundant_annotations(doc[0])
    assert len(extracted) == 3
    valid_count = 0
    tampered_count = 0
    for ext in extracted:
        if ext == payload:
            valid_count += 1
        elif ext == "TAMPERED_PAYLOAD":
            tampered_count += 1
    assert valid_count == 2
    assert tampered_count == 1
    doc.close()

    # Attack 3: Delete all annotations
    attack3_path = str(tmp_path / "attack3.pdf")
    doc = fitz.open(embedded_path)
    for annot in doc[0].annots():
        doc[0].delete_annot(annot)
    doc.save(attack3_path)
    doc.close()
    
    doc = fitz.open(attack3_path)
    extracted = extract_redundant_annotations(doc[0])
    assert len(extracted) == 0
    doc.close()

def test_structural_survival_redundancy(original_pdf, mock_data, tmp_path):
    doc_uid, nonce, hmac_hex = mock_data
    payload = encode_compact_payload(doc_uid, nonce, hmac_hex)
    
    embedded_path = str(tmp_path / "embedded.pdf")
    doc = fitz.open(original_pdf)
    embed_redundant_annotations(doc[0], payload, copies=2)
    doc.save(embedded_path)
    doc.close()
    
    # Page reordering
    reorder_path = str(tmp_path / "reorder.pdf")
    doc = fitz.open(embedded_path)
    doc.select([1, 0])
    doc.save(reorder_path)
    doc.close()
    
    doc = fitz.open(reorder_path)
    # The annotations were on original page 0, which is now page 1
    extracted = extract_redundant_annotations(doc[1])
    assert len(extracted) == 2
    assert extracted[0] == payload
    doc.close()
