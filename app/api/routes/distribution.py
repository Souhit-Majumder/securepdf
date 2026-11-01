from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import os
import re
import uuid
import secrets
import asyncio
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from app.config import config
from app.api.dependencies import (
    get_fingerprint_service,
    get_repository,
    get_current_user_from_session,
)
from app.database.models import User
from app.database.repository import Repository
from app.services.fingerprint_service import FingerprintService
from app.api.schemas.distribution import (
    DistributionBatchCreateRequest,
    DistributionBatchResponse,
    BatchRecipientResponse,
)

from starlette.background import BackgroundTask

logger = logging.getLogger(__name__)

router = APIRouter()

_ACTIVE_BATCH_GENERATIONS: set[str] = set()
_ACTIVE_DOWNLOADS: dict[Path, int] = {}
_DOWNLOAD_LOCK = threading.Lock()

class DownloadReleaseGuard:
    """
    Idempotent guard for tracking active PDF download streams and closing file descriptors.
    Ensures safe, atomic reference-count increments and decrements, and prevents
    duplicate release attempts between iter_file finally blocks and Starlette BackgroundTask.
    """
    def __init__(self, path: Path):
        self.path = path
        self.file_handle = None
        self._released = False
        self._lock = threading.Lock()

        with _DOWNLOAD_LOCK:
            _ACTIVE_DOWNLOADS[self.path] = _ACTIVE_DOWNLOADS.get(self.path, 0) + 1

    def attach_file(self, file_handle):
        self.file_handle = file_handle

    def release(self):
        with self._lock:
            if self._released:
                return
            self._released = True

        if self.file_handle is not None:
            try:
                self.file_handle.close()
            except Exception:
                pass
            self.file_handle = None

        with _DOWNLOAD_LOCK:
            if self.path in _ACTIVE_DOWNLOADS:
                _ACTIVE_DOWNLOADS[self.path] -= 1
                if _ACTIVE_DOWNLOADS[self.path] <= 0:
                    del _ACTIVE_DOWNLOADS[self.path]



class DistributeRequest(BaseModel):
    student_uid: str

@router.post("/{document_uid}/distribute")
def distribute_document(
    document_uid: str,
    request: DistributeRequest,
    current_user: User = Depends(get_current_user_from_session),
    repo: Repository = Depends(get_repository),
    service: FingerprintService = Depends(get_fingerprint_service)
):
    # Retrieve document metadata from database
    doc = repo.get_document_by_uid(document_uid)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Strict ownership check: ordinary user can ONLY distribute their own documents.
    # Legacy documents (user_id is None) and documents owned by other users are strictly denied.
    if doc.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to distribute this document."
        )

    doc_dir = config.DOCUMENTS_DIR
    out_dir = config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    input_pdf_path = os.path.join(str(doc_dir), f"{document_uid}.pdf")
    if not os.path.exists(input_pdf_path):
        raise HTTPException(status_code=404, detail="Document file not found on server")
        
    safe_doc_uid = document_uid.replace("/", "_").replace("\\", "_")
    safe_stu_uid = request.student_uid.replace("/", "_").replace("\\", "_")
    
    output_pdf_path = os.path.join(str(out_dir), f"{safe_doc_uid}_{safe_stu_uid}.pdf")
    
    try:
        service.fingerprint_pdf(
            student_uid=request.student_uid,
            document_uid=document_uid,
            input_pdf_path=input_pdf_path,
            output_pdf_path=output_pdf_path
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    return FileResponse(
        path=output_pdf_path, 
        media_type="application/pdf", 
        filename=f"secure_{document_uid}.pdf"
    )

@router.post("/{document_uid}/batches", response_model=DistributionBatchResponse, status_code=status.HTTP_201_CREATED)
def create_distribution_batch(
    document_uid: str,
    payload: DistributionBatchCreateRequest,
    current_user: User = Depends(get_current_user_from_session),
    repo: Repository = Depends(get_repository),
):
    """
    Creates a distribution batch and registers its recipient list.
    Enforces document ownership, validates inputs, and isolates recipient records.
    """
    doc = repo.get_document_by_uid(document_uid)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to distribute this document."
        )

    batch_uid = f"batch_{uuid.uuid4().hex[:16]}"
    recipients_data = [{"name": r.name, "student_uid": r.student_uid} for r in payload.recipients]

    batch = repo.create_distribution_batch(
        batch_uid=batch_uid,
        user_id=current_user.id,
        document_id=doc.id,
        expiry_duration_seconds=payload.expiry_duration_seconds,
        recipients_data=recipients_data
    )

    recipients = repo.get_batch_recipients(batch.id)

    return _format_batch_response(batch, doc.document_uid, recipients)

