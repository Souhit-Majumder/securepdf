from Crypto.Hash import HMAC, SHA256
from Crypto.Random import get_random_bytes
import binascii

def generate_nonce() -> str:
    """Generates a secure random 128-bit nonce as a hex string."""
    return binascii.hexlify(get_random_bytes(16)).decode('utf-8')

def build_canonical_message(document_uid: str, student_uid: str, nonce: str) -> bytes:
    """Builds the canonical versioned message for the HMAC."""
    msg = f"SPDF-V1|{document_uid}|{student_uid}|{nonce}"
    return msg.encode('utf-8')

def generate_fingerprint(master_key: bytes, document_uid: str, student_uid: str, nonce: str) -> str:
    """
    Generates an HMAC-SHA256 fingerprint.
    Returns a 64-character hexadecimal string.
    """
    msg = build_canonical_message(document_uid, student_uid, nonce)
    hmac = HMAC.new(master_key, digestmod=SHA256)
    hmac.update(msg)
    return hmac.hexdigest()
