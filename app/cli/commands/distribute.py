import os
from pathlib import Path
from typing import Optional
from app.config import config
from app.services.fingerprint_service import FingerprintService

def distribute_cmd(
    doc_uid: str,
    student_uid: str,
    output_path: Optional[str] = None
) -> Optional[str]:
    """Generates a personalized fingerprinted PDF copy for a student."""
    doc_dir = config.DOCUMENTS_DIR
    in_path = doc_dir / f"{doc_uid}.pdf"
    
    # If not in documents dir, check if doc_uid is an actual file path
    if not in_path.exists():
        if os.path.exists(doc_uid):
            in_path = Path(doc_uid)
        else:
            print(f"Error: Document with UID '{doc_uid}' not found in {doc_dir}.")
            return None

    out_dir = config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    
    safe_doc_uid = str(doc_uid).replace("/", "_").replace("\\", "_")
    safe_stu_uid = str(student_uid).replace("/", "_").replace("\\", "_")
    target_out = output_path or str(out_dir / f"{safe_doc_uid}_{safe_stu_uid}.pdf")

    f_service = FingerprintService()
    try:
        fp_hex = f_service.fingerprint_pdf(
            student_uid=student_uid,
            document_uid=doc_uid,
            input_pdf_path=str(in_path),
            output_pdf_path=str(target_out)
        )
        print(f"✓ Personalized PDF generated: {target_out}")
        return target_out
    except Exception as e:
        print(f"Error generating copy: {e}")
        return None
