import uuid
import os
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from typing import Optional
from app.api.dependencies import get_repository
from app.database.repository import Repository
from app.api.schemas.document import DocumentResponse

router = APIRouter()

DOC_DIR = "data/documents"

@router.post("/", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    repo: Repository = Depends(get_repository)
):
    if file.content_type != "application/pdf" and not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    # Optional size limits can be enforced here, but FastAPI makes streaming it safe
    
    document_uid = str(uuid.uuid4())
    filename = title if title else file.filename
    
    # Save the original file
    if not os.path.exists(DOC_DIR):
        os.makedirs(DOC_DIR, exist_ok=True)
        
    file_path = os.path.join(DOC_DIR, f"{document_uid}.pdf")
    with open(file_path, "wb") as buffer:
        header = await file.read(4)
        if header != b"%PDF":
            raise HTTPException(status_code=400, detail="Invalid PDF file format")
        buffer.write(header)
        
        file_size = 4
        while chunk := await file.read(1024 * 1024):  # 1 MB chunks
            file_size += len(chunk)
            if file_size > 20 * 1024 * 1024:  # 20 MB limit
                buffer.close()
                os.remove(file_path)
                raise HTTPException(status_code=413, detail="File too large")
            buffer.write(chunk)
        
    doc = repo.get_or_create_document(document_uid, filename)
    return DocumentResponse(
        document_uid=doc.document_uid,
        original_filename=doc.original_filename
    )
