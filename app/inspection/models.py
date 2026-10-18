"""
Data models for SecurePDF evidence reporting and inspection.

Guarantees:
- Secrets (master keys, subkeys, raw nonces, raw HMACs, canonical messages)
  are completely excluded from all models.
- Student PII is guarded by a trusted AuthorizationContext.
- Location schemas strictly separate catalog, annotation, and content-stream primitives.
"""
from __future__ import annotations

import hashlib
from typing import Any, List, Literal, Optional, Union
from pydantic import BaseModel, Field, ConfigDict


class CatalogLocation(BaseModel):
    """Layer 1: Document Catalog dictionary entry."""
    model_config = ConfigDict(frozen=True)

    carrier_type: Literal["CATALOG"] = "CATALOG"
    catalog_xref: int
    key_name: Literal["SPDFPayload"] = "SPDFPayload"
    format: Literal["HEX_STRING"] = "HEX_STRING"


class AnnotationLocation(BaseModel):
    """Layer 2: Invisible Annotation on Page 0."""
    model_config = ConfigDict(frozen=True)

    carrier_type: Literal["ANNOTATION"] = "ANNOTATION"
    page_index: int = 0
    annotation_xref: int
    rect: List[float]  # [x0, y0, x1, y1]
    flags: int = 35    # 1 (Invisible) + 2 (Hidden) + 32 (NoView)
    opacity: float = 0.0
    title: str         # e.g. "SPDF0", "SPDF1", "SPDF2"


class ContentStreamLocation(BaseModel):
    """Layer 3: TJ operator inter-word gap in page content stream."""
    model_config = ConfigDict(frozen=True)

    carrier_type: Literal["CONTENT_STREAM"] = "CONTENT_STREAM"
    page_index: int
    content_stream_xref: int
    gap_index: int
    content_stream_offset: int  # 0-indexed byte offset in uncompressed page stream
    preceding_word: str
    displacement: int           # -20 for bit 1, 0 for bit 0
    bit_value: Optional[Literal["0", "1"]] = None  # None for unconfirmed static syntax


LocationModel = Union[CatalogLocation, AnnotationLocation, ContentStreamLocation]


class ModulationSample(BaseModel):
    """Telemetry sample of a modulated inter-word gap."""
    model_config = ConfigDict(frozen=True)

    location: ContentStreamLocation
    is_intentional_modulation: bool
    source: Literal["RUNTIME_CAPTURE", "STRUCTURAL_RESCAN"]


CarrierVerificationStatus = Literal[
    "VALID",
    "INVALID",
    "NOT_FOUND",
    "SECURITY_CONFLICT",
    "ERROR",
    "OBSERVED_SYNTAX",
    "STRUCTURALLY_DECODED",
]


class CarrierInspectionResult(BaseModel):
    """Inspection or verification result for a single carrier layer."""
    carrier_name: Literal[
        "Layer 1 (Catalog)",
        "Layer 2 (Annotations)",
        "Layer 3 (Stego Kerning)",
    ]
    status: CarrierVerificationStatus
    locations: List[LocationModel] = Field(default_factory=list)
    signature_ref: Optional[str] = None  # Opaque session reference (e.g. "evref_sig_01")
    nonce_ref: Optional[str] = None      # Opaque session reference (e.g. "evref_nonce_01")
    total_word_gaps: Optional[int] = None
    modulated_word_gaps: Optional[int] = None
    bit_1_count: Optional[int] = None
    bit_0_count: Optional[int] = None
    modulation_samples: List[ModulationSample] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class SubjectEvidence(BaseModel):
    """Student identity evidence with redaction support."""
    subject_ref: str                    # Always safe opaque reference (e.g. "subj_anon_8f3d")
    student_uid: Optional[str] = None   # Populated ONLY when caller is authorized for PII
    student_name: Optional[str] = None  # Populated ONLY when caller is authorized for PII


class CrossLayerEvidence(BaseModel):
    """Cross-layer correlation and conflict analysis."""
    l1_signature_ref: Optional[str] = None
    l2_signature_refs: List[str] = Field(default_factory=list)
    l3_signature_ref: Optional[str] = None
    signatures_match: Optional[bool] = None
    cross_carrier_conflict: bool = False
    conflict_reason: Optional[str] = None


class EvidenceReport(BaseModel):
    """Top-level evidence report across all carriers."""
    document_uid: str
    overall_status: str
    subject: SubjectEvidence
    carriers: List[CarrierInspectionResult] = Field(default_factory=list)
    cross_layer: CrossLayerEvidence = Field(default_factory=CrossLayerEvidence)
    telemetry_source: Literal[
        "READ_ONLY_INSPECTION",
        "ACTIVE_VERIFICATION",
        "EPHEMERAL_SIMULATION",
    ]
    timestamp: str


class AuthorizationContext(BaseModel):
    """Trusted authorization context evaluated by server boundaries."""
    principal: str
    roles: List[str] = Field(default_factory=list)
    has_pii_clearance: bool = False


def create_subject_ref(student_uid: str, session_salt: str = "") -> str:
    """Produces an opaque, deterministic, session-scoped pseudonym for student identity."""
    digest = hashlib.sha256(f"{student_uid}:{session_salt}".encode("utf-8")).hexdigest()
    return f"subj_anon_{digest[:8]}"


def create_evidence_ref(prefix: str, index: int) -> str:
    """Produces a clean, opaque session reference token (e.g. 'evref_sig_01')."""
    return f"evref_{prefix}_{index:02d}"


def redact_subject_evidence(
    subject: SubjectEvidence,
    auth_ctx: AuthorizationContext,
) -> SubjectEvidence:
    """
    Applies trusted boundary redaction: if the caller lacks PII clearance,
    returns a new SubjectEvidence instance containing only subject_ref.
    """
    if not auth_ctx.has_pii_clearance:
        return SubjectEvidence(
            subject_ref=subject.subject_ref,
            student_uid=None,
            student_name=None,
        )
    return subject
