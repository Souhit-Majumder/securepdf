import sqlite3
import threading
from pathlib import Path
from typing import Optional, List, Union, Tuple
from .database import get_connection
from .models import (
    Student,
    Document,
    Fingerprint,
    User,
    Session,
    DistributionBatch,
    DistributionBatchRecipient,
)

class Repository:
    _ACTIVE_CLAIMS: set[int] = set()
    _CLAIMS_LOCK = threading.Lock()

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

    def create_document(
        self,
        document_uid: str,
        original_filename: str,
        user_id: Optional[int] = None
    ) -> Document:
        """
        Creates a new document record associated with an optional user_id.
        Raises sqlite3.IntegrityError if document_uid already exists.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO documents (document_uid, original_filename, user_id) VALUES (?, ?, ?)",
                (document_uid, original_filename, user_id)
            )
            conn.commit()
            doc_id = cursor.lastrowid
            cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
            row = cursor.fetchone()
            conn.close()
            return Document(**dict(row))
        except Exception:
            conn.rollback()
            conn.close()
            raise

    def get_or_create_document(
        self,
        document_uid: str,
        original_filename: str,
        user_id: Optional[int] = None
    ) -> Document:
        """
        Gets an existing document or creates a new one.
        Guarantees:
        - Never silently transfers ownership of existing documents.
        - If user_id is provided and the existing document is owned by a different user, raises ValueError.
        - If existing document is owned by a user, but caller is CLI/service without user_id (user_id is None),
          preserves existing ownership and returns the document (preserving CLI compatibility).
        - If existing document has user_id=None (legacy), returns the document with user_id=None without claiming it.
        - Transactionally consistent insert.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE document_uid = ?", (document_uid,))
        row = cursor.fetchone()
        
        if row:
            existing = Document(**dict(row))
            conn.close()
            if user_id is not None and existing.user_id is not None and existing.user_id != user_id:
                raise ValueError(
                    f"Document with UID '{document_uid}' is already owned by user_id {existing.user_id}."
                )
            return existing
            
        try:
            cursor.execute(
                "INSERT INTO documents (document_uid, original_filename, user_id) VALUES (?, ?, ?)",
                (document_uid, original_filename, user_id)
            )
            conn.commit()
            doc_id = cursor.lastrowid
            cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
            row = cursor.fetchone()
            conn.close()
            return Document(**dict(row))
        except sqlite3.IntegrityError:
            conn.rollback()
            cursor.execute("SELECT * FROM documents WHERE document_uid = ?", (document_uid,))
            row = cursor.fetchone()
            conn.close()
            if row:
                existing = Document(**dict(row))
                if user_id is not None and existing.user_id is not None and existing.user_id != user_id:
                    raise ValueError(
                        f"Document with UID '{document_uid}' is already owned by user_id {existing.user_id}."
                    )
                return existing
            raise
        except Exception:
            conn.rollback()
            conn.close()
            raise

    def get_documents_by_user_id(self, user_id: int) -> List[Document]:
        """Returns all documents owned by a specific user."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE user_id = ? ORDER BY id DESC", (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [Document(**dict(r)) for r in rows]

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

    def get_fingerprint_by_id(self, fingerprint_id: int) -> Optional[Fingerprint]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM fingerprints WHERE id = ?", (fingerprint_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Fingerprint(**dict(row))
        return None

    def create_user(self, email: str, username: str, password_hash: str, salt: str) -> User:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (email, username, password_hash, salt) VALUES (?, ?, ?, ?)",
            (email.strip().lower(), username.strip(), password_hash, salt)
        )
        conn.commit()
        user_id = cursor.lastrowid
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return User(**dict(row))

    def get_user_by_email(self, email: str) -> Optional[User]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE lower(email) = ?", (email.strip().lower(),))
        row = cursor.fetchone()
        conn.close()
        if row:
            return User(**dict(row))
        return None

    def get_user_by_username(self, username: str) -> Optional[User]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE lower(username) = ?", (username.strip().lower(),))
        row = cursor.fetchone()
        conn.close()
        if row:
            return User(**dict(row))
        return None

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return User(**dict(row))
        return None

    def create_session(self, session_token: str, user_id: int, expires_at: str) -> Session:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (session_token, user_id, expires_at) VALUES (?, ?, ?)",
            (session_token, user_id, expires_at)
        )
        conn.commit()
        cursor.execute("SELECT * FROM sessions WHERE session_token = ?", (session_token,))
        row = cursor.fetchone()
        conn.close()
        return Session(**dict(row))

    def get_session(self, session_token: str) -> Optional[Session]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE session_token = ?", (session_token,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Session(**dict(row))
        return None

    def delete_session(self, session_token: str) -> bool:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE session_token = ?", (session_token,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def get_or_create_carrier_student(self, conn: sqlite3.Connection, student_uid: str, name: str) -> int:
        """
        Gets existing student_id for student_uid, or inserts a new record.
        CRITICAL IDENTITY SAFETY GUARANTEE: Never updates or overwrites existing student records.
        """
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM students WHERE student_uid = ?", (student_uid,))
        row = cursor.fetchone()
        if row:
            return row["id"]
        cursor.execute("INSERT INTO students (student_uid, name) VALUES (?, ?)", (student_uid, name))
        return cursor.lastrowid

    def create_distribution_batch(
        self,
        batch_uid: str,
        user_id: int,
        document_id: int,
        expiry_duration_seconds: int,
        recipients_data: List[dict]
    ) -> DistributionBatch:
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO distribution_batches 
                (batch_uid, user_id, document_id, total_recipients, expiry_duration_seconds, status)
                VALUES (?, ?, ?, ?, ?, 'PENDING')
                """,
                (batch_uid, user_id, document_id, len(recipients_data), expiry_duration_seconds)
            )
            batch_id = cursor.lastrowid
            
            for r in recipients_data:
                name = r["name"]
                identifier = r["student_uid"]
                student_id = self.get_or_create_carrier_student(conn, identifier, name)
                cursor.execute(
                    """
                    INSERT INTO distribution_batch_recipients
                    (batch_id, student_id, recipient_name, recipient_identifier, status)
                    VALUES (?, ?, ?, ?, 'PENDING')
                    """,
                    (batch_id, student_id, name, identifier)
                )
            conn.commit()
            cursor.execute("SELECT * FROM distribution_batches WHERE id = ?", (batch_id,))
            row = cursor.fetchone()
            conn.close()
            return DistributionBatch(**dict(row))
        except Exception:
            conn.rollback()
            conn.close()
            raise

    def get_distribution_batch_by_uid(self, batch_uid: str) -> Optional[DistributionBatch]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM distribution_batches WHERE batch_uid = ?", (batch_uid,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return DistributionBatch(**dict(row))
        return None

    def get_batch_recipients(self, batch_id: int) -> List[DistributionBatchRecipient]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM distribution_batch_recipients WHERE batch_id = ? ORDER BY id ASC",
            (batch_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [DistributionBatchRecipient(**dict(row)) for row in rows]

    def get_distribution_batches_by_user(self, user_id: int) -> List[DistributionBatch]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM distribution_batches WHERE user_id = ? ORDER BY id DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [DistributionBatch(**dict(row)) for row in rows]

    def get_distribution_batches_by_document(self, document_id: int) -> List[DistributionBatch]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM distribution_batches WHERE document_id = ? ORDER BY id DESC",
            (document_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [DistributionBatch(**dict(row)) for row in rows]

    def get_recipient_by_fingerprint_id(self, fingerprint_id: int) -> Optional[DistributionBatchRecipient]:
        """Retrieves a batch recipient demonstrably linked to a verified fingerprint ID."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM distribution_batch_recipients WHERE fingerprint_id = ?",
            (fingerprint_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return DistributionBatchRecipient(**dict(row))
        return None

    def claim_batch_for_generation(self, batch_id: int, allow_recovery: bool = False) -> bool:
        """
        Atomically transitions a batch to 'PROCESSING' if it is in 'PENDING',
        'PARTIALLY_FAILED', or 'FAILED' state (or interrupted 'PROCESSING' if allow_recovery=True).
        Guarantees protection against concurrent generation executions, including recovery.
        """
        with self._CLAIMS_LOCK:
            if batch_id in self._ACTIVE_CLAIMS:
                return False

            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM distribution_batches WHERE id = ?", (batch_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return False

            current_status = row["status"]
            if current_status in ('PENDING', 'PARTIALLY_FAILED', 'FAILED', 'COMPLETED'):
                cursor.execute(
                    "UPDATE distribution_batches SET status = 'PROCESSING' WHERE id = ? AND status = ?",
                    (batch_id, current_status)
                )
                claimed = cursor.rowcount > 0
            elif current_status == 'PROCESSING' and allow_recovery:
                # Interrupted batch recovered after restart: can only be claimed once in current runtime
                claimed = True
            else:
                claimed = False

            if claimed:
                self._ACTIVE_CLAIMS.add(batch_id)
                conn.commit()
            conn.close()
            return claimed

    def release_batch_claim(self, batch_id: int) -> None:
        """Releases the active generation claim on a batch."""
        with self._CLAIMS_LOCK:
            self._ACTIVE_CLAIMS.discard(batch_id)

    def get_uncompleted_batch_recipients(self, batch_id: int) -> List[DistributionBatchRecipient]:
        """
        Retrieves recipients requiring generation (PENDING or FAILED or unlinked fingerprint).
        Strictly excludes successfully GENERATED recipients with linked fingerprints.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM distribution_batch_recipients 
            WHERE batch_id = ? AND (status != 'GENERATED' OR fingerprint_id IS NULL)
            ORDER BY id ASC
            """,
            (batch_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [DistributionBatchRecipient(**dict(row)) for row in rows]

    def record_recipient_generation(
        self,
        recipient_id: int,
        document_id: int,
        student_id: int,
        nonce: str,
        fingerprint_hex: str,
        generated_at: str,
        expires_at: str,
        download_token: str
    ) -> int:
        """
        Atomically commits the carrier fingerprint and links it to the batch recipient.
        Raises exception and rolls back on failure so caller can safely clean up disk assets.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO fingerprints (document_id, student_id, nonce, fingerprint)
                VALUES (?, ?, ?, ?)
                """,
                (document_id, student_id, nonce, fingerprint_hex)
            )
            fp_id = cursor.lastrowid
            cursor.execute(
                """
                UPDATE distribution_batch_recipients
                SET status = 'GENERATED',
                    fingerprint_id = ?,
                    generated_at = ?,
                    expires_at = ?,
                    download_token = ?
                WHERE id = ?
                """,
                (fp_id, generated_at, expires_at, download_token, recipient_id)
            )
            conn.commit()
            conn.close()
            return fp_id
        except Exception:
            conn.rollback()
            conn.close()
            raise

    def update_recipient_status_generated(
        self,
        recipient_id: int,
        generated_at: str,
        expires_at: str,
        download_token: Optional[str] = None
    ) -> None:
        """Updates recipient status to GENERATED without creating a new fingerprint record, preserving or setting download_token."""
        conn = self._get_conn()
        cursor = conn.cursor()
        if download_token:
            cursor.execute(
                """
                UPDATE distribution_batch_recipients
                SET status = 'GENERATED',
                    generated_at = ?,
                    expires_at = ?,
                    download_token = COALESCE(download_token, ?)
                WHERE id = ?
                """,
                (generated_at, expires_at, download_token, recipient_id)
            )
        else:
            cursor.execute(
                """
                UPDATE distribution_batch_recipients
                SET status = 'GENERATED',
                    generated_at = ?,
                    expires_at = ?
                WHERE id = ?
                """,
                (generated_at, expires_at, recipient_id)
            )
        conn.commit()
        conn.close()

    def get_recipient_by_download_token(self, token: str):
        """
        Retrieves recipient, batch, and document by unique download_token.
        Returns None if token is invalid or does not exist.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                r.id as r_id, r.batch_id as r_batch_id, r.student_id as r_student_id,
                r.recipient_name as r_recipient_name, r.recipient_identifier as r_recipient_identifier,
                r.status as r_status, r.created_at as r_created_at, r.generated_at as r_generated_at,
                r.expires_at as r_expires_at, r.fingerprint_id as r_fingerprint_id,
                r.download_token as r_download_token,
                b.id as b_id, b.batch_uid as b_batch_uid, b.user_id as b_user_id,
                b.document_id as b_document_id, b.total_recipients as b_total_recipients,
                b.expiry_duration_seconds as b_expiry_duration_seconds, b.status as b_status,
                b.created_at as b_created_at,
                d.id as d_id, d.document_uid as d_document_uid, d.original_filename as d_original_filename,
                d.user_id as d_user_id, d.created_at as d_created_at
            FROM distribution_batch_recipients r
            JOIN distribution_batches b ON r.batch_id = b.id
            JOIN documents d ON b.document_id = d.id
            WHERE r.download_token = ?
            """,
            (token,)
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None

        recipient = DistributionBatchRecipient(
            id=row["r_id"],
            batch_id=row["r_batch_id"],
            student_id=row["r_student_id"],
            recipient_name=row["r_recipient_name"],
            recipient_identifier=row["r_recipient_identifier"],
            status=row["r_status"],
            created_at=row["r_created_at"],
            generated_at=row["r_generated_at"],
            expires_at=row["r_expires_at"],
            fingerprint_id=row["r_fingerprint_id"],
            download_token=row["r_download_token"],
        )
        batch = DistributionBatch(
            id=row["b_id"],
            batch_uid=row["b_batch_uid"],
            user_id=row["b_user_id"],
            document_id=row["b_document_id"],
            total_recipients=row["b_total_recipients"],
            expiry_duration_seconds=row["b_expiry_duration_seconds"],
            status=row["b_status"],
            created_at=row["b_created_at"],
        )
        doc = Document(
            id=row["d_id"],
            document_uid=row["d_document_uid"],
            original_filename=row["d_original_filename"],
            user_id=row["d_user_id"],
            created_at=row["d_created_at"],
        )
        return recipient, batch, doc

    def mark_recipient_expired(self, recipient_id: int) -> None:
        """Transitions recipient status to EXPIRED while preserving attribution."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE distribution_batch_recipients SET status = 'EXPIRED' WHERE id = ?",
            (recipient_id,)
        )
        conn.commit()
        conn.close()

    def get_expired_recipients_for_cleanup(self, current_utc_iso: str) -> List[Tuple[int, str, str]]:
        """
        Finds recipients where expires_at <= current_utc_iso and status IN ('GENERATED', 'EXPIRED').
        Returns list of (recipient_id, batch_uid, recipient_status).
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.id, b.batch_uid, r.status
            FROM distribution_batch_recipients r
            JOIN distribution_batches b ON r.batch_id = b.id
            WHERE r.expires_at IS NOT NULL 
              AND r.expires_at <= ?
              AND r.status IN ('GENERATED', 'EXPIRED')
            """,
            (current_utc_iso,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [(r["id"], r["batch_uid"], r["status"]) for r in rows]

    def record_recipient_failure(self, recipient_id: int) -> None:
        """Marks recipient as FAILED without inserting fingerprint row."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE distribution_batch_recipients SET status = 'FAILED' WHERE id = ?",
            (recipient_id,)
        )
        conn.commit()
        conn.close()

    def finalize_batch_generation_status(self, batch_id: int) -> str:
        """
        Calculates and updates aggregate batch status ('COMPLETED', 'PARTIALLY_FAILED', 'FAILED')
        based on recipient statuses and releases the active claim.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM distribution_batch_recipients WHERE batch_id = ?", (batch_id,))
        rows = cursor.fetchall()
        statuses = [r["status"] for r in rows]
        
        total = len(statuses)
        completed_count = sum(1 for s in statuses if s in ("GENERATED", "EXPIRED"))
        
        if total == 0:
            final_status = "FAILED"
        elif completed_count == total:
            final_status = "COMPLETED"
        elif completed_count > 0:
            final_status = "PARTIALLY_FAILED"
        else:
            final_status = "FAILED"
            
        cursor.execute("UPDATE distribution_batches SET status = ? WHERE id = ?", (final_status, batch_id))
        conn.commit()
        conn.close()
        self.release_batch_claim(batch_id)
        return final_status



