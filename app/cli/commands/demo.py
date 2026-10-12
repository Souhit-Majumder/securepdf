import os
from pathlib import Path
import fitz
from app.config import config
from app.database.repository import Repository
from app.services.fingerprint_service import FingerprintService

def demo_cmd(output_dir: str = None) -> list[str]:
    """Runs an automated demo workflow setting up 3 students and distinct copies."""
    print("\nRunning SecurePDF Demo Setup...\n")
    repo = Repository()
    f_service = FingerprintService()
    
    # 1. Create a dummy original PDF in config.TEMP_DIR or data/
    temp_dir = config.TEMP_DIR
    temp_dir.mkdir(parents=True, exist_ok=True)
    original_pdf = str(temp_dir / "demo_lecture.pdf")
    
    if not os.path.exists(original_pdf):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "SecurePDF Demo Lecture Notes")
        doc.save(original_pdf)
        doc.close()
        print(f"Created base demo PDF: {original_pdf}")

    # 2. Register Document
    doc_uid = "DEMO-DOC-001"
    repo.get_or_create_document(doc_uid, "Lecture Notes")
    
    # 3. Register Students
    students = [
        {"name": "Alice", "uid": "STU-ALICE-01"},
        {"name": "Bob", "uid": "STU-BOB-02"},
        {"name": "Charlie", "uid": "STU-CHARLIE-03"}
    ]
    
    print("Registered Students:")
    for i, s in enumerate(students, 1):
        repo.create_student(s["uid"], s["name"])
        print(f"  {i}. {s['name']} ({s['uid']})")
        
    print("\nGenerating personalized student copies...\n")
    out_dir = Path(output_dir) if output_dir else config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    
    generated_files = []
    for s in students:
        out_path = str(out_dir / f"{s['name']}_lecture.pdf")
        f_service.fingerprint_pdf(
            student_uid=s["uid"],
            document_uid=doc_uid,
            input_pdf_path=original_pdf,
            output_pdf_path=out_path
        )
        generated_files.append(out_path)
        print(f"✓ {s['name']} → {out_path}")
        
    print("\nDemo setup complete.")
    print(f"Verify any copy with: python -m app.cli verify {generated_files[1]}\n")
    return generated_files
