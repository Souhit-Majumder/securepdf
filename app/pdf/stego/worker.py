"""
Isolated worker entrypoint for Layer 3 steganographic carrier extraction.
Runs as a top-level module function compatible with Python's spawn multiprocessing context.
"""
from __future__ import annotations

import fitz

from app.pdf.stego.decompression import safe_flate_decompress
from app.pdf.stego.extract import extract_bits_from_stream
from app.pdf.stego.framing import parse_stego_bitstream


def worker_extract_entrypoint(
    child_conn,
    pdf_path: str,
    max_output_bytes: int = 5 * 1024 * 1024,
    max_pages: int = 50,
) -> None:
    """
    Subprocess target: scans content streams in the PDF, extracts bits,
    and returns a candidate payload result over child_conn.
    """
    try:
        doc = fitz.open(pdf_path)
        all_bits = []

        for page_idx in range(min(len(doc), max_pages)):
            page = doc[page_idx]
            for xref in page.get_contents():
                # Read raw stream and safely decompress with bounds
                raw_stream = doc.xref_stream_raw(xref)
                stream_bytes = safe_flate_decompress(raw_stream, max_output_bytes=max_output_bytes)
                if stream_bytes:
                    bits = extract_bits_from_stream(stream_bytes)
                    if bits:
                        all_bits.append(bits)

        doc.close()
        combined_bits = "".join(all_bits)

        parse_result = parse_stego_bitstream(combined_bits)

        if parse_result.payload:
            payload_dict = {
                "document_uid": parse_result.payload.document_uid,
                "recipient_uid": parse_result.payload.recipient_uid,
                "nonce": parse_result.payload.nonce,
                "hmac_tag": parse_result.payload.hmac_tag,
            }
        else:
            payload_dict = None

        child_conn.send({
            "status": "SUCCESS",
            "frame_detected": parse_result.frame_detected,
            "crc_valid": parse_result.crc_valid,
            "payload": payload_dict,
            "error": parse_result.error,
        })
    except Exception as e:
        child_conn.send({
            "status": "ERROR",
            "frame_detected": False,
            "crc_valid": False,
            "payload": None,
            "error": str(e),
        })
    finally:
        child_conn.close()
