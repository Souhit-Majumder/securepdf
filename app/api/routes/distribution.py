from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
from app.api.dependencies import get_fingerprint_service
from app.services.fingerprint_service import FingerprintService

router = APIRouter()

class DistributeRequest(BaseModel):
    student_uid: str

DOC_DIR = "data/documents"
OUT_DIR = "data/output"

@router.post("/{document_uid}/distribute")
def distribute_document(
    document_uid: str,
    request: DistributeRequest,
    service: FingerprintService = Depends(get_fingerprint_service)
):
    input_pdf_path = os.path.join(DOC_DIR, f"{document_uid}.pdf")
    if not os.path.exists(input_pdf_path):
        raise HTTPException(status_code=404, detail="Document not found")
        
    if not os.path.exists(OUT_DIR):
        os.makedirs(OUT_DIR, exist_ok=True)
        
    safe_doc_uid = document_uid.replace("/", "_").replace("\\", "_")
    safe_stu_uid = request.student_uid.replace("/", "_").replace("\\", "_")
    
    # In FingerprintService, fingerprint_pdf signature:
    # fingerprint_pdf(student_uid, document_uid, input_pdf_path, output_pdf_path)
    output_pdf_path = os.path.join(OUT_DIR, f"{safe_doc_uid}_{safe_stu_uid}.pdf")
    
    try:
        service.fingerprint_pdf(
            student_uid=request.student_uid,
            document_uid=document_uid,
            input_pdf_path=input_pdf_path,
            output_pdf_path=output_pdf_path
        )
    except Exception as e:
        # e.g. student not found, etc.
        raise HTTPException(status_code=400, detail=str(e))
        
    return FileResponse(
        path=output_pdf_path, 
        media_type="application/pdf", 
        filename=f"secure_{document_uid}.pdf"
    )
