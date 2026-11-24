"""Validation layer: types, ranges and cross-field checks (SOV reconciliation, dates, pincodes)."""
from __future__ import annotations

from datetime import date, timedelta

from app.domain.extraction.normalise import parse_date, pincode_valid

RECON_TOLERANCE = 0.005  # 0.5%
LOW_CONFIDENCE = 0.85


def validate(fields: dict[str, dict], received: date) -> dict[str, list[str]]:
    """`fields` maps path -> {"value": ...}. Returns path -> list of error messages."""
    errs: dict[str, list[str]] = {}

    def add(path: str, msg: str) -> None:
        errs.setdefault(path, []).append(msg)

    def val(path: str):
        f = fields.get(path)
        return f["value"] if f else None

    si = val("cover.sum_insured")
    if si is None:
        add("cover.sum_insured", "Sum insured is required.")
    elif not isinstance(si, int) or si <= 0:
        add("cover.sum_insured", "Sum insured must be a positive amount.")
    for path, f in fields.items():
        v = f["value"]
        if path.endswith(".pincode") and v not in (None, "") and not pincode_valid(v):
            add(path, "Pincode is not a valid Indian pincode in the reference set.")
        if path.endswith(".year_built") and v not in (None, ""):
            if not isinstance(v, int) or v < 1850 or v > received.year:
                add(path, f"Year built must be between 1850 and {received.year}.")
        if path.startswith("locations[") and path.split(".")[-1] in ("building", "plant_machinery", "stock",
                                                                     "contents", "other", "total"):
            if v is not None and (not isinstance(v, int) or v < 0):
                add(path, "Amount must be a non-negative number.")
        if path.startswith("loss_history[") and path.endswith(".year") and isinstance(v, int) and v > received.year:
            add(path, "Loss year cannot be in the future.")
    inc = parse_date(val("cover.inception_date"))
    if val("cover.inception_date") and inc is None:
        add("cover.inception_date", "Inception date is not a recognised date.")
    elif inc and not (received - timedelta(days=30) <= inc <= received + timedelta(days=365)):
        add("cover.inception_date", "Inception date should be within 30 days before to 12 months after receipt.")
    # per-location component sums
    loc_idx = sorted({int(p.split("]")[0].split("[")[1]) for p in fields if p.startswith("locations[")})
    sov_total = 0
    for i in loc_idx:
        comps = [val(f"locations[{i}].sov.{c}") for c in ("building", "plant_machinery", "stock", "contents", "other")]
        comp_sum = sum(c for c in comps if isinstance(c, int))
        row_total = val(f"locations[{i}].sov.total")
        if isinstance(row_total, int) and comp_sum and abs(row_total - comp_sum) > max(1, row_total * RECON_TOLERANCE):
            add(f"locations[{i}].sov.total",
                f"Row total {row_total:,} does not equal the sum of its components {comp_sum:,}.")
        sov_total += row_total if isinstance(row_total, int) else comp_sum
    if loc_idx and isinstance(si, int) and si > 0:
        if abs(sov_total - si) > si * RECON_TOLERANCE:
            msg = f"SOV total {sov_total:,} does not reconcile to declared sum insured {si:,}."
            add("sov.total", msg)
            add("cover.sum_insured", msg)
    cc = val("loss.claims_count_3y")
    years = [val(p) for p in fields if p.startswith("loss_history[") and p.endswith(".year")]
    recent = [y for y in years if isinstance(y, int) and y >= received.year - 3]
    if isinstance(cc, int) and years and cc != len(recent):
        add("loss.claims_count_3y", f"Declared claim count {cc} differs from {len(recent)} loss-history rows.")
    return errs


def status_for(confidence: float, errors: list[str]) -> str:
    if errors:
        return "invalid"
    if confidence < LOW_CONFIDENCE:
        return "low_confidence"
    return "ok"
