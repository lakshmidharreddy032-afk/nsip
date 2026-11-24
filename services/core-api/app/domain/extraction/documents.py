"""Document parsing into a common shape: tables (with cell refs) and text lines (with page/line/bbox)."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field

from openpyxl.utils import get_column_letter


@dataclass
class Cell:
    value: object
    ref: dict


@dataclass
class Table:
    name: str
    rows: list[list[Cell]]


@dataclass
class TextLine:
    text: str
    ref: dict


@dataclass
class ParsedDocument:
    filename: str
    attachment_id: str
    kind: str  # spreadsheet | pdf_text | pdf_scan | image | email_body
    tables: list[Table] = field(default_factory=list)
    lines: list[TextLine] = field(default_factory=list)
    ocr_engine: str | None = None
    ocr_cost_units: int = 0

    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


def _ref(att_id: str, filename: str, **kw) -> dict:
    return {"attachment_id": att_id, "file": filename, **kw}


def parse_xlsx(data: bytes, att_id: str, filename: str) -> ParsedDocument:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    doc = ParsedDocument(filename, att_id, "spreadsheet")
    for ws in wb.worksheets:
        rows = []
        for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            rows.append([Cell(v, _ref(att_id, filename, sheet=ws.title, cell=f"{get_column_letter(c)}{r_idx}"))
                         for c, v in enumerate(row, start=1)])
        doc.tables.append(Table(ws.title, rows))
    wb.close()
    return doc


def parse_xls(data: bytes, att_id: str, filename: str) -> ParsedDocument:  # pragma: no cover - legacy format
    import xlrd

    book = xlrd.open_workbook(file_contents=data)
    doc = ParsedDocument(filename, att_id, "spreadsheet")
    for sh in book.sheets():
        rows = [[Cell(sh.cell_value(r, c), _ref(att_id, filename, sheet=sh.name,
                                                cell=f"{get_column_letter(c + 1)}{r + 1}"))
                 for c in range(sh.ncols)] for r in range(sh.nrows)]
        doc.tables.append(Table(sh.name, rows))
    return doc


def parse_csv(data: bytes, att_id: str, filename: str) -> ParsedDocument:
    text = data.decode("utf-8-sig", errors="replace")
    doc = ParsedDocument(filename, att_id, "spreadsheet")
    rows = []
    for r_idx, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        rows.append([Cell(v, _ref(att_id, filename, sheet="csv", cell=f"{get_column_letter(c)}{r_idx}"))
                     for c, v in enumerate(row, start=1)])
    doc.tables.append(Table("csv", rows))
    return doc


def _lines_to_tables(doc: ParsedDocument) -> None:
    """Pipe-delimited text rows (PDF tables / OCR) become a table preserving line refs."""
    rows = []
    for line in doc.lines:
        if line.text.count("|") >= 3:
            cells = [c.strip() for c in line.text.strip().strip("|").split("|")]
            rows.append([Cell(c, dict(line.ref, column=i + 1)) for i, c in enumerate(cells)])
        elif rows and not line.text.strip():
            rows.append([])
    if rows:
        doc.tables.append(Table("text-table", rows))


def parse_pdf(data: bytes, att_id: str, filename: str, ocr) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    doc = ParsedDocument(filename, att_id, "pdf_text")
    for p_idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for l_idx, line in enumerate(text.splitlines(), start=1):
            doc.lines.append(TextLine(line, _ref(att_id, filename, page=p_idx, line=l_idx, text=line[:120])))
    if not any(line.text.strip() for line in doc.lines):
        doc.kind = "pdf_scan"
        doc.lines = []
        result = ocr_pdf(reader, ocr)
        doc.ocr_engine = result.engine
        doc.ocr_cost_units = max(len(reader.pages), 1)
        for l_idx, ln in enumerate(result.lines, start=1):
            doc.lines.append(TextLine(ln.text, _ref(att_id, filename, page=1, line=l_idx, bbox=ln.bbox,
                                                    ocr_confidence=ln.confidence, text=ln.text[:120])))
    _lines_to_tables(doc)
    return doc


def ocr_pdf(reader, ocr):
    """Scanned PDF: OCR each embedded page image. The mock reads the synthetic ground layer."""
    from app.adapters.ocr import OcrLine, OcrResult

    meta = reader.metadata or {}
    layer = meta.get("/Keywords") if hasattr(meta, "get") else None
    if layer and str(layer).startswith("{"):
        payload = json.loads(str(layer))
        return OcrResult([OcrLine(x["text"], x["bbox"], x.get("conf", 0.9)) for x in payload["lines"]], "mock-ocr")
    lines: list = []
    engine = ""
    for page in reader.pages:  # pragma: no cover - real OCR path
        for img in page.images:
            res = ocr.read(img.data)
            lines.extend(res.lines)
            engine = res.engine
    return OcrResult(lines, engine)


def parse_image(data: bytes, att_id: str, filename: str, ocr) -> ParsedDocument:
    doc = ParsedDocument(filename, att_id, "image")
    res = ocr.read(data)
    doc.ocr_engine = res.engine
    doc.ocr_cost_units = 1
    for l_idx, ln in enumerate(res.lines, start=1):
        doc.lines.append(TextLine(ln.text, _ref(att_id, filename, page=1, line=l_idx, bbox=ln.bbox,
                                                ocr_confidence=ln.confidence, text=ln.text[:120],
                                                image_size=[res.width, res.height])))
    _lines_to_tables(doc)
    return doc


def parse_text(text: str, att_id: str, filename: str, kind: str = "email_body") -> ParsedDocument:
    doc = ParsedDocument(filename, att_id, kind)
    for l_idx, line in enumerate(text.splitlines(), start=1):
        doc.lines.append(TextLine(line, _ref(att_id, filename, line=l_idx, text=line[:120])))
    _lines_to_tables(doc)
    return doc


SPREADSHEET_EXT = (".xlsx", ".xlsm", ".csv", ".xls")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff")


def parse(data: bytes, att_id: str, filename: str, ocr) -> ParsedDocument | None:
    low = filename.lower()
    if low.endswith((".xlsx", ".xlsm")):
        return parse_xlsx(data, att_id, filename)
    if low.endswith(".xls"):
        return parse_xls(data, att_id, filename)
    if low.endswith(".csv"):
        return parse_csv(data, att_id, filename)
    if low.endswith(".pdf"):
        return parse_pdf(data, att_id, filename, ocr)
    if low.endswith(IMAGE_EXT):
        return parse_image(data, att_id, filename, ocr)
    if low.endswith(".txt"):
        return parse_text(data.decode("utf-8", errors="replace"), att_id, filename, "text")
    return None


def needs_ocr(filename: str, data: bytes) -> bool:
    low = filename.lower()
    if low.endswith(IMAGE_EXT):
        return True
    if low.endswith(".pdf"):
        return b"/Font" not in data
    return False
