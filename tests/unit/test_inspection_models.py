"""
Unit tests for SecurePDF Evidence Models and Cryptographic Redaction (Stage 1).
"""
import json
import pytest
from pydantic import ValidationError

from app.inspection.models import (
    CatalogLocation,
    AnnotationLocation,
    ContentStreamLocation,
    ModulationSample,
    CarrierInspectionResult,
    SubjectEvidence,
    CrossLayerEvidence,
    EvidenceReport,
    AuthorizationContext,
    create_subject_ref,
    create_evidence_ref,
    redact_subject_evidence,
)


def test_catalog_location_schema():
    loc = CatalogLocation(catalog_xref=10)
    assert loc.carrier_type == "CATALOG"
    assert loc.catalog_xref == 10
    assert loc.key_name == "SPDFPayload"
    assert loc.format == "HEX_STRING"


def test_annotation_location_schema():
    loc = AnnotationLocation(
        page_index=0,
        annotation_xref=25,
        rect=[0.0, 0.0, 0.1, 0.1],
        title="SPDF0",
    )
    assert loc.carrier_type == "ANNOTATION"
    assert loc.page_index == 0
    assert loc.flags == 35
    assert loc.opacity == 0.0
    assert loc.title == "SPDF0"


def test_content_stream_location_schema():
    loc = ContentStreamLocation(
        page_index=1,
        content_stream_xref=15,
        gap_index=42,
        content_stream_offset=1024,
        preceding_word="SecurePDF",
        displacement=-20,
        bit_value="1",
    )
    assert loc.carrier_type == "CONTENT_STREAM"
    assert loc.page_index == 1
    assert loc.content_stream_offset == 1024
    assert loc.displacement == -20
    assert loc.bit_value == "1"


def test_modulation_sample_schema():
    loc = ContentStreamLocation(
        page_index=0,
        content_stream_xref=12,
        gap_index=3,
        content_stream_offset=150,
        preceding_word="hello",
        displacement=0,
        bit_value="0",
    )
    sample = ModulationSample(
        location=loc,
        is_intentional_modulation=True,
        source="RUNTIME_CAPTURE",
    )
    assert sample.source == "RUNTIME_CAPTURE"
    assert sample.is_intentional_modulation is True


def test_secrets_completely_excluded_from_model_fields():
    """Verify that models have no fields for raw master keys, subkeys, nonces, or HMACs."""
    forbidden_attributes = [
        "master_key",
        "derived_subkey",
        "canonical_message",
        "raw_payload",
        "nonce_bytes",
        "hmac_bytes",
        "raw_nonce",
        "raw_hmac",
    ]
    models = [
        CatalogLocation,
        AnnotationLocation,
        ContentStreamLocation,
        ModulationSample,
        CarrierInspectionResult,
        SubjectEvidence,
        CrossLayerEvidence,
        EvidenceReport,
    ]
    for model in models:
        for attr in forbidden_attributes:
            assert attr not in model.model_fields, f"Forbidden attribute '{attr}' found in {model.__name__}"


def test_trusted_authorization_boundary_pii_redaction():
    subject = SubjectEvidence(
        subject_ref="subj_anon_1234abcd",
        student_uid="STU-ALICE-100",
        student_name="Alice Smith",
    )

    unauthorized_ctx = AuthorizationContext(
        principal="auditor_guest",
        roles=["AUDITOR"],
        has_pii_clearance=False,
    )

    redacted = redact_subject_evidence(subject, unauthorized_ctx)
    assert redacted.subject_ref == "subj_anon_1234abcd"
    assert redacted.student_uid is None
    assert redacted.student_name is None

    authorized_ctx = AuthorizationContext(
        principal="compliance_officer_admin",
        roles=["ADMIN", "COMPLIANCE_OFFICER"],
        has_pii_clearance=True,
    )

    allowed = redact_subject_evidence(subject, authorized_ctx)
    assert allowed.subject_ref == "subj_anon_1234abcd"
    assert allowed.student_uid == "STU-ALICE-100"
    assert allowed.student_name == "Alice Smith"


def test_create_subject_ref_deterministic_and_opaque():
    ref1 = create_subject_ref("STU-ALICE-100", session_salt="sess_01")
    ref2 = create_subject_ref("STU-ALICE-100", session_salt="sess_01")
    ref3 = create_subject_ref("STU-ALICE-100", session_salt="sess_02")
    ref4 = create_subject_ref("STU-BOB-200", session_salt="sess_01")

    assert ref1.startswith("subj_anon_")
    assert ref1 == ref2
    assert ref1 != ref3
    assert ref1 != ref4
    assert "ALICE" not in ref1


def test_create_evidence_ref():
    ref_sig = create_evidence_ref("sig", 1)
    ref_nonce = create_evidence_ref("nonce", 2)
    assert ref_sig == "evref_sig_01"
    assert ref_nonce == "evref_nonce_02"


def test_evidence_report_serialization_integrity():
    cat_loc = CatalogLocation(catalog_xref=10)
    annot_loc = AnnotationLocation(
        page_index=0,
        annotation_xref=20,
        rect=[0.0, 0.0, 0.1, 0.1],
        title="SPDF0",
    )
    stego_loc = ContentStreamLocation(
        page_index=0,
        content_stream_xref=15,
        gap_index=1,
        content_stream_offset=80,
        preceding_word="doc",
        displacement=-20,
        bit_value="1",
    )

    sample = ModulationSample(
        location=stego_loc,
        is_intentional_modulation=True,
        source="RUNTIME_CAPTURE",
    )

    c1 = CarrierInspectionResult(
        carrier_name="Layer 1 (Catalog)",
        status="VALID",
        locations=[cat_loc],
        signature_ref="evref_sig_01",
        nonce_ref="evref_nonce_01",
    )
    c2 = CarrierInspectionResult(
        carrier_name="Layer 2 (Annotations)",
        status="VALID",
        locations=[annot_loc],
        signature_ref="evref_sig_01",
        nonce_ref="evref_nonce_01",
    )
    c3 = CarrierInspectionResult(
        carrier_name="Layer 3 (Stego Kerning)",
        status="VALID",
        locations=[stego_loc],
        signature_ref="evref_sig_01",
        nonce_ref="evref_nonce_01",
        total_word_gaps=500,
        modulated_word_gaps=250,
        bit_1_count=120,
        bit_0_count=130,
        modulation_samples=[sample],
    )

    cross = CrossLayerEvidence(
        l1_signature_ref="evref_sig_01",
        l2_signature_refs=["evref_sig_01"],
        l3_signature_ref="evref_sig_01",
        signatures_match=True,
        cross_carrier_conflict=False,
    )

    report = EvidenceReport(
        document_uid="DOC-TEST-123",
        overall_status="VALID",
        subject=SubjectEvidence(subject_ref="subj_anon_abcd1234"),
        carriers=[c1, c2, c3],
        cross_layer=cross,
        telemetry_source="ACTIVE_VERIFICATION",
        timestamp="2026-10-19T03:00:00Z",
    )

    json_str = report.model_dump_json()
    data = json.loads(json_str)

    assert data["document_uid"] == "DOC-TEST-123"
    assert len(data["carriers"]) == 3
    assert data["cross_layer"]["signatures_match"] is True
    assert data["subject"]["student_uid"] is None

    # Verify round-trip deserialization
    recovered = EvidenceReport.model_validate_json(json_str)
    assert recovered.document_uid == report.document_uid
    assert recovered.cross_layer.signatures_match is True
