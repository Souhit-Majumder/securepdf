"""
Worker supervisor for Layer 3 extraction.
Manages multiprocessing process lifecycle, semaphore concurrency bounds,
timeout enforcement, and clean process reaping.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import threading
import time
from typing import Optional, Dict

from app.config import config
from app.pdf.stego.worker import worker_extract_entrypoint

logger = logging.getLogger(__name__)

# Concurrency semaphore to bound simultaneous extraction processes
_WORKER_SEMAPHORE = threading.BoundedSemaphore(config.MAX_CONCURRENT_STEGO_WORKERS)


def extract_layer3_with_timeout(
    pdf_path: str,
    timeout: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[Dict]:
    """
    Supervises Layer 3 extraction in a spawned subprocess within a bounded timeout.
    Returns result dictionary on completion, or None if timed out, saturated, or failed.
    """
    extract_timeout = timeout if timeout is not None else config.STEGO_EXTRACT_TIMEOUT

    # Attempt to acquire concurrency semaphore slot with short wait
    acquired = _WORKER_SEMAPHORE.acquire(timeout=0.5)
    if not acquired:
        logger.warning("Layer 3 extraction semaphore saturated; falling back to L1/L2.")
        return None

    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc: Optional[mp.Process] = None
    result: Optional[Dict] = None

    try:
        proc = ctx.Process(
            target=worker_extract_entrypoint,
            args=(child_conn, pdf_path, config.STEGO_MAX_OUTPUT_BYTES, 50),
        )
        proc.start()
        child_conn.close()  # Close child endpoint in parent

        start_time = time.monotonic()
        deadline = start_time + extract_timeout

        while time.monotonic() < deadline:
            if cancel_event and cancel_event.is_set():
                logger.info("Extraction cancellation signal received.")
                break

            remaining = deadline - time.monotonic()
            poll_interval = min(0.05, max(0.001, remaining))

            if parent_conn.poll(poll_interval):
                try:
                    result = parent_conn.recv()
                except EOFError:
                    logger.warning("Worker pipe closed unexpectedly (worker crashed).")
                    result = None
                break

        if result is None and time.monotonic() >= deadline:
            logger.warning("Layer 3 extraction timed out after %.2fs", extract_timeout)

        return result
    except Exception as e:
        logger.warning("Layer 3 supervisor encountered an error: %s", e)
        return None
    finally:
        # Guarantee child process termination, reaping, and pipe cleanup
        if proc is not None:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=0.3)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=0.5)
            else:
                proc.join(timeout=0.1)

        parent_conn.close()
        _WORKER_SEMAPHORE.release()
