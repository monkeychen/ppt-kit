import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

VISION_SWIFT_SOURCE = """
import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count > 1 else { exit(1) }
let imgPath = args[1]
guard let img = NSImage(contentsOfFile: imgPath),
      let cgImg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    exit(2)
}

let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.recognitionLanguages = ["zh-Hans", "en-US"]
req.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImg, options: [:])
try handler.perform([req])

var out: [[String: Any]] = []
for obs in req.results ?? [] {
    guard let top = obs.topCandidates(1).first else { continue }
    let b = obs.boundingBox
    out.append([
        "text": top.string,
        "confidence": top.confidence,
        "x": b.origin.x,
        "y": 1.0 - b.origin.y - b.size.height,
        "w": b.size.width,
        "h": b.size.height
    ])
}
let data = try JSONSerialization.data(withJSONObject: out, options: [])
print(String(data: data, encoding: .utf8)!)
"""

MERGED_BADGE_PATTERN = re.compile(r"^([0oO]\d|\d{2})\s+(.+)$")
STRAY_ICON_PREFIX_PATTERN = re.compile(r"^(?:太|★|☆)\s+(.+)$")


@dataclass
class OCRBox:
    text: str
    bbox_px: tuple[int, int, int, int]
    confidence: float


def _ensure_vision_binary() -> Path:
    cache_dir = Path.home() / ".cache" / "pptkit" / "bin"
    cache_dir.mkdir(parents=True, exist_ok=True)
    bin_path = cache_dir / "vision_ocr"
    src_path = cache_dir / "vision_ocr.swift"

    if (
        not bin_path.exists()
        or not src_path.exists()
        or src_path.read_text() != VISION_SWIFT_SOURCE
    ):
        src_path.write_text(VISION_SWIFT_SOURCE, encoding="utf-8")
        subprocess.run(
            ["swiftc", "-O", str(src_path), "-o", str(bin_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    return bin_path


def clean_ocr_boxes(boxes: list[OCRBox]) -> list[OCRBox]:
    cleaned: list[OCRBox] = []
    for box in boxes:
        text = box.text.strip()
        if not text:
            continue

        x, y, w, h = box.bbox_px

        # 1. Split merged two-digit badge prefix like "o7 回答AI跟你提出的问题"
        m_badge = MERGED_BADGE_PATTERN.match(text)
        if m_badge:
            raw_num, rest = m_badge.group(1), m_badge.group(2).strip()
            norm_num = raw_num.replace("o", "0").replace("O", "0")
            badge_w = min(int(h * 1.4), max(int(w * 0.14), 24))
            gap = max(int(h * 0.35), 8)
            cleaned.append(
                OCRBox(
                    text=norm_num,
                    bbox_px=(x, y, badge_w, h),
                    confidence=box.confidence,
                )
            )
            cleaned.append(
                OCRBox(
                    text=rest,
                    bbox_px=(x + badge_w + gap, y, max(w - badge_w - gap, 10), h),
                    confidence=box.confidence,
                )
            )
            continue

        # 2. Strip stray star/icon character misrecognized at start of banner text
        m_star = STRAY_ICON_PREFIX_PATTERN.match(text)
        if m_star:
            rest = m_star.group(1).strip()
            icon_shift = min(int(h * 1.35), max(int(w * 0.06), 20))
            cleaned.append(
                OCRBox(
                    text=rest,
                    bbox_px=(x + icon_shift, y, max(w - icon_shift, 10), h),
                    confidence=box.confidence,
                )
            )
            continue

        cleaned.append(OCRBox(text=text, bbox_px=(x, y, w, h), confidence=box.confidence))

    return cleaned


class AppleVisionOCRAdapter:
    def recognize(self, image_path: Path | str, clean: bool = True) -> list[OCRBox]:
        img_p = Path(image_path).resolve()
        with Image.open(img_p) as im:
            width_px, height_px = im.size

        bin_path = _ensure_vision_binary()
        proc = subprocess.run(
            [str(bin_path), str(img_p)],
            check=True,
            capture_output=True,
            text=True,
        )
        raw_items = json.loads(proc.stdout)
        boxes: list[OCRBox] = []
        for item in raw_items:
            nx = float(item["x"])
            ny = float(item["y"])
            nw = float(item["w"])
            nh = float(item["h"])
            x_px = max(0, min(width_px - 1, round(nx * width_px)))
            y_px = max(0, min(height_px - 1, round(ny * height_px)))
            w_px = max(1, min(width_px - x_px, round(nw * width_px)))
            h_px = max(1, min(height_px - y_px, round(nh * height_px)))
            boxes.append(
                OCRBox(
                    text=str(item["text"]),
                    bbox_px=(x_px, y_px, w_px, h_px),
                    confidence=float(item["confidence"]),
                )
            )

        return clean_ocr_boxes(boxes) if clean else boxes
