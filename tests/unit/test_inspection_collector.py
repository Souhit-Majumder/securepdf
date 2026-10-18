"""
Unit tests for SecurePDF Evidence Collector Engine (Stage 2).
"""
import concurrent.futures
import json
import pytest

from app.inspection.collector import EvidenceCollector
from app.inspection.models import (
    SubjectEvidence,
    AuthorizationContext,
)


def test_aggregate_counts_beyond_sample_limit():
    """
    Verifies that O(1) scalar aggregate counters accurately track all events
    even when in-flight sample retention is strictly capped by sample_limit_per_page.
    """
    collector = EvidenceCollector(sample_limit_per_page=5, collect_all=False)

    # Record 100 word gaps
    for _ in range(100):
        collector.record_word_gap(page_index=0)

    # Record 60 bit '1's and 40 bit '0's (total 100 modulations)
    for i in range(60):
        collector.record_modulation(
            page_index=0,
            content_stream_xref=10,
            gap_index=i,
            content_stream_offset=100 + i * 10,
            preceding_word=f"word{i}",
            displacement=-20,
            bit_value="1",
        )
    for i in range(40):
        collector.record_modulation(
            page_index=0,
            content_stream_xref=10,
            gap_index=60 + i,
            content_stream_offset=700 + i * 10,
            preceding_word=f"term{i}",
            displacement=0,
            bit_value="0",
        )

    counts = collector.get_aggregate_counts()
    assert counts["total_word_gaps_scanned"] == 100
    assert counts["total_modulations_applied"] == 100
    assert counts["bit_1_count"] == 60
    assert counts["bit_0_count"] == 40
    assert counts["pages_scanned_count"] == 1

    # Verify report snapshot: samples are capped at 5, but aggregates report 100
    auth_ctx = AuthorizationContext(principal="tester", has_pii_clearance=False)
    subject = SubjectEvidence(subject_ref="subj_anon_1234")
    report = collector.build_report("DOC-AGG-1", "VALID", subject, auth_ctx)

    l3 = next(c for c in report.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert l3.total_word_gaps == 100
    assert l3.modulated_word_gaps == 100
    assert l3.bit_1_count == 60
    assert l3.bit_0_count == 40
    assert len(l3.modulation_samples) == 5, "Modulation samples must be capped at sample_limit_per_page"
    assert len(l3.locations) == 5


def test_multi_page_bounded_sampling():
    collector = EvidenceCollector(sample_limit_per_page=3, collect_all=False)

    # Page 0: 5 modulations (retains 3)
    for i in range(5):
        collector.record_modulation(
            page_index=0,
            content_stream_xref=10,
            gap_index=i,
            content_stream_offset=i * 20,
            preceding_word="p0",
            displacement=-20,
            bit_value="1",
        )

    # Page 1: 4 modulations (retains 3)
    for i in range(4):
        collector.record_modulation(
            page_index=1,
            content_stream_xref=11,
            gap_index=i,
            content_stream_offset=i * 20,
            preceding_word="p1",
            displacement=0,
            bit_value="0",
        )

    counts = collector.get_aggregate_counts()
    assert counts["total_modulations_applied"] == 9
    assert counts["pages_scanned_count"] == 2

    auth_ctx = AuthorizationContext(principal="tester")
    subject = SubjectEvidence(subject_ref="subj_anon_1234")
    report = collector.build_report("DOC-MP-1", "VALID", subject, auth_ctx)

    l3 = next(c for c in report.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert l3.modulated_word_gaps == 9
    assert len(l3.modulation_samples) == 6  # 3 from page 0 + 3 from page 1


def test_collect_all_retains_all_samples():
    collector = EvidenceCollector(sample_limit_per_page=2, collect_all=True)
    for i in range(10):
        collector.record_modulation(
            page_index=0,
            content_stream_xref=10,
            gap_index=i,
            content_stream_offset=i * 10,
            preceding_word="all",
            displacement=0,
            bit_value="0",
        )

    auth_ctx = AuthorizationContext(principal="tester")
    report = collector.build_report("DOC-ALL-1", "VALID", SubjectEvidence(subject_ref="s"), auth_ctx)
    l3 = next(c for c in report.carriers if c.carrier_name == "Layer 3 (Stego Kerning)")
    assert len(l3.modulation_samples) == 10


def test_concurrency_thread_safety():
    """Validates that concurrent updates from multiple threads do not cause race conditions."""
    collector = EvidenceCollector(sample_limit_per_page=10, collect_all=False)
    num_threads = 8
    events_per_thread = 50

    def worker(thread_id: int):
        for i in range(events_per_thread):
            collector.record_word_gap(page_index=thread_id % 3)
            bit_val = "1" if (i % 2 == 0) else "0"
            disp = -20 if bit_val == "1" else 0
            collector.record_modulation(
                page_index=thread_id % 3,
                content_stream_xref=20 + (thread_id % 3),
                gap_index=i,
                content_stream_offset=100 + i,
                preceding_word=f"t{thread_id}_{i}",
                displacement=disp,
                bit_value=bit_val,
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, t_idx) for t_idx in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    total_expected = num_threads * events_per_thread  # 8 * 50 = 400
    counts = collector.get_aggregate_counts()
    assert counts["total_word_gaps_scanned"] == total_expected
    assert counts["total_modulations_applied"] == total_expected
    assert counts["bit_1_count"] == total_expected // 2
    assert counts["bit_0_count"] == total_expected // 2


def test_sensitive_data_exclusion_in_references():
    """
    Confirms that raw HMAC tags, nonces, and secret tokens are never stored or exposed,
    and are cleanly mapped to session references.
    """
    collector = EvidenceCollector(session_id="test_session_xyz")
    raw_secret_hmac = "a94a8fe5ccb19ba61c4c0873d391e987982fbbd3"
    raw_secret_nonce = "1234567890abcdef1234567890abcdef"

    collector.record_layer1_embedding(
        catalog_xref=10,
        signature_token=raw_secret_hmac,
        nonce_token=raw_secret_nonce,
        status="VALID",
    )
    collector.record_layer2_annotation(
        page_index=0,
        annotation_xref=15,
        rect=[0.0, 0.0, 1.0, 1.0],
        title="SPDF0",
        signature_token=raw_secret_hmac,
        nonce_token=raw_secret_nonce,
        status="VALID",
    )

    auth_ctx = AuthorizationContext(principal="tester", has_pii_clearance=False)
    report = collector.build_report("DOC-SEC-1", "VALID", SubjectEvidence(subject_ref="s"), auth_ctx)
    report_json = report.model_dump_json()

    # Raw secrets must NOT appear anywhere in the serialized report
    assert raw_secret_hmac not in report_json
    assert raw_secret_nonce not in report_json

    # Opaque references must be present and match across L1 and L2
    assert "evref_sig_01" in report_json
    assert "evref_nonce_01" in report_json
    assert report.cross_layer.signatures_match is True
    assert report.cross_layer.cross_carrier_conflict is False


def test_cross_layer_conflict_reporting():
    collector = EvidenceCollector(session_id="sess_conflict")
    collector.record_layer1_embedding(catalog_xref=10, signature_token="hmac_alice", status="VALID")
    collector.record_layer2_annotation(
        page_index=0,
        annotation_xref=20,
        rect=[0.0, 0.0, 1.0, 1.0],
        title="SPDF0",
        signature_token="hmac_bob",
        status="VALID",
    )

    auth_ctx = AuthorizationContext(principal="tester", has_pii_clearance=False)
    report = collector.build_report("DOC-CONF-1", "SECURITY_CONFLICT", SubjectEvidence(subject_ref="s"), auth_ctx)

    assert report.cross_layer.signatures_match is False
    assert report.cross_layer.cross_carrier_conflict is True
    assert "mismatch" in str(report.cross_layer.conflict_reason).lower()
