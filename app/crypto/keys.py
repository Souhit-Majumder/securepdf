from pathlib import Path
from typing import Optional, Union
from Crypto.Random import get_random_bytes
from app.config import config

def get_or_create_master_key(key_path: Optional[Union[str, Path]] = None) -> bytes:
    """Loads the master key from disk or generates a new one securely."""
    path = Path(key_path) if key_path else config.KEY_PATH
    key_dir = path.parent
    
    if not key_dir.exists():
        key_dir.mkdir(parents=True, exist_ok=True)
        
    if path.exists():
        with open(path, "rb") as f:
            return f.read()
            
    # Generate a new 32-byte (256-bit) key
    key = get_random_bytes(32)
    with open(path, "wb") as f:
        f.write(key)
    return key
