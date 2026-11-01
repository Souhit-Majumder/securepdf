from dataclasses import dataclass

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
