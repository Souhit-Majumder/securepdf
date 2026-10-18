from pathlib import Path
import threading
from typing import Optional, Dict, Union
from app.config import config
from app.crypto.integrity import verify_fingerprint
from app.database.repository import Repository
from app.crypto.keys import get_or_create_master_key
from app.pdf.processor import open_pdf
from app.pdf.extract import extract_layer1, extract_layer2
from app.pdf.payload_redundancy import decode_compact_payload
from app.pdf.stego.crypto import derive_layer3_subkey, verify_layer3_tag
from app.pdf.stego.supervisor import extract_layer3_with_timeout

class VerificationService:
    def __init__(
        self,
        repo: Optional[Repository] = None,
        master_key: Optional[bytes] = None,
        key_path: Optional[Union[str, Path]] = None
    ):
        self.repo = repo or Repository()
        self.master_key = master_key or get_or_create_master_key(key_path)

    def _authenticate_payload(self, document_uid: str, nonce: str, extracted_fingerprint: str) -> Optional[Dict]:
        """Attempts to authenticate a candidate payload. Returns attribution dict if VALID, else None."""
        doc_record = self.repo.get_document_by_uid(document_uid)
        if not doc_record:
            return None
        fp_record = self.repo.get_fingerprint_by_doc_and_nonce(doc_record.id, nonce)
        
        if not fp_record:
            return None
            
        student_record = self.repo.get_student_by_id(fp_record.student_id)
        if not student_record:
            return None
            
        student_uid = student_record.student_uid
        
        is_valid = verify_fingerprint(
            self.master_key, document_uid, student_uid, nonce, extracted_fingerprint
        )
        
        if is_valid:
            return {
                "status": "VALID",
                "document_uid": document_uid,
                "student_uid": student_uid,
                "student_name": student_record.name,
                "nonce": nonce,
                "fingerprint": extracted_fingerprint
            }
        return None

    def investigate_pdf(self, pdf_path: str, cancel_event: Optional[threading.Event] = None) -> dict:
        """
        Full verification pipeline for a leaked PDF checking all active carriers independently.
        """
        try:
            doc = open_pdf(pdf_path)
            l1_payload = extract_layer1(doc)
            l2_payloads = extract_layer2(doc)
            doc.close()
        except Exception as e:
            return {"status": "ERROR", "reason": str(e)}
            
        # Authenticate Layer 1
        l1_result = None
        if l1_payload:
            parts = l1_payload.split('|')
            if len(parts) == 4 and parts[0] == "SPDF-V1":
                _, document_uid, nonce, extracted_fingerprint = parts
                l1_result = self._authenticate_payload(document_uid, nonce, extracted_fingerprint)

        # Authenticate Layer 2
        l2_valid_results = []
        if l2_payloads:
            for payload in l2_payloads:
                try:
                    ver, document_uid, nonce, extracted_fingerprint = decode_compact_payload(payload)
                    if ver == "SPDF1":
                        res = self._authenticate_payload(document_uid, nonce, extracted_fingerprint)
                        if res:
                            l2_valid_results.append(res)
                except Exception:
                    continue

        # Check for L2 internal conflict
        l2_conflict = False
        l2_fingerprint = None
        if l2_valid_results:
            l2_fingerprint = l2_valid_results[0]["fingerprint"]
            for r in l2_valid_results:
                if r["fingerprint"] != l2_fingerprint:
                    l2_conflict = True
                    break

        # Optional Layer 3 Steganographic Carrier Authentication
        has_l3 = False
        l3_result = None
        stego_enabled = getattr(config, "ENABLE_STEGO_CARRIER", False)
        if stego_enabled:
            l3_extract_res = extract_layer3_with_timeout(pdf_path, cancel_event=cancel_event)
            if l3_extract_res:
                has_l3 = bool(l3_extract_res.get("frame_detected"))
                if l3_extract_res.get("crc_valid") and l3_extract_res.get("payload"):
                    p = l3_extract_res["payload"]
                    doc_uid = p["document_uid"]
                    rec_uid = p["recipient_uid"]
                    nonce_bytes = p["nonce"]
                    nonce_hex = nonce_bytes.hex()
                    hmac_tag = p["hmac_tag"]

                    # 1. Cryptographic HMAC verification under derived subkey
                    subkey = derive_layer3_subkey(self.master_key)
                    if verify_layer3_tag(subkey, doc_uid, rec_uid, nonce_bytes, hmac_tag):
                        # 2. Database issuance binding check
                        doc_record = self.repo.get_document_by_uid(doc_uid)
                        if doc_record:
                            fp_record = self.repo.get_fingerprint_by_doc_and_nonce(doc_record.id, nonce_hex)
                            if fp_record:
                                student_record = self.repo.get_student_by_id(fp_record.student_id)
                                if student_record and student_record.student_uid == rec_uid:
                                    l3_result = {
                                        "status": "VALID",
                                        "document_uid": doc_uid,
                                        "student_uid": rec_uid,
                                        "student_name": student_record.name,
                                        "nonce": nonce_hex,
                                        "fingerprint": hmac_tag.hex(),
                                    }

        has_l1 = bool(l1_payload)
        has_l2 = len(l2_payloads) > 0
        l1_valid = l1_result is not None
        l2_valid = len(l2_valid_results) > 0 and not l2_conflict
        l3_valid = l3_result is not None

        # F. All carriers missing
        if not has_l1 and not has_l2 and not has_l3:
            return {"status": "NOT_FOUND", "reason": "No SecurePDF fingerprint found"}

        # Conflict Handling: L2 internal conflict
        if l2_conflict:
            return {"status": "SECURITY_CONFLICT", "reason": "Layer 2 internal conflict"}

        # Compile all authenticated layers
        authenticated = []
        if l1_valid and l1_result:
            authenticated.append(("Layer 1", l1_result))
        if l2_valid and l2_valid_results:
            authenticated.append(("Layer 2", l2_valid_results[0]))
        if l3_valid and l3_result:
            authenticated.append(("Layer 3", l3_result))

        # Check cross-carrier identity conflicts
        if len(authenticated) >= 2:
            first_ident = (authenticated[0][1]["document_uid"], authenticated[0][1]["student_uid"])
            for name, r in authenticated[1:]:
                ident = (r["document_uid"], r["student_uid"])
                if ident != first_ident:
                    return {
                        "status": "SECURITY_CONFLICT",
                        "reason": "Carriers authenticate to different identities",
                    }

        # Successful verification if at least one carrier authenticated
        if len(authenticated) > 0:
            result = dict(authenticated[0][1])
            result["authenticated_layers"] = [name for name, _ in authenticated]
            return result

        # G. Carriers present but none authenticate
        return {"status": "INVALID", "reason": "Carriers present but none authenticate"}

