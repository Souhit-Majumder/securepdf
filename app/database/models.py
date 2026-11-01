from dataclasses import dataclass
from typing import Optional

@dataclass
class Student:
    id: int
    student_uid: str
    name: str
    created_at: str

@dataclass
class Document:
    id: int
    document_uid: str
    original_filename: str
    created_at: str
    user_id: Optional[int] = None

@dataclass
class Fingerprint:
    id: int
    document_id: int
    student_id: int
    nonce: str
    fingerprint: str
    created_at: str

@dataclass
class User:
    id: int
    email: str
    username: str
    password_hash: str
    salt: str
    created_at: str

@dataclass
class Session:
    session_token: str
    user_id: int
    expires_at: str
    created_at: str

@dataclass
class DistributionBatch:
    id: int
    batch_uid: str
    user_id: int
    document_id: int
    total_recipients: int
    expiry_duration_seconds: int
    status: str
    created_at: str

@dataclass
class DistributionBatchRecipient:
    id: int
    batch_id: int
    student_id: int
    recipient_name: str
    recipient_identifier: str
    status: str
    created_at: str
    generated_at: Optional[str] = None
    expires_at: Optional[str] = None
    fingerprint_id: Optional[int] = None
    download_token: Optional[str] = None

