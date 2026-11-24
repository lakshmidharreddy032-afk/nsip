"""Licensed per-call geocoding and catastrophe-model adapters (mock + live client)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.adapters.data import centroid, lookup

CAT_BASE = {"low": 0.15, "medium": 0.35, "high": 0.6, "very_high": 0.85}


@dataclass
class GeoResult:
    lat: float
    lon: float
    precision: str  # rooftop | street | pincode
    provider: str


class GeocodingAdapter(Protocol):
    def geocode(self, address: str, pincode: str) -> GeoResult | None: ...


class CatModelAdapter(Protocol):
    def score(self, lat: float, lon: float, construction: str, occupancy_code: str | None) -> dict: ...


class MockGeocoder:
    def geocode(self, address: str, pincode: str) -> GeoResult | None:
        c = centroid(pincode)
        if not c:
            return None
        h = int(hashlib.sha256(address.lower().encode()).hexdigest()[:6], 16)
        return GeoResult(round(c[0] + (h % 100) * 0.0002, 6), round(c[1] + (h // 100 % 100) * 0.0002, 6),
                         "street", "mock-geo")


class MockCatModel:
    def score(self, lat: float, lon: float, construction: str, occupancy_code: str | None) -> dict:
        zone = "low"
        best = 1e9
        from app.adapters.data import PINCODE_PREFIXES

        for _, (_, _, clat, clon, z) in PINCODE_PREFIXES.items():
            d = (clat - lat) ** 2 + (clon - lon) ** 2
            if d < best:
                best, zone = d, z
        base = CAT_BASE[zone]
        factor = {"rcc": 0.85, "steel": 0.95, "masonry": 1.1, "kutcha": 1.4}.get(construction, 1.0)
        return {"zone": zone, "score": round(min(base * factor, 1.0), 3),
                "perils": {"flood": round(base * 0.9, 2), "cyclone": round(base * 0.7, 2),
                           "earthquake": round(base * 0.6, 2)}, "model": "mock-cat-2026.1"}


class LiveGeocoder:  # pragma: no cover
    def __init__(self, url: str, api_key: str) -> None:
        self.url, self.api_key = url, api_key

    def geocode(self, address: str, pincode: str) -> GeoResult | None:
        r = httpx.get(self.url, params={"q": f"{address} {pincode} India"},
                      headers={"X-Api-Key": self.api_key}, timeout=10)
        r.raise_for_status()
        d = r.json()
        return GeoResult(d["lat"], d["lon"], d.get("precision", "street"), "live")


def offline_zone(pincode: str | None) -> str | None:
    ref = lookup(pincode)
    return ref[4] if ref else None
