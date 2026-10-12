from pathlib import Path
from typing import Optional, Dict, Union
from app.crypto.integrity import verify_fingerprint
from app.database.repository import Repository
from app.crypto.keys import get_or_create_master_key
from app.pdf.processor import open_pdf
from app.pdf.extract import extract_layer1, extract_layer2
from app.pdf.payload_redundancy import decode_compact_payload

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

    def investigate_pdf(self, pdf_path: str) -> dict:
        """
        Full verification pipeline for a leaked PDF checking both layers independently.
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

        has_l1 = bool(l1_payload)
        has_l2 = len(l2_payloads) > 0
        l1_valid = l1_result is not None
        l2_valid = len(l2_valid_results) > 0 and not l2_conflict
        
        # F. All carriers missing
        if not has_l1 and not has_l2:
            return {"status": "NOT_FOUND", "reason": "No SecurePDF fingerprint found"}

        # Conflict Handling
        if l2_conflict:
            return {"status": "SECURITY_CONFLICT", "reason": "Layer 2 internal conflict"}

        # E. Layer 1 and Layer 2 both present but authenticate to DIFFERENT fingerprints
        if l1_valid and l2_valid and l1_result["fingerprint"] != l2_fingerprint:
            return {"status": "SECURITY_CONFLICT", "reason": "Layer 1 and Layer 2 authenticate to different identities"}

        # A. Layer 1 valid + Layer 2 valid and identical
        if l1_valid and l2_valid:
            l1_result["authenticated_layers"] = ["Layer 1", "Layer 2"]
            return l1_result
            
        # C. Layer 1 valid + Layer 2 missing/invalid
        if l1_valid and not l2_valid:
            l1_result["authenticated_layers"] = ["Layer 1"]
            return l1_result
            
        # B/D. Layer 1 missing/invalid + Layer 2 valid
        if not l1_valid and l2_valid:
            res = l2_valid_results[0]
            res["authenticated_layers"] = ["Layer 2"]
            return res

        # G. Carriers present but none authenticate
        return {"status": "INVALID", "reason": "Carriers present but none authenticate"}

