from app.database.repository import Repository
from app.services.fingerprint_service import FingerprintService
from app.services.verification_service import VerificationService

def get_repository() -> Repository:
    return Repository()

def get_fingerprint_service() -> FingerprintService:
    return FingerprintService()

def get_verification_service() -> VerificationService:
    return VerificationService()
