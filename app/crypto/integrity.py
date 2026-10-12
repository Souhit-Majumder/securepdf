from Crypto.Hash import HMAC, SHA256
from .fingerprint import build_canonical_message

def verify_fingerprint(master_key: bytes, document_uid: str, student_uid: str, nonce: str, provided_fingerprint_hex: str) -> bool:
    """
    Verifies a fingerprint using constant-time comparison to prevent timing attacks.
    """
    msg = build_canonical_message(document_uid, student_uid, nonce)
    hmac = HMAC.new(master_key, digestmod=SHA256)
    hmac.update(msg)
    
    try:
        # Crypto.Hash.HMAC.verify() performs a constant-time comparison
        # and raises ValueError if they don't match.
        provided_mac_bytes = bytes.fromhex(provided_fingerprint_hex)
        hmac.verify(provided_mac_bytes)
        return True
    except ValueError:
        return False
