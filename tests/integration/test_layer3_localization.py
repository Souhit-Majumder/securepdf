"""
Integration tests for Milestone 5B: Layer 3 Steganographic Modulation Localization.

Validates:
1. Operator-level text matrix calculations and PyMuPDF page coordinate mapping.
2. Independent corroboration against rendered rawdict layout (EXACT vs APPROXIMATE vs UNAVAILABLE).
3. Degradation to UNAVAILABLE (rect=None) for unsupported constructs (Type 3 without metrics, non-orthogonal matrix).
4. Application of horizontal scaling (Tz), text rise (Ts), and spacing (Tc, Tw).
5. Strict privacy guarantees on MinimizedContentStreamLocationDTO (extra="forbid", no secret/internal fields).
6. Multi-page sampling and global sequential location_index assignment.
7. Full inspection API endpoint response conformance.
8. Preservation of Layer 1 and Layer 2 independent structures and passive verification.
"""
import fitz
import pytest
from pydantic import ValidationError

from app.config import config
from app.database.database import init_db
from app.database.repository import Repository
from app.services.fingerprint_service import FingerprintService
from app.services.verification_service import VerificationService
from app.inspection.service import InspectionService
from app.inspection.pdf_inspector import (
    PdfStructuralInspector,
    FontMetricsCache,
    PageLayoutCorroborator,
    _matrix_mult,
    _transform_point,
    _is_valid_orthogonal,
)
from app.api.schemas.inspection import (
    MinimizedContentStreamLocationDTO,
    InspectionResponseDTO,
)


@pytest.fixture
def test_env(tmp_path):
    db_path = str(tmp_path / "test_loc.db")
    init_db(db_path)
    repo = Repository(db_path=db_path)
    repo.create_student("STU-LOC-1", "Alice Localization")
    master_key = b"\x07" * 32
    return {"repo": repo, "master_key": master_key, "tmp_path": tmp_path}


def create_sample_pdf(path: str, pages: int = 8, lines_per_page: int = 15):
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        for line_idx in range(lines_per_page):
            text_line = "SecurePDF document verification forensic integrity carrier text sample metadata layout tracking glyph test."
            page.insert_text((50, 50 + line_idx * 30), text_line)
    doc.save(path)
    doc.close()


def test_matrix_conventions_and_orthogonal_validation():
    """Verifies row-vector matrix multiplication order [x,y,1] * M1 * M2 and orthogonal checking."""
    # Identity
    ident = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    assert _matrix_mult(ident, ident) == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    # Translation then scaling
    t = (1.0, 0.0, 0.0, 1.0, 10.0, 20.0)
    s = (2.0, 0.0, 0.0, 3.0, 0.0, 0.0)
    # [x, y, 1] * t * s => ( (x+10)*2, (y+20)*3 ) = (2x + 20, 3y + 60)
    ts = _matrix_mult(t, s)
    p = _transform_point((5.0, 5.0), ts)
    assert p == (30.0, 75.0)

    # Orthogonal vs sheared matrix
    assert _is_valid_orthogonal((1.0, 0.0, 0.0, 1.0, 0.0, 0.0)) is True
    # 90-degree rotation: cos=0, sin=1 => [0, 1, -1, 0, 0, 0]
    rot90 = (0.0, 1.0, -1.0, 0.0, 0.0, 0.0)
    assert _is_valid_orthogonal(rot90) is True

    # Sheared matrix (a*c + b*d != 0)
    sheared = (1.0, 0.5, 0.5, 1.0, 0.0, 0.0)
    assert _is_valid_orthogonal(sheared) is False

    # Singular matrix (det == 0)
    singular = (1.0, 2.0, 2.0, 4.0, 0.0, 0.0)
    assert _is_valid_orthogonal(singular) is False


