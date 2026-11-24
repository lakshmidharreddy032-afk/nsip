"""DPDP Act 2023 jobs: purpose-bound retention and data-principal erasure.

Erasure masks personal data in derived records (sanitised text, extracted fields, AI call logs).
Original documents bound to a sealed quote are retained under the insurer's statutory record-keeping
obligation and access-restricted; the registry records the legal basis (see docs/governance/dpdp.md).
"""
from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import Adapters
from app.ai.guards.pii import mask
from app.domain.audit import service as audit
from app.models import Email, ExtractedField, PiiRegistry, Quote, Submission, utcnow


def _mask_email(db: Session, email_id) -> None:
    em = db.get(Email, email_id)
    if em:
        em.sanitized_text = mask(em.sanitized_text)


def _mask_fields(db: Session, submission_id) -> None:
    for f in db.scalars(select(ExtractedField).where(ExtractedField.submission_id == submission_id)):
        if isinstance(f.value, str):
            f.value = mask(f.value)
        if isinstance(f.source_value, str):
            f.source_value = mask(f.source_value)


def run_retention(db: Session, adapters: Adapters, actor_id=None) -> dict:
    """Mask personal data whose purpose-bound retention period has expired."""
    now = utcnow()
    due = list(db.scalars(select(PiiRegistry).where(PiiRegistry.retention_until <= now,
                                                    PiiRegistry.erased_at.is_(None))))
    emails, subs = set(), set()
    for r in due:
        if r.email_id:
            emails.add(r.email_id)
        if r.submission_id:
            subs.add(r.submission_id)
        r.erased_at = now
    for e in emails:
        _mask_email(db, e)
        em = db.get(Email, e)
        sub = db.scalar(select(Submission).where(Submission.email_id == e))
        sealed = sub and db.scalar(select(Quote.id).where(Quote.submission_id == sub.id))
        if em and not sealed:
            adapters.object_store.delete(em.raw_object_key)  # type: ignore[attr-defined]
    for s in subs:
        _mask_fields(db, s)
    audit.record(db, action="privacy.retention_run", entity_type="pii_registry", entity_id="batch",
                 actor_id=actor_id, actor_type="human" if actor_id else "system",
                 data={"records": len(due), "emails": len(emails), "submissions": len(subs)})
    db.commit()
    return {"records": len(due), "emails": len(emails), "submissions": len(subs)}


def erase_principal(db: Session, identifier: str, actor_id, reason: str) -> dict:
    """Erasure request for a data principal identified by phone, email, PAN or name."""
    h = hashlib.sha256(identifier.strip().lower().encode()).hexdigest()
    rows = list(db.scalars(select(PiiRegistry).where(PiiRegistry.value_hash == h, PiiRegistry.erased_at.is_(None))))
    for r in rows:
        if r.email_id:
            _mask_email(db, r.email_id)
        if r.submission_id:
            _mask_fields(db, r.submission_id)
        r.erased_at = utcnow()
    audit.record(db, action="privacy.erasure", entity_type="pii_registry", entity_id=h[:16], actor_id=actor_id,
                 actor_type="human", data={"records": len(rows), "reason": reason})
    db.commit()
    return {"records_erased": len(rows)}
