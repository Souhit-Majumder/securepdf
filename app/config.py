import os
from pathlib import Path

class Config:
    """
    Centralized configuration for SecurePDF.
    Provides predictable file and directory paths with environment-variable overrides.
    """
    def __init__(self):
        self.BASE_DIR = Path(__file__).resolve().parent.parent

    @property
    def DATA_DIR(self) -> Path:
        return Path(os.getenv("SECUREPDF_DATA_DIR", str(self.BASE_DIR / "data")))

    @property
    def DB_PATH(self) -> Path:
        return Path(os.getenv("SECUREPDF_DB_PATH", str(self.DATA_DIR / "securepdf.db")))

    @property
    def KEY_PATH(self) -> Path:
        return Path(os.getenv("SECUREPDF_KEY_PATH", str(self.DATA_DIR / "master.key")))

    @property
    def DOCUMENTS_DIR(self) -> Path:
        return Path(os.getenv("SECUREPDF_DOCUMENTS_DIR", str(self.DATA_DIR / "documents")))

    @property
    def OUTPUT_DIR(self) -> Path:
        return Path(os.getenv("SECUREPDF_OUTPUT_DIR", str(self.DATA_DIR / "output")))

    @property
    def TEMP_DIR(self) -> Path:
        return Path(os.getenv("SECUREPDF_TEMP_DIR", str(self.DATA_DIR / "temp")))

    def ensure_directories(self):
        """Ensures that all runtime directories exist on disk."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.TEMP_DIR.mkdir(parents=True, exist_ok=True)

config = Config()
