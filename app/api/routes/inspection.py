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
import re
import uuid
import fitz
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.schemas.inspection import (
    CarrierStatusType,
    InspectionResponseDTO,
    MinimizedAnnotationLocationDTO,
    MinimizedCarrierDTO,
    MinimizedCatalogLocationDTO,
    MinimizedContentStreamLocationDTO,
    MinimizedCrossLayerDTO,
    PageDimensionDTO,
)
from app.config import config
from app.inspection.models import AnnotationLocation, CatalogLocation
from app.inspection.pdf_inspector import PdfStructuralInspector

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB
CHUNK_SIZE = 64 * 1024              # 64 KB
ALLOWED_ROTATIONS = (0, 90, 180, 270)


def sanitize_filename(filename: str | None) -> str:
    """Strips path traversal sequences and bounds filename to safe ASCII symbols."""
    if not filename:
        return "uploaded.pdf"
    clean = re.sub(r"[^a-zA-Z0-9._-]", "_", Path(filename).name)
    return clean[:128] if clean else "uploaded.pdf"


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
        # 1. Read first chunk to validate magic bytes
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

        with open(temp_path, "wb") as f:
            f.write(first_chunk)
            while chunk := await file.read(CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="File too large (maximum 20MB)",
                    )
                f.write(chunk)

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

        minimized_carriers: list[MinimizedCarrierDTO] = []
        for carrier in report.carriers:
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
                status=carrier.status,  # type: ignore[arg-type]
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
