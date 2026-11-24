"""Licensed enrichment (geocode + cat model): cached by normalised address, daily budget capped,
and only invoked after triage passes (never for declined or duplicate submissions).
"""
from __future__ import annotations

from datetime import datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.data import centroid, geohash
from app.adapters.registry import Adapters
from app.core.config import get_settings
from app.domain.extraction.normalise import normalise_address, normalise_construction
from app.models import EnrichmentCache, IntegrationConfig, RiskLocation, Submission, ThirdPartyCall, utcnow

DEFAULT_BUDGETS = {"geocoding_daily_calls": 3000, "cat_model_daily_calls": 1500, "monthly_budget_inr": 250000}


def budgets(db: Session) -> dict:
    row = db.scalar(select(IntegrationConfig).where(IntegrationConfig.key == "budgets"))
    return {**DEFAULT_BUDGETS, **(row.config if row else {})}


def _calls_today(db: Session, provider: str) -> int:
    start = datetime.combine(utcnow().date(), time.min)
    return db.scalar(select(func.count()).select_from(ThirdPartyCall).where(
        ThirdPartyCall.provider == provider, ThirdPartyCall.cache_hit.is_(False), ThirdPartyCall.status == "ok",
        ThirdPartyCall.created_at >= start)) or 0


def _cached(db: Session, provider: str, key: str) -> dict | None:
    row = db.scalar(select(EnrichmentCache).where(EnrichmentCache.provider == provider, EnrichmentCache.key == key))
    return row.payload if row else None


def enrich(db: Session, adapters: Adapters, sub: Submission) -> dict:
    if sub.triage_outcome == "out_of_appetite" or sub.duplicate_of_id:
        return {"skipped": True}
    s = get_settings()
    b = budgets(db)
    stats = {"geocode_calls": 0, "geocode_cache_hits": 0, "cat_calls": 0, "cat_cache_hits": 0, "budget_blocked": 0}
    for loc in db.scalars(select(RiskLocation).where(RiskLocation.submission_id == sub.id)):
        key = f"{normalise_address(loc.address)}|{loc.pincode}"
        geo = _cached(db, "geocoding", key)
        if geo:
            stats["geocode_cache_hits"] += 1
            db.add(ThirdPartyCall(provider="geocoding", submission_id=sub.id, request_key=key[:200], cache_hit=True))
        elif _calls_today(db, "geocoding") >= b["geocoding_daily_calls"]:
            stats["budget_blocked"] += 1
            db.add(ThirdPartyCall(provider="geocoding", submission_id=sub.id, request_key=key[:200],
                                  status="budget_exceeded"))
            c = centroid(loc.pincode)
            geo = {"lat": c[0], "lon": c[1], "precision": "pincode"} if c else None
        else:
            res = adapters.geocoder.geocode(loc.address, loc.pincode)  # type: ignore[attr-defined]
            stats["geocode_calls"] += 1
            db.add(ThirdPartyCall(provider="geocoding", submission_id=sub.id, request_key=key[:200],
                                  cost_inr=s.geocode_cost_inr))
            if res:
                geo = {"lat": res.lat, "lon": res.lon, "precision": res.precision}
                db.add(EnrichmentCache(provider="geocoding", key=key, payload=geo))
                db.flush()
        if not geo:
            continue
        loc.lat, loc.lon = geo["lat"], geo["lon"]
        loc.geohash = geohash(geo["lat"], geo["lon"], 7)
        cons = normalise_construction(loc.construction) or "unknown"
        cat_key = f"{loc.geohash}|{cons}"
        cat = _cached(db, "cat_model", cat_key)
        if cat:
            stats["cat_cache_hits"] += 1
            db.add(ThirdPartyCall(provider="cat_model", submission_id=sub.id, request_key=cat_key, cache_hit=True))
        elif _calls_today(db, "cat_model") >= b["cat_model_daily_calls"]:
            stats["budget_blocked"] += 1
            db.add(ThirdPartyCall(provider="cat_model", submission_id=sub.id, request_key=cat_key,
                                  status="budget_exceeded"))
        else:
            cat = adapters.cat_model.score(geo["lat"], geo["lon"], cons, loc.occupancy_code)  # type: ignore[attr-defined]
            stats["cat_calls"] += 1
            db.add(ThirdPartyCall(provider="cat_model", submission_id=sub.id, request_key=cat_key,
                                  cost_inr=s.cat_model_cost_inr))
            db.add(EnrichmentCache(provider="cat_model", key=cat_key, payload=cat))
            db.flush()
        if cat:
            loc.cat_zone, loc.cat_score = cat["zone"], cat["score"]
    db.flush()
    return stats
