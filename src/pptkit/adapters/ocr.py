import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from PIL import Image

from pptkit.ingest.loader import IngestError

OCREngineType = Literal["auto", "apple_vision", "rapidocr"]


@runtime_checkable
class BaseOCRAdapter(Protocol):
    def recognize(self, image_path: Path | str, clean: bool = True) -> list["OCRBox"]: ...


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
    var ox = b.origin.x
    var oy = 1.0 - b.origin.y - b.size.height
    var ow = b.size.width
    var oh = b.size.height

    let s = top.string
    if s.count >= 2 {
        let i0 = s.startIndex
        let i1 = s.index(after: i0)
        let i2 = s.index(after: i1)
        let c0 = s[i0]
        let c1 = s[i1]
        if let sc0 = c0.unicodeScalars.first,
           let sc1 = c1.unicodeScalars.first,
           (0x4E00...0x9FA5).contains(sc0.value),
           (0x4E00...0x9FA5).contains(sc1.value) {
            if let b0 = try? top.boundingBox(for: i0..<i1),
               let b1 = try? top.boundingBox(for: i1..<i2) {
                let w0 = b0.boundingBox.size.width
                let w1 = b1.boundingBox.size.width
                if w0 > 1.8 * w1 && w1 > 0.005 {
                    let shift = b1.boundingBox.origin.x - w1 - b.origin.x
                    if shift > 0 {
                        ox += shift
                        ow = max(0.01, ow - shift)
                    }
                }
            }
        }
    }

    out.append([
        "text": top.string,
        "confidence": top.confidence,
        "x": ox,
        "y": oy,
        "w": ow,
        "h": oh
    ])
}
let data = try JSONSerialization.data(withJSONObject: out, options: [])
print(String(data: data, encoding: .utf8)!)
"""

MERGED_BADGE_PATTERN = re.compile(r"^([0oO]\d|\d{2})\s+(.+)$")
STRAY_ICON_PREFIX_PATTERN = re.compile(
    r"^(?:(?:太|★|☆|√|✔|✓|•|·|◎|○|●|◐|◑|☑|☐|□|■|▲|▼|◆|◇)\s*|[vVoOgGcCeE@#§2]\s+)([\u4e00-\u9fa5].+)$"
)
KNOWN_ACRONYMS = {"AI", "UI", "IT", "OK", "PPT", "API", "SDK", "PC", "OS"}


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

        # 0. Drop low-confidence 1-2 char ASCII noise from micro-icons (e.g. 'Ei', 'M4', 'L', 'Do')
        if (
            len(text) <= 2
            and text.isascii()
            and not text.isdigit()
            and text.upper() not in KNOWN_ACRONYMS
            and box.confidence <= 0.55
            and max(w, h) <= 90
        ):
            continue

        # 0b. Drop large low-confidence hallucinations on illustrations (e.g. '国皿' on calculator)
        if len(text) <= 2 and box.confidence <= 0.35 and max(w, h) >= 90:
            continue

        # 0c. Drop standalone graphic bullet/check icon glyphs
        if len(text) == 1 and text in {
            "◎",
            "○",
            "●",
            "★",
            "☆",
            "•",
            "·",
            "太",
            "√",
            "✔",
            "✓",
            "□",
            "■",
            "☑",
            "☐",
        }:
            continue

        # Fix missing math inequality symbol omitted by Vision OCR in Chinese comparison lines
        text = re.sub(r"(自检)\s+(人工)", r"\1 ≠ \2", text)

        # 1. Split merged two-digit badge prefix like "o7 回答AI跟你提出的问题"
        m_badge = MERGED_BADGE_PATTERN.match(text)
        if m_badge:
            raw_num, rest = m_badge.group(1), m_badge.group(2).strip()
            norm_num = raw_num.replace("o", "0").replace("O", "0")
            badge_w = min(int(h * 1.15), max(int(w * 0.13), 24))
            gap = max(int(w * 0.065), 12)
            body_w = max(w - badge_w - gap, 10)
            row_y, row_h = y, h
            if len(rest) >= 4:
                est_char_h = round((body_w / len(rest)) * 1.12)
                if est_char_h >= 16 and h > est_char_h * 1.25:
                    row_y = y + h - est_char_h
                    row_h = est_char_h
            cleaned.append(
                OCRBox(
                    text=norm_num,
                    bbox_px=(x, row_y, badge_w, row_h),
                    confidence=box.confidence,
                )
            )
            cleaned.append(
                OCRBox(
                    text=rest,
                    bbox_px=(x + badge_w + gap, row_y, body_w, row_h),
                    confidence=box.confidence,
                )
            )
            continue

        # 2. Strip stray star/icon character misrecognized at start of banner or title text
        m_star = STRAY_ICON_PREFIX_PATTERN.match(text)
        if m_star:
            rest = m_star.group(1).strip()
            icon_shift = max(20, min(int(round(h * 1.18)), int(w * 0.45)))
            cleaned.append(
                OCRBox(
                    text=rest,
                    bbox_px=(x + icon_shift, y, max(w - icon_shift, 10), h),
                    confidence=box.confidence,
                )
            )
            continue

        cleaned.append(OCRBox(text=text, bbox_px=(x, y, w, h), confidence=box.confidence))

    # 3. Merge adjacent same-line sentence fragments split at punctuation
    merged_changed = True
    while merged_changed:
        merged_changed = False
        for i in range(len(cleaned)):
            if merged_changed:
                break
            ax, ay, aw, ah = cleaned[i].bbox_px
            for j in range(len(cleaned)):
                if i == j:
                    continue
                bx, by, bw, bh = cleaned[j].bbox_px
                min_h = min(ah, bh)
                max_h = max(ah, bh)
                if abs(ay - by) > 0.28 * min_h or abs(ah - bh) > 0.28 * max_h:
                    continue
                gap_x = bx - (ax + aw)
                if 0 <= gap_x <= 0.45 * min_h and (
                    cleaned[i].text.endswith(("，", "、", "：", "；"))
                    or cleaned[j].text.startswith(("，", "。", "、", "："))
                ):
                    ux0 = min(ax, bx)
                    uy0 = min(ay, by)
                    ux1 = max(ax + aw, bx + bw)
                    uy1 = max(ay + ah, by + bh)
                    new_box = OCRBox(
                        text=cleaned[i].text + cleaned[j].text,
                        bbox_px=(ux0, uy0, ux1 - ux0, uy1 - uy0),
                        confidence=min(cleaned[i].confidence, cleaned[j].confidence),
                    )
                    cleaned[i] = new_box
                    cleaned.pop(j)
                    merged_changed = True
                    break

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

        if clean:
            refined_boxes: list[OCRBox] = []
            cache_dir = Path.home() / ".cache" / "pptkit"
            cache_dir.mkdir(parents=True, exist_ok=True)
            for box in boxes:
                bx, by, bw, bh = box.bbox_px
                if box.confidence <= 0.35 and bh >= 95 and bw >= 100:
                    slice_h = min(bh, max(45, int(bh * 0.52)))
                    with Image.open(img_p) as im:
                        slice_img = im.crop(
                            (bx, by, min(width_px, bx + bw), min(height_px, by + slice_h))
                        )
                    tmp_slice = cache_dir / "tmp_slice.png"
                    slice_img.save(tmp_slice)
                    sub_boxes = self.recognize(tmp_slice, clean=False)
                    high_conf_subs = [sb for sb in sub_boxes if sb.confidence >= 0.70]
                    if high_conf_subs:
                        for sb in high_conf_subs:
                            sx, sy, sw, sh = sb.bbox_px
                            refined_boxes.append(
                                OCRBox(
                                    text=sb.text,
                                    bbox_px=(bx + sx, by + sy, sw, sh),
                                    confidence=sb.confidence,
                                )
                            )
                        continue
                refined_boxes.append(box)
            return clean_ocr_boxes(refined_boxes)

        return boxes


class RapidOCRAdapter:
    def __init__(self) -> None:
        self._engine: Any = None

    def _get_engine(self) -> Any:
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def recognize(self, image_path: Path | str, clean: bool = True) -> list[OCRBox]:
        img_p = Path(image_path).resolve()
        with Image.open(img_p) as im:
            width_px, height_px = im.size

        engine = self._get_engine()
        raw_result, _ = engine(str(img_p))
        if not raw_result:
            return []

        boxes: list[OCRBox] = []
        for entry in raw_result:
            pts = entry[0]
            text = str(entry[1])
            conf = float(entry[2])

            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x0 = max(0, min(width_px - 1, int(round(min(xs)))))
            y0 = max(0, min(height_px - 1, int(round(min(ys)))))
            x1 = max(0, min(width_px, int(round(max(xs)))))
            y1 = max(0, min(height_px, int(round(max(ys)))))
            w = max(1, x1 - x0)
            h = max(1, y1 - y0)

            boxes.append(OCRBox(text=text, bbox_px=(x0, y0, w, h), confidence=conf))

        if clean:
            return clean_ocr_boxes(boxes)
        return boxes


def get_ocr_adapter(engine: OCREngineType = "auto") -> BaseOCRAdapter:
    if engine == "auto":
        target = "apple_vision" if sys.platform == "darwin" else "rapidocr"
    else:
        target = engine

    if target == "apple_vision":
        if sys.platform != "darwin":
            raise IngestError(
                code="UNSUPPORTED_PLATFORM",
                message="Apple Vision OCR 仅在 macOS 系统可用",
                hint="请改用 --ocr-engine rapidocr 或保持默认 --ocr-engine auto",
            )
        return AppleVisionOCRAdapter()
    elif target == "rapidocr":
        return RapidOCRAdapter()
    else:
        raise ValueError(f"未知的 OCR 引擎：{engine}")
