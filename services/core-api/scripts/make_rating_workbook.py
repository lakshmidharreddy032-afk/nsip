"""Builds the sample actuarial property rating workbook (filed sample for the pilot).

Sheets: Inputs (written by the adapter), Rates (filed tables), Calc (formulas), Output (premium).
No macros and no external links, so it can run in the sandboxed pycel calc service.
"""
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).resolve().parents[1] / "app" / "adapters" / "rating_models" / "property_rating_v2026_1.xlsx"


def build(path: Path = OUT) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Inputs"
    for r, (label, val) in enumerate([("Sum insured", 250000000), ("Hazard class", "medium"),
                                      ("Construction", "rcc"), ("Cat zone", "medium"), ("Claims 3y", 0),
                                      ("Deductible", 100000)], start=2):
        ws.cell(r, 1, label)
        ws.cell(r, 2, val)
    rates = wb.create_sheet("Rates")
    rates["A1"], rates["B1"] = "Hazard", "Per mille"
    for i, (k, v) in enumerate([("low", 0.38), ("medium", 0.62), ("high", 1.05)], start=2):
        rates.cell(i, 1, k)
        rates.cell(i, 2, v)
    rates["D1"], rates["E1"] = "Construction", "Factor"
    for i, (k, v) in enumerate([("rcc", 1.0), ("steel", 1.06), ("masonry", 1.18), ("kutcha", 1.7)], start=2):
        rates.cell(i, 4, k)
        rates.cell(i, 5, v)
    rates["G1"], rates["H1"] = "Cat zone", "Factor"
    for i, (k, v) in enumerate([("low", 1.0), ("medium", 1.1), ("high", 1.25), ("very_high", 1.45)], start=2):
        rates.cell(i, 7, k)
        rates.cell(i, 8, v)
    calc = wb.create_sheet("Calc")
    formulas = [
        ("Base rate", "=VLOOKUP(Inputs!B3,Rates!A2:B4,2,FALSE)"),
        ("Construction factor", "=VLOOKUP(Inputs!B4,Rates!D2:E5,2,FALSE)"),
        ("Cat factor", "=VLOOKUP(Inputs!B5,Rates!G2:H5,2,FALSE)"),
        ("Claims factor", "=1+0.12*MIN(Inputs!B6,5)"),
        ("Deductible factor", "=IF(Inputs!B7>=500000,0.9,IF(Inputs!B7>=100000,0.95,1))"),
        ("Technical premium", "=ROUND(Inputs!B2*B2/1000*B3*B4*B5*B6,0)"),
        ("Minimum premium", "=MAX(B7,25000)"),
    ]
    for r, (label, f) in enumerate(formulas, start=2):
        calc.cell(r, 1, label)
        calc.cell(r, 2, f)
    out = wb.create_sheet("Output")
    out["A2"], out["B2"] = "Premium (excl. GST)", "=Calc!B8"
    out["A4"], out["B4"] = "Table version", "NSG-PROP-2026.1"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


if __name__ == "__main__":
    print(build())
