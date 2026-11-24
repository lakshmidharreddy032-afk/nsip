from __future__ import annotations

import uuid
from typing import Any, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.adapters.registry import get_adapters
from app.api.v1 import serializers as ser
from app.core.db import get_db
from app.core.deps import EDIT_FIELDS, UNDERWRITE, VIEW_SUBMISSIONS, get_human_actor, require_roles
from app.core.security import HumanActor, Principal
from app.domain.authority import service as authority
from app.domain.clearance import service as clearance
from app.domain.extraction.documents import parse
from app.domain.quoting import service as quoting
from app.domain.rating import service as rating
from app.domain.referrals import service as referrals
from app.domain.submissions import pipeline
from app.domain.submissions import service as subs
from app.models import Attachment, Broker, DuplicateLink, Email, RatingRun, Referral, Submission, SubmissionVersion

router = APIRouter(prefix="/api/v1", tags=["submissions"])


def _err(e: Exception, code: int = 409) -> NoReturn:
    raise HTTPException(code, detail={"code": type(e).__name__, "message": str(e)})


def load_sub(db: Session, p: Principal, sub_id: uuid.UUID) -> Submission:
    s = db.get(Submission, sub_id)
    if s is None or s.deleted_at is not None or not p.can_see_region(s.region):
        raise HTTPException(404, detail={"code": "not_found", "message": "Submission not found."})
    return s


QUEUE_STATUSES = {
    "review": ["in_review", "needs_info", "info_requested"],
    "ready": ["ready_for_rating", "rated"],
    "triage": ["decline_pending", "clearance_review"],
    "manual": ["manual_review"],
    "closed": ["quoted", "declined", "duplicate", "closed"],
}


@router.get("/submissions")
def list_submissions(
    status: str | None = None, queue: str | None = None, region: str | None = None, priority: str | None = None,
    q: str | None = None, triage_outcome: str | None = None, broker_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), sort: str = "sla",
    p: Principal = Depends(require_roles(*VIEW_SUBMISSIONS)), db: Session = Depends(get_db),
) -> dict:
    stmt = select(Submission).where(Submission.deleted_at.is_(None))
    if not p.all_regions:
        stmt = stmt.where(Submission.region == p.region)
    elif region:
        stmt = stmt.where(Submission.region == region)
    if p.has("risk_engineer") and not p.has("underwriter", "senior_underwriter", "data_entry", "cuo", "admin"):
        stmt = stmt.where(Submission.referral_status != "none")
    if queue in QUEUE_STATUSES:
        stmt = stmt.where(Submission.status.in_(QUEUE_STATUSES[queue]))
    if status:
        stmt = stmt.where(Submission.status.in_(status.split(",")))
    if priority:
        stmt = stmt.where(Submission.priority == priority)
    if triage_outcome:
        stmt = stmt.where(Submission.triage_outcome == triage_outcome)
    if broker_id:
        stmt = stmt.where(Submission.broker_id == broker_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Submission.insured_name).like(like), func.lower(Submission.reference).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order: Any = {"sla": Submission.sla_due_at.asc(), "received": Submission.received_at.desc(),
             "sum_insured": Submission.total_sum_insured.desc()}.get(sort, Submission.sla_due_at.asc())
    rows = list(db.scalars(stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)))
    brokers = {b.id: b for b in db.scalars(select(Broker).where(Broker.id.in_({r.broker_id for r in rows if r.broker_id})))}
    counts = dict(db.execute(select(Submission.status, func.count()).where(
        Submission.deleted_at.is_(None), *( [] if p.all_regions else [Submission.region == p.region]))
        .group_by(Submission.status)).all())
    return {"items": [ser.summary(r, brokers.get(r.broker_id) if r.broker_id else None) for r in rows], "total": total, "page": page,
            "page_size": page_size, "status_counts": counts}


@router.get("/submissions/{sub_id}")
def get_submission(sub_id: uuid.UUID, p: Principal = Depends(require_roles(*VIEW_SUBMISSIONS)),
                   db: Session = Depends(get_db)) -> dict:
    return ser.detail(db, load_sub(db, p, sub_id))


def _attachment(db: Session, p: Principal, sub: Submission, att_id: uuid.UUID) -> Attachment:
    att = db.get(Attachment, att_id)
    email_ids = [sub.email_id] + list(db.scalars(select(SubmissionVersion.source_email_id)
                                                 .where(SubmissionVersion.submission_id == sub.id)))
    if att is None or att.email_id not in email_ids or att.av_status != "clean":
        raise HTTPException(404, detail={"code": "not_found", "message": "Document not found."})
    return att


