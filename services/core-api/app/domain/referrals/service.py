"""Risk-engineering referrals: raised at triage, worked in parallel, findings unlock pricing."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.security import Principal
from app.domain.audit import service as audit
from app.models import Referral, Submission, utcnow

RECOMMENDATIONS = ("proceed", "proceed_with_conditions", "decline")


class ReferralError(Exception):
    pass


def claim(db: Session, p: Principal, referral_id: uuid.UUID) -> Referral:
    r = db.get(Referral, referral_id)
    if r is None or r.status == "completed":
        raise ReferralError("Referral is not open.")
    if not p.can_see_region(r.region):
        raise ReferralError("Referral is outside your region.")
    r.status, r.assigned_to = "in_progress", p.user_id
    audit.record(db, action="referral.claimed", entity_type="referral", entity_id=r.id, actor_id=p.user_id,
                 actor_type="human", region=r.region, data={"submission": str(r.submission_id)})
    db.commit()
    return r


def complete(db: Session, p: Principal, referral_id: uuid.UUID, findings: str, recommendation: str,
             conditions: list[str]) -> Referral:
    r = db.get(Referral, referral_id)
    if r is None or r.status == "completed":
        raise ReferralError("Referral is not open.")
    if recommendation not in RECOMMENDATIONS:
        raise ReferralError("Invalid recommendation.")
    if not findings.strip():
        raise ReferralError("Survey findings are required.")
    r.status, r.findings, r.recommendation, r.conditions = "completed", findings, recommendation, conditions
    r.completed_by, r.completed_at = p.user_id, utcnow()
    sub = db.get(Submission, r.submission_id)
    assert sub is not None
    sub.referral_status = "completed"
    audit.record(db, action="referral.completed", entity_type="referral", entity_id=r.id, actor_id=p.user_id,
                 actor_type="human", region=r.region,
                 data={"submission": str(sub.id), "recommendation": recommendation, "conditions": conditions})
    db.commit()
    return r
