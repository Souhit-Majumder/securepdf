import os
import shutil
import uuid
from typing import Optional
from app.config import config
from app.database.repository import Repository
from app.database.models import Document, Student

def register_document_cmd(file_path: str, title: Optional[str] = None, doc_uid: Optional[str] = None) -> Optional[Document]:
    """Registers an original PDF in the database and archives a copy."""
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.")
        return None

    repo = Repository()
    document_uid = doc_uid or str(uuid.uuid4())[:8]
    doc_title = title or os.path.basename(file_path)
    
    doc = repo.get_or_create_document(document_uid, doc_title)
    
    doc_dir = config.DOCUMENTS_DIR
    doc_dir.mkdir(parents=True, exist_ok=True)
    target_path = doc_dir / f"{document_uid}.pdf"
    
    shutil.copy(file_path, target_path)
    print(f"✓ Document registered. UID: {document_uid} (saved to {target_path})")
    return doc

def register_student_cmd(student_uid: str, name: str) -> Student:
    """Registers a student recipient in the database."""
    repo = Repository()
    student = repo.create_student(student_uid, name)
    print(f"✓ Student registered: {student.name} ({student.student_uid})")
    return student