@router.get("/submissions/{sub_id}/documents/{att_id}/content")
def document_content(sub_id: uuid.UUID, att_id: uuid.UUID, p: Principal = Depends(require_roles(*VIEW_SUBMISSIONS)),
                     db: Session = Depends(get_db)):
    sub = load_sub(db, p, sub_id)
    att = _attachment(db, p, sub, att_id)
    data = get_adapters().object_store.get(att.object_key)  # type: ignore[attr-defined]
    safe_types = {"application/pdf", "image/png", "image/jpeg", "text/csv"}
    ctype = att.content_type if att.content_type in safe_types else "application/octet-stream"
    return Response(data, media_type=ctype, headers={
        "Content-Disposition": f'inline; filename="{att.filename.replace(chr(34), "")}"',
        "Content-Security-Policy": "sandbox; default-src 'none'", "Cache-Control": "private, max-age=300"})


@router.get("/submissions/{sub_id}/documents/{att_id}/preview")
def document_preview(sub_id: uuid.UUID, att_id: uuid.UUID, p: Principal = Depends(require_roles(*VIEW_SUBMISSIONS)),
                     db: Session = Depends(get_db)) -> dict:
    sub = load_sub(db, p, sub_id)
    att = _attachment(db, p, sub, att_id)
    adapters = get_adapters()
    doc = parse(adapters.object_store.get(att.object_key), str(att.id), att.filename, adapters.ocr)  # type: ignore[attr-defined]
    if doc is None:
        return {"kind": "unsupported", "filename": att.filename}
    return {"kind": doc.kind, "filename": att.filename, "ocr_engine": doc.ocr_engine,
            "sheets": [{"name": t.name, "rows": [[{"v": None if c.value is None else str(c.value),
                                                   "ref": c.ref.get("cell")} for c in row] for row in t.rows[:300]]}
                       for t in doc.tables if doc.kind == "spreadsheet"],
            "lines": [{"text": ln.text, "page": ln.ref.get("page"), "line": ln.ref.get("line"),
                       "bbox": ln.ref.get("bbox"), "image_size": ln.ref.get("image_size")} for ln in doc.lines[:2000]]}


class FieldEditIn(BaseModel):
    value: Any = None
    reason: str = Field(default="", max_length=1000)


@router.patch("/submissions/{sub_id}/fields/{field_id}")
def edit_field(sub_id: uuid.UUID, field_id: uuid.UUID, body: FieldEditIn,
               p: Principal = Depends(require_roles(*EDIT_FIELDS)), db: Session = Depends(get_db)) -> dict:
    sub = load_sub(db, p, sub_id)
    try:
        f = subs.edit_field(db, p, sub, field_id, body.value, body.reason)
    except subs.SubmissionError as e:
        _err(e, 422)
    return {"field": ser.field_out(f), "submission": ser.summary(sub)}


@router.post("/submissions/{sub_id}/fields/{field_id}/accept")
def accept_field(sub_id: uuid.UUID, field_id: uuid.UUID, p: Principal = Depends(require_roles(*EDIT_FIELDS)),
                 db: Session = Depends(get_db)) -> dict:
    sub = load_sub(db, p, sub_id)
    try:
        return ser.field_out(subs.accept_field(db, p, sub, field_id))
    except subs.SubmissionError as e:
        _err(e)


class ConflictIn(BaseModel):
    keep: Literal["mine", "incoming"]


@router.post("/submissions/{sub_id}/fields/{field_id}/resolve")
def resolve_conflict(sub_id: uuid.UUID, field_id: uuid.UUID, body: ConflictIn,
                     p: Principal = Depends(require_roles(*EDIT_FIELDS)), db: Session = Depends(get_db)) -> dict:
    sub = load_sub(db, p, sub_id)
    try:
        return ser.field_out(subs.resolve_conflict(db, p, sub, field_id, body.keep))
    except subs.SubmissionError as e:
        _err(e)


@router.post("/submissions/{sub_id}/ready")
def mark_ready(sub_id: uuid.UUID, p: Principal = Depends(require_roles(*EDIT_FIELDS)),
               db: Session = Depends(get_db)) -> dict:
    sub = load_sub(db, p, sub_id)
    try:
        return ser.summary(subs.mark_ready(db, p, sub))
    except subs.SubmissionError as e:
        _err(e, 422)


@router.get("/submissions/{sub_id}/versions/{version_no}")
def version_diff(sub_id: uuid.UUID, version_no: int, p: Principal = Depends(require_roles(*VIEW_SUBMISSIONS)),
                 db: Session = Depends(get_db)) -> dict:
    sub = load_sub(db, p, sub_id)
    v = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == sub.id,
                                                  SubmissionVersion.version_no == version_no))
    if v is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Version not found."})
    return {"version_no": v.version_no, "diff": v.diff, "snapshot": v.snapshot, "created_at": v.created_at.isoformat()}


# ---------------------------------------------------------------- triage, declines, info requests

