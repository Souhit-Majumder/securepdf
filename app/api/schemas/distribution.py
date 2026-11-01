from typing import List, Optional
from pydantic import BaseModel, constr, Field, field_validator

class RecipientItem(BaseModel):
    name: constr(min_length=1, max_length=255, strip_whitespace=True)
    student_uid: constr(min_length=1, max_length=255, strip_whitespace=True)

class DistributionBatchCreateRequest(BaseModel):
    expiry_duration_seconds: int = Field(
        default=120,
        ge=30,
        le=2592000,
        description="Validity duration in seconds (default 120s / 2min; min 30s, max 30 days)"
    )
    recipients: List[RecipientItem] = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Recipients for personalized watermarked distribution"
    )

    @field_validator("recipients")
    @classmethod
    def validate_unique_identifiers(cls, v):
        seen = set()
        for r in v:
            if r.student_uid in seen:
                raise ValueError(f"Duplicate recipient identifier in batch: {r.student_uid}")
            seen.add(r.student_uid)
        return v

class BatchRecipientResponse(BaseModel):
    recipient_name: str
    recipient_identifier: str
    status: str
    generated_at: Optional[str] = None
    expires_at: Optional[str] = None
    download_url: Optional[str] = None
    created_at: str


class DistributionBatchResponse(BaseModel):
    batch_uid: str
    document_uid: str
    total_recipients: int
    expiry_duration_seconds: int
    status: str
    created_at: str
    recipients: List[BatchRecipientResponse]
