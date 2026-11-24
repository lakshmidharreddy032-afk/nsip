"""Offline reference data (free, no per-call licence): pincode prefix centroids and cat zones.

Used for validation, region checks, clearance blocking and triage. Licensed geocoding and cat
model calls happen only after triage passes (see domain/submissions/enrichment.py).
"""
from __future__ import annotations

# prefix: (city, state, lat, lon, cat_zone)
PINCODE_PREFIXES: dict[str, tuple[str, str, float, float, str]] = {
    "110": ("New Delhi", "Delhi", 28.61, 77.21, "medium"),
    "122": ("Gurugram", "Haryana", 28.46, 77.03, "medium"),
    "141": ("Ludhiana", "Punjab", 30.90, 75.85, "low"),
    "160": ("Chandigarh", "Chandigarh", 30.73, 76.78, "low"),
    "201": ("Noida", "Uttar Pradesh", 28.54, 77.39, "medium"),
    "226": ("Lucknow", "Uttar Pradesh", 26.85, 80.95, "low"),
    "302": ("Jaipur", "Rajasthan", 26.91, 75.79, "low"),
    "370": ("Bhuj", "Gujarat", 23.24, 69.67, "very_high"),
    "380": ("Ahmedabad", "Gujarat", 23.02, 72.57, "medium"),
    "395": ("Surat", "Gujarat", 21.17, 72.83, "high"),
    "400": ("Mumbai", "Maharashtra", 19.08, 72.88, "high"),
    "411": ("Pune", "Maharashtra", 18.52, 73.86, "low"),
    "421": ("Bhiwandi", "Maharashtra", 19.30, 73.06, "medium"),
    "440": ("Nagpur", "Maharashtra", 21.15, 79.09, "low"),
    "452": ("Indore", "Madhya Pradesh", 22.72, 75.86, "low"),
    "500": ("Hyderabad", "Telangana", 17.39, 78.49, "low"),
    "530": ("Visakhapatnam", "Andhra Pradesh", 17.69, 83.22, "very_high"),
    "560": ("Bengaluru", "Karnataka", 12.97, 77.59, "low"),
    "600": ("Chennai", "Tamil Nadu", 13.08, 80.27, "high"),
    "641": ("Coimbatore", "Tamil Nadu", 11.02, 76.96, "low"),
    "682": ("Kochi", "Kerala", 9.93, 76.27, "high"),
    "700": ("Kolkata", "West Bengal", 22.57, 88.36, "high"),
    "751": ("Bhubaneswar", "Odisha", 20.30, 85.82, "very_high"),
    "781": ("Guwahati", "Assam", 26.14, 91.74, "very_high"),
    "800": ("Patna", "Bihar", 25.59, 85.14, "high"),
}

REGION_BY_FIRST_DIGIT = {"1": "north", "2": "north", "3": "west", "4": "west", "5": "south", "6": "south",
                         "7": "east", "8": "east"}


def lookup(pincode: str | None) -> tuple[str, str, float, float, str] | None:
    if not pincode or len(pincode) != 6 or not pincode.isdigit():
        return None
    return PINCODE_PREFIXES.get(pincode[:3])


def centroid(pincode: str) -> tuple[float, float] | None:
    ref = lookup(pincode)
    if not ref:
        return None
    # deterministic offset by the last three digits keeps distinct pincodes in distinct cells
    tail = int(pincode[3:])
    return ref[2] + (tail % 31) * 0.004, ref[3] + (tail % 17) * 0.004


_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lon: float, precision: int = 6) -> str:
    lat_r, lon_r = [-90.0, 90.0], [-180.0, 180.0]
    out: list[str] = []
    bit, ch, even = 0, 0, True
    while len(out) < precision:
        rng, val = (lon_r, lon) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            ch |= 1 << (4 - bit)
            rng[0] = mid
        else:
            rng[1] = mid
        even = not even
        bit += 1
        if bit == 5:
            out.append(_B32[ch])
            bit, ch = 0, 0
    return "".join(out)
