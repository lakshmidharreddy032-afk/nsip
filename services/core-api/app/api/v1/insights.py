"""Dashboards, audit explorer, current user and the real-time event stream."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import get_adapters
from app.core.db import get_db
from app.core.deps import get_principal, require_roles
from app.core.events import broadcaster
from app.core.security import Principal
from app.domain.analytics import service as analytics
from app.domain.audit import service as audit
from app.domain.authority import service as authority
from app.models import AuditEvent

router = APIRouter(prefix="/api/v1", tags=["insights"])


@router.get("/me")
def me(p: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
    return {"id": str(p.user_id), "email": p.email, "name": p.name, "roles": sorted(p.roles), "region": p.region,
            "mfa": p.mfa, "authority": authority.user_claims(db, p.user_id), "token_authority": list(p.authority)}


@router.get("/dashboards/ops")
def ops(days: int = 30, p: Principal = Depends(require_roles("data_entry", "underwriter", "senior_underwriter", "cuo",
                                                               "admin")), db: Session = Depends(get_db)) -> dict:
    return analytics.ops(db, p, min(days, 365))


@router.get("/dashboards/underwriting")
def uw(days: int = 90, p: Principal = Depends(require_roles("underwriter", "senior_underwriter", "cuo", "admin")),
       db: Session = Depends(get_db)) -> dict:
    return analytics.underwriting(db, p, min(days, 365))


@router.get("/dashboards/cuo")
def cuo(p: Principal = Depends(require_roles("cuo", "admin")), db: Session = Depends(get_db)) -> dict:
    return analytics.cuo(db, get_adapters(), p)


@router.get("/dashboards/distribution")
def distribution(broker_id: uuid.UUID | None = None,
                 p: Principal = Depends(require_roles("distribution", "cuo", "admin")),
                 db: Session = Depends(get_db)) -> dict:
    return analytics.distribution(db, p, broker_id)


# ---------------------------------------------------------------- audit explorer

def _audit_query(entity_id: str | None, entity_type: str | None, action: str | None, actor_id: str | None,
                 since: datetime | None, until: datetime | None, p: Principal):
    q = select(AuditEvent)
    if entity_id:
        q = q.where(AuditEvent.entity_id == entity_id)
    if entity_type:
        q = q.where(AuditEvent.entity_type == entity_type)
    if action:
        q = q.where(AuditEvent.action.like(f"{action}%"))
    if actor_id:
        q = q.where(AuditEvent.actor_id == actor_id)
    if since:
        q = q.where(AuditEvent.ts >= since)
    if until:
        q = q.where(AuditEvent.ts <= until)
    if not p.all_regions:
        q = q.where((AuditEvent.region == p.region) | (AuditEvent.region.is_(None)))
    return q


def _ev(e: AuditEvent) -> dict:
    return {"seq": e.seq, "ts": e.ts.isoformat(), "actor_id": e.actor_id, "actor_type": e.actor_type,
            "action": e.action, "entity_type": e.entity_type, "entity_id": e.entity_id, "region": e.region,
            "data": e.data, "prev_hash": e.prev_hash, "hash": e.hash}


AUDITORS = require_roles("cuo", "admin", "underwriter", "senior_underwriter")


@router.get("/audit")
def audit_events(entity_id: str | None = None, entity_type: str | None = None, action: str | None = None,
                 actor_id: str | None = None, since: datetime | None = None, until: datetime | None = None,
                 limit: int = 200, offset: int = 0, p: Principal = Depends(AUDITORS),
                 db: Session = Depends(get_db)) -> dict:
    q = _audit_query(entity_id, entity_type, action, actor_id, since, until, p)
    rows = list(db.scalars(q.order_by(AuditEvent.seq.desc()).offset(offset).limit(min(limit, 1000))))
    return {"items": [_ev(e) for e in rows], "total": audit.count(db)}


@router.get("/audit/verify")
def audit_verify(_: Principal = Depends(require_roles("cuo", "admin")), db: Session = Depends(get_db)) -> dict:
    return audit.verify_chain(db)


@router.get("/audit/export")
def audit_export(fmt: str = "jsonl", entity_id: str | None = None, entity_type: str | None = None,
                 p: Principal = Depends(require_roles("cuo", "admin")), db: Session = Depends(get_db)):
    rows = [_ev(e) for e in db.scalars(_audit_query(entity_id, entity_type, None, None, None, None, p)
                                       .order_by(AuditEvent.seq))]
    audit.record(db, action="audit.exported", entity_type="audit", entity_id=entity_id or "all", actor_id=p.user_id,
                 actor_type="human", data={"rows": len(rows), "format": fmt})
    db.commit()
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["seq"])
        w.writeheader()
        for r in rows:
            w.writerow({**r, "data": json.dumps(r["data"], default=str)})
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=nsip-audit.csv"})
    body = "\n".join(json.dumps(r, default=str) for r in rows)
    return StreamingResponse(iter([body]), media_type="application/x-ndjson",
                             headers={"Content-Disposition": "attachment; filename=nsip-audit.jsonl"})


# ---------------------------------------------------------------- server-sent events

@router.get("/events")
async def events(request: Request, p: Principal = Depends(get_principal)):
    q = broadcaster.subscribe()

    async def stream():
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if not p.can_see_region(msg["data"].get("region", "")):
                    continue
                yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'], default=str)}\n\n"
        finally:
            broadcaster.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/healthz/deep")
def deep_health(_: Principal = Depends(require_roles("admin")), db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(select(1))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    if not db_ok:
        raise HTTPException(503, detail={"code": "db_down", "message": "Database unavailable."})
    return {"database": "ok", "audit_chain": audit.verify_chain(db)["valid"]}