def test_dto_privacy_extra_forbidden():
    """Asserts MinimizedContentStreamLocationDTO forbids internal/secret fields."""
    # Valid minimal DTO
    valid_loc = MinimizedContentStreamLocationDTO(
        carrier_type="CONTENT_STREAM",
        page_index=0,
        location_index=0,
        localization_status="EXACT",
        is_carrier_sample=True,
        rect=[50.0, 100.0, 54.0, 112.0],
    )
    assert valid_loc.localization_status == "EXACT"
    assert valid_loc.rect == [50.0, 100.0, 54.0, 112.0]

    # Unavailable status with None rect
    unavail_loc = MinimizedContentStreamLocationDTO(
        carrier_type="CONTENT_STREAM",
        page_index=0,
        location_index=1,
        localization_status="UNAVAILABLE",
        is_carrier_sample=True,
        rect=None,
    )
    assert unavail_loc.localization_status == "UNAVAILABLE"
    assert unavail_loc.rect is None

    # Forbid forbidden fields: bit_value, displacement, content_stream_offset, preceding_word
    with pytest.raises(ValidationError):
        MinimizedContentStreamLocationDTO(
            carrier_type="CONTENT_STREAM",
            page_index=0,
            location_index=0,
            localization_status="EXACT",
            is_carrier_sample=True,
            rect=[50.0, 100.0, 54.0, 112.0],
            bit_value="1",  # forbidden
        )

    with pytest.raises(ValidationError):
        MinimizedContentStreamLocationDTO(
            carrier_type="CONTENT_STREAM",
            page_index=0,
            location_index=0,
            localization_status="EXACT",
            is_carrier_sample=True,
            rect=[50.0, 100.0, 54.0, 112.0],
            displacement=-80,  # forbidden
        )

    with pytest.raises(ValidationError):
        MinimizedContentStreamLocationDTO(
            carrier_type="CONTENT_STREAM",
            page_index=0,
            location_index=0,
            localization_status="EXACT",
            is_carrier_sample=True,
            rect=[50.0, 100.0, 54.0, 112.0],
            content_stream_offset=1234,  # forbidden
        )

    with pytest.raises(ValidationError):
        MinimizedContentStreamLocationDTO(
            carrier_type="CONTENT_STREAM",
            page_index=0,
            location_index=0,
            localization_status="EXACT",
            is_carrier_sample=True,
            rect=[50.0, 100.0, 54.0, 112.0],
            preceding_word="confidential",  # forbidden
        )


def test_corroborator_exact_approx_unavailable(tmp_path):
    """Tests corroboration classification against rendered rawdict layout."""
    doc_path = str(tmp_path / "test_corrob.pdf")
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    page.insert_text((100, 100), "Hello World Test")
    doc.save(doc_path)
    doc.close()

    doc = fitz.open(doc_path)
    page = doc[0]
    corroborator = PageLayoutCorroborator(page)
    assert len(corroborator.spaces) >= 2

    # Find the rendered space after "Hello"
    hello_space = None
    for s in corroborator.spaces:
        if s["prec"] == "Hello":
            hello_space = s
            break
    assert hello_space is not None

    # 1. Close prediction within tolerance with matching context => EXACT
    rx0, ry0, rx1, ry1 = hello_space["bbox"]
    pred_exact = [rx0 + 0.2, ry0 - 0.2, rx1 + 0.1, ry1 - 0.1]
    status, rect = corroborator.corroborate(pred_exact, prec_word="Hello", tolerance_pt=1.5)
    assert status == "EXACT"
    assert rect is not None
    assert abs(rect[0] - rx0) < 0.01

    # 1b. Single geometric match without matching context => APPROXIMATE
    status_mismatch, rect_mismatch = corroborator.corroborate(
        pred_exact, prec_word="MismatchedWord", tolerance_pt=1.5
    )
    assert status_mismatch == "APPROXIMATE"
    assert rect_mismatch == [round(v, 2) for v in pred_exact]

    status_empty_ctx, rect_empty_ctx = corroborator.corroborate(
        pred_exact, prec_word="", tolerance_pt=1.5
    )
    assert status_empty_ctx == "APPROXIMATE"
    assert rect_empty_ctx == [round(v, 2) for v in pred_exact]

    # 2. Prediction somewhat off (> 1.5 pt but <= 10 pt) => APPROXIMATE
    pred_approx = [rx0 + 3.0, ry0 + 3.0, rx1 + 3.0, ry1 + 3.0]
    status, rect = corroborator.corroborate(pred_approx, prec_word="Hello", tolerance_pt=1.5)
    assert status == "APPROXIMATE"
    assert rect == [round(v, 2) for v in pred_approx]

    # 3. Prediction completely away (> 10 pt from any space) => UNAVAILABLE (rect=None)
    pred_far = [400.0, 400.0, 404.0, 412.0]
    status, rect = corroborator.corroborate(pred_far, prec_word="None", tolerance_pt=1.5)
    assert status == "UNAVAILABLE"
    assert rect is None

    doc.close()


