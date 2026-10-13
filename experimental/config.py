"""
Configuration and constants for the experimental steganographic watermarking prototype.
Strictly isolated within experimental/ directory.
"""
from __future__ import annotations

import os
from pathlib import Path

EXPERIMENTAL_DIR = Path(__file__).resolve().parent
PDFS_DIR = EXPERIMENTAL_DIR / "pdfs"
OUTPUT_DIR = EXPERIMENTAL_DIR / "output"
REPORTS_DIR = EXPERIMENTAL_DIR / "reports"
CHARTS_DIR = EXPERIMENTAL_DIR / "charts"
WORKING_DIR = EXPERIMENTAL_DIR / "working"

# Isolated experimental master key (never uses production key)
DEFAULT_KEY_PATH = WORKING_DIR / "exp_master.key"

# Steganographic Bit Modulation Parameters
# In PDF TJ operators, kerning is measured in 1/1000 of an em.
# Negative shifts displace glyphs to the right (widen inter-word space).
DEFAULT_KERNING_SHIFT = -25  # ~0.24-0.30 pt at 10-12pt font
MIN_KERNING_THRESHOLD = -10  # Threshold used in stream parsing to decide bit 1 vs 0

# Preamble marker for frame synchronization: "SPDF" in ASCII (32 bits)
SYNC_PREAMBLE = b"SPDF"
SYNC_PREAMBLE_BITS = "".join(f"{byte:08b}" for byte in SYNC_PREAMBLE)

# Protocol version
STEGO_VERSION = 0x01
