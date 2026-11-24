"""OCR for scanned PDFs and images: Tesseract locally or a cloud OCR behind the AI gateway."""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image


@dataclass
class OcrLine:
    text: str
    bbox: list[int]  # x, y, w, h in pixels
    confidence: float


@dataclass
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    engine: str = ""
    width: int = 0
    height: int = 0


class OcrAdapter(Protocol):
    def read(self, data: bytes) -> OcrResult: ...


class MockOcr:
    """Reads the synthetic OCR ground layer that the eval generator embeds in each scan (PNG tEXt).

    This mirrors a real engine's line + bbox + confidence output so downstream code is identical.
    """

    def read(self, data: bytes) -> OcrResult:
        img = Image.open(io.BytesIO(data))
        layer = img.info.get("nsip-ocr")
        if not layer:
            return OcrResult(engine="mock", width=img.width, height=img.height)
        payload = json.loads(layer)
        return OcrResult(lines=[OcrLine(x["text"], x["bbox"], x.get("conf", 0.9)) for x in payload["lines"]],
                         engine="mock-ocr", width=img.width, height=img.height)


class TesseractOcr:  # pragma: no cover - requires tesseract binary
    def read(self, data: bytes) -> OcrResult:
        import pytesseract

        img = Image.open(io.BytesIO(data))
        d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 6")
        rows: dict[tuple, list[int]] = {}
        for i, word in enumerate(d["text"]):
            if not word.strip():
                continue
            key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
            rows.setdefault(key, []).append(i)
        lines = []
        for idx in rows.values():
            xs = [d["left"][i] for i in idx]
            ys = [d["top"][i] for i in idx]
            x2 = [d["left"][i] + d["width"][i] for i in idx]
            y2 = [d["top"][i] + d["height"][i] for i in idx]
            conf = sum(float(d["conf"][i]) for i in idx) / len(idx) / 100
            lines.append(OcrLine(" ".join(d["text"][i] for i in idx),
                                 [min(xs), min(ys), max(x2) - min(xs), max(y2) - min(ys)], conf))
        return OcrResult(lines=lines, engine="tesseract", width=img.width, height=img.height)