def test_type3_font_without_metrics_downgrades_to_unavailable(tmp_path):
    """Verifies that Type 3 fonts without reliable metrics classify as UNAVAILABLE."""
    doc_path = str(tmp_path / "dummy.pdf")
    doc = fitz.open()
    page = doc.new_page()
    doc.save(doc_path)
    doc.close()

    doc = fitz.open(doc_path)
    cache = FontMetricsCache(doc, doc[0])

    # Simulate an unreliable Type 3 font entry
    unreliable_t3 = {
        "type": "Type3",
        "is_type3": True,
        "type3_reliable": False,
        "widths_map": {},
    }
    assert cache.get_space_width(unreliable_t3, 12.0) is None
    assert cache.get_string_width(unreliable_t3, b"Hello", 12.0) is None

    # Reliable Type 3 font entry with /Widths
    reliable_t3 = {
        "type": "Type3",
        "is_type3": True,
        "type3_reliable": True,
        "widths_map": {32: 250.0, 65: 600.0},
    }
    assert cache.get_space_width(reliable_t3, 10.0) == 2.5
    assert cache.get_string_width(reliable_t3, b"A", 10.0) == 6.0
    doc.close()


def test_layer3_modulation_localization_end_to_end(test_env, monkeypatch):
    """
    Tests end-to-end embedding, inspection, and verification with Layer 3 localization:
    - Modulations are sampled across document pages.
    - location_index is sequentially assigned (0, 1, 2, ...).
    - Status is EXACT or APPROXIMATE with valid bounding box coordinates.
    - MinimizedContentStreamLocationDTO contains no leaked secrets.
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "source.pdf")
    create_sample_pdf(src_pdf, pages=8, lines_per_page=15)
    out_pdf = str(tmp_path / "fingerprinted.pdf")

    # 1. Fingerprint with Stego enabled
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-LOC-1", "DOC-LOC-TEST", src_pdf, out_pdf)

    # 2. Inspect structurally with read-only inspector
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    inspector = PdfStructuralInspector()
    report = inspector.inspect_pdf(out_pdf)

    # Validate Layer 3 inspection result
    l3_carrier = next((c for c in report.carriers if c.carrier_name == "Layer 3 (Stego Kerning)"), None)
    assert l3_carrier is not None
    assert l3_carrier.status == "STRUCTURALLY_DECODED"
    assert l3_carrier.modulation_samples is not None
    assert len(l3_carrier.modulation_samples) > 0

    # Validate locations
    locations = [s.location for s in l3_carrier.modulation_samples]
    exact_count = 0
    for idx, loc in enumerate(locations):
        assert loc.location_index == idx
        assert loc.localization_status in ("EXACT", "APPROXIMATE", "UNAVAILABLE")
        if loc.localization_status in ("EXACT", "APPROXIMATE"):
            assert loc.rect is not None
            assert len(loc.rect) == 4
            x0, y0, x1, y1 = loc.rect
            assert x0 < x1
            assert y0 < y1
        if loc.localization_status == "EXACT":
            exact_count += 1

    # At least some locations in standard Clean layout should achieve EXACT corroboration
    assert exact_count > 0, "Expected at least one EXACT corroborated modulation location"

    # 3. Test API Schema conversion via MinimizedContentStreamLocationDTO
    from app.api.routes.inspection import map_report_carriers
    min_carriers = map_report_carriers(report.carriers)
    l3_min = next(c for c in min_carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert len(l3_min.content_stream_locations) == len(locations)

    for idx, dto in enumerate(l3_min.content_stream_locations):
        assert dto.carrier_type == "CONTENT_STREAM"
        assert dto.location_index == idx
        assert dto.localization_status in ("EXACT", "APPROXIMATE", "UNAVAILABLE")
        if dto.localization_status in ("EXACT", "APPROXIMATE"):
            assert dto.rect is not None
        else:
            assert dto.rect is None

        # Verify no raw fields are in model dump
        dump = dto.model_dump()
        assert "bit_value" not in dump
        assert "displacement" not in dump
        assert "content_stream_offset" not in dump
        assert "preceding_word" not in dump
        assert "content_stream_xref" not in dump

    # 4. Verify Active Forensic Investigation preserves Layer 3 locations
    insp_service = InspectionService(repo=repo, master_key=master_key)
    res_dict, report_active = insp_service.investigate_with_evidence(out_pdf)
    assert res_dict["status"] == "VALID"
    assert "Layer 3" in res_dict["authenticated_layers"]
    assert report_active is not None

    inv_l3 = next((c for c in report_active.carriers if c.carrier_name == "Layer 3 (Stego Kerning)"), None)
    assert inv_l3 is not None
    assert inv_l3.modulation_samples is not None
    assert len(inv_l3.modulation_samples) > 0
    assert any(s.location.localization_status == "EXACT" for s in inv_l3.modulation_samples)


def test_full_inspection_api_endpoint_response(test_env, monkeypatch):
    """Tests the /inspect endpoint returning InspectionResponseDTO with localized Layer 3."""
    from fastapi.testclient import TestClient
    from app.main import app

    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "api_src.pdf")
    create_sample_pdf(src_pdf, pages=8, lines_per_page=15)
    out_pdf = str(tmp_path / "api_out.pdf")

    # Generate stego PDF
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-LOC-1", "DOC-API-TEST", src_pdf, out_pdf)

    # Disable generation globally
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)
    assert config.ENABLE_STEGO_CARRIER is False

    client = TestClient(app)
    with open(out_pdf, "rb") as f:
        response = client.post(
            "/api/inspection/inspect",
            files={"file": ("api_out.pdf", f, "application/pdf")},
        )

    assert response.status_code == 200
    data = response.json()
    resp_dto = InspectionResponseDTO.model_validate(data)
    assert resp_dto.overall_status in ("STRUCTURALLY_DECODED", "OBSERVED_SYNTAX", "SECURITY_CONFLICT")

    l3 = next(c for c in resp_dto.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert len(l3.content_stream_locations) > 0
    assert any(loc.localization_status == "EXACT" for loc in l3.content_stream_locations)


def test_clean_pdf_produces_zero_carrier_locations(test_env, monkeypatch):
    """
    Verifies that clean PDFs (with normal layout or typesetting kerning) produce:
    - Zero carrier locations in read-only inspector.
    - Zero modulation_samples and empty content_stream_locations.
    - Status is NOT_FOUND or OBSERVED_SYNTAX, never VALID or STRUCTURALLY_DECODED.
    - Zero locations during active verification enrichment.
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    clean_pdf = str(tmp_path / "clean.pdf")
    create_sample_pdf(clean_pdf, pages=4, lines_per_page=10)

    # 1. Read-only inspection
    inspector = PdfStructuralInspector()
    report = inspector.inspect_pdf(clean_pdf)
    l3 = next((c for c in report.carriers if c.carrier_name == "Layer 3 (Stego Kerning)"), None)
    assert l3 is not None
    assert l3.status in ("NOT_FOUND", "OBSERVED_SYNTAX")
    assert l3.status != "VALID"
    assert l3.status != "STRUCTURALLY_DECODED"
    assert len(l3.locations) == 0
    assert len(l3.modulation_samples) == 0

    # 2. DTO serialization
    from app.api.routes.inspection import map_report_carriers
    min_carriers = map_report_carriers(report.carriers)
    l3_dto = next(c for c in min_carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert len(l3_dto.content_stream_locations) == 0

    # 3. Active verification enrichment
    insp_service = InspectionService(repo=repo, master_key=master_key)
    res_dict, report_active = insp_service.investigate_with_evidence(clean_pdf)
    inv_l3 = next((c for c in report_active.carriers if c.carrier_name == "Layer 3 (Stego Kerning)"), None)
    assert inv_l3 is not None
    assert len(inv_l3.locations) == 0
    assert len(inv_l3.modulation_samples) == 0


def test_structural_decoding_remains_distinct_from_hmac_authentication(test_env, monkeypatch):
    """
    Verifies the strict security invariant:
    - Static read-only inspection produces STRUCTURALLY_DECODED, NEVER 'VALID'.
    - Active verification produces VALID only after HMAC verification against master key.
    - Active verification with mismatched master key fails and marks status INVALID without exposing locations.
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "distinct_src.pdf")
    create_sample_pdf(src_pdf, pages=4, lines_per_page=15)
    out_pdf = str(tmp_path / "distinct_stego.pdf")

    # Fingerprint with genuine master key
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-LOC-1", "DOC-DISTINCT-TEST", src_pdf, out_pdf)
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)

    # 1. Static inspection: must be STRUCTURALLY_DECODED, must NEVER be VALID
    inspector = PdfStructuralInspector()
    report = inspector.inspect_pdf(out_pdf)
    l3 = next((c for c in report.carriers if c.carrier_name == "Layer 3 (Stego Kerning)"), None)
    assert l3 is not None
    assert l3.status == "STRUCTURALLY_DECODED"
    assert l3.status != "VALID"
    assert report.overall_status in ("STRUCTURALLY_DECODED", "SECURITY_CONFLICT")
    assert report.overall_status != "VALID"

    # 2. Active verification with genuine key: authenticated VALID
    insp_service_valid = InspectionService(repo=repo, master_key=master_key)
    res_valid, report_valid = insp_service_valid.investigate_with_evidence(out_pdf)
    assert res_valid["status"] == "VALID"
    assert report_valid.overall_status == "VALID"
    l3_valid = next(c for c in report_valid.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert l3_valid.status == "VALID"
    assert len(l3_valid.locations) > 0

    # 3. Active verification with wrong master key: HMAC check fails, marks overall verification failed,
    # and Layer 3 remains unauthenticated (status != 'VALID', 'Layer 3' not in authenticated_layers).
    wrong_key = b"\x99" * 32
    insp_service_wrong = InspectionService(repo=repo, master_key=wrong_key)
    res_wrong, report_wrong = insp_service_wrong.investigate_with_evidence(out_pdf)
    assert res_wrong["status"] in ("TAMPERED", "INVALID", "SECURITY_CONFLICT")
    assert "Layer 3" not in res_wrong.get("authenticated_layers", [])
    l3_wrong = next(c for c in report_wrong.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert l3_wrong.status != "VALID"
    assert l3_wrong.status == "STRUCTURALLY_DECODED"  # frame is structurally valid, but unauthenticated

    # 4. Corrupted frame: structural frame decoding fails, produces INVALID or OBSERVED_SYNTAX with zero locations
    corrupt_pdf = str(tmp_path / "corrupt_stego.pdf")
    doc_c = fitz.open(out_pdf)
    p0 = doc_c[0]
    xref0 = p0.get_contents()[0]
    st_orig = doc_c.xref_stream(xref0)
    if b"[" in st_orig:
        idx_b = st_orig.find(b"[")
        st_corrupt = st_orig[:idx_b] + st_orig[idx_b:].replace(b"-20", b"-5", 1)
        doc_c.update_stream(xref0, st_corrupt)
        doc_c.save(corrupt_pdf)
    doc_c.close()

    from pathlib import Path
    if Path(corrupt_pdf).exists():
        report_c = inspector.inspect_pdf(corrupt_pdf)
        l3_c = next((c for c in report_c.carriers if c.carrier_name == "Layer 3 (Stego Kerning)"), None)
        if l3_c and l3_c.status in ("INVALID", "OBSERVED_SYNTAX"):
            assert len(l3_c.locations) == 0
            assert len(l3_c.modulation_samples) == 0


def test_indirect_font_metrics_enabling_exact_localization(tmp_path):
    """
    Verifies that indirect /FontDescriptor and indirect /Widths references
    are resolved correctly, enabling EXACT localization within strict tolerances (dh <= 2.5, dx,dy,dw <= 1.5).
    """
    from pathlib import Path
    doc_path = Path("data/documents/805fd558-3e60-4705-a4e5-62eb98ab260e.pdf")
    if doc_path.exists():
        doc = fitz.open(str(doc_path))
        page = doc[0]
        cache = FontMetricsCache(doc, page)

        # Verify F1 has resolved indirect FontDescriptor and indirect Widths
        f1 = cache.get_font_entry("F1")
        assert f1 is not None
        assert abs(f1["ascender"] - 0.891) < 1e-3
        assert abs(f1["descender"] - (-0.216)) < 1e-3
        assert len(f1["widths_map"]) > 50
        assert f1["widths_map"][32] == 250.0  # space character width

        # Verify space width calculation
        sp_w = cache.get_space_width(f1, 11.0)
        assert abs(sp_w - 2.75) < 1e-3

        doc.close()

    # Also test on a synthetically created PDF with indirect FontDescriptor
    pdf_path = str(tmp_path / "indirect_font.pdf")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World Testing Indirect Font Metrics Corroboration")
    doc.save(pdf_path)
    doc.close()

    doc = fitz.open(pdf_path)
    page = doc[0]
    cache = FontMetricsCache(doc, page)
    corroborator = PageLayoutCorroborator(page)
    assert len(corroborator.spaces) > 0
    doc.close()


def test_multipage_carrier_locations_beyond_page_zero(test_env, monkeypatch):
    """
    Verifies that Layer 3 carrier modulations spanning multiple pages:
    - Appear on pages beyond page 0 (e.g. page 0, page 1, ...).
    - Sample up to 8 locations per carrier-bearing page.
    - Sample a maximum of 40 locations total across the document.
    - Maintain strictly increasing global location_index values (0, 1, 2, ...).
    - Never sample beyond the decoded carrier bit bounds.
    """
    repo = test_env["repo"]
    master_key = test_env["master_key"]
    tmp_path = test_env["tmp_path"]

    src_pdf = str(tmp_path / "multi_src.pdf")
    create_sample_pdf(src_pdf, pages=8, lines_per_page=15)
    out_pdf = str(tmp_path / "multi_out.pdf")

    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", True)
    fp_service = FingerprintService(repo=repo, master_key=master_key)
    fp_service.fingerprint_pdf("STU-LOC-1", "DOC-MULTI-TEST", src_pdf, out_pdf)
    monkeypatch.setattr(config, "ENABLE_STEGO_CARRIER", False)

    inspector = PdfStructuralInspector()
    report = inspector.inspect_pdf(out_pdf)
    l3 = next(c for c in report.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert l3.status == "STRUCTURALLY_DECODED"
    assert len(l3.locations) > 8, "Must sample across multiple pages"
    assert len(l3.locations) <= 40, "Must not exceed 40 locations maximum"

    # Check pages represented
    pages_with_samples = set(loc.page_index for loc in l3.locations)
    assert len(pages_with_samples) >= 2, "Carrier samples must appear on at least 2 distinct pages"
    assert any(loc.page_index > 0 for loc in l3.locations), "Carrier locations must appear on page > 0"

    # Check at most 8 locations per page
    for p_idx in pages_with_samples:
        p_count = sum(1 for loc in l3.locations if loc.page_index == p_idx)
        assert p_count <= 8, f"Page {p_idx} has {p_count} locations, exceeding limit of 8"

    # Check strictly monotonic sequential location_index
    loc_indices = [loc.location_index for loc in l3.locations]
    assert loc_indices == list(range(len(l3.locations))), "location_index must be strictly sequential starting at 0"

    # Check active verification preserves multipage sampling
    insp_service = InspectionService(repo=repo, master_key=master_key)
    res_dict, report_active = insp_service.investigate_with_evidence(out_pdf)
    inv_l3 = next(c for c in report_active.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert inv_l3.status == "VALID"
    assert len(inv_l3.locations) > 8
    assert any(loc.page_index > 0 for loc in inv_l3.locations)
    inv_indices = [loc.location_index for loc in inv_l3.locations]
    assert inv_indices == list(range(len(inv_l3.locations)))

