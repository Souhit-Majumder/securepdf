import sqlite3
from pathlib import Path
from typing import Optional, Union
from app.config import config

def get_connection(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else config.DB_PATH
    db_dir = path.parent
    if not db_dir.exists():
        db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: Optional[Union[str, Path]] = None):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_uid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_uid TEXT UNIQUE NOT NULL,
            original_filename TEXT NOT NULL,
            user_id INTEGER DEFAULT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
        )
    ''')

    # Safe idempotent column migration for existing databases
    cursor.execute("PRAGMA table_info(documents)")
    doc_cols = [row["name"] for row in cursor.fetchall()]
    if "user_id" not in doc_cols:
        cursor.execute("ALTER TABLE documents ADD COLUMN user_id INTEGER DEFAULT NULL REFERENCES users (id)")
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fingerprints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            nonce TEXT NOT NULL,
            fingerprint TEXT UNIQUE NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (document_id) REFERENCES documents (id),
            FOREIGN KEY (student_id) REFERENCES students (id),
            UNIQUE(document_id, nonce)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at DATETIME NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS distribution_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_uid TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            total_recipients INTEGER NOT NULL,
            expiry_duration_seconds INTEGER NOT NULL DEFAULT 120,
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_distribution_batches_user ON distribution_batches (user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_distribution_batches_doc ON distribution_batches (document_id)')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS distribution_batch_recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            recipient_name TEXT NOT NULL,
            recipient_identifier TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            generated_at DATETIME DEFAULT NULL,
            expires_at DATETIME DEFAULT NULL,
            fingerprint_id INTEGER DEFAULT NULL,
            download_token TEXT UNIQUE DEFAULT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (batch_id) REFERENCES distribution_batches (id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students (id),
            FOREIGN KEY (fingerprint_id) REFERENCES fingerprints (id),
            UNIQUE(batch_id, recipient_identifier)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_batch_recipients_batch ON distribution_batch_recipients (batch_id)')
    
    # Safe idempotent column migration for distribution_batch_recipients download_token
    cursor.execute("PRAGMA table_info(distribution_batch_recipients)")
    rec_cols = [row["name"] for row in cursor.fetchall()]
    if "download_token" not in rec_cols:
        cursor.execute("ALTER TABLE distribution_batch_recipients ADD COLUMN download_token TEXT DEFAULT NULL")

    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_batch_recipients_token ON distribution_batch_recipients (download_token)')

    conn.commit()
    conn.close()