@router.get("/batches/{batch_uid}", response_model=DistributionBatchResponse)
def get_distribution_batch(
    batch_uid: str,
    current_user: User = Depends(get_current_user_from_session),
    repo: Repository = Depends(get_repository),
):
    """
    Retrieves distribution batch details and recipient status for the batch owner.
    """
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    if not batch:
        raise HTTPException(status_code=404, detail="Distribution batch not found")

    if batch.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to view this distribution batch."
        )

    doc = repo.get_document_by_id(batch.document_id)
    recipients = repo.get_batch_recipients(batch.id)

    return _format_batch_response(batch, doc.document_uid if doc else "", recipients)

def _format_batch_response(batch, document_uid: str, recipients) -> DistributionBatchResponse:
    now_utc = datetime.now(timezone.utc)
    recipient_items = []
    for r in recipients:
        is_expired = False
        if r.expires_at:
            try:
                exp_dt = datetime.fromisoformat(r.expires_at.replace("Z", "+00:00"))
                if now_utc >= exp_dt:
                    is_expired = True
            except Exception:
                pass

        effective_status = r.status
        if is_expired and r.status == "GENERATED":
            effective_status = "EXPIRED"

        download_url = None
        if effective_status == "GENERATED" and r.download_token and not is_expired:
            download_url = f"/documents/download/{r.download_token}"

        recipient_items.append(
            BatchRecipientResponse(
                recipient_name=r.recipient_name,
                recipient_identifier=r.recipient_identifier,
                status=effective_status,
                generated_at=str(r.generated_at) if r.generated_at else None,
                expires_at=str(r.expires_at) if r.expires_at else None,
                download_url=download_url,
                created_at=str(r.created_at)
            )
        )

    return DistributionBatchResponse(
        batch_uid=batch.batch_uid,
        document_uid=document_uid,
        total_recipients=batch.total_recipients,
        expiry_duration_seconds=batch.expiry_duration_seconds,
        status=batch.status,
        created_at=str(batch.created_at),
        recipients=recipient_items
    )

