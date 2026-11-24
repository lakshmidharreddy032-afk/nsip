"""SOV parsing: header detection, format fingerprinting, deterministic mapping, LLM fallback for unknown
layouts (saved as a *proposed* mapping that requires human approval before it becomes deterministic).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.extraction.documents import Cell, Table
from app.domain.extraction.normalise import parse_amount, parse_int
from app.models import SovMapping

MONEY_FIELDS = ("building", "plant_machinery", "stock", "contents", "other")
DETERMINISTIC_CONFIDENCE = 0.97
LLM_CAP = 0.84  # unapproved learned mappings stay below the review threshold


def norm_header(h) -> str:
    return re.sub(r"\s+", " ", str(h or "").strip().lower())


def fingerprint(headers: list[str]) -> str:
    return hashlib.sha256("|".join(norm_header(h) for h in headers if norm_header(h)).encode()).hexdigest()[:32]


@lru_cache
def library() -> list[dict]:
    data = yaml.safe_load((Path(__file__).parent / "sov_layouts.yaml").read_text(encoding="utf-8"))
    out = []
    for lay in data["layouts"]:
        headers = [c[0] for c in lay["columns"]]
        out.append({"id": lay["id"], "broker": lay["broker"], "headers": headers,
                    "mapping": {norm_header(c[0]): {"field": c[1], "unit_multiplier": int(c[2])} for c in lay["columns"]},
                    "fingerprint": fingerprint(headers)})
    return out


def seed_library(db: Session) -> int:
    n = 0
    for lay in library():
        if db.scalar(select(SovMapping).where(SovMapping.fingerprint == lay["fingerprint"])):
            continue
        db.add(SovMapping(layout_id=lay["id"], fingerprint=lay["fingerprint"], broker_hint=lay["broker"],
                          headers=lay["headers"], mapping=lay["mapping"], status="approved", source="seed"))
        n += 1
    db.flush()
    return n


_HEADER_TOKENS = ("address", "loc", "pin", "occupancy", "building", "total", "stock", "sum", "site", "trade",
                  "construction", "year", "city", "premises", "risk", "value", "si", "bldg", "machinery")


def find_header_row(table: Table) -> int | None:
    for i, row in enumerate(table.rows[:15]):
        texts = [norm_header(c.value) for c in row if isinstance(c.value, str) and c.value.strip()]
        hits = sum(1 for t in texts if any(tok in t for tok in _HEADER_TOKENS))
        if len(texts) >= 3 and hits >= 3:
            return i
    return None


@dataclass
class FieldValue:
    value: object
    confidence: float
    ref: dict
    method: str


@dataclass
class SovLocation:
    fields: dict[str, FieldValue] = field(default_factory=dict)


@dataclass
class SovParse:
    layout_id: str
    fingerprint: str
    mapping_status: str  # approved | proposed
    method: str  # deterministic | llm
    locations: list[SovLocation]
    declared_total: FieldValue | None
    headers: list[str]
    prompt_version: str | None = None
    model_version: str | None = None


class UnknownLayout(Exception):
    def __init__(self, headers: list[str], samples: list[list[str]]):
        super().__init__("unknown SOV layout")
        self.headers, self.samples = headers, samples


def resolve_mapping(db: Session, headers: list[str]) -> SovMapping | None:
    fp = fingerprint(headers)
    m = db.scalar(select(SovMapping).where(SovMapping.fingerprint == fp, SovMapping.status != "rejected"))
    return m


def parse_table(db: Session, table: Table, mapping_lookup=resolve_mapping) -> SovParse:
    h_idx = find_header_row(table)
    if h_idx is None:
        raise ValueError("no SOV header row found")
    header_cells = table.rows[h_idx]
    headers = [str(c.value).strip() for c in header_cells if c.value not in (None, "")]
    m = mapping_lookup(db, headers)
    if m is None:
        samples = [[str(c.value) for c in r if c.value not in (None, "")] for r in table.rows[h_idx + 1:h_idx + 3]]
        raise UnknownLayout(headers, samples)
    m.times_used += 1
    approved = m.status == "approved"
    conf = DETERMINISTIC_CONFIDENCE if approved else LLM_CAP
    method = "deterministic" if approved else "llm"
    col_map: dict[int, dict] = {}
    for idx, c in enumerate(header_cells):
        spec = m.mapping.get(norm_header(c.value))
        if spec and spec["field"] != "ignore":
            col_map[idx] = spec
    locations: list[SovLocation] = []
    declared_total: FieldValue | None = None
    for row in table.rows[h_idx + 1:]:
        vals = [c.value for c in row]
        if not any(v not in (None, "") for v in vals):
            if locations:
                break
            continue
        first_text = " ".join(str(v) for v in vals[:3] if v not in (None, "")).lower()
        if "total" in first_text and not any(
            spec["field"] == "address" and row[i].value and "total" not in str(row[i].value).lower()
            for i, spec in col_map.items() if i < len(row)
        ):
            tot_idx = next((i for i, s in col_map.items() if s["field"] == "total"), None)
            if tot_idx is not None and tot_idx < len(row):
                amt = parse_amount(row[tot_idx].value, col_map[tot_idx]["unit_multiplier"])
                if amt is not None:
                    declared_total = FieldValue(amt, conf, row[tot_idx].ref, method)
            break
        loc = SovLocation()
        for i, spec in col_map.items():
            if i >= len(row):
                continue
            cell: Cell = row[i]
            f = spec["field"]
            raw = cell.value
            v: object
            if f in MONEY_FIELDS or f == "total":
                v = parse_amount(raw, spec["unit_multiplier"])
            elif f in ("year_built", "loc_no"):
                v = parse_int(raw)
            elif f == "pincode":
                v = re.sub(r"\D", "", str(raw or ""))[:6] or None
            else:
                v = str(raw).strip() if raw not in (None, "") else None
            c_conf = conf * float(cell.ref.get("ocr_confidence", 1.0)) if "ocr_confidence" in cell.ref else conf
            loc.fields[f] = FieldValue(v, round(c_conf, 3), cell.ref, method)
        if "loc_no" not in loc.fields:
            loc.fields["loc_no"] = FieldValue(len(locations) + 1, conf, row[0].ref if row else {}, "derived")
        locations.append(loc)
    return SovParse(m.layout_id, m.fingerprint, m.status, method, locations, declared_total, headers)


def save_learned_mapping(db: Session, headers: list[str], mappings: list[dict], broker_hint: str) -> SovMapping:
    fp = fingerprint(headers)
    existing = db.scalar(select(SovMapping).where(SovMapping.fingerprint == fp))
    if existing:
        return existing
    mp = {norm_header(x["header"]): {"field": x["field"], "unit_multiplier": int(x.get("unit_multiplier", 1)),
                                     "confidence": x.get("confidence")} for x in mappings}
    m = SovMapping(layout_id=f"LEARNED-{fp[:8]}", fingerprint=fp, broker_hint=broker_hint, headers=headers,
                   mapping=mp, status="proposed", source="llm")
    db.add(m)
    db.flush()
    return m
