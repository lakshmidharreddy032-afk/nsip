"""Deterministic occupancy taxonomy. Most specific keywords first. Hazard 'prohibited' = prohibited trade."""
from __future__ import annotations

import re

OCCUPANCIES: list[tuple[str, str, list[str]]] = [
    ("FIREWORKS", "prohibited", ["fireworks", "firecracker", "explosive", "pyrotechnic"]),
    ("LPG_BOTTLING", "prohibited", ["lpg", "gas bottling", "gas cylinder"]),
    ("CHEMICAL_HAZ", "prohibited", ["hazardous chemical", "chemical manufactur", "solvent", "petrochemical",
                                    "acid manufactur"]),
    ("FOAM_MFG", "prohibited", ["foam", "polyurethane"]),
    ("PAINT_MFG", "prohibited", ["paint", "varnish", "lacquer"]),
    ("COTTON_GINNING", "prohibited", ["cotton ginning", "ginning"]),
    ("MINING", "prohibited", ["mining", "quarry"]),
    ("COLD_STORAGE", "high", ["cold storage", "cold chain", "ammonia"]),
    ("PHARMA_MFG", "high", ["pharmaceutical", "pharma", "formulation"]),
    ("PLASTICS_MFG", "high", ["plastic", "polymer", "moulding", "molding"]),
    ("PAPER_MILL", "high", ["paper mill", "paper product", "corrugated"]),
    ("FURNITURE_MFG", "high", ["furniture", "sawmill", "timber", "wood work"]),
    ("AUTO_SHOWROOM", "low", ["car showroom", "automobile showroom", "auto dealership", "two-wheeler showroom"]),
    ("HOTEL", "medium", ["hotel", "resort", "lodging"]),
    ("RESTAURANT", "medium", ["restaurant", "cafe", "banquet", "food court"]),
    ("HOSPITAL", "medium", ["hospital", "clinic", "nursing home", "diagnostic"]),
    ("SCHOOL", "low", ["school", "college", "educational"]),
    ("FOOD_PROCESSING", "medium", ["food processing", "bakery", "dairy", "spice", "rice mill", "flour mill"]),
    ("TEXTILE_MFG", "medium", ["textile", "garment", "weaving", "spinning", "apparel"]),
    ("ELECTRONICS_ASSEMBLY", "medium", ["electronics", "pcb", "electrical assembly"]),
    ("ENGINEERING_WORKSHOP", "medium", ["engineering", "fabrication", "machining", "auto component", "auto part",
                                        "forging"]),
    ("PRINTING_PRESS", "medium", ["printing"]),
    ("WAREHOUSE_GENERAL", "medium", ["warehouse", "godown", "logistics"]),
    ("RETAIL_SHOP", "low", ["retail", "showroom", "shop", "supermarket", "store"]),
    ("OFFICE", "low", ["office", "it services", "software", "consultancy", "bpo"]),
]
HAZARD_BY_CODE = {c: h for c, h, _ in OCCUPANCIES}


def classify_occupancy(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    low = re.sub(r"\s+", " ", text.lower())
    for code, hazard, keys in OCCUPANCIES:
        if any(k in low for k in keys):
            return code, hazard
    return None, None