def _process_batch_generation(
    batch_id: int,
    batch_uid: str,
    document_uid: str,
    expiry_duration_seconds: int,
    repo: Repository,
    service: FingerprintService,
):
    try:
        doc = repo.get_document_by_uid(document_uid)
        if not doc:
            repo.finalize_batch_generation_status(batch_id)
            return

        input_pdf_path = config.DOCUMENTS_DIR / f"{doc.document_uid}.pdf"
        if not input_pdf_path.exists():
            repo.finalize_batch_generation_status(batch_id)
            return

        safe_batch_uid = batch_uid.replace("/", "_").replace("\\", "_")
        batch_dir = config.OUTPUT_DIR / "batches" / safe_batch_uid
        batch_dir.mkdir(parents=True, exist_ok=True)

        recipients = repo.get_batch_recipients(batch_id)
        stego_enabled = getattr(config, "ENABLE_STEGO_CARRIER", False)

        for recipient in recipients:
            final_filename = f"rec_{recipient.id}.pdf"
            final_path = batch_dir / final_filename
            temp_path = batch_dir / f"tmp_{recipient.id}.pdf"

            is_file_valid = final_path.exists() and final_path.is_file() and final_path.stat().st_size > 0

            # Skip recipient only when status is GENERATED, fingerprint_id is non-null, and output PDF exists and is valid
            if recipient.status == "GENERATED" and recipient.fingerprint_id is not None and is_file_valid:
                continue

            existing_fp = None
            if recipient.fingerprint_id is not None:
                existing_fp = repo.get_fingerprint_by_id(recipient.fingerprint_id)

            # Reconciliation check: if final_path already exists on disk from an interrupted previous run
            if is_file_valid and existing_fp is not None:
                reconcile_res = service.verify_saved_pdf_carriers(
                    str(final_path),
                    doc.document_uid,
                    recipient.recipient_identifier,
                    existing_fp.nonce,
                    existing_fp.fingerprint,
                    stego_expected=stego_enabled,
                )
                if reconcile_res.is_valid:
                    # final_path is already authentic and verified! Reconcile database update only:
                    if recipient.generated_at and recipient.expires_at:
                        gen_at = recipient.generated_at
                        exp_at = recipient.expires_at
                    else:
                        now_utc = datetime.now(timezone.utc)
                        gen_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                        exp_at = (now_utc + timedelta(seconds=expiry_duration_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

                    token = recipient.download_token or secrets.token_urlsafe(32)
                    repo.update_recipient_status_generated(
                        recipient_id=recipient.id,
                        generated_at=gen_at,
                        expires_at=exp_at,
                        download_token=token,
                    )
                    continue

            # Note: If existing final_path failed verification, do not delete it before a replacement
            # has been generated and independently verified. Only then atomically replace it.
            # If regeneration fails, preserve the existing artifact for investigation.
            had_existing_final = final_path.exists()
            promoted_this_attempt = False

            try:
                # Ensure stale temp_path from any prior aborted attempt is cleaned up
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)

                if existing_fp is not None:
                    # Reuse existing cryptographic nonce and fingerprint to avoid corrupting or duplicating attribution
                    nonce = existing_fp.nonce
                    fingerprint_hex = existing_fp.fingerprint
                else:
                    nonce, fingerprint_hex = service.generate_fingerprint_payload(
                        recipient.recipient_identifier,
                        doc.document_uid
                    )

                # Stage 1: Generate payload and embed to temporary file
                embed_stage = service.embed_and_save_pdf(
                    doc.document_uid,
                    recipient.recipient_identifier,
                    nonce,
                    fingerprint_hex,
                    str(input_pdf_path),
                    str(temp_path),
                )

                if not embed_stage.success or embed_stage.l3_status == "FAILED":
                    raise RuntimeError(f"Embedding stage failed for recipient {recipient.id}: {embed_stage.error or 'L3 failure'}")

                if not temp_path.exists() or temp_path.stat().st_size == 0:
                    raise RuntimeError(f"Temporary PDF generation produced an invalid file for recipient {recipient.id}")

                # Stage 2: Post-Serialization Output Verification on temp_path
                stego_expected = (embed_stage.l3_status == "EMBEDDED")
                stego_skipped_capacity = (embed_stage.l3_status == "SKIPPED_INSUFFICIENT_CAPACITY")
                verify_result = service.verify_saved_pdf_carriers(
                    str(temp_path),
                    doc.document_uid,
                    recipient.recipient_identifier,
                    nonce,
                    fingerprint_hex,
                    stego_expected=stego_expected,
                    stego_skipped_capacity=stego_skipped_capacity,
                )

                if not verify_result.is_valid:
                    raise RuntimeError(f"Post-generation verification failed for recipient {recipient.id}: {verify_result.error or 'Carrier verification failed'}")

                # 3. Atomically replace final opaque path (only now, after temp_path is 100% verified!)
                temp_path.replace(final_path)
                promoted_this_attempt = True

                # 4. Commit database updates
                if existing_fp is not None:
                    # Regenerated/re-verified file: preserve existing attribution without duplicating fingerprints
                    if recipient.generated_at and recipient.expires_at:
                        gen_at = recipient.generated_at
                        exp_at = recipient.expires_at
                    else:
                        now_utc = datetime.now(timezone.utc)
                        gen_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                        exp_at = (now_utc + timedelta(seconds=expiry_duration_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

                    token = recipient.download_token or secrets.token_urlsafe(32)
                    repo.update_recipient_status_generated(
                        recipient_id=recipient.id,
                        generated_at=gen_at,
                        expires_at=exp_at,
                        download_token=token
                    )
                else:
                    # Fresh generation: calculate timezone-aware UTC timestamps
                    now_utc = datetime.now(timezone.utc)
                    generated_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    expires_at = (now_utc + timedelta(seconds=expiry_duration_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    download_token = secrets.token_urlsafe(32)

                    # Commit fingerprint, token, and recipient link in single atomic DB transaction
                    repo.record_recipient_generation(
                        recipient_id=recipient.id,
                        document_id=doc.id,
                        student_id=recipient.student_id,
                        nonce=nonce,
                        fingerprint_hex=fingerprint_hex,
                        generated_at=generated_at,
                        expires_at=expires_at,
                        download_token=download_token
                    )
            except Exception as e:
                # Safe cleanup: only remove temporary artifacts owned by this attempt.
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                # If fresh attempt promoted final_path but subsequent DB commit failed:
                # remove the uncommitted orphan so no orphan file remains on disk.
                # If final_path existed prior to this attempt, it is preserved for investigation.
                if promoted_this_attempt and not had_existing_final and final_path.exists():
                    final_path.unlink(missing_ok=True)
                logger.warning(
                    "Batch recipient generation failed: batch_uid=%s, error_type=%s",
                    safe_batch_uid,
                    type(e).__name__,
                )
                repo.record_recipient_failure(recipient.id)

        repo.finalize_batch_generation_status(batch_id)
    finally:
        _ACTIVE_BATCH_GENERATIONS.discard(batch_uid)
        repo.release_batch_claim(batch_id)

@router.post("/batches/{batch_uid}/generate", response_model=DistributionBatchResponse)
def trigger_batch_generation(
    batch_uid: str,
    background_tasks: BackgroundTasks,
    sync: bool = False,
    current_user: User = Depends(get_current_user_from_session),
    repo: Repository = Depends(get_repository),
    service: FingerprintService = Depends(get_fingerprint_service),
):
    """
    Triggers personalized PDF generation for all uncompleted recipients in a batch.
    Protects against concurrent runs, supports recovery of interrupted jobs,
    and isolates partial failures safely.
    """
    batch = repo.get_distribution_batch_by_uid(batch_uid)
    if not batch:
        raise HTTPException(status_code=404, detail="Distribution batch not found")

    if batch.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to generate this batch."
        )

    doc = repo.get_document_by_id(batch.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Source document record not found")

    input_pdf_path = config.DOCUMENTS_DIR / f"{doc.document_uid}.pdf"
    if not input_pdf_path.exists():
        raise HTTPException(status_code=404, detail="Source document PDF file not found on server")

    # If all already completed:
    if batch.status == "COMPLETED":
        recipients = repo.get_batch_recipients(batch.id)
        # Check if all files actually exist; if not, allow regeneration
        batch_dir = config.OUTPUT_DIR / "batches" / batch.batch_uid.replace("/", "_").replace("\\", "_")
        all_files_exist = all((batch_dir / f"rec_{r.id}.pdf").exists() for r in recipients)
        if all_files_exist:
            return _format_batch_response(batch, doc.document_uid, recipients)

    # Check active in-process lock
    if batch.batch_uid in _ACTIVE_BATCH_GENERATIONS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Batch generation is currently in progress."
        )

    # If batch is in PROCESSING but not in _ACTIVE_BATCH_GENERATIONS, it was interrupted by server restart
    is_interrupted = (batch.status == "PROCESSING")
    claimed = repo.claim_batch_for_generation(batch.id, allow_recovery=is_interrupted)
    if not claimed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Batch generation could not be claimed."
        )

    # Synchronously acquire lock BEFORE scheduling background task
    _ACTIVE_BATCH_GENERATIONS.add(batch.batch_uid)

    try:
        # Refresh batch record
        batch = repo.get_distribution_batch_by_uid(batch_uid)

        if sync:
            _process_batch_generation(
                batch.id,
                batch.batch_uid,
                doc.document_uid,
                batch.expiry_duration_seconds,
                repo,
                service
            )
            batch = repo.get_distribution_batch_by_uid(batch_uid)
            recipients = repo.get_batch_recipients(batch.id)
            return _format_batch_response(batch, doc.document_uid, recipients)
        else:
            background_tasks.add_task(
                _process_batch_generation,
                batch.id,
                batch.batch_uid,
                doc.document_uid,
                batch.expiry_duration_seconds,
                repo,
                service
            )
            recipients = repo.get_batch_recipients(batch.id)
            return _format_batch_response(batch, doc.document_uid, recipients)
    except Exception:
        _ACTIVE_BATCH_GENERATIONS.discard(batch.batch_uid)
        repo.release_batch_claim(batch.id)
        raise

@router.get("/download/{token}")
def download_recipient_pdf(token: str, repo: Repository = Depends(get_repository)):
    """
    Public bearer-token endpoint for downloading a recipient's personalized watermarked PDF.
    - Public access; no recipient login required.
    - Validates token (404 on invalid).
    - Checks expiry server-side on every request (410 on expired).
    - Streams valid PDF with a sanitized, non-sensitive filename (no recipient identifier, no internal IDs or paths).
    - Prevents new downloads after expiry and coordinates safely with concurrent downloads and cleanup.
    """
    result = repo.get_recipient_by_download_token(token)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or non-existent download token."
        )

    recipient, batch, doc = result

    # Server-side expiry check
    now_utc = datetime.now(timezone.utc)
    is_expired = False
    if recipient.expires_at:
        try:
            exp_dt = datetime.fromisoformat(recipient.expires_at.replace("Z", "+00:00"))
            if now_utc >= exp_dt:
                is_expired = True
        except Exception:
            is_expired = True

    safe_batch_uid = batch.batch_uid.replace("/", "_").replace("\\", "_")
    batch_dir = config.OUTPUT_DIR / "batches" / safe_batch_uid
    pdf_path = batch_dir / f"rec_{recipient.id}.pdf"

    if is_expired or recipient.status == "EXPIRED":
        if recipient.status != "EXPIRED":
            repo.mark_recipient_expired(recipient.id)

        with _DOWNLOAD_LOCK:
            is_in_use = _ACTIVE_DOWNLOADS.get(pdf_path, 0) > 0

        if not is_in_use and pdf_path.exists():
            pdf_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This download link has expired."
        )

    if recipient.status != "GENERATED" or not pdf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The requested document is not available."
        )

    # Register active download under lock via idempotent reference-counted guard
    guard = DownloadReleaseGuard(pdf_path)

    # Sanitize download filename: use clean document name without recipient IDs, internal paths, or database keys
    base_name = Path(doc.original_filename).stem
    clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', base_name).strip('_')
    if not clean_name:
        clean_name = "document"
    download_filename = f"{clean_name}.pdf"

    try:
        f = open(pdf_path, "rb")
        guard.attach_file(f)
    except Exception:
        guard.release()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read document file."
        )

    def iter_file():
        try:
            while chunk := f.read(64 * 1024):
                yield chunk
        finally:
            guard.release()

    return StreamingResponse(
        iter_file(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{download_filename}"'
        },
        background=BackgroundTask(guard.release)
    )

