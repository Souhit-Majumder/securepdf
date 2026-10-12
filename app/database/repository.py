import sqlite3
from pathlib import Path
from typing import Optional, List, Union
from .database import get_connection
from .models import Student, Document, Fingerprint

class Repository:
    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def create_student(self, student_uid: str, name: str) -> Student:
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO students (student_uid, name) VALUES (?, ?)",
                (student_uid, name)
            )
            conn.commit()
            student_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            cursor.execute("SELECT * FROM students WHERE student_uid = ?", (student_uid,))
            row = cursor.fetchone()
            student_id = row['id']
            
        cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        row = cursor.fetchone()
        conn.close()
        return Student(**dict(row))

    def get_student_by_uid(self, student_uid: str) -> Optional[Student]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE student_uid = ?", (student_uid,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Student(**dict(row))
        return None

    def get_student_by_id(self, student_id: int) -> Optional[Student]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Student(**dict(row))
        return None

    def get_or_create_document(self, document_uid: str, original_filename: str) -> Document:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE document_uid = ?", (document_uid,))
        row = cursor.fetchone()
        
        if row:
            conn.close()
            return Document(**dict(row))
            
        cursor.execute(
            "INSERT INTO documents (document_uid, original_filename) VALUES (?, ?)",
            (document_uid, original_filename)
        )
        conn.commit()
        doc_id = cursor.lastrowid
        
        cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        conn.close()
        return Document(**dict(row))

    def get_document_by_uid(self, document_uid: str) -> Optional[Document]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE document_uid = ?", (document_uid,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Document(**dict(row))
        return None

    def get_document_by_id(self, document_id: int) -> Optional[Document]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Document(**dict(row))
        return None

    def create_fingerprint(self, document_id: int, student_id: int, nonce: str, fingerprint: str) -> Fingerprint:
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO fingerprints (document_id, student_id, nonce, fingerprint) VALUES (?, ?, ?, ?)",
                (document_id, student_id, nonce, fingerprint)
            )
            conn.commit()
            fp_id = cursor.lastrowid
        except sqlite3.IntegrityError as e:
            # It could fail due to UNIQUE(fingerprint) or UNIQUE(document_id, nonce)
            cursor.execute("SELECT * FROM fingerprints WHERE fingerprint = ? OR (document_id = ? AND nonce = ?)", 
                           (fingerprint, document_id, nonce))
            row = cursor.fetchone()
            if not row:
                raise ValueError("IntegrityError occurred but record not found") from e
            fp_id = row['id']
        
        cursor.execute("SELECT * FROM fingerprints WHERE id = ?", (fp_id,))
        row = cursor.fetchone()
        conn.close()
        return Fingerprint(**dict(row))

    def get_fingerprint(self, fingerprint: str) -> Optional[Fingerprint]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM fingerprints WHERE fingerprint = ?", (fingerprint,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Fingerprint(**dict(row))
        return None

    def get_fingerprint_by_doc_and_nonce(self, document_id: int, nonce: str) -> Optional[Fingerprint]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM fingerprints WHERE document_id = ? AND nonce = ?", (document_id, nonce))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Fingerprint(**dict(row))
        return None