class DeclineIn(BaseModel):
    body: str | None = Field(default=None, max_length=6000)
    reason: str = Field(default="", max_length=1000)


@router.post("/submissions/{sub_id}/triage/decline")
def confirm_decline(sub_id: uuid.UUID, body: DeclineIn, p: Principal = Depends(require_roles(*UNDERWRITE)),
                    db: Session = Depends(get_db)) -> dict:
    sub = load_sub(db, p, sub_id)
    try:
        subs.confirm_decline(db, get_adapters(), p, sub, body.body, body.reason)
    except subs.SubmissionError as e:
        _err(e, 422)
    return ser.summary(sub)


class OverrideIn(BaseModel):
    outcome: Literal["in_appetite", "refer_risk_engineering", "out_of_appetite"]
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/submissions/{sub_id}/triage/override")
def override_triage(sub_id: uuid.UUID, body: OverrideIn, p: Principal = Depends(require_roles(*UNDERWRITE)),
                    db: Session = Depends(get_db)) -> dict:
    sub = load_sub(db, p, sub_id)
    try:
        subs.override_triage(db, p, sub, body.outcome, body.reason)
    except subs.SubmissionError as e:
        _err(e, 422)
    if sub.status == "received":
        pipeline.resume_after_clearance(db, sub)
    return ser.summary(sub)


class InfoIn(BaseModel):
    message: str = Field(min_length=10, max_length=6000)


@router.post("/submissions/{sub_id}/request-info")
def request_info(sub_id: uuid.UUID, body: InfoIn, p: Principal = Depends(require_roles(*EDIT_FIELDS)),
                 db: Session = Depends(get_db)) -> dict:
    sub = load_sub(db, p, sub_id)
    try:
        subs.request_info(db, get_adapters(), p, sub, body.message)
    except subs.SubmissionError as e:
        _err(e)
    return ser.summary(sub)


# ---------------------------------------------------------------- clearance

@router.get("/clearance")
def clearance_queue(p: Principal = Depends(require_roles(*VIEW_SUBMISSIONS)), db: Session = Depends(get_db)) -> list:
    links = list(db.scalars(select(DuplicateLink).where(DuplicateLink.status.in_(["pending", "linked"]))
                            .order_by(DuplicateLink.created_at.desc()).limit(200)))
    out = []
    for link in links:
        a, b = db.get(Submission, link.submission_id), db.get(Submission, link.candidate_id)
        if not a or not b or not p.can_see_region(a.region):
            continue
        ba = db.get(Broker, a.broker_id) if a.broker_id else None
        bb = db.get(Broker, b.broker_id) if b.broker_id else None
        out.append({"id": str(link.id), "score": link.score, "band": link.band, "status": link.status,
                    "components": link.components, "bor_rule": link.bor_rule,
                    "first_arrived_id": str(link.first_arrived_id),
                    "submission": ser.summary(a, ba), "candidate": ser.summary(b, bb)})
    return out


class ResolveIn(BaseModel):
    confirm: bool
    reason: str = Field(default="", max_length=1000)


@router.post("/clearance/{link_id}/resolve")
def resolve_duplicate(link_id: uuid.UUID, body: ResolveIn, p: Principal = Depends(require_roles(*EDIT_FIELDS)),
                      db: Session = Depends(get_db)) -> dict:
    link = db.get(DuplicateLink, link_id)
    if link is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Link not found."})
    sub = load_sub(db, p, link.submission_id)
    try:
        clearance.resolve(db, link_id, p.user_id, body.confirm, body.reason)
    except clearance.ClearanceError as e:
        _err(e)
    db.commit()
    if not body.confirm:
        pipeline.resume_after_clearance(db, sub)
    return ser.summary(sub)


# ---------------------------------------------------------------- rating, authority, decisions

@router.post("/submissions/{sub_id}/rating")
def run_rating(sub_id: uuid.UUID, p: Principal = Depends(require_roles(*UNDERWRITE)),
               db: Session = Depends(get_db)) -> dict:
    sub = load_sub(db, p, sub_id)
    try:
        run = rating.run_rating(db, p, sub)
    except rating.RatingServiceError as e:
        _err(e, 422)
    chk = authority.check(db, p, line=sub.line, sum_insured=int(run.inputs["sum_insured"]), premium=run.premium,
                          region=sub.region)
    return {"rating_run": ser.rating_out(run), "authority": chk.to_dict(),
            "fast_lane": float(run.premium) < 200_000 and chk.allowed}