def run_expired_batch_pdfs_cleanup(repo: Optional[Repository] = None) -> int:
    """
    Lightweight periodic cleanup function:
    - Scans for expired batch recipient PDFs.
    - Safely unlinks expired PDF files on disk.
    - Never unlinks a file currently in _ACTIVE_DOWNLOADS.
    - Strictly preserves database records (recipients, students, fingerprints, batches).
    - Returns count of files deleted.
    """
    if repo is None:
        repo = Repository()

    now_utc_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    expired = repo.get_expired_recipients_for_cleanup(now_utc_iso)

    cleaned = 0
    for rec_id, batch_uid, rec_status in expired:
        if rec_status != "EXPIRED":
            repo.mark_recipient_expired(rec_id)

        safe_batch_uid = batch_uid.replace("/", "_").replace("\\", "_")
        batch_dir = config.OUTPUT_DIR / "batches" / safe_batch_uid
        pdf_path = batch_dir / f"rec_{rec_id}.pdf"

        with _DOWNLOAD_LOCK:
            is_in_use = _ACTIVE_DOWNLOADS.get(pdf_path, 0) > 0

        if not is_in_use and pdf_path.exists():
            try:
                pdf_path.unlink(missing_ok=True)
                cleaned += 1
            except Exception as e:
                logger.warning(f"Failed to delete expired batch PDF {pdf_path}: {e}")

    return cleaned

async def periodic_cleanup_loop(interval_seconds: int = 15):
    """Periodic background cleanup loop running while the server is active."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            run_expired_batch_pdfs_cleanup()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Error in periodic_cleanup_loop: {e}")



