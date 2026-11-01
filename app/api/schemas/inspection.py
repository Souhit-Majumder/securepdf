"""
Minimized, privacy-safe Pydantic DTO schemas for SecurePDF structural inspection.

Guarantees:
- extra="forbid" on all models to prevent unknown or internal model field leakage.
- Strict field whitelisting: no raw cryptographic material, nonces, HMACs, or master keys.
- No document text (preceding_word omitted).
- No personal student information (student_uid and student_name excluded).
- subject_ref is optional and None when absent; never defaults to placeholder identity tokens.
- document_uid is optional and None when absent or unknown.
- Rotation is strictly validated to orthogonal rotations: 0, 90, 180, 270.
"""
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

CarrierStatusType = Literal[
    "VALID",
    "STRUCTURALLY_DECODED",
    "OBSERVED_SYNTAX",
    "INVALID",
    "NOT_FOUND",
    "SECURITY_CONFLICT",
    "ERROR",
]

VerificationStatusType = Literal[
    "VALID",
    "INVALID",
    "NOT_FOUND",
    "SECURITY_CONFLICT",
    "ERROR",
]


class PageDimensionDTO(BaseModel):
    """Geometry and rotation metadata for a single PDF page."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_index: int = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rotation: Literal[0, 90, 180, 270]
    cropbox: List[float] = Field(min_length=4, max_length=4)
    mediabox: List[float] = Field(min_length=4, max_length=4)


class MinimizedCatalogLocationDTO(BaseModel):
    """Layer 1: Structural catalog dictionary object reference."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    carrier_type: Literal["CATALOG"] = "CATALOG"
    catalog_xref: int = Field(ge=0)


class MinimizedAnnotationLocationDTO(BaseModel):
    """Layer 2: Structural annotation location in unrotated page coordinates."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    carrier_type: Literal["ANNOTATION"] = "ANNOTATION"
    page_index: int = Field(ge=0)
    annotation_xref: int = Field(ge=0)
    rect: List[float] = Field(min_length=4, max_length=4)
    title: str = Field(max_length=64)


class MinimizedContentStreamLocationDTO(BaseModel):
    """Layer 3: Structural inter-word gap modulation sample."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    carrier_type: Literal["CONTENT_STREAM"] = "CONTENT_STREAM"
    page_index: int = Field(ge=0)
    content_stream_xref: int = Field(ge=0)
    gap_index: int = Field(ge=0)
    displacement: int
    bit_value: Optional[Literal["0", "1"]] = None
    is_intentional: bool


class MinimizedCarrierDTO(BaseModel):
    """Inspection result for a single carrier layer."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    carrier_name: Literal[
        "Layer 1 (Catalog)",
        "Layer 2 (Annotations)",
        "Layer 3 (Stego Kerning)",
    ]
    status: CarrierStatusType
    signature_ref: Optional[str] = Field(default=None, max_length=64)
    total_word_gaps: Optional[int] = Field(default=None, ge=0)
    modulated_word_gaps: Optional[int] = Field(default=None, ge=0)
    bit_1_count: Optional[int] = Field(default=None, ge=0)
    bit_0_count: Optional[int] = Field(default=None, ge=0)
    catalog_location: Optional[MinimizedCatalogLocationDTO] = None
    annotation_locations: List[MinimizedAnnotationLocationDTO] = Field(default_factory=list)
    content_stream_locations: List[MinimizedContentStreamLocationDTO] = Field(default_factory=list)


class MinimizedCrossLayerDTO(BaseModel):
    """Cross-layer structural consistency analysis."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    carrier_tokens_match: Optional[bool] = None
    cross_carrier_conflict: bool = False
    conflict_reason: Optional[str] = Field(default=None, max_length=256)


class InspectionResponseDTO(BaseModel):
    """Top-level structural inspection response returned by the API."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_uid: Optional[str] = Field(default=None, max_length=64)
    overall_status: CarrierStatusType
    subject_ref: Optional[str] = Field(default=None, max_length=64)
    page_dimensions: List[PageDimensionDTO] = Field(default_factory=list)
    carriers: List[MinimizedCarrierDTO] = Field(default_factory=list)
    cross_layer: MinimizedCrossLayerDTO = Field(default_factory=MinimizedCrossLayerDTO)
    timestamp: str = Field(max_length=64)


class ActiveVerificationResponseDTO(BaseModel):
    """
    Top-level active verification response returned by the API.
    Privacy-safe, minimized DTO: zero leakage of secrets, nonces, raw HMACs, or student PII.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    verification_status: VerificationStatusType
    authenticated_layers: List[str] = Field(default_factory=list)
    reason: Optional[str] = Field(default=None, max_length=256)
    document_uid: Optional[str] = Field(default=None, max_length=64)
    subject_ref: Optional[str] = Field(default=None, max_length=64)
    carriers: List[MinimizedCarrierDTO] = Field(default_factory=list)
    cross_layer: MinimizedCrossLayerDTO = Field(default_factory=MinimizedCrossLayerDTO)
    timestamp: str = Field(max_length=64)
