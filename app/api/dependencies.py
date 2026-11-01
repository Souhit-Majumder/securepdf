from collections import defaultdict
import secrets
import threading
import time
from fastapi import HTTPException, Request
from app.config import config
from app.database.repository import Repository
from app.inspection.models import AuthorizationContext
from app.inspection.service import InspectionService
from app.services.fingerprint_service import FingerprintService
from app.services.verification_service import VerificationService

class AntiOracleRateLimiter:
    """In-memory sliding-window rate limiter per client IP to mitigate verification oracle attacks."""
    def __init__(self, max_requests: int = 5, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._requests = defaultdict(list)

    def check_and_record(self, client_ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self.window_seconds
            timestamps = [t for t in self._requests[client_ip] if t > cutoff]
            if len(timestamps) >= self.max_requests:
                self._requests[client_ip] = timestamps
                return False
            timestamps.append(now)
            self._requests[client_ip] = timestamps
            return True

    def reset_for_ip(self, client_ip: str):
        with self._lock:
            if client_ip in self._requests:
                del self._requests[client_ip]

_rate_limiter = AntiOracleRateLimiter()

def get_repository() -> Repository:
    return Repository()

def get_fingerprint_service() -> FingerprintService:
    return FingerprintService()

def get_verification_service() -> VerificationService:
    return VerificationService()

def get_inspection_service() -> InspectionService:
    return InspectionService()

def get_rate_limiter() -> AntiOracleRateLimiter:
    return _rate_limiter

def get_authenticated_forensic_context(request: Request) -> AuthorizationContext:
    """
    Enforces forensic key authentication and anti-oracle rate limiting
    before granting access to active verification services.
    """
    expected_key = config.FORENSIC_KEY
    if not expected_key:
        raise HTTPException(
            status_code=503,
            detail="Active verification disabled: 'SECUREPDF_FORENSIC_KEY' is not configured on this server.",
        )

    audit_key = request.headers.get("X-SecurePDF-Audit-Key")
    if not audit_key:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: missing 'X-SecurePDF-Audit-Key' header",
        )

    if not secrets.compare_digest(audit_key, expected_key):
        raise HTTPException(
            status_code=403,
            detail="Access denied: invalid forensic audit key",
        )

    client_ip = request.client.host if request.client else "127.0.0.1"
    if not _rate_limiter.check_and_record(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Verification rate limit exceeded. Anti-oracle cooldown active.",
            headers={"Retry-After": "12"},
        )

    return AuthorizationContext(
        principal="authenticated_auditor",
        roles=["investigator"],
        has_pii_clearance=False,
    )
