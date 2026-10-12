import os
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz
from fastapi.testclient import TestClient

def run_smoke_verification():
    print("=" * 60)
    print("SecurePDF Comprehensive System Verification")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["SECUREPDF_DATA_DIR"] = tmp_dir
        
        # 1. Imports and Config Validation
        print("\n[1] Testing imports and configuration...")
        from app.config import config
        from app.database.database import init_db
        from app.database.repository import Repository
        from app.services.fingerprint_service import FingerprintService
        from app.services.verification_service import VerificationService
        from app.cli.commands.register import register_document_cmd, register_student_cmd
        from app.cli.commands.distribute import distribute_cmd
        from app.cli.commands.verify import verify_cmd
        from app.main import app

        init_db()
        assert str(config.DATA_DIR) == tmp_dir
        assert Path(config.DB_PATH).exists()
        print("  ✓ Configuration and imports verified.")

        # 2. Document Creation & Registration (Item 4)
        print("\n[2] Testing PDF registration...")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Master Security Lecture Notes 2026")
        orig_pdf_path = os.path.join(tmp_dir, "original_lecture.pdf")
        doc.save(orig_pdf_path)
        doc.close()

        doc_record = register_document_cmd(orig_pdf_path, title="Lecture Notes", doc_uid="DOC-SMOKE-01")
        assert doc_record is not None
        assert doc_record.document_uid == "DOC-SMOKE-01"
        print("  ✓ Original PDF registered with UID 'DOC-SMOKE-01'.")

        # 3. Register Three Students (Item 5)
        print("\n[3] Testing multi-recipient registration...")
        students = [
            ("STU-001", "Alice Alpha"),
            ("STU-002", "Bob Beta"),
            ("STU-003", "Charlie Gamma")
        ]
        for s_uid, s_name in students:
            stu_rec = register_student_cmd(s_uid, s_name)
            assert stu_rec.student_uid == s_uid
        print("  ✓ Three distinct students registered.")

        # 4. Generate Distinct Personalized Copies (Item 5 & 6)
        print("\n[4] Generating and verifying 3 distinct personalized copies...")
        generated_copies = {}
        for s_uid, s_name in students:
            out_copy = os.path.join(tmp_dir, f"{s_name.split()[0]}_copy.pdf")
            res_path = distribute_cmd("DOC-SMOKE-01", s_uid, output_path=out_copy)
            assert res_path == out_copy
            assert os.path.exists(out_copy)
            generated_copies[s_uid] = out_copy

            # Verify attribution (Item 6)
            ver_res = verify_cmd(out_copy)
            assert ver_res["status"] == "VALID"
            assert ver_res["student_uid"] == s_uid
            assert ver_res["student_name"] == s_name
            assert ver_res["document_uid"] == "DOC-SMOKE-01"
            assert "Layer 1" in ver_res["authenticated_layers"]
            assert "Layer 2" in ver_res["authenticated_layers"]
            print(f"  ✓ {s_name} ({s_uid}) copy authenticates correctly across both layers.")

        # 5. Verify Unmarked PDF is NOT Falsely Attributed (Item 7)
        print("\n[5] Testing ordinary unmarked PDF verification...")
        unmarked_res = verify_cmd(orig_pdf_path)
        assert unmarked_res["status"] == "NOT_FOUND"
        print("  ✓ Unmarked PDF correctly returns NOT_FOUND (no false positive attribution).")

        # 6. Verify Tampered Fingerprint Fails (Item 8)
        print("\n[6] Testing tampered fingerprint detection...")
        tampered_copy = os.path.join(tmp_dir, "tampered_copy.pdf")
        doc_tamper = fitz.open(generated_copies["STU-001"])
        # Tamper Layer 1
        doc_tamper.xref_set_key(doc_tamper.pdf_catalog(), "SPDFPayload", "<535044462d56317c>")
        # Tamper Layer 2
        for page in doc_tamper:
            for annot in page.annots():
                info = annot.info
                info["content"] = "TAMPERED_FORGED_DATA"
                annot.set_info(info)
                annot.update()
        doc_tamper.save(tampered_copy)
        doc_tamper.close()

        tampered_res = verify_cmd(tampered_copy)
        assert tampered_res["status"] == "INVALID"
        print("  ✓ Tampered PDF correctly fails authentication (returns INVALID).")

        # 7. Verify Splicing Conflict Fails Closed (Item 9)
        print("\n[7] Testing carrier conflict fail-closed behavior...")
        conflict_copy = os.path.join(tmp_dir, "conflict_copy.pdf")
        # Extract L1 from Alice, put into Bob's document (which has Bob's L2)
        from app.pdf.extract import extract_layer1
        doc_alice = fitz.open(generated_copies["STU-001"])
        alice_l1 = extract_layer1(doc_alice)
        doc_alice.close()

        doc_bob = fitz.open(generated_copies["STU-002"])
        hex_payload = alice_l1.encode('utf-8').hex()
        doc_bob.xref_set_key(doc_bob.pdf_catalog(), "SPDFPayload", f"<{hex_payload}>")
        doc_bob.save(conflict_copy)
        doc_bob.close()

        conflict_res = verify_cmd(conflict_copy)
        assert conflict_res["status"] == "SECURITY_CONFLICT"
        print("  ✓ Spliced document triggers SECURITY_CONFLICT and fails closed.")

        # 8. Testing API Upload-Size Limits & Magic Bytes (Item 10)
        print("\n[8] Testing API security boundaries (magic bytes & size limit)...")
        client = TestClient(app)
        
        # Non-PDF
        bad_format = client.post("/documents/", files={"file": ("fake.pdf", b"NOT_A_PDF", "application/pdf")})
        assert bad_format.status_code == 400
        assert "Invalid PDF" in bad_format.json()["detail"]
        print("  ✓ Malformed non-PDF upload rejected with 400.")

        # Oversized upload (>20MB)
        oversized_data = b"%PDF-1.4" + (b"A" * (20 * 1024 * 1024 + 1024))
        oversized_res = client.post("/documents/", files={"file": ("huge.pdf", oversized_data, "application/pdf")})
        assert oversized_res.status_code == 413
        assert "File too large" in oversized_res.json()["detail"]
        print("  ✓ Oversized upload (>20MB) aborted with 413.")

        # 9. Confirm Verification Does NOT Create DB Records (Item 11)
        print("\n[9] Testing verification side-effect protection...")
        ghost_path = os.path.join(tmp_dir, "ghost.pdf")
        doc_ghost = fitz.open()
        doc_ghost.new_page()
        ghost_payload = "SPDF-V1|DOC-GHOST-999|nonce123|ffffffff"
        doc_ghost.xref_set_key(doc_ghost.pdf_catalog(), "SPDFPayload", f"<{ghost_payload.encode('utf-8').hex()}>")
        doc_ghost.save(ghost_path)
        doc_ghost.close()

        ver_service = VerificationService()
        ghost_res = ver_service.investigate_pdf(ghost_path)
        assert ghost_res["status"] in ["INVALID", "NOT_FOUND"]

        repo = Repository()
        assert repo.get_document_by_uid("DOC-GHOST-999") is None
        print("  ✓ Unauthenticated verification created NO database records (read-only verified).")

        print("\n" + "=" * 60)
        print("ALL VERIFICATION CHECKS PASSED SUCCESSFULLY!")
        print("=" * 60)

if __name__ == "__main__":
    run_smoke_verification()
