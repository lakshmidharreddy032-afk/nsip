"""JSON-schema-constrained outputs for every prompt. Model output is rejected if it fails validation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClassifyEmailOut(_Strict):
    category: Literal["new_submission", "updated_schedule", "query", "noise"]
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list, max_length=5)


class FactValue(_Strict):
    value: str | int | float | None
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(default="", max_length=300)
    line: int | None = None


class KeyFactsOut(_Strict):
    insured_name: FactValue | None = None
    risk_address: FactValue | None = None
    pincode: FactValue | None = None
    occupancy: FactValue | None = None
    construction: FactValue | None = None
    year_built: FactValue | None = None
    sum_insured: FactValue | None = None
    coverage: FactValue | None = None
    deductible: FactValue | None = None
    inception_date: FactValue | None = None
    claims_count_3y: FactValue | None = None
    claims_amount_3y: FactValue | None = None


class HeaderMapping(_Strict):
    header: str
    field: Literal["loc_no", "address", "city", "pincode", "occupancy", "construction", "year_built",
                   "building", "plant_machinery", "stock", "contents", "other", "total", "ignore"]
    unit_multiplier: int = 1
    confidence: float = Field(ge=0, le=1)


class SovHeaderMapOut(_Strict):
    mappings: list[HeaderMapping]


class AppetiteSignalsOut(_Strict):
    occupancy_code_suggestion: str | None = None
    hazard_notes: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(default="", max_length=1200)
    suggested_outcome: Literal["in_appetite", "out_of_appetite", "refer_risk_engineering", "needs_info"] | None = None


class DeclineLetterOut(_Strict):
    subject: str = Field(max_length=200)
    body: str = Field(max_length=4000)


OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "classify_email": ClassifyEmailOut,
    "extract_key_facts": KeyFactsOut,
    "map_sov_headers": SovHeaderMapOut,
    "appetite_signals": AppetiteSignalsOut,
    "decline_letter": DeclineLetterOut,
}
