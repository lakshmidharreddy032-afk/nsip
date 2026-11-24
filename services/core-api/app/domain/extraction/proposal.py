"""Deterministic proposal-form and loss-history parsing (labelled key/value text and two-column sheets)."""
from __future__ import annotations

import re

from app.domain.extraction.documents import ParsedDocument
from app.domain.extraction.normalise import parse_amount, parse_int
from app.domain.extraction.sov import FieldValue

LABELS: dict[str, list[str]] = {
    "insured_name": ["name of insured", "insured name", "name of proposer", "proposer name", "proposer", "insured"],
    "risk_address": ["risk address", "address of premises", "location address", "premises address", "address"],
    "pincode": ["pincode", "pin code", "pin"],
    "occupancy": ["occupancy", "nature of business", "occupation of premises", "trade"],
    "construction": ["construction type", "building construction", "construction"],
    "year_built": ["year of construction", "year built", "age of building"],
    "protections": ["fire protection", "protections", "protection"],
    "sum_insured": ["total sum insured", "sum insured", "total si", "tsi"],
    "coverage": ["cover required", "coverage", "policy type"],
    "deductible": ["deductible", "excess"],
    "inception_date": ["proposed inception", "inception date", "period from"],
    "claims_count_3y": ["claims in last 3 years", "number of claims (3 yrs)", "claims (last 3 years)"],
    "claims_amount_3y": ["claims amount (3 yrs)", "total claims paid (3 yrs)", "claims amount last 3 years"],
    "contact_person": ["contact person"],
    "contact_phone": ["contact no", "mobile", "phone"],
}
_ORDERED = sorted(((lab, key) for key, labs in LABELS.items() for lab in labs), key=lambda x: -len(x[0]))
_KV = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 ()/.&'-]{1,60}?)\s*[:\-–]\s+(.+?)\s*$")
CONF_KV = 0.96


def _label_key(label: str) -> str | None:
    low = re.sub(r"\s+", " ", label.strip().lower())
    for lab, key in _ORDERED:
        if low == lab:
            return key
    return None


def parse_key_values(doc: ParsedDocument) -> dict[str, FieldValue]:
    out: dict[str, FieldValue] = {}
    for line in doc.lines:
        m = _KV.match(line.text)
        if not m:
            continue
        key = _label_key(m.group(1))
        if key and key not in out:
            out[key] = FieldValue(m.group(2).strip(), CONF_KV, line.ref, "deterministic")
    for t in doc.tables:
        for row in t.rows:
            cells = [c for c in row if c.value not in (None, "")]
            if len(cells) == 2 and isinstance(cells[0].value, str):
                key = _label_key(cells[0].value.rstrip(":"))
                if key and key not in out:
                    out[key] = FieldValue(cells[1].value, CONF_KV, cells[1].ref, "deterministic")
    return out


def parse_loss_history(doc: ParsedDocument) -> list[dict[str, FieldValue]]:
    """Rows under a 'Loss history' heading: Year | Cause | Paid | Outstanding (text) or a loss sheet."""
    rows: list[dict[str, FieldValue]] = []
    in_section = False
    for line in doc.lines:
        low = line.text.lower()
        if "loss history" in low or "claims history" in low:
            in_section = True
            continue
        if in_section:
            parts = [p.strip() for p in line.text.strip().strip("|").split("|")]
            if len(parts) >= 3 and re.fullmatch(r"(19|20)\d{2}", parts[0]):
                rows.append({
                    "year": FieldValue(int(parts[0]), CONF_KV, line.ref, "deterministic"),
                    "cause": FieldValue(parts[1], CONF_KV, line.ref, "deterministic"),
                    "amount_paid": FieldValue(parse_amount(parts[2]) or 0, CONF_KV, line.ref, "deterministic"),
                    "amount_outstanding": FieldValue(parse_amount(parts[3]) if len(parts) > 3 else 0, CONF_KV,
                                                     line.ref, "deterministic"),
                })
            elif rows and not line.text.strip():
                in_section = False
    if doc.kind == "spreadsheet":
        for t in doc.tables:
            if not t.rows:
                continue
            head = [str(c.value or "").strip().lower() for c in t.rows[0]]
            if "year" in head and any("cause" in h for h in head):
                yi = head.index("year")
                ci = next(i for i, h in enumerate(head) if "cause" in h)
                pi = next((i for i, h in enumerate(head) if "paid" in h), None)
                oi = next((i for i, h in enumerate(head) if "outstanding" in h), None)
                for r in t.rows[1:]:
                    y = parse_int(r[yi].value) if yi < len(r) else None
                    if not y:
                        continue
                    rows.append({
                        "year": FieldValue(y, CONF_KV, r[yi].ref, "deterministic"),
                        "cause": FieldValue(str(r[ci].value), CONF_KV, r[ci].ref, "deterministic"),
                        "amount_paid": FieldValue(parse_amount(r[pi].value) or 0 if pi is not None else 0, CONF_KV,
                                                  r[pi].ref if pi is not None else r[yi].ref, "deterministic"),
                        "amount_outstanding": FieldValue(parse_amount(r[oi].value) or 0 if oi is not None else 0,
                                                         CONF_KV, r[oi].ref if oi is not None else r[yi].ref,
                                                         "deterministic"),
                    })
    return rows
