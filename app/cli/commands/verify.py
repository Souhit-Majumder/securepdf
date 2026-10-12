import os
from app.services.verification_service import VerificationService

def verify_cmd(pdf_path: str) -> dict:
    """Verifies a suspected leaked PDF and displays attribution details."""
    print(f"\nPDF: {pdf_path}\n")
    if not os.path.exists(pdf_path):
        print(f"Error: File '{pdf_path}' not found.\n")
        return {"status": "ERROR", "reason": f"File '{pdf_path}' not found"}

    service = VerificationService()
    result = service.investigate_pdf(pdf_path)

    if result["status"] == "VALID":
        print("✓ PDF fingerprint found")
        print("✓ HMAC authentication successful")
        print("✓ Document identified")
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("  STATUS: AUTHENTIC")
        print(f"  STUDENT: {result['student_name']}")
        print(f"  STUDENT UID: {result['student_uid']}")
        print(f"  DOCUMENT: {result['document_uid']}")
        layers = result.get("authenticated_layers", [])
        if layers:
            print(f"  LAYERS: {', '.join(layers)}")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    elif result["status"] == "SECURITY_CONFLICT":
        print("⚠ SECURITY CONFLICT")
        layers = result.get("authenticated_layers", [])
        if layers:
            print(f"\nConflicting layers: {', '.join(layers)}")
        print("Verification failed closed.")
        print("The PDF must not be attributed to either student.\n")
    else:
        print("✗ No valid authenticated fingerprint found")
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("  STATUS: UNVERIFIED")
        print("  STUDENT: Unknown")
        if result.get("reason"):
            print(f"  REASON: {result['reason']}")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    return result
