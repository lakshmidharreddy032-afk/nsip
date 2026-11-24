"""Extraction pipeline: deterministic first, LLM only where needed; every field carries value,
confidence, source reference, method and model/prompt versions, then passes validation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.adapters.data import lookup
from app.adapters.enrichment import offline_zone
from app.ai.gateway import GatewayError
from app.ai.tasks import AITasks
from app.domain.appetite.occupancy import HAZARD_BY_CODE, classify_occupancy
from app.domain.extraction import sov as sovmod
from app.domain.extraction.documents import ParsedDocument
from app.domain.extraction.normalise import (
    normalise_construction,
    parse_amount,
    parse_date,
    parse_int,
    parse_year,
    pincode_valid,
)
from app.domain.extraction.proposal import parse_key_values, parse_loss_history

CRITICAL_SUFFIXES = (".address", ".occupancy", "cover.sum_insured", "sov.total")
LABELS = {
    "insured.name": "Insured name", "risk.address": "Risk address", "risk.pincode": "Pincode",
    "risk.occupancy": "Occupancy", "risk.construction": "Construction", "risk.year_built": "Year built",
    "risk.protections": "Fire protection", "cover.sum_insured": "Declared sum insured",
    "cover.coverage": "Coverage requested", "cover.deductible": "Deductible", "cover.inception_date": "Inception date",
    "loss.claims_count_3y": "Claims (3 yrs)", "loss.claims_amount_3y": "Claims amount (3 yrs)",
    "broker.name": "Broker", "broker.email": "Broker email", "sov.total": "SOV total",
}
FACT_TO_PATH = {
    "insured_name": "insured.name", "risk_address": "risk.address", "pincode": "risk.pincode",
    "occupancy": "risk.occupancy", "construction": "risk.construction", "year_built": "risk.year_built",
    "protections": "risk.protections", "sum_insured": "cover.sum_insured", "coverage": "cover.coverage",
    "deductible": "cover.deductible", "inception_date": "cover.inception_date",
    "claims_count_3y": "loss.claims_count_3y", "claims_amount_3y": "loss.claims_amount_3y",
}
KEY_FACTS_REQUIRED = ("insured_name", "risk_address", "pincode", "occupancy", "sum_insured")
HAZARD_RANK = {None: 0, "low": 1, "medium": 2, "high": 3, "prohibited": 4}
CONSTRUCTION_RANK = {None: 0, "rcc": 1, "steel": 2, "masonry": 3, "kutcha": 4}
ZONE_RANK = {None: 0, "low": 1, "medium": 2, "high": 3, "very_high": 4}


@dataclass
class Candidate:
    path: str
    value: object
    confidence: float
    source_ref: dict
    method: str
    prompt_version: str | None = None
    model_version: str | None = None

    @property
    def critical(self) -> bool:
        return self.path.endswith(CRITICAL_SUFFIXES)


@dataclass
class ExtractionResult:
    fields: dict[str, Candidate] = field(default_factory=dict)
    sov_layouts: list[dict] = field(default_factory=list)
    learned_mappings: list[str] = field(default_factory=list)
    ocr_pages: int = 0
    notes: list[str] = field(default_factory=list)

    def values(self) -> dict[str, object]:
        return {p: c.value for p, c in self.fields.items()}

    def put(self, c: Candidate) -> None:
        self.fields[c.path] = c


def _coerce(fact: str, raw):
    if fact in ("sum_insured", "claims_amount_3y", "deductible"):
        return parse_amount(raw)
    if fact == "year_built":
        return parse_year(raw)
    if fact == "claims_count_3y":
        return parse_int(raw)
    if fact == "pincode":
        digits = re.sub(r"\D", "", str(raw or ""))
        return digits[:6] or None
    if fact == "inception_date":
        d = parse_date(raw)
        return d.isoformat() if d else str(raw)
    return str(raw).strip() if raw is not None else None


def key_facts(docs: list[ParsedDocument], ai: AITasks | None, submission_id, body_text: str,
              result: ExtractionResult | None = None) -> ExtractionResult:
    """Stage A (pre-triage, cheap): labelled facts from the body and text documents; LLM only for gaps."""
    res = result or ExtractionResult()
    for doc in docs:
        if doc.kind not in ("email_body", "pdf_text", "spreadsheet", "text"):
            continue
        for fact, fv in parse_key_values(doc).items():
            path = FACT_TO_PATH.get(fact)
            if path and path not in res.fields:
                res.put(Candidate(path, _coerce(fact, fv.value), fv.confidence, fv.ref, fv.method))
    missing = [f for f in KEY_FACTS_REQUIRED if FACT_TO_PATH[f] not in res.fields]
    if missing and ai is not None:
        try:
            out, pver, model = ai.key_facts(body_text, submission_id)
        except GatewayError:
            res.notes.append("AI gateway unavailable for key facts; manual completion required.")
            return res
        for fact, fv in out.model_dump().items():
            path = FACT_TO_PATH.get(fact)
            if not fv or not path or path in res.fields or fv.get("value") in (None, ""):
                continue
            res.put(Candidate(path, _coerce(fact, fv["value"]), min(float(fv["confidence"]), 0.9),
                              {"file": "email body", "attachment_id": "body", "line": fv.get("line"),
                               "text": (fv.get("evidence") or "")[:120]}, "llm", pver, model))
    return res


def _sov_from_doc(db: Session, doc: ParsedDocument, ai: AITasks | None, submission_id,
                  broker_hint: str, res: ExtractionResult) -> sovmod.SovParse | None:
    for table in doc.tables:
        if sovmod.find_header_row(table) is None:
            continue
        try:
            return sovmod.parse_table(db, table)
        except sovmod.UnknownLayout as e:
            if ai is None:
                res.notes.append(f"Unknown SOV layout in {doc.filename}; manual mapping required.")
                return None
            try:
                out, pver, model = ai.map_sov_headers(e.headers, e.samples, submission_id)
            except GatewayError:
                res.notes.append(f"Unknown SOV layout in {doc.filename}; AI gateway unavailable.")
                return None
            m = sovmod.save_learned_mapping(db, e.headers, [x.model_dump() for x in out.mappings], broker_hint)
            res.learned_mappings.append(m.layout_id)
            parsed = sovmod.parse_table(db, table)
            parsed.prompt_version, parsed.model_version = pver, model
            return parsed
        except ValueError:
            continue
    return None


def full_extraction(db: Session, docs: list[ParsedDocument], ai: AITasks | None, submission_id,
                    broker_hint: str, res: ExtractionResult) -> ExtractionResult:
    """Stage B (post-triage): SOV per location, loss history; OCR/LLM costs incurred only here."""
    loc_i = 0
    for doc in docs:
        res.ocr_pages += doc.ocr_cost_units
        parsed = _sov_from_doc(db, doc, ai, submission_id, broker_hint, res)
        if not parsed:
            continue
        res.sov_layouts.append({"file": doc.filename, "layout_id": parsed.layout_id, "method": parsed.method,
                                "mapping_status": parsed.mapping_status})
        for loc in parsed.locations:
            for f, fv in loc.fields.items():
                if f == "loc_no":
                    continue
                path = f"locations[{loc_i}].sov.{f}" if f in (*sovmod.MONEY_FIELDS, "total") else f"locations[{loc_i}].{f}"
                res.put(Candidate(path, fv.value, fv.confidence, fv.ref, fv.method if doc.ocr_engine is None else "ocr",
                                  parsed.prompt_version, parsed.model_version))
            comps = [loc.fields[c].value for c in sovmod.MONEY_FIELDS if c in loc.fields]
            if f"locations[{loc_i}].sov.total" not in res.fields:
                total = sum(c for c in comps if isinstance(c, int))
                first = next(iter(loc.fields.values()))
                res.put(Candidate(f"locations[{loc_i}].sov.total", total, first.confidence, first.ref, "derived"))
            loc_i += 1
        if parsed.declared_total:
            res.notes.append(f"SOV footer total {parsed.declared_total.value:,} in {doc.filename}.")
    if loc_i == 0:
        # single-location risk without an SOV: location 1 mirrors the proposal facts
        for src, dst in (("risk.address", "address"), ("risk.pincode", "pincode"), ("risk.occupancy", "occupancy"),
                         ("risk.construction", "construction"), ("risk.year_built", "year_built")):
            c = res.fields.get(src)
            if c:
                res.put(Candidate(f"locations[0].{dst}", c.value, c.confidence, c.source_ref, "derived"))
        si = res.fields.get("cover.sum_insured")
        if si:
            res.put(Candidate("locations[0].sov.total", si.value, si.confidence, si.source_ref, "derived"))
        loc_i = 1
    # location city from pincode reference when not supplied
    for i in range(loc_i):
        pin = res.fields.get(f"locations[{i}].pincode")
        if pin and f"locations[{i}].city" not in res.fields and lookup(str(pin.value)):
            res.put(Candidate(f"locations[{i}].city", lookup(str(pin.value))[0], 0.99,  # type: ignore[index]
                              {"reference": "pincode-directory"}, "derived"))
    totals = [res.fields[p].value for p in res.fields if p.endswith(".sov.total") and p.startswith("locations[")]
    first_total = next((res.fields[p] for p in res.fields if p.endswith(".sov.total")), None)
    res.put(Candidate("sov.total", sum(t for t in totals if isinstance(t, int)),
                      min((res.fields[p].confidence for p in res.fields if p.endswith(".sov.total")), default=0.9),
                      first_total.source_ref if first_total else {}, "derived"))
    loss_i = 0
    for doc in docs:
        for row in parse_loss_history(doc):
            for k, fv in row.items():
                res.put(Candidate(f"loss_history[{loss_i}].{k}", fv.value, fv.confidence, fv.ref, fv.method))
            loss_i += 1
    return res


def location_indices(values: dict) -> list[int]:
    return sorted({int(p.split("]")[0].split("[")[1]) for p in values if p.startswith("locations[")})


def build_features(values: dict, region: str) -> dict:
    """Deterministic features for clearance and triage. Only validated, code-derived values."""
    locs = location_indices(values)
    occ_texts = [values.get("risk.occupancy")] + [values.get(f"locations[{i}].occupancy") for i in locs]
    best_code, best_haz = None, None
    for t in occ_texts:
        code, haz = classify_occupancy(t if isinstance(t, str) else None)
        if code and HAZARD_RANK[haz] > HAZARD_RANK[best_haz]:
            best_code, best_haz = code, haz
    cons = [normalise_construction(values.get("risk.construction"))] + [
        normalise_construction(values.get(f"locations[{i}].construction")) for i in locs]
    worst_cons = max(cons, key=lambda c: CONSTRUCTION_RANK[c]) if cons else None
    years = [y for y in [values.get("risk.year_built")] + [values.get(f"locations[{i}].year_built") for i in locs]
             if isinstance(y, int)]
    pins = [p for p in [values.get("risk.pincode")] + [values.get(f"locations[{i}].pincode") for i in locs] if p]
    zones = [offline_zone(str(p)) for p in pins]
    worst_zone = max(zones, key=lambda z: ZONE_RANK[z]) if zones else None
    si = values.get("cover.sum_insured")
    if not isinstance(si, int) or si <= 0:
        sov_total = values.get("sov.total")
        si = sov_total if isinstance(sov_total, int) and sov_total > 0 else None
    claims_amt = values.get("loss.claims_amount_3y")
    claims_cnt = values.get("loss.claims_count_3y")
    primary_pin = str(values.get("risk.pincode") or (pins[0] if pins else "") or "") or None
    return {
        "occupancy_code": best_code,
        "occupancy_hazard": best_haz,
        "sum_insured": si,
        "construction": worst_cons,
        "year_built": min(years) if years else None,
        "pincode": primary_pin,
        "pincode_valid": pincode_valid(primary_pin) if primary_pin else False,
        "cat_zone": worst_zone,
        "claims_count_3y": claims_cnt if isinstance(claims_cnt, int) else 0,
        "claims_amount_3y": claims_amt if isinstance(claims_amt, int) else 0,
        "claims_ratio_3y": round(claims_amt / si, 4) if isinstance(claims_amt, int) and si else 0.0,
        "region": region,
        "locations": max(len(locs), 1),
        "hazard_known": best_code is not None and best_code in HAZARD_BY_CODE,
    }


def received_date(dt) -> date:
    return dt.date() if hasattr(dt, "date") else dt
