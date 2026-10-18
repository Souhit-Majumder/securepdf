import os
import threading
import fitz
import pytest

from app.pdf.stego.supervisor import extract_layer3_with_timeout, _WORKER_SEMAPHORE


@pytest.fixture
def sample_pdf(tmp_path):
    pdf_path = str(tmp_path / "worker_test.pdf")
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50), "Hello world text content with TJ word gaps.")
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_supervisor_normal_execution(sample_pdf):
    # Runs worker subprocess on PDF without stego carrier
    res = extract_layer3_with_timeout(sample_pdf, timeout=2.0)
    assert res is not None
    assert res["status"] == "SUCCESS"
    assert res["frame_detected"] is False
    assert res["payload"] is None


def test_supervisor_timeout_reaping(sample_pdf):
    # Timeout of 0.0001s forces timeout in parent polling loop
    res = extract_layer3_with_timeout(sample_pdf, timeout=0.0001)
    # Returns None gracefully when timed out
    assert res is None


def test_supervisor_cancellation(sample_pdf):
    cancel_event = threading.Event()
    cancel_event.set()
    res = extract_layer3_with_timeout(sample_pdf, timeout=2.0, cancel_event=cancel_event)
    # Exits early cleanly
    assert res is None


def test_supervisor_semaphore_saturation(sample_pdf):
    # Acquire all slots to simulate concurrency saturation
    slots = []
    # 4 slots in default config
    for _ in range(4):
        slots.append(_WORKER_SEMAPHORE.acquire(timeout=0.1))

    try:
        # Next acquisition should fail and return None without hanging
        res = extract_layer3_with_timeout(sample_pdf, timeout=1.0)
        assert res is None
    finally:
        for acquired in slots:
            if acquired:
                _WORKER_SEMAPHORE.release()

    # Semaphore is healthy afterwards
    assert _WORKER_SEMAPHORE.acquire(timeout=0.1)
    _WORKER_SEMAPHORE.release()
