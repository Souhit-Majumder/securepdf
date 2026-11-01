from pydantic import BaseModel
from typing import Optional, List

class VerificationResponse(BaseModel):
    status: str
    student_uid: Optional[str] = None
    student_name: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_identifier: Optional[str] = None
    document_uid: Optional[str] = None
    authenticated_layers: Optional[List[str]] = None
    reason: Optional[str] = None
