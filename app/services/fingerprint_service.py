from pathlib import Path
from typing import Optional, Union
from app.crypto.keys import get_or_create_master_key
from app.crypto.fingerprint import generate_nonce, generate_fingerprint
from app.database.repository import Repository
from app.pdf.processor import open_pdf, save_pdf
from app.pdf.embed import embed_payload

class FingerprintService:
    def __init__(
        self,
        repo: Optional[Repository] = None,
        master_key: Optional[bytes] = None,
        key_path: Optional[Union[str, Path]] = None
    ):
        self.repo = repo or Repository()
        self.master_key = master_key or get_or_create_master_key(key_path)

    def fingerprint_pdf(self, student_uid: str, document_uid: str, input_pdf_path: str, output_pdf_path: str) -> str:
        """
        Orchestrates reading a PDF, generating a fingerprint, embedding it, and saving.
        """
        student = self.repo.get_student_by_uid(student_uid)
        if not student:
            raise ValueError(f"Student with UID {student_uid} not found.")
            
        document = self.repo.get_or_create_document(document_uid, f"{document_uid}_original.pdf")
        
        nonce = generate_nonce()
        
        fingerprint_hex = generate_fingerprint(
            master_key=self.master_key,
            document_uid=document_uid,
            student_uid=student_uid,
            nonce=nonce
        )
        
        self.repo.create_fingerprint(
            document_id=document.id,
            student_id=student.id,
            nonce=nonce,
            fingerprint=fingerprint_hex
        )
        
        doc = open_pdf(input_pdf_path)
        embed_payload(
            doc,
            document_uid,
            nonce,
            fingerprint_hex,
            student_uid=student_uid,
            master_key=self.master_key,
        )
        save_pdf(doc, output_pdf_path)
        doc.close()
        
        return fingerprint_hex

    def generate_fingerprint_payload(self, student_uid: str, document_uid: str) -> tuple[str, str]:
        """Generates cryptographic nonce and fingerprint hex."""
        nonce = generate_nonce()
        fingerprint_hex = generate_fingerprint(
            master_key=self.master_key,
            document_uid=document_uid,
            student_uid=student_uid,
            nonce=nonce
        )
        return nonce, fingerprint_hex

    def embed_and_save_pdf(
        self,
        document_uid: str,
        student_uid: str,
        nonce: str,
        fingerprint_hex: str,
        input_pdf_path: str,
        output_pdf_path: str
    ) -> None:
        """Embeds watermarks and saves to output path."""
        doc = open_pdf(input_pdf_path)
        embed_payload(
            doc,
            document_uid,
            nonce,
            fingerprint_hex,
            student_uid=student_uid,
            master_key=self.master_key,
        )
        save_pdf(doc, output_pdf_path)
        doc.close()

