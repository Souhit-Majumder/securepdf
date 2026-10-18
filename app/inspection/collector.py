"""
Thread-safe Evidence Collector for SecurePDF active pipeline events.

Guarantees:
- O(1) scalar aggregate counters independent of bounded sample limits.
- Enforcement of sample_limit_per_page without truncating aggregate counts.
- Thread-safe updates and consistent report snapshots via RLock.
- Absolute exclusion of secret keys, raw nonces, and raw HMACs;
  opaque session-scoped evidence references are generated deterministically.
"""
from __future__ import annotations

from collections import defaultdict
import datetime
import hashlib
import threading
from typing import Any, Dict, List, Literal, Optional, Set

from app.inspection.models import (
    CatalogLocation,
    AnnotationLocation,
    ContentStreamLocation,
    ModulationSample,
    CarrierVerificationStatus,
    CarrierInspectionResult,
    SubjectEvidence,
    CrossLayerEvidence,
    EvidenceReport,
    AuthorizationContext,
    create_evidence_ref,
    redact_subject_evidence,
)


class EvidenceCollector:
    """
    Collects structural and modulation evidence during active embedding and verification.
    Thread-safe and bounded for production use.
    """

    def __init__(
        self,
        sample_limit_per_page: int = 20,
        collect_all: bool = False,
        session_id: Optional[str] = None,
    ):
        self.sample_limit_per_page = max(0, sample_limit_per_page)
        self.collect_all = collect_all
        self.session_id = session_id or hashlib.sha256(str(id(self)).encode()).hexdigest()[:12]

        self._lock = threading.RLock()

        # O(1) scalar aggregate counters (independent of sample limits)
        self._total_word_gaps_scanned: int = 0
        self._total_modulations_applied: int = 0
        self._bit_1_count: int = 0
        self._bit_0_count: int = 0
        self._pages_scanned: Set[int] = set()

        # Bounded in-flight sample storage
        self._samples_by_page: Dict[int, List[ModulationSample]] = defaultdict(list)

        # Carrier structural locations
        self._catalog_locations: List[CatalogLocation] = []
        self._annotation_locations: List[AnnotationLocation] = []

        # Carrier statuses and details
        self._l1_status: CarrierVerificationStatus = "NOT_FOUND"
        self._l2_status: CarrierVerificationStatus = "NOT_FOUND"
        self._l3_status: CarrierVerificationStatus = "NOT_FOUND"

        self._l1_sig_ref: Optional[str] = None
        self._l1_nonce_ref: Optional[str] = None
        self._l2_sig_refs: List[str] = []
        self._l2_nonce_refs: List[str] = []
        self._l3_sig_ref: Optional[str] = None
        self._l3_nonce_ref: Optional[str] = None

        self._l1_details: Dict[str, Any] = {}
        self._l2_details: Dict[str, Any] = {}
        self._l3_details: Dict[str, Any] = {}

        # Opaque reference mapping (token hash -> session reference)
        # Prevents storing or exposing raw secrets/HMACs
        self._ref_map: Dict[str, str] = {}
        self._ref_counters: Dict[str, int] = defaultdict(int)

    def get_or_create_ref(self, prefix: str, secret_or_token: str | bytes) -> str:
        """
        Maps a sensitive token or signature to an opaque session-scoped reference
        (e.g. 'evref_sig_01'). The raw input is hashed and never stored.
        """
        with self._lock:
            if isinstance(secret_or_token, bytes):
                token_bytes = secret_or_token
            else:
                token_bytes = str(secret_or_token).encode("utf-8")

            # Hash token with session ID to form an internal lookup key
            lookup_key = f"{prefix}:{hashlib.sha256(self.session_id.encode() + token_bytes).hexdigest()}"
            if lookup_key in self._ref_map:
                return self._ref_map[lookup_key]

            self._ref_counters[prefix] += 1
            ref = create_evidence_ref(prefix, self._ref_counters[prefix])
            self._ref_map[lookup_key] = ref
            return ref

    # --- Layer 1 Recording ---

    def record_layer1_embedding(
        self,
        catalog_xref: int,
        signature_token: Optional[str | bytes] = None,
        nonce_token: Optional[str | bytes] = None,
        status: CarrierVerificationStatus = "VALID",
        details: Optional[Dict[str, Any]] = None,
    ):
        """Records Layer 1 catalog embedding."""
        with self._lock:
            self._catalog_locations.append(CatalogLocation(catalog_xref=catalog_xref))
            self._l1_status = status
            if signature_token:
                self._l1_sig_ref = self.get_or_create_ref("sig", signature_token)
            if nonce_token:
                self._l1_nonce_ref = self.get_or_create_ref("nonce", nonce_token)
            if details:
                self._l1_details.update(details)

    # --- Layer 2 Recording ---

    def record_layer2_annotation(
        self,
        page_index: int,
        annotation_xref: int,
        rect: List[float],
        title: str,
        signature_token: Optional[str | bytes] = None,
        nonce_token: Optional[str | bytes] = None,
        status: CarrierVerificationStatus = "VALID",
        details: Optional[Dict[str, Any]] = None,
    ):
        """Records Layer 2 invisible annotation embedding."""
        with self._lock:
            self._annotation_locations.append(
                AnnotationLocation(
                    page_index=page_index,
                    annotation_xref=annotation_xref,
                    rect=rect,
                    title=title,
                )
            )
            self._l2_status = status
            if signature_token:
                sig_ref = self.get_or_create_ref("sig", signature_token)
                self._l2_sig_refs.append(sig_ref)
            if nonce_token:
                nonce_ref = self.get_or_create_ref("nonce", nonce_token)
                self._l2_nonce_refs.append(nonce_ref)
            if details:
                self._l2_details.update(details)

    # --- Layer 3 Telemetry Recording ---

    def record_word_gap(self, page_index: int):
        """O(1) scalar count update for every scanned inter-word gap."""
        with self._lock:
            self._total_word_gaps_scanned += 1
            self._pages_scanned.add(page_index)

    def record_modulation(
        self,
        page_index: int,
        content_stream_xref: int,
        gap_index: int,
        content_stream_offset: int,
        preceding_word: str,
        displacement: int,
        bit_value: Literal["0", "1"],
        source: Literal["RUNTIME_CAPTURE", "STRUCTURAL_RESCAN"] = "RUNTIME_CAPTURE",
    ):
        """
        Records an intentional kerning modulation event.
        O(1) counters are updated unconditionally.
        Detailed sample retention is bounded by sample_limit_per_page.
        """
        with self._lock:
            self._total_modulations_applied += 1
            if bit_value == "1":
                self._bit_1_count += 1
            else:
                self._bit_0_count += 1
            self._pages_scanned.add(page_index)

            # Bounded sample collection
            page_samples = self._samples_by_page[page_index]
            if self.collect_all or len(page_samples) < self.sample_limit_per_page:
                location = ContentStreamLocation(
                    page_index=page_index,
                    content_stream_xref=content_stream_xref,
                    gap_index=gap_index,
                    content_stream_offset=content_stream_offset,
                    preceding_word=preceding_word,
                    displacement=displacement,
                    bit_value=bit_value,
                )
                sample = ModulationSample(
                    location=location,
                    is_intentional_modulation=True,
                    source=source,
                )
                page_samples.append(sample)

    def record_layer3_result(
        self,
        status: CarrierVerificationStatus,
        signature_token: Optional[str | bytes] = None,
        nonce_token: Optional[str | bytes] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Records Layer 3 verification status."""
        with self._lock:
            self._l3_status = status
            if signature_token:
                self._l3_sig_ref = self.get_or_create_ref("sig", signature_token)
            if nonce_token:
                self._l3_nonce_ref = self.get_or_create_ref("nonce", nonce_token)
            if details:
                self._l3_details.update(details)

    # --- Snapshots and Reporting ---

    def get_aggregate_counts(self) -> Dict[str, int]:
        """Returns thread-safe snapshot of scalar aggregate counters."""
        with self._lock:
            return {
                "total_word_gaps_scanned": self._total_word_gaps_scanned,
                "total_modulations_applied": self._total_modulations_applied,
                "bit_1_count": self._bit_1_count,
                "bit_0_count": self._bit_0_count,
                "pages_scanned_count": len(self._pages_scanned),
            }

    def build_report(
        self,
        document_uid: str,
        overall_status: str,
        subject: SubjectEvidence,
        auth_ctx: AuthorizationContext,
        telemetry_source: Literal[
            "READ_ONLY_INSPECTION",
            "ACTIVE_VERIFICATION",
            "EPHEMERAL_SIMULATION",
        ] = "ACTIVE_VERIFICATION",
    ) -> EvidenceReport:
        """
        Builds a thread-safe, sanitized EvidenceReport snapshot.
        Enforces PII redaction according to auth_ctx.
        """
        with self._lock:
            # 1. Flatten bounded modulation samples deterministically
            all_samples: List[ModulationSample] = []
            for page_idx in sorted(self._samples_by_page.keys()):
                all_samples.extend(self._samples_by_page[page_idx])

            # 2. Build Layer 1 Result
            l1_result = CarrierInspectionResult(
                carrier_name="Layer 1 (Catalog)",
                status=self._l1_status,
                locations=list(self._catalog_locations),
                signature_ref=self._l1_sig_ref,
                nonce_ref=self._l1_nonce_ref,
                details=dict(self._l1_details),
            )

            # 3. Build Layer 2 Result
            l2_primary_sig = self._l2_sig_refs[0] if self._l2_sig_refs else None
            l2_primary_nonce = self._l2_nonce_refs[0] if self._l2_nonce_refs else None
            l2_result = CarrierInspectionResult(
                carrier_name="Layer 2 (Annotations)",
                status=self._l2_status,
                locations=list(self._annotation_locations),
                signature_ref=l2_primary_sig,
                nonce_ref=l2_primary_nonce,
                details=dict(self._l2_details),
            )

            # 4. Build Layer 3 Result
            l3_locations = [sample.location for sample in all_samples]
            l3_result = CarrierInspectionResult(
                carrier_name="Layer 3 (Stego Kerning)",
                status=self._l3_status,
                locations=l3_locations,
                signature_ref=self._l3_sig_ref,
                nonce_ref=self._l3_nonce_ref,
                total_word_gaps=self._total_word_gaps_scanned,
                modulated_word_gaps=self._total_modulations_applied,
                bit_1_count=self._bit_1_count,
                bit_0_count=self._bit_0_count,
                modulation_samples=all_samples,
                details=dict(self._l3_details),
            )

            # 5. Evaluate Cross-Layer Evidence
            sig_pool = [s for s in [self._l1_sig_ref, l2_primary_sig, self._l3_sig_ref] if s is not None]
            unique_sigs = set(sig_pool)
            sigs_match = (len(unique_sigs) == 1) if len(sig_pool) >= 2 else None
            cross_conflict = (len(unique_sigs) > 1)

            cross_layer = CrossLayerEvidence(
                l1_signature_ref=self._l1_sig_ref,
                l2_signature_refs=list(self._l2_sig_refs),
                l3_signature_ref=self._l3_sig_ref,
                signatures_match=sigs_match,
                cross_carrier_conflict=cross_conflict,
                conflict_reason="Cross-carrier signature reference mismatch" if cross_conflict else None,
            )

            # 6. Apply trusted PII redaction
            safe_subject = redact_subject_evidence(subject, auth_ctx)

            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

            return EvidenceReport(
                document_uid=document_uid,
                overall_status=overall_status,
                subject=safe_subject,
                carriers=[l1_result, l2_result, l3_result],
                cross_layer=cross_layer,
                telemetry_source=telemetry_source,
                timestamp=timestamp,
            )
