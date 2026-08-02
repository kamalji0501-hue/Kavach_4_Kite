#!/usr/bin/env python3
"""Local OCR helper for path-based image reading.

Usage:
  python tools/read_image_ocr.py --image "C:/path/to/file.png"
  python tools/read_image_ocr.py --image "C:/path/to/file.png" --json
  python tools/read_image_ocr.py --image "C:/path/to/file.png" --save-txt out.txt --save-json out.json
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Literal

import cv2
from rapidocr_onnxruntime import RapidOCR


@dataclass
class OcrLine:
    text: str
    score: float
    box: list[list[float]]


def _preprocess(img_bgr):
    # Mild preprocessing helps on dense UI screenshots.
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    den = cv2.fastNlMeansDenoising(up, h=7)
    thr = cv2.adaptiveThreshold(
        den,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11,
    )
    return thr


def _preprocess_otsu(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    den = cv2.fastNlMeansDenoising(up, h=5)
    _, thr = cv2.threshold(den, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thr


def _preprocess_clahe(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    con = clahe.apply(up)
    return cv2.GaussianBlur(con, (3, 3), 0)


def _parse_results(raw: Sequence | None) -> list[OcrLine]:
    rows: list[OcrLine] = []
    for item in raw or []:
        if not item or len(item) < 3:
            continue
        box, text, score = item[0], item[1], item[2]
        text = str(text).strip()
        if not text:
            continue
        rows.append(OcrLine(text=text, score=float(score), box=box))
    return rows


def _score_payload(lines: Sequence[OcrLine]) -> tuple[int, float]:
    total_chars = sum(len(x.text) for x in lines)
    avg_conf = (sum(x.score for x in lines) / len(lines)) if lines else 0.0
    return total_chars, avg_conf


def _center_xy(box: list[list[float]]) -> tuple[float, float]:
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _sort_reading_order(lines: list[OcrLine], y_bucket_px: float = 18.0) -> list[OcrLine]:
    with_coords = [(line, *_center_xy(line.box)) for line in lines]
    with_coords.sort(key=lambda item: (round(item[2] / y_bucket_px), item[1]))
    return [item[0] for item in with_coords]


def _merge_lines(candidates: Sequence[list[OcrLine]]) -> list[OcrLine]:
    # Keep highest-confidence line while suppressing OCR duplicates.
    def _norm_key(text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    kept: list[tuple[str, OcrLine]] = []
    for lines in candidates:
        for row in lines:
            key = _norm_key(row.text)
            if not key:
                continue

            replaced = False
            for idx, (prev_key, prev_line) in enumerate(kept):
                ratio = difflib.SequenceMatcher(a=key, b=prev_key).ratio()
                if ratio >= 0.93:
                    # Prefer confidence first, then richer text payload.
                    if (row.score > prev_line.score) or (
                        row.score == prev_line.score and len(key) > len(prev_key)
                    ):
                        kept[idx] = (key, row)
                    replaced = True
                    break

            if not replaced:
                kept.append((key, row))

    return [line for _, line in kept]


def run_ocr(image_path: str, mode: Literal["best", "merge"] = "merge") -> list[OcrLine]:
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Unable to decode image: {image_path}")

    engine = RapidOCR()

    variants = [
        img,
        _preprocess(img),
        _preprocess_otsu(img),
        _preprocess_clahe(img),
    ]

    all_lines: list[list[OcrLine]] = []
    for variant in variants:
        raw, _ = engine(variant)
        all_lines.append(_parse_results(raw))

    if mode == "best":
        best = max(all_lines, key=lambda lines: _score_payload(lines))
        return _sort_reading_order(best)

    merged = _merge_lines(all_lines)
    return _sort_reading_order(merged)


def main() -> int:
    # Ensure Windows terminals can print OCR text containing Unicode symbols.
    try:
        reconfig_out = getattr(sys.stdout, "reconfigure", None)
        if callable(reconfig_out):
            reconfig_out(encoding="utf-8", errors="replace")
        reconfig_err = getattr(sys.stderr, "reconfigure", None)
        if callable(reconfig_err):
            reconfig_err(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Extract OCR text from an image path.")
    parser.add_argument("--image", required=True, help="Absolute or relative image path")
    parser.add_argument("--min-score", type=float, default=0.35, help="Confidence filter (0-1)")
    parser.add_argument(
        "--mode",
        choices=["best", "merge"],
        default="merge",
        help="best: choose strongest single OCR pass, merge: combine all passes",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of plain text")
    parser.add_argument("--save-txt", default="", help="Optional path to save plain-text lines")
    parser.add_argument("--save-json", default="", help="Optional path to save JSON lines")
    args = parser.parse_args()

    lines = [x for x in run_ocr(args.image, mode=args.mode) if x.score >= args.min_score]

    if args.json:
        payload = [asdict(x) for x in lines]
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    else:
        for row in lines:
            print(row.text)

    if args.save_txt:
        with open(args.save_txt, "w", encoding="utf-8") as f:
            for row in lines:
                f.write(row.text + "\n")

    if args.save_json:
        with open(args.save_json, "w", encoding="utf-8") as f:
            json.dump([asdict(x) for x in lines], f, ensure_ascii=True, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
