from collections import defaultdict
from typing import Optional
import secrets
import threading
import time
from fastapi import HTTPException, Request, Depends
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

SESSION_COOKIE_NAME = "securepdf_session"

def get_current_user_from_session(
    request: Request,
    repo: Repository = Depends(get_repository)
) -> "User":
    """Extract and validate the user session from the HttpOnly cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: No session cookie provided."
        )

    session = repo.get_session(token)
    if not session:
        raise HTTPException(
            status_code=401,
            detail="Invalid or terminated session."
        )

    from app.crypto.auth import is_session_expired
    if is_session_expired(session.expires_at):
        repo.delete_session(token)
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please log in again."
        )

    user = repo.get_user_by_id(session.user_id)
    if not user:
        repo.delete_session(token)
        raise HTTPException(
            status_code=401,
            detail="User account associated with session no longer exists."
        )

    return user

def get_optional_user_from_session(
    request: Request,
    repo: Repository = Depends(get_repository)
) -> Optional["User"]:
    """Safely extracts the user from the HttpOnly session cookie without raising 401 if missing."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    session = repo.get_session(token)
    if not session:
        return None

    from app.crypto.auth import is_session_expired
    if is_session_expired(session.expires_at):
        return None

    return repo.get_user_by_id(session.user_id)

class LegacyVerificationAuth:
    def __init__(self, auth_type: str, user: Optional["User"] = None):
        self.auth_type = auth_type
        self.user = user

def get_legacy_verification_auth(
    request: Request,
    repo: Repository = Depends(get_repository)
) -> LegacyVerificationAuth:
    """
    Dual-mode access guard for legacy /verify/ endpoint:
    - Enforces sliding-window anti-oracle rate limit for all requests.
    - Requires either valid forensic audit key OR active user session cookie.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    if not _rate_limiter.check_and_record(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Verification rate limit exceeded. Anti-oracle cooldown active.",
            headers={"Retry-After": "12"},
        )

    # 1. Check for user session cookie (authenticated session takes precedence for ownership verification)
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        session = repo.get_session(token)
        if session:
            from app.crypto.auth import is_session_expired
            if not is_session_expired(session.expires_at):
                user = repo.get_user_by_id(session.user_id)
                if user:
                    return LegacyVerificationAuth(auth_type="user_session", user=user)

    # 2. Check for independent forensic audit key header
    audit_key = request.headers.get("X-SecurePDF-Audit-Key")
    if audit_key:
        expected_key = config.FORENSIC_KEY
        if not expected_key or not secrets.compare_digest(audit_key, expected_key):
            raise HTTPException(
                status_code=403,
                detail="Access denied: invalid forensic audit key",
            )
        return LegacyVerificationAuth(auth_type="forensic_key", user=None)

    # 3. Reject unauthenticated access
    raise HTTPException(
        status_code=401,
        detail="Authentication required: Provide a valid session cookie or 'X-SecurePDF-Audit-Key' header.",
    )
