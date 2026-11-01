import uuid
import os
import sqlite3
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from typing import Optional, List
from app.config import config
from app.api.dependencies import get_repository, get_current_user_from_session
from app.database.models import User
from app.database.repository import Repository
from app.api.schemas.document import DocumentResponse

router = APIRouter()

@router.post("/", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user_from_session),
    repo: Repository = Depends(get_repository)
):
    if file.content_type != "application/pdf" and not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    document_uid = str(uuid.uuid4())
    filename = title if title else file.filename
    
    doc_dir = config.DOCUMENTS_DIR
    doc_dir.mkdir(parents=True, exist_ok=True)
        
    file_path = doc_dir / f"{document_uid}.pdf"
    try:
        with open(file_path, "wb") as buffer:
            header = await file.read(4)
            if header != b"%PDF":
                raise HTTPException(status_code=400, detail="Invalid PDF file format")
            buffer.write(header)
            
            file_size = 4
            while chunk := await file.read(1024 * 1024):  # 1 MB chunks
                file_size += len(chunk)
                if file_size > 20 * 1024 * 1024:  # 20 MB limit
                    raise HTTPException(status_code=413, detail="File too large")
                buffer.write(chunk)
    except Exception:
        if file_path.exists():
            file_path.unlink()
        raise
        
    try:
        doc = repo.create_document(
            document_uid=document_uid,
            original_filename=filename,
            user_id=current_user.id
        )
    except sqlite3.IntegrityError:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document UID already registered."
        )

    return DocumentResponse(
        document_uid=doc.document_uid,
        original_filename=doc.original_filename
    )

@router.get("/", response_model=List[DocumentResponse])
def list_user_documents(
    current_user: User = Depends(get_current_user_from_session),
    repo: Repository = Depends(get_repository)
):
    """List documents owned by the currently authenticated user."""
    docs = repo.get_documents_by_user_id(current_user.id)
    return [
        DocumentResponse(
            document_uid=d.document_uid,
            original_filename=d.original_filename
        )
        for d in docs
    ]
