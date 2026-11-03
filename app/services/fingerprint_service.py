from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union, Literal
from app.crypto.keys import get_or_create_master_key
from app.crypto.fingerprint import generate_nonce, generate_fingerprint
from app.database.repository import Repository
from app.pdf.processor import open_pdf, save_pdf
from app.pdf.embed import embed_payload, EmbeddingStageResult
from app.pdf.extract import extract_layer1, extract_layer2
from app.pdf.payload_redundancy import decode_compact_payload
from app.pdf.stego.crypto import derive_layer3_subkey, verify_layer3_tag
from app.pdf.stego.decompression import safe_flate_decompress
from app.pdf.stego.extract import extract_bits_from_stream
from app.pdf.stego.framing import parse_stego_bitstream

L3VerificationStatus = Literal[
    "VERIFIED",
    "NOT_ATTEMPTED_CAPACITY",
    "NOT_ATTEMPTED_DISABLED",
    "FAILED",
]

@dataclass(frozen=True)
class PostVerificationResult:
    is_valid: bool
    l1_verified: bool
    l2_verified: bool
    l3_status: L3VerificationStatus
    authenticated_layers: list[str]
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.is_valid

class FingerprintService:
    def __init__(
        self,
        repo: Optional[Repository] = None,
        master_key: Optional[bytes] = None,
        key_path: Optional[Union[str, Path]] = None
    ):
        self.repo = repo or Repository()
        self.master_key = master_key or get_or_create_master_key(key_path)

    def fingerprint_pdf(
        self,
        student_uid: str,
        document_uid: str,
        input_pdf_path: str,
        output_pdf_path: str,
        enable_stage1: bool = True,
        enable_stage2: bool = True,
        enable_stage3: bool = False,
    ) -> str:
        """
        Orchestrates reading a PDF, generating a fingerprint, embedding it, and saving.
        """
        student = self.repo.get_student_by_uid(student_uid)
        if not student:
            raise ValueError(f"Student with UID {student_uid} not found.")
            
        document = self.repo.get_or_create_document(document_uid, f"{document_uid}_original.pdf")
        
        nonce = generate_nonce()
        
        fingerprint_hex = generate_fingerprint(
            master_key=self.master_key,
            document_uid=document_uid,
            student_uid=student_uid,
            nonce=nonce
        )
        
        self.repo.create_fingerprint(
            document_id=document.id,
            student_id=student.id,
            nonce=nonce,
            fingerprint=fingerprint_hex
        )
        
        doc = open_pdf(input_pdf_path)
        embed_payload(
            doc,
            document_uid,
            nonce,
            fingerprint_hex,
            enable_stage1=enable_stage1,
            enable_stage2=enable_stage2,
            enable_stage3=enable_stage3,
            student_uid=student_uid,
            master_key=self.master_key,
        )
        save_pdf(doc, output_pdf_path)
        doc.close()
        
        return fingerprint_hex

    def generate_fingerprint_payload(self, student_uid: str, document_uid: str) -> tuple[str, str]:
        """Generates cryptographic nonce and fingerprint hex."""
        nonce = generate_nonce()
        fingerprint_hex = generate_fingerprint(
            master_key=self.master_key,
            document_uid=document_uid,
            student_uid=student_uid,
            nonce=nonce
        )
        return nonce, fingerprint_hex

    def embed_and_save_pdf(
        self,
        document_uid: str,
        student_uid: str,
        nonce: str,
        fingerprint_hex: str,
        input_pdf_path: str,
        output_pdf_path: str,
        enable_stage1: bool = True,
        enable_stage2: bool = True,
        enable_stage3: bool = False,
    ) -> EmbeddingStageResult:
        """Embeds watermarks according to selected stages and saves to output path, returning stage result."""
        doc = open_pdf(input_pdf_path)
        stage_result = embed_payload(
            doc,
            document_uid,
            nonce,
            fingerprint_hex,
            enable_stage1=enable_stage1,
            enable_stage2=enable_stage2,
            enable_stage3=enable_stage3,
            student_uid=student_uid,
            master_key=self.master_key,
        )
        save_pdf(doc, output_pdf_path)
        doc.close()
        return stage_result

    def verify_saved_pdf_carriers(
        self,
        pdf_path: str,
        document_uid: str,
        recipient_uid: str,
        nonce: str,
        fingerprint_hex: str,
        enable_stage1: bool = True,
        enable_stage2: bool = True,
        enable_stage3: bool = False,
        stego_expected: Optional[bool] = None,
        stego_skipped_capacity: bool = False,
    ) -> PostVerificationResult:
        """
        Independently verifies the saved PDF on disk against expected carriers.
        Verifies every selected stage and requires successful verification of all selected stages.
        Does not fail simply because an unselected stage is absent.
        """
        if stego_expected is not None:
            enable_stage3 = bool(stego_expected)

        path_obj = Path(pdf_path)
        if not path_obj.exists() or path_obj.stat().st_size == 0:
            return PostVerificationResult(
                is_valid=False,
                l1_verified=False,
                l2_verified=False,
                l3_status="FAILED",
                authenticated_layers=[],
                error="Output PDF does not exist or is empty on disk",
            )

        l1_verified = False
        l2_verified = False
        l3_status: L3VerificationStatus = "NOT_ATTEMPTED_DISABLED"
        auth_layers: list[str] = []
        err: Optional[str] = None

        try:
            doc = open_pdf(pdf_path)
            # 1. Layer 1 Check
            l1_payload = extract_layer1(doc)
            expected_l1 = f"SPDF-V1|{document_uid}|{nonce}|{fingerprint_hex}"
            if l1_payload == expected_l1:
                l1_verified = True
                auth_layers.append("Layer 1")
            elif enable_stage1:
                err = "Layer 1 catalog payload missing or mismatched"

            # 2. Layer 2 Check
            l2_payloads = extract_layer2(doc)
            l2_valid_matches = 0
            if l2_payloads:
                for p in l2_payloads:
                    try:
                        ver, d_uid, n_str, fp_str = decode_compact_payload(p)
                        if ver == "SPDF1" and d_uid == document_uid and n_str == nonce and fp_str == fingerprint_hex:
                            l2_valid_matches += 1
                    except Exception:
                        pass
            if l2_valid_matches > 0:
                l2_verified = True
                auth_layers.append("Layer 2")
            elif enable_stage2:
                if not err:
                    err = "Layer 2 redundant annotations missing or mismatched"

            # 3. Layer 3 Check
            if stego_skipped_capacity:
                l3_status = "NOT_ATTEMPTED_CAPACITY"
            elif not enable_stage3:
                l3_status = "NOT_ATTEMPTED_DISABLED"
            else:
                all_bits = []
                for page in doc:
                    for xref in page.get_contents():
                        raw_stream = doc.xref_stream_raw(xref)
                        stream_bytes = safe_flate_decompress(raw_stream, max_output_bytes=5 * 1024 * 1024)
                        if stream_bytes:
                            bits = extract_bits_from_stream(stream_bytes)
                            if bits:
                                all_bits.append(bits)

                combined_bits = "".join(all_bits)
                parse_res = parse_stego_bitstream(combined_bits)

                if parse_res.frame_detected and parse_res.crc_valid and parse_res.payload:
                    p = parse_res.payload
                    nonce_bytes = bytes.fromhex(nonce) if isinstance(nonce, str) else nonce

                    doc_match = (p.document_uid == document_uid)
                    rec_match = (p.recipient_uid == recipient_uid)
                    nonce_match = (p.nonce == nonce_bytes)

                    subkey = derive_layer3_subkey(self.master_key)
                    hmac_valid = verify_layer3_tag(subkey, document_uid, recipient_uid, nonce_bytes, p.hmac_tag)

                    if doc_match and rec_match and nonce_match and hmac_valid:
                        l3_status = "VERIFIED"
                        auth_layers.append("Layer 3")
                    else:
                        l3_status = "FAILED"
                        err = "Layer 3 payload attributes or HMAC validation mismatch"
                else:
                    l3_status = "FAILED"
                    err = f"Layer 3 frame parsing failed: {parse_res.error or 'invalid frame/CRC'}"

            doc.close()
        except Exception as e:
            return PostVerificationResult(
                is_valid=False,
                l1_verified=False,
                l2_verified=False,
                l3_status="FAILED",
                authenticated_layers=[],
                error=f"Exception during verification: {str(e)}",
            )

        at_least_one = enable_stage1 or enable_stage2 or enable_stage3
        s1_ok = (not enable_stage1) or l1_verified
        s2_ok = (not enable_stage2) or l2_verified
        s3_ok = (not enable_stage3) or (l3_status == "VERIFIED" or (stego_skipped_capacity and l3_status == "NOT_ATTEMPTED_CAPACITY"))

        is_valid = at_least_one and s1_ok and s2_ok and s3_ok

        return PostVerificationResult(
            is_valid=is_valid,
            l1_verified=l1_verified,
            l2_verified=l2_verified,
            l3_status=l3_status,
            authenticated_layers=auth_layers,
            error=err if not is_valid else None,
        )

