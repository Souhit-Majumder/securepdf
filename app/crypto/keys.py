import os
from Crypto.Random import get_random_bytes

KEY_DIR = os.path.join("data")
KEY_PATH = os.path.join(KEY_DIR, "master.key")

def get_or_create_master_key() -> bytes:
    """Loads the master key from disk or generates a new one securely."""
    if not os.path.exists(KEY_DIR):
        os.makedirs(KEY_DIR, exist_ok=True)
        
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            return f.read()
            
    # Generate a new 32-byte (256-bit) key
    key = get_random_bytes(32)
    with open(KEY_PATH, "wb") as f:
        f.write(key)
    return key
