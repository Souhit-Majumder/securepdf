"""
Password hashing and verification using hashlib.scrypt with unique salts,
and session token generation.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Tuple

# scrypt parameters: N=16384 (CPU/memory cost), r=8 (block size), p=1 (parallelization)
# Output length: 64 bytes (512 bits)
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SALT_BYTES = 16
SESSION_LIFETIME_DAYS = 7
SESSION_COOKIE_MAX_AGE = SESSION_LIFETIME_DAYS * 24 * 3600


def generate_salt() -> bytes:
    """Generate a cryptographically secure 16-byte salt."""
    return secrets.token_bytes(SALT_BYTES)


def hash_password(password: str, salt: bytes | None = None) -> Tuple[str, str]:
    """
    Hash a password using hashlib.scrypt and return (password_hash_hex, salt_hex).
    If salt is not provided, a fresh 16-byte random salt is generated.
    """
    if salt is None:
        salt = generate_salt()
    
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN
    )
    return key.hex(), salt.hex()


def verify_password(password: str, stored_hash_hex: str, salt_hex: str) -> bool:
    """
    Verify a plaintext password against a stored hash and salt using constant-time comparison.
    """
    try:
        salt_bytes = bytes.fromhex(salt_hex)
        expected_hash = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt_bytes,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=SCRYPT_DKLEN
        ).hex()
        return secrets.compare_digest(expected_hash, stored_hash_hex)
    except Exception:
        return False


def generate_session_token() -> str:
    """Generate a high-entropy URL-safe session token."""
    return secrets.token_urlsafe(32)


def calculate_session_expiry() -> str:
    """Return an ISO 8601 UTC timestamp string for session expiration."""
    expiry = datetime.now(timezone.utc) + timedelta(days=SESSION_LIFETIME_DAYS)
    return expiry.isoformat()


def is_session_expired(expires_at_iso: str) -> bool:
    """Check if the given ISO 8601 UTC timestamp has passed."""
    try:
        expiry = datetime.fromisoformat(expires_at_iso)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expiry
    except Exception:
        return True
