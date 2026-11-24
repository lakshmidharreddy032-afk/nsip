"""Minimal dependency-free PDF writer (text) and scan renderer (PNG / image-PDF with an OCR ground layer)."""
from __future__ import annotations

import io
import json

from PIL import Image, ImageDraw, ImageFont


def _esc(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf(lines: list[str], title: str = "Document") -> bytes:
    """One or more A4 pages of Helvetica 9pt text."""
    per_page = 60
    pages = [lines[i:i + per_page] for i in range(0, max(len(lines), 1), per_page)] or [[]]
    objs: list[bytes] = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages)))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_obj = 3 + len(pages) * 2
    for i, pl in enumerate(pages):
        content = ["BT", "/F1 9 Tf", "11 TL", "40 800 Td"]
        for ln in pl:
            content.append(f"({_esc(ln)}) Tj T*")
        content.append("ET")
        stream = "\n".join(content).encode("latin-1")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {4 + i * 2} 0 R "
                    f"/Resources << /Font << /F1 {font_obj} 0 R >> >> >>".encode())
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append(f"<< /Title ({_esc(title)}) /Producer (NSIP synthetic) >>".encode())
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {len(objs)} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def _render(lines: list[str]) -> tuple[Image.Image, list[dict]]:
    font = ImageFont.load_default()
    width = max(900, max((len(ln) for ln in lines), default=10) * 7 + 60)
    height = 40 + 18 * len(lines) + 40
    img = Image.new("L", (width, height), 250)
    d = ImageDraw.Draw(img)
    layer = []
    for i, ln in enumerate(lines):
        y = 30 + 18 * i
        d.text((30, y), ln, fill=20, font=font)
        layer.append({"text": ln, "bbox": [30, y, min(len(ln) * 7, width - 30), 14], "conf": 0.93})
    # light scan noise
    for x in range(0, width, 37):
        d.point((x, (x * 7) % height), fill=160)
    return img, layer


def scan_png(lines: list[str]) -> bytes:
    from PIL import PngImagePlugin

    img, layer = _render(lines)
    meta = PngImagePlugin.PngInfo()
    meta.add_text("nsip-ocr", json.dumps({"lines": layer}))
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=meta)
    return buf.getvalue()


def scan_pdf(lines: list[str]) -> bytes:
    img, layer = _render(lines)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PDF", resolution=100.0, keywords=json.dumps({"lines": layer}))
    return buf.getvalue()
