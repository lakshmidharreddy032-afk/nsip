"""Rating adapters. Premiums come only from filed sources (IRDAI file-and-use):

* Package products: the filed rating API (live client + mock implementing the same filed tables).
* Larger property risks: the actuarial Excel workbook, evaluated in a controlled calc service
  (pycel, no macros, no external links). The workbook SHA-256 must be on the filed allow-list.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Protocol

import httpx

BUNDLED_WORKBOOK = Path(__file__).parent / "rating_models" / "property_rating_v2026_1.xlsx"


class RatingError(Exception):
    pass


@dataclass
class RatingRequest:
    line: str
    sum_insured: int
    hazard_class: str  # low | medium | high
    construction: str  # rcc | steel | masonry | kutcha
    cat_zone: str  # low | medium | high | very_high
    claims_count_3y: int
    deductible: int
    occupancy_code: str = ""

    def canonical(self) -> dict:
        return {"line": self.line, "sum_insured": self.sum_insured, "hazard_class": self.hazard_class,
                "construction": self.construction, "cat_zone": self.cat_zone,
                "claims_count_3y": self.claims_count_3y, "deductible": self.deductible,
                "occupancy_code": self.occupancy_code}

    def inputs_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.canonical(), sort_keys=True).encode()).hexdigest()


@dataclass
class RatingResult:
    source: str
    source_version: str
    filing_ref: str
    premium: Decimal
    breakdown: dict = field(default_factory=dict)
    workbook_hash: str | None = None


class RatingAdapter(Protocol):
    source: str

    def rate(self, req: RatingRequest) -> RatingResult: ...


# Filed package tables (sample filing used for the pilot; replace via filed-table release process).
PKG_VERSION = "NSG-PKG-2026.1"
PKG_FILING = "SAMPLE-FILING-PKG-2026-01"
PKG_BASE_PER_MILLE = {"low": Decimal("0.45"), "medium": Decimal("0.75"), "high": Decimal("1.20")}
PKG_CONSTRUCTION = {"rcc": Decimal("1.00"), "steel": Decimal("1.05"), "masonry": Decimal("1.15"),
                    "kutcha": Decimal("1.60")}
PKG_CAT = {"low": Decimal("1.00"), "medium": Decimal("1.08"), "high": Decimal("1.20"), "very_high": Decimal("1.40")}
PKG_MIN_PREMIUM = Decimal("7500")


def _round(d: Decimal) -> Decimal:
    return d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


class MockPackageRatingApi:
    """Implements the filed package tables exactly as the live rating API does (contract-tested)."""

    source = "rating_api"

    def rate(self, req: RatingRequest) -> RatingResult:
        try:
            base = PKG_BASE_PER_MILLE[req.hazard_class]
            cons = PKG_CONSTRUCTION[req.construction]
            cat = PKG_CAT[req.cat_zone]
        except KeyError as e:
            raise RatingError(f"input outside filed table: {e}") from e
        claims = Decimal("1") + Decimal("0.10") * min(req.claims_count_3y, 5)
        ded = Decimal("0.92") if req.deductible >= 500000 else Decimal("0.96") if req.deductible >= 100000 else Decimal("1")
        premium = _round(Decimal(req.sum_insured) * base / Decimal(1000) * cons * cat * claims * ded)
        premium = max(premium, PKG_MIN_PREMIUM)
        return RatingResult(self.source, PKG_VERSION, PKG_FILING, premium, {
            "base_rate_per_mille": str(base), "construction_factor": str(cons), "cat_factor": str(cat),
            "claims_factor": str(claims), "deductible_factor": str(ded), "minimum_premium": str(PKG_MIN_PREMIUM),
            "gst_18pct": str(_round(premium * Decimal("0.18")))})


class LivePackageRatingApi:  # pragma: no cover
    source = "rating_api"

    def __init__(self, url: str) -> None:
        self.url = url

    def rate(self, req: RatingRequest) -> RatingResult:
        r = httpx.post(f"{self.url}/v1/rate", json=req.canonical(), timeout=15)
        r.raise_for_status()
        d = r.json()
        return RatingResult(self.source, d["table_version"], d["filing_ref"], Decimal(str(d["premium"])),
                            d.get("breakdown", {}))


def workbook_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExcelModelRatingAdapter:
    """Evaluates the filed actuarial workbook with pycel. Inputs written to `Inputs`, result read from `Output`."""

    source = "excel_model"
    INPUT_CELLS = {"sum_insured": "Inputs!B2", "hazard_class": "Inputs!B3", "construction": "Inputs!B4",
                   "cat_zone": "Inputs!B5", "claims_count_3y": "Inputs!B6", "deductible": "Inputs!B7"}

    def __init__(self, path: Path | None, allow_list: dict[str, dict]) -> None:
        self.path = path or BUNDLED_WORKBOOK
        self.allow_list = allow_list

    def rate(self, req: RatingRequest) -> RatingResult:
        from app.adapters.excel_calc import CalcError, Workbook

        if not self.path.exists():
            raise RatingError("rating workbook not available")
        data = self.path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        filed = self.allow_list.get(digest)
        if not filed:
            raise RatingError("workbook hash is not on the filed allow-list; refusing to rate")
        try:
            xl = Workbook(data)
            for k, cell in self.INPUT_CELLS.items():
                xl.set(cell, getattr(req, k))
            premium = xl.get("Output!B2")
        except CalcError as e:
            raise RatingError(f"workbook evaluation failed: {e}") from e
        if premium is None or isinstance(premium, str):
            raise RatingError(f"workbook returned no premium: {premium!r}")
        breakdown = {name: xl.get(f"Calc!B{row}") for row, name in
                     [(2, "base_rate_per_mille"), (3, "construction_factor"), (4, "cat_factor"),
                      (5, "claims_factor"), (6, "deductible_factor"), (8, "minimum_premium_applied")]}
        prem = _round(Decimal(str(premium)))
        out = {k: str(v) for k, v in breakdown.items()} | {"gst_18pct": str(_round(prem * Decimal("0.18")))}
        return RatingResult(self.source, filed["version"], filed["filing_ref"], prem, out, digest)
