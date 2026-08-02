#!/usr/bin/env python3
"""Verify RapidOCR + OpenCV are installed for Sensibull screenshot ingest."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    errors: list[str] = []
    try:
        import cv2  # noqa: F401
    except ImportError:
        errors.append("opencv-python-headless (import cv2)")

    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401
    except ImportError:
        errors.append("rapidocr-onnxruntime")

    if errors:
        print("MISSING:", ", ".join(errors))
        print("Install: .venv\\Scripts\\pip install -r requirements.txt")
        return 1

    from tools.read_image_ocr import run_ocr  # noqa: F401

    print("OK: OCR stack ready (RapidOCR + OpenCV + read_image_ocr)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
