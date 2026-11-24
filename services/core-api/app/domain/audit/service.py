"""Append-only, hash-chained audit log.

hash_n = SHA256(prev_hash || canonical_json(seq, ts, actor, action, entity, data)). Any edit or
deletion breaks the chain and is reported by `verify_chain`. UPDATE/DELETE are refused by an ORM
guard here and by a database trigger in the PostgreSQL migration.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from app.models import AuditEvent, utcnow

GENESIS = "0" * 64


class AuditImmutableError(Exception):
    pass


@event.listens_for(AuditEvent, "before_update")
def _no_update(*_):
    raise AuditImmutableError("audit events are append-only")


@event.listens_for(AuditEvent, "before_delete")
def _no_delete(*_):
    raise AuditImmutableError("audit events are append-only")


def _canonical(seq: int, ts: datetime, actor_id: str | None, actor_type: str, action: str, entity_type: str,
               entity_id: str, data: dict) -> str:
    return json.dumps({"seq": seq, "ts": ts.replace(tzinfo=None).isoformat(timespec="microseconds"),
                       "actor_id": actor_id, "actor_type": actor_type, "action": action,
                       "entity_type": entity_type, "entity_id": entity_id, "data": data},
                      sort_keys=True, default=str, separators=(",", ":"))


def compute_hash(prev_hash: str, canonical: str) -> str:
    return hashlib.sha256((prev_hash + canonical).encode()).hexdigest()


def record(db: Session, *, action: str, entity_type: str, entity_id: object, data: dict | None = None,
           actor_id: object | None = None, actor_type: str = "system", region: str | None = None) -> AuditEvent:
    """Append an audit event within the caller's transaction."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":  # pragma: no cover
        db.execute(text("SELECT pg_advisory_xact_lock(424242)"))
    db.flush()
    last = db.execute(select(AuditEvent.seq, AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)).first()
    seq = (last[0] + 1) if last else 1
    prev = last[1] if last else GENESIS
    ts = utcnow()
    payload = json.loads(json.dumps(data or {}, default=str))
    canon = _canonical(seq, ts, str(actor_id) if actor_id else None, actor_type, action, entity_type,
                       str(entity_id), payload)
    ev = AuditEvent(seq=seq, ts=ts, actor_id=str(actor_id) if actor_id else None, actor_type=actor_type,
                    action=action, entity_type=entity_type, entity_id=str(entity_id), region=region,
                    data=payload, prev_hash=prev, hash=compute_hash(prev, canon))
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session) -> dict:
    prev = GENESIS
    count = 0
    for ev in db.scalars(select(AuditEvent).order_by(AuditEvent.seq)):
        canon = _canonical(ev.seq, ev.ts, ev.actor_id, ev.actor_type, ev.action, ev.entity_type, ev.entity_id,
                           ev.data)
        if ev.prev_hash != prev or compute_hash(prev, canon) != ev.hash:
            return {"valid": False, "broken_at_seq": ev.seq, "checked": count}
        prev = ev.hash
        count += 1
    return {"valid": True, "checked": count, "head": prev}


def count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AuditEvent)) or 0
