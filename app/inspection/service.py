"""
Inspection Service providing structural inspection, active verification with evidence,
and ephemeral fingerprinting simulation.

Guarantees:
- inspect_pdf_structure is strictly read-only and requires zero DB access.
- investigate_with_evidence runs full verification while collecting rich evidence.
- simulate_fingerprinting is strictly ephemeral: zero DB writes, source PDF bytes
  remain unchanged, and temporary files in config.TEMP_DIR are deleted unconditionally
  in finally blocks on both success and failure.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
from typing import Optional, Tuple, Union
import fitz

from app.config import config
from app.crypto.fingerprint import generate_nonce, generate_fingerprint
from app.crypto.keys import get_or_create_master_key
from app.database.repository import Repository
from app.inspection.collector import EvidenceCollector
from app.inspection.models import (
    EvidenceReport,
    SubjectEvidence,
    AuthorizationContext,
    create_subject_ref,
)
from app.inspection.pdf_inspector import PdfStructuralInspector
from app.pdf.embed import embed_payload
from app.pdf.processor import save_pdf
from app.services.verification_service import VerificationService


class InspectionService:
    def __init__(
        self,
        repo: Optional[Repository] = None,
        master_key: Optional[bytes] = None,
        key_path: Optional[Union[str, Path]] = None,
    ):
        self.repo = repo or Repository()
        self.master_key = master_key or get_or_create_master_key(key_path)
        self.verification_service = VerificationService(repo=self.repo, master_key=self.master_key)
        self.inspector = PdfStructuralInspector()

    def inspect_pdf_structure(
        self,
        pdf_path: str,
        auth_ctx: Optional[AuthorizationContext] = None,
    ) -> EvidenceReport:
        """
        Performs non-destructive, read-only structural inspection on cold PDFs.
        Requires zero database queries and never spawns worker subprocesses.
        """
        return self.inspector.inspect_pdf(pdf_path, auth_ctx=auth_ctx)

    def investigate_with_evidence(
        self,
        pdf_path: str,
        auth_ctx: Optional[AuthorizationContext] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Tuple[dict, EvidenceReport]:
        """
        Runs the full verification pipeline checking all active carriers independently,
        while collecting rich evidence events and delta telemetry.
        """
        auth = auth_ctx or AuthorizationContext(principal="investigator", has_pii_clearance=False)
        collector = EvidenceCollector()

        result_dict = self.verification_service.investigate_pdf(
            pdf_path,
            cancel_event=cancel_event,
            collector=collector,
        )

        doc_uid = result_dict.get("document_uid", "UNKNOWN")
        overall_status = result_dict.get("status", "UNKNOWN")

        if result_dict.get("student_uid"):
            student_uid_val = result_dict["student_uid"]
            subj_ref = create_subject_ref(student_uid_val, session_salt=collector.session_id)
            student_uid = student_uid_val if auth.has_pii_clearance else None
            student_name = result_dict.get("student_name") if auth.has_pii_clearance else None
        else:
            subj_ref = "subj_anon_unknown"
            student_uid = None
            student_name = None

        subject = SubjectEvidence(
            subject_ref=subj_ref,
            student_uid=student_uid,
            student_name=student_name,
        )

        report = collector.build_report(
            document_uid=doc_uid,
            overall_status=overall_status,
            subject=subject,
            auth_ctx=auth,
            telemetry_source="ACTIVE_VERIFICATION",
        )

        return result_dict, report

    def simulate_fingerprinting(
        self,
        pdf_path: str,
        student_uid: str,
        doc_uid: str,
        auth_ctx: Optional[AuthorizationContext] = None,
        enable_stego: Optional[bool] = None,
    ) -> Tuple[str, EvidenceReport]:
        """
        Simulates fingerprint issuance ephemerally without persisting to the database.
        Temporary output PDF is unlinked unconditionally in a finally block.
        """
        auth = auth_ctx or AuthorizationContext(principal="simulator", has_pii_clearance=False)
        nonce = generate_nonce()
        fingerprint_hex = generate_fingerprint(
            master_key=self.master_key,
            document_uid=doc_uid,
            student_uid=student_uid,
            nonce=nonce,
        )

        collector = EvidenceCollector()
        tmp_file: Optional[str] = None
        doc: Optional[fitz.Document] = None

        try:
            # Ensure TEMP_DIR exists
            os.makedirs(config.TEMP_DIR, exist_ok=True)
            tmp_fd, tmp_file = tempfile.mkstemp(dir=config.TEMP_DIR, suffix=".pdf")
            os.close(tmp_fd)

            # Open source read-only
            doc = fitz.open(pdf_path)

            embed_payload(
                doc,
                document_uid=doc_uid,
                nonce=nonce,
                fingerprint=fingerprint_hex,
                enable_stego=enable_stego,
                student_uid=student_uid,
                master_key=self.master_key,
                collector=collector,
            )

            # Save to temporary file to execute real PyMuPDF serialization
            save_pdf(doc, tmp_file)

        finally:
            if doc is not None:
                doc.close()
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.unlink(tmp_file)
                except OSError:
                    pass

        subj_ref = create_subject_ref(student_uid, session_salt=collector.session_id)
        subject = SubjectEvidence(
            subject_ref=subj_ref,
            student_uid=student_uid if auth.has_pii_clearance else None,
            student_name=None,
        )

        report = collector.build_report(
            document_uid=doc_uid,
            overall_status="VALID",
            subject=subject,
            auth_ctx=auth,
            telemetry_source="EPHEMERAL_SIMULATION",
        )

        return fingerprint_hex, report
