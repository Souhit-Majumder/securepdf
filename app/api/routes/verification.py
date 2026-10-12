import os
import uuid
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from app.config import config
from app.api.dependencies import get_verification_service
from app.services.verification_service import VerificationService
from app.api.schemas.verification import VerificationResponse

router = APIRouter()

@router.post("/", response_model=VerificationResponse)
async def verify_document(
    file: UploadFile = File(...),
    service: VerificationService = Depends(get_verification_service)
):
    if file.content_type != "application/pdf" and not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
        
    temp_dir = config.TEMP_DIR
    temp_dir.mkdir(parents=True, exist_ok=True)
        
    temp_path = str(temp_dir / f"verify_{uuid.uuid4()}.pdf")
    
    try:
        header = await file.read(4)
        if header != b"%PDF":
            raise HTTPException(status_code=400, detail="Invalid PDF file format")
            
        with open(temp_path, "wb") as f:
            f.write(header)
            file_size = 4
            while chunk := await file.read(1024 * 1024):
                file_size += len(chunk)
                if file_size > 20 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="File too large")
                f.write(chunk)
            
            
        result = service.investigate_pdf(temp_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
    if result["status"] == "ERROR":
        raise HTTPException(status_code=400, detail=result.get("reason", "Unknown error"))
        
    return VerificationResponse(**result)
