from pydantic import BaseModel
from typing import Optional

class DocumentCreate(BaseModel):
    # Because we upload a file, we won't use this directly in the endpoint body 
    # but it's good practice. We'll use Form data in the endpoint for file + optional title.
    pass

class DocumentResponse(BaseModel):
    document_uid: str
    original_filename: str
