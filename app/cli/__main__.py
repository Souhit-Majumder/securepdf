import sys
import os
import uuid
import shutil
from app.database.database import init_db
from app.database.repository import Repository
from app.services.fingerprint_service import FingerprintService
from app.services.verification_service import VerificationService

def print_banner():
    print("\n╔══════════════════════════════╗")
    print("║         SecurePDF            ║")
    print("╚══════════════════════════════╝\n")

def verify_cmd(pdf_path: str):
    print(f"\nPDF: {pdf_path}\n")
    if not os.path.exists(pdf_path):
        print(f"Error: File '{pdf_path}' not found.\n")
        return

    service = VerificationService()
    result = service.investigate_pdf(pdf_path)

    if result["status"] == "VALID":
        print("✓ PDF fingerprint found")
        print("✓ HMAC authentication successful")
        print("✓ Document identified")
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("  STATUS: AUTHENTIC")
        print(f"  STUDENT: {result['student_name']}")
        print(f"  DOCUMENT: {result['document_uid']}")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    elif result["status"] == "SECURITY_CONFLICT":
        print("⚠ SECURITY CONFLICT")
        layers = result.get("authenticated_layers", [])
        print(f"\nConflicting layers: {', '.join(layers)}")
        print("Verification failed closed.")
        print("The PDF must not be attributed to either student.\n")
    else:
        print("✗ No valid authenticated fingerprint found")
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("  STATUS: UNVERIFIED")
        print("  STUDENT: Unknown")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

def demo_cmd():
    print("\nRunning Demo Setup...\n")
    repo = Repository()
    f_service = FingerprintService()
    
    # 1. Create a dummy original PDF if none exists
    original_pdf = "demo_lecture.pdf"
    if not os.path.exists(original_pdf):
        import pymupdf as fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "SecurePDF Demo Lecture Notes")
        doc.save(original_pdf)
        doc.close()
        print(f"Created dummy PDF: {original_pdf}")

    print(f"Original PDF path: ./{original_pdf}\n")

    # 2. Register Document
    doc_uid = "DEMO-DOC-001"
    repo.get_or_create_document(doc_uid, "Lecture Notes")
    
    # 3. Register Students
    students = [
        {"name": "Alice", "uid": "STU-ALICE-01"},
        {"name": "Bob", "uid": "STU-BOB-02"},
        {"name": "Charlie", "uid": "STU-CHARLIE-03"}
    ]
    
    print("Students:")
    for i, s in enumerate(students, 1):
        repo.create_student(s["uid"], s["name"])
        print(f"{i}. {s['name']}")
        
    print("\nGenerating copies...\n")
    
    os.makedirs("output", exist_ok=True)
    
    for s in students:
        out_path = f"output/{s['name']}_lecture.pdf"
        f_service.fingerprint_pdf(
            student_uid=s["uid"],
            document_uid=doc_uid,
            input_pdf_path=original_pdf,
            output_pdf_path=out_path
        )
        print(f"✓ {s['name']} → {out_path}")
        
    print("\nDemo setup complete.")
    print("Test it with: python -m app.cli verify output/Bob_lecture.pdf\n")

def interactive_mode():
    repo = Repository()
    f_service = FingerprintService()
    
    while True:
        print_banner()
        print("1. Register Document")
        print("2. Register Student")
        print("3. Generate Student Copy")
        print("4. Verify PDF")
        print("5. Exit\n")
        
        choice = input("Select option: ").strip()
        
        if choice == "1":
            path = input("Path to original PDF: ").strip()
            if not os.path.exists(path):
                print("File not found.")
                continue
            doc_uid = str(uuid.uuid4())[:8]
            title = os.path.basename(path)
            repo.get_or_create_document(doc_uid, title)
            # Copy to data/documents for safe keeping
            os.makedirs("data/documents", exist_ok=True)
            shutil.copy(path, f"data/documents/{doc_uid}.pdf")
            print(f"✓ Document registered. UID: {doc_uid}")
            
        elif choice == "2":
            name = input("Student Name: ").strip()
            uid = input("Student UID (e.g. roll number): ").strip()
            repo.create_student(uid, name)
            print(f"✓ Student registered: {name} ({uid})")
            
        elif choice == "3":
            doc_uid = input("Document UID: ").strip()
            stu_uid = input("Student UID: ").strip()
            in_path = f"data/documents/{doc_uid}.pdf"
            if not os.path.exists(in_path):
                print(f"Document {doc_uid} not found in data/documents/.")
                continue
            out_dir = "data/output"
            os.makedirs(out_dir, exist_ok=True)
            out_path = f"{out_dir}/{doc_uid}_{stu_uid}.pdf"
            try:
                f_service.fingerprint_pdf(stu_uid, doc_uid, in_path, out_path)
                print(f"✓ Personalized PDF generated: {out_path}")
            except Exception as e:
                print(f"Error: {e}")
                
        elif choice == "4":
            path = input("Path to PDF to verify: ").strip()
            verify_cmd(path)
            
        elif choice == "5":
            print("Exiting...")
            break
        else:
            print("Invalid choice.")

def main():
    init_db()
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "verify":
            if len(sys.argv) < 3:
                print("Usage: python -m app.cli verify <pdf_path>")
                sys.exit(1)
            verify_cmd(sys.argv[2])
        elif cmd == "demo":
            demo_cmd()
        else:
            print(f"Unknown command: {cmd}")
            print("Valid commands: verify, demo")
    else:
        interactive_mode()

if __name__ == "__main__":
    main()
