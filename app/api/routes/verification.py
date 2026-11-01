import os
import uuid
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from app.config import config
from app.api.dependencies import (
    get_verification_service,
    get_repository,
    get_legacy_verification_auth,
    LegacyVerificationAuth,
)
from app.database.repository import Repository
from app.services.verification_service import VerificationService
from app.api.schemas.verification import VerificationResponse

router = APIRouter()

@router.post("/", response_model=VerificationResponse)
async def verify_document(
    file: UploadFile = File(...),
    auth: LegacyVerificationAuth = Depends(get_legacy_verification_auth),
    service: VerificationService = Depends(get_verification_service),
    repo: Repository = Depends(get_repository),
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

    # Enforce data isolation and privacy scoping
    if auth.auth_type == "user_session":
        doc_uid = result.get("document_uid")
        if doc_uid:
            doc_record = repo.get_document_by_uid(doc_uid)
            # If document is not owned by the authenticated user (or is unowned legacy doc), deny attribution
            if not doc_record or doc_record.user_id != auth.user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: You do not own the document carrier in this file."
                )
        return VerificationResponse(**result)

    # Forensic key authorization: return validity status while preserving student PII privacy
    return VerificationResponse(
        status=result["status"],
        document_uid=result.get("document_uid"),
        authenticated_layers=result.get("authenticated_layers"),
        reason=result.get("reason"),
        student_uid=None,
        student_name=None,
        recipient_name=None,
        recipient_identifier=None,
    )