@router.get("/submissions/{sub_id}/authority-check")
def authority_check(sub_id: uuid.UUID, rating_run_id: uuid.UUID, p: Principal = Depends(require_roles(*UNDERWRITE)),
                    db: Session = Depends(get_db)) -> dict:
    sub = load_sub(db, p, sub_id)
    run = db.get(RatingRun, rating_run_id)
    if run is None or run.submission_id != sub.id:
        raise HTTPException(404, detail={"code": "not_found", "message": "Rating run not found."})
    chk = authority.check(db, p, line=sub.line, sum_insured=int(run.inputs["sum_insured"]), premium=run.premium,
                          region=sub.region)
    return chk.to_dict() | {"rating_current": rating.is_current(db, sub, run)}


class QuoteIn(BaseModel):
    rating_run_id: uuid.UUID
    confirm: bool


@router.post("/submissions/{sub_id}/quote")
def issue_quote(sub_id: uuid.UUID, body: QuoteIn, actor: HumanActor = Depends(get_human_actor),
                db: Session = Depends(get_db)) -> dict:
    """The only quote-creation endpoint: authenticated underwriter + explicit confirmation."""
    load_sub(db, actor.principal, sub_id)
    try:
        q = quoting.issue_quote(db, actor, sub_id, body.rating_run_id, body.confirm)
    except quoting.QuoteError as e:
        raise HTTPException(403 if e.authority_check else 409,
                            detail={"code": "QuoteError", "message": str(e), "authority": e.authority_check})
    return {"quote_id": str(q.id), "policy_admin_ref": q.policy_admin_ref, "premium": str(q.premium),
            "fast_lane": q.fast_lane, "audit_seal_hash": q.audit_seal_hash}


class ReferIn(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


@router.post("/submissions/{sub_id}/refer")
def refer_up(sub_id: uuid.UUID, body: ReferIn, p: Principal = Depends(require_roles(*UNDERWRITE)),
             db: Session = Depends(get_db)) -> dict:
    """Refer to a senior underwriter (authority) or to risk engineering at any time."""
    from datetime import timedelta

    from app.core.config import get_settings
    from app.domain.audit import service as audit
    from app.models import Decision, utcnow

    sub = load_sub(db, p, sub_id)
    db.add(Decision(submission_id=sub.id, action="refer", user_id=p.user_id, reason=body.reason))
    if sub.referral_status != "open":
        db.add(Referral(submission_id=sub.id, kind="risk_engineering", reason=body.reason, region=sub.region,
                        sla_due_at=utcnow() + timedelta(hours=get_settings().referral_sla_hours)))
        sub.referral_status = "open"
    audit.record(db, action="decision.refer", entity_type="submission", entity_id=sub.id, actor_id=p.user_id,
                 actor_type="human", region=sub.region, data={"reason": body.reason})
    db.commit()
    return ser.summary(sub)


# ---------------------------------------------------------------- referrals

@router.get("/referrals")
def list_referrals(status: str | None = None,
                   p: Principal = Depends(require_roles("risk_engineer", "underwriter", "senior_underwriter", "cuo",
                                                        "admin")),
                   db: Session = Depends(get_db)) -> list:
    stmt = select(Referral).order_by(Referral.sla_due_at.asc())
    if status:
        stmt = stmt.where(Referral.status.in_(status.split(",")))
    if not p.all_regions:
        stmt = stmt.where(Referral.region == p.region)
    return [ser.referral_out(r, db.get(Submission, r.submission_id)) for r in db.scalars(stmt.limit(300))]


@router.post("/referrals/{ref_id}/claim")
def claim_referral(ref_id: uuid.UUID, p: Principal = Depends(require_roles("risk_engineer")),
                   db: Session = Depends(get_db)) -> dict:
    try:
        return ser.referral_out(referrals.claim(db, p, ref_id))
    except referrals.ReferralError as e:
        _err(e)


class FindingsIn(BaseModel):
    findings: str = Field(min_length=1, max_length=20000)
    recommendation: Literal["proceed", "proceed_with_conditions", "decline"]
    conditions: list[str] = Field(default_factory=list, max_length=20)


@router.post("/referrals/{ref_id}/complete")
def complete_referral(ref_id: uuid.UUID, body: FindingsIn, p: Principal = Depends(require_roles("risk_engineer")),
                      db: Session = Depends(get_db)) -> dict:
    try:
        return ser.referral_out(referrals.complete(db, p, ref_id, body.findings, body.recommendation, body.conditions))
    except referrals.ReferralError as e:
        _err(e, 422)


@router.get("/emails/{email_id}")
def get_email(email_id: uuid.UUID, p: Principal = Depends(require_roles(*VIEW_SUBMISSIONS)),
              db: Session = Depends(get_db)) -> dict:
    em = db.get(Email, email_id)
    if em is None or not p.can_see_region(em.region):
        raise HTTPException(404, detail={"code": "not_found", "message": "Email not found."})
    return {"id": str(em.id), "subject": em.subject, "from": em.from_addr, "body": em.sanitized_text,
            "classification": em.classification, "injection_flags": em.injection_flags}
