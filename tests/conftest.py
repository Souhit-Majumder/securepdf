import pytest
from app.config import config
from app.database.database import init_db

@pytest.fixture(autouse=True)
def isolate_test_environment(tmp_path, monkeypatch):
    """
    Globally isolates tests to a per-test temporary data directory.
    Guarantees tests never touch the production data/ directory,
    master.key, securepdf.db, or real documents.
    """
    test_data_dir = tmp_path / "test_data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    
    monkeypatch.setenv("SECUREPDF_DATA_DIR", str(test_data_dir))
    
    # Ensure fresh database schema in the isolated directory
    init_db()
    yield
