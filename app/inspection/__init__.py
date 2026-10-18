"""
SecurePDF Visualization-Ready Evidence & Inspection Engine.
Provides strongly-typed evidence data models, event collectors, and read-only structural inspectors.
"""
from app.inspection.models import (
    CatalogLocation,
    AnnotationLocation,
    ContentStreamLocation,
    LocationModel,
    ModulationSample,
    CarrierVerificationStatus,
    CarrierInspectionResult,
    SubjectEvidence,
    CrossLayerEvidence,
    EvidenceReport,
    AuthorizationContext,
    create_subject_ref,
    create_evidence_ref,
    redact_subject_evidence,
)
from app.inspection.collector import EvidenceCollector
from app.inspection.pdf_inspector import PdfStructuralInspector
from app.inspection.service import InspectionService

__all__ = [
    "CatalogLocation",
    "AnnotationLocation",
    "ContentStreamLocation",
    "LocationModel",
    "ModulationSample",
    "CarrierVerificationStatus",
    "CarrierInspectionResult",
    "SubjectEvidence",
    "CrossLayerEvidence",
    "EvidenceReport",
    "AuthorizationContext",
    "create_subject_ref",
    "create_evidence_ref",
    "redact_subject_evidence",
    "EvidenceCollector",
    "PdfStructuralInspector",
    "InspectionService",
]
