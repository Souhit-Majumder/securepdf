"""
FastAPI route for read-only PDF structural inspection.

Guarantees:
- Zero database queries, connections, or writes.
- Zero master-key access or active verification.
- Zero ephemeral simulations or worker process spawns.
- Chunked streaming upload with strict 20 MB ceiling.
- Best-effort temporary file cleanup on success, exceptions, and task cancellation.
- Generic public error responses without leaking file paths or internal exceptions.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import threading
import uuid
import fitz
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from app.api.dependencies import (
    get_authenticated_forensic_context,
    get_inspection_service,
    get_optional_user_from_session,
    get_repository,
)
from app.database.repository import Repository
from app.database.models import User
from app.api.schemas.inspection import (
    ActiveVerificationResponseDTO,
    CarrierStatusType,
    InspectionResponseDTO,
    MinimizedAnnotationLocationDTO,
    MinimizedCarrierDTO,
    MinimizedCatalogLocationDTO,
    MinimizedContentStreamLocationDTO,
    MinimizedCrossLayerDTO,
    PageDimensionDTO,
    VerificationStatusType,
)
from app.config import config
from app.inspection.models import (
    AnnotationLocation,
    AuthorizationContext,
    CatalogLocation,
)
from app.inspection.pdf_inspector import PdfStructuralInspector
from app.inspection.service import InspectionService

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB
CHUNK_SIZE = 64 * 1024              # 64 KB
ALLOWED_ROTATIONS = (0, 90, 180, 270)


async def save_upload_pdf(file: UploadFile, dest_path: Path) -> None:
    """
    Validates PDF magic bytes, bounds upload size to 20 MB,
    and streams the upload to destination in 64 KB chunks.
    """
    first_chunk = await file.read(CHUNK_SIZE)
    if not first_chunk.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="Invalid PDF file format: missing '%PDF-' header",
        )

    total_bytes = len(first_chunk)
    if total_bytes > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File too large (maximum 20MB)",
        )

    with open(dest_path, "wb") as f:
        f.write(first_chunk)
        while chunk := await file.read(CHUNK_SIZE):
            total_bytes += len(chunk)
            if total_bytes > MAX_UPLOAD_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail="File too large (maximum 20MB)",
                )
            f.write(chunk)


def map_report_carriers(carriers: list) -> list[MinimizedCarrierDTO]:
    """Maps internal carrier inspection results to privacy-safe minimized DTOs."""
    minimized_carriers: list[MinimizedCarrierDTO] = []
    for carrier in carriers:
        cat_loc: MinimizedCatalogLocationDTO | None = None
        annot_locs: list[MinimizedAnnotationLocationDTO] = []
        stream_locs: list[MinimizedContentStreamLocationDTO] = []

        for loc in carrier.locations:
            if isinstance(loc, CatalogLocation):
                cat_loc = MinimizedCatalogLocationDTO(
                    carrier_type="CATALOG",
                    catalog_xref=loc.catalog_xref,
                )
            elif isinstance(loc, AnnotationLocation):
                annot_locs.append(
                    MinimizedAnnotationLocationDTO(
                        carrier_type="ANNOTATION",
                        page_index=loc.page_index,
                        annotation_xref=loc.annotation_xref,
                        rect=[float(v) for v in loc.rect],
                        title=loc.title,
                    )
                )

        if carrier.modulation_samples:
            for sample in carrier.modulation_samples:
                s_loc = sample.location
                stream_locs.append(
                    MinimizedContentStreamLocationDTO(
                        carrier_type="CONTENT_STREAM",
                        page_index=s_loc.page_index,
                        content_stream_xref=s_loc.content_stream_xref,
                        gap_index=s_loc.gap_index,
                        displacement=s_loc.displacement,
                        bit_value=s_loc.bit_value,
                        is_intentional=sample.is_intentional_modulation,
                    )
                )

        min_carrier = MinimizedCarrierDTO(
            carrier_name=carrier.carrier_name,
            status=carrier.status,
            signature_ref=carrier.signature_ref,
            total_word_gaps=carrier.total_word_gaps,
            modulated_word_gaps=carrier.modulated_word_gaps,
            bit_1_count=carrier.bit_1_count,
            bit_0_count=carrier.bit_0_count,
            catalog_location=cat_loc,
            annotation_locations=annot_locs,
            content_stream_locations=stream_locs,
        )
        minimized_carriers.append(min_carrier)
    return minimized_carriers


@router.post("/inspect", response_model=InspectionResponseDTO)
async def inspect_document(file: UploadFile = File(...)) -> InspectionResponseDTO:
    """
    Performs purely read-only structural inspection on an uploaded PDF.
    Does not access the database, master key, or active verification services.
    """
    request_id = uuid.uuid4().hex
    temp_dir = config.TEMP_DIR
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"inspect_{request_id}.pdf"

    try:
        # 1. Stream and validate uploaded PDF to temporary storage
        await save_upload_pdf(file, temp_path)

        # 2. Extract page dimensions using PyMuPDF in read-only mode
        try:
            doc = fitz.open(str(temp_path))
        except Exception as exc:
            logger.warning(
                "PDF open failed: request_id=%s, error_type=%s",
                request_id,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=422,
                detail="Unprocessable PDF: document structure is corrupt or unparseable",
            )

        page_dimensions: list[PageDimensionDTO] = []
        try:
            for p_idx, page in enumerate(doc):
                rot = page.rotation % 360
                valid_rot = rot if rot in ALLOWED_ROTATIONS else 0
                mb = [float(page.mediabox.x0), float(page.mediabox.y0), float(page.mediabox.x1), float(page.mediabox.y1)]
                cb = [float(page.cropbox.x0), float(page.cropbox.y0), float(page.cropbox.x1), float(page.cropbox.y1)]
                page_dimensions.append(
                    PageDimensionDTO(
                        page_index=p_idx,
                        width=float(page.rect.width),
                        height=float(page.rect.height),
                        rotation=valid_rot,  # type: ignore[arg-type]
                        cropbox=cb,
                        mediabox=mb,
                    )
                )
        finally:
            doc.close()

        # 3. Instantiate isolated ephemeral structural inspector (ZERO DB ACCESS)
        inspector = PdfStructuralInspector(session_id=request_id)
        report = inspector.inspect_pdf(str(temp_path))

        # 4. Map report to minimized, privacy-safe DTO
        document_uid = (
            report.document_uid
            if report.document_uid and report.document_uid != "UNKNOWN"
            else None
        )
        subject_ref = (
            report.subject.subject_ref
            if report.subject and report.subject.subject_ref and report.subject.subject_ref != "subj_anon_unknown"
            else None
        )

        minimized_carriers = map_report_carriers(report.carriers)

        cross_layer = MinimizedCrossLayerDTO(
            carrier_tokens_match=report.cross_layer.signatures_match,
            cross_carrier_conflict=report.cross_layer.cross_carrier_conflict,
            conflict_reason=report.cross_layer.conflict_reason,
        )

        return InspectionResponseDTO(
            document_uid=document_uid,
            overall_status=report.overall_status,  # type: ignore[arg-type]
            subject_ref=subject_ref,
            page_dimensions=page_dimensions,
            carriers=minimized_carriers,
            cross_layer=cross_layer,
            timestamp=report.timestamp,
        )

    except asyncio.CancelledError:
        logger.info("Inspection request cancelled by client: request_id=%s", request_id)
        raise
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Inspection error: request_id=%s, error_type=%s",
            request_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "Internal inspection error", "request_id": request_id},
        )
    finally:
        # Best-effort temporary file deletion
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception as cleanup_err:
                logger.warning(
                    "Failed to delete temp file %s: %s",
                    request_id,
                    type(cleanup_err).__name__,
                )


@router.post("/verify", response_model=ActiveVerificationResponseDTO)
async def verify_document(
    request: Request,
    file: UploadFile = File(...),
    auth_ctx: AuthorizationContext = Depends(get_authenticated_forensic_context),
    optional_user: Optional[User] = Depends(get_optional_user_from_session),
    inspection_service: InspectionService = Depends(get_inspection_service),
    repo: Repository = Depends(get_repository),
) -> ActiveVerificationResponseDTO:
    """
    Performs active cryptographic fingerprint investigation and verification.
    Guarantees:
    - Enforces forensic key authentication and anti-oracle rate limiting.
    - Runs isolated verification pipeline while collecting bounded evidence.
    - Enforces document ownership when authenticated user session is present.
    - Redacts recipient PII when invoked purely via forensic audit key.
    - Cooperative cancellation via ASGI disconnect monitoring and threading.Event.
    - Best-effort temporary file cleanup.
    - Minimized, privacy-safe response DTO without master keys, HMACs, or nonces.
    """
    request_id = uuid.uuid4().hex
    temp_dir = config.TEMP_DIR
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"verify_{request_id}.pdf"

    cancel_event = threading.Event()

    try:
        # 1. Stream and validate uploaded PDF to temporary storage
        await save_upload_pdf(file, temp_path)

        # 2. Watcher for ASGI client disconnection
        async def watch_client_disconnect():
            while not cancel_event.is_set():
                if await request.is_disconnected():
                    cancel_event.set()
                    logger.info("Client HTTP disconnect detected during verification: request_id=%s", request_id)
                    break
                await asyncio.sleep(0.05)

        worker_task = asyncio.create_task(
            asyncio.to_thread(
                inspection_service.investigate_with_evidence,
                str(temp_path),
                auth_ctx,
                cancel_event,
            )
        )
        watcher_task = asyncio.create_task(watch_client_disconnect())

        done, pending = await asyncio.wait(
            [worker_task, watcher_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for t in pending:
            t.cancel()

        if cancel_event.is_set() and not worker_task.done():
            raise HTTPException(status_code=499, detail="Client closed request")

        result_dict, report = await worker_task

        # 3. Map to ActiveVerificationResponseDTO & Scoping
        verification_status = result_dict.get("status", report.overall_status)
        authenticated_layers = result_dict.get("authenticated_layers", [])
        reason = result_dict.get("reason", None)

        document_uid = (
            report.document_uid
            if report.document_uid and report.document_uid != "UNKNOWN"
            else None
        )
        subject_ref = (
            report.subject.subject_ref
            if report.subject and report.subject.subject_ref and report.subject.subject_ref != "subj_anon_unknown"
            else None
        )

        # Recipient PII Scoping and Document Ownership:
        recipient_name: Optional[str] = None
        recipient_identifier: Optional[str] = None

        if optional_user is not None:
            # Authenticated session: verify document ownership before releasing recipient PII
            if document_uid:
                doc_record = repo.get_document_by_uid(document_uid)
                if not doc_record or doc_record.user_id != optional_user.id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access denied: You do not own the document carrier in this file."
                    )
            if verification_status == "VALID":
                recipient_name = result_dict.get("recipient_name")
                recipient_identifier = result_dict.get("recipient_identifier")
        else:
            # Independent forensic audit-key only: strictly redact recipient PII
            recipient_name = None
            recipient_identifier = None

        minimized_carriers = map_report_carriers(report.carriers)

        cross_layer = MinimizedCrossLayerDTO(
            carrier_tokens_match=report.cross_layer.signatures_match,
            cross_carrier_conflict=report.cross_layer.cross_carrier_conflict,
            conflict_reason=report.cross_layer.conflict_reason,
        )

        return ActiveVerificationResponseDTO(
            verification_status=verification_status,
            authenticated_layers=authenticated_layers,
            reason=reason,
            document_uid=document_uid,
            subject_ref=subject_ref,
            recipient_name=recipient_name,
            recipient_identifier=recipient_identifier,
            carriers=minimized_carriers,
            cross_layer=cross_layer,
            timestamp=report.timestamp,
        )

    except HTTPException:
        raise
    except asyncio.CancelledError:
        logger.info("Verification request cancelled: request_id=%s", request_id)
        cancel_event.set()
        raise
    except Exception as exc:
        logger.error(
            "Verification error: request_id=%s, error_type=%s",
            request_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "Internal verification error", "request_id": request_id},
        )
    finally:
        # Best-effort temporary file cleanup
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception as cleanup_err:
                logger.warning(
                    "Failed to delete temp file %s: %s",
                    temp_path,
                    type(cleanup_err).__name__,
                )
