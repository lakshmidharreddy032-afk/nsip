"""Submission state: field persistence and validation, human edits, mid-flight update diffs, declines."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.adapters.registry import Adapters
from app.core.config import get_settings
from app.core.security import Principal
from app.domain.audit import service as audit
from app.domain.extraction import service as ext
from app.domain.extraction.normalise import (
    normalise_address,
    normalise_name,
    parse_amount,
    parse_int,
)
from app.domain.extraction.validation import status_for, validate
from app.models import (
    Broker,
    Decision,
    Email,
    ExtractedField,
    FieldEdit,
    LossHistory,
    RiskLocation,
    SovLine,
    Submission,
    SubmissionVersion,
    TriageResult,
    aware,
    utcnow,
)

MONEY_SUFFIXES = (".building", ".plant_machinery", ".stock", ".contents", ".other", ".total", "sum_insured",
                  "claims_amount_3y", "deductible", "amount_paid", "amount_outstanding")
INT_SUFFIXES = (".year_built", "claims_count_3y", ".year")


class SubmissionError(Exception):
    pass


def next_reference(db: Session) -> str:
    year = utcnow().year
    n = (db.scalar(select(func.count()).select_from(Submission)) or 0) + 1
    ref = f"NSIP-{year}-{n:06d}"
    while db.scalar(select(Submission.id).where(Submission.reference == ref)):
        n += 1
        ref = f"NSIP-{year}-{n:06d}"
    return ref


def create_submission(db: Session, em: Email) -> Submission:
    s = get_settings()
    received = aware(em.received_at) or utcnow()
    sub = Submission(reference=next_reference(db), region=em.region, channel=em.channel, broker_id=em.broker_id,
                     email_id=em.id, received_at=received, sla_due_at=received + timedelta(hours=s.sla_hours),
                     injection_flagged=bool(em.injection_flags),
                     consent={"purpose": "underwriting_submission", "basis": "legitimate_use_s7",
                              "notice": "broker-attested proposer consent", "captured_at": utcnow().isoformat()})
    db.add(sub)
    db.flush()
    db.add(SubmissionVersion(submission_id=sub.id, version_no=1, source_email_id=em.id))
    audit.record(db, action="submission.created", entity_type="submission", entity_id=sub.id, region=sub.region,
                 data={"reference": sub.reference, "email": str(em.id), "channel": em.channel})
    return sub


def fields_of(db: Session, sub_id: uuid.UUID) -> dict[str, ExtractedField]:
    return {f.path: f for f in db.scalars(select(ExtractedField).where(ExtractedField.submission_id == sub_id))}


def current_values(db: Session, sub_id: uuid.UUID) -> dict[str, object]:
    return {p: f.value for p, f in fields_of(db, sub_id).items()}


def _label(path: str) -> str:
    if path in ext.LABELS:
        return ext.LABELS[path]
    if path.startswith("locations["):
        i = int(path.split("]")[0].split("[")[1]) + 1
        tail = path.split("].", 1)[1].replace("sov.", "").replace("_", " ")
        return f"Location {i} - {tail}"
    if path.startswith("loss_history["):
        i = int(path.split("]")[0].split("[")[1]) + 1
        return f"Loss {i} - {path.split('].', 1)[1].replace('_', ' ')}"
    return path


def upsert_candidates(db: Session, sub: Submission, res: ext.ExtractionResult, version_no: int) -> None:
    existing = fields_of(db, sub.id)
    for path, c in res.fields.items():
        f = existing.get(path)
        if f is None:
            db.add(ExtractedField(submission_id=sub.id, version_no=version_no, path=path, label=_label(path),
                                  value=c.value, source_value=c.value, confidence=c.confidence,
                                  source_ref=c.source_ref, method=c.method, model_version=c.model_version,
                                  prompt_version=c.prompt_version, critical=c.critical))
        elif not f.edited:
            f.value = f.source_value = c.value
            f.confidence, f.source_ref, f.method = c.confidence, c.source_ref, c.method
            f.model_version, f.prompt_version, f.version_no = c.model_version, c.prompt_version, version_no
    db.flush()


def revalidate(db: Session, sub: Submission) -> dict[str, list[str]]:
    fields = fields_of(db, sub.id)
    errs = validate({p: {"value": f.value} for p, f in fields.items()}, (aware(sub.received_at) or utcnow()).date())
    for p, f in fields.items():
        f.validation_errors = errs.get(p, [])
        if f.status != "conflict":
            f.status = status_for(1.0 if f.edited or f.method == "human" else f.confidence, f.validation_errors)
    vals = {p: f.value for p, f in fields.items()}
    sub.insured_name = str(vals.get("insured.name") or sub.insured_name or "")[:300]
    sub.insured_name_norm = normalise_name(sub.insured_name)
    si = vals.get("cover.sum_insured")
    sub.declared_sum_insured = si if isinstance(si, int) else None
    tot = vals.get("sov.total")
    sub.total_sum_insured = tot if isinstance(tot, int) and tot > 0 else sub.declared_sum_insured
    sub.sov_reconciled = None if "sov.total" not in fields else not bool(errs.get("sov.total"))
    rebuild_structured(db, sub, vals)
    db.flush()
    return errs


def rebuild_structured(db: Session, sub: Submission, vals: dict) -> None:
    """Project current field values into normalised tables (locations, SOV lines, loss history)."""
    from app.domain.appetite.occupancy import classify_occupancy

    db.execute(delete(SovLine).where(SovLine.submission_id == sub.id))
    db.execute(delete(RiskLocation).where(RiskLocation.submission_id == sub.id))
    db.execute(delete(LossHistory).where(LossHistory.submission_id == sub.id))
    for i in ext.location_indices(vals):
        g = lambda k, i=i: vals.get(f"locations[{i}].{k}")  # noqa: E731
        occ = str(g("occupancy") or vals.get("risk.occupancy") or "")
        loc = RiskLocation(submission_id=sub.id, loc_no=i + 1, address=str(g("address") or ""),
                           city=str(g("city") or ""), pincode=str(g("pincode") or vals.get("risk.pincode") or ""),
                           occupancy=occ, occupancy_code=classify_occupancy(occ)[0],
                           construction=str(g("construction") or vals.get("risk.construction") or ""),
                           year_built=g("year_built") if isinstance(g("year_built"), int) else None)
        from app.adapters.enrichment import offline_zone

        loc.cat_zone = offline_zone(loc.pincode)
        db.add(loc)
        db.flush()
        for cat in ("building", "plant_machinery", "stock", "contents", "other"):
            v = g(f"sov.{cat}")
            if isinstance(v, int) and v:
                db.add(SovLine(location_id=loc.id, submission_id=sub.id, category=cat, amount=v))
    idx = sorted({int(p.split("]")[0].split("[")[1]) for p in vals if p.startswith("loss_history[")})
    for i in idx:
        y = vals.get(f"loss_history[{i}].year")
        if isinstance(y, int):
            db.add(LossHistory(submission_id=sub.id, year=y, cause=str(vals.get(f"loss_history[{i}].cause") or ""),
                               amount_paid=vals.get(f"loss_history[{i}].amount_paid") or 0,
                               amount_outstanding=vals.get(f"loss_history[{i}].amount_outstanding") or 0))
    first_pin = vals.get("risk.pincode") or vals.get("locations[0].pincode")
    sub.primary_pincode = str(first_pin)[:6] if first_pin else None
    sub.primary_address_norm = normalise_address(str(vals.get("risk.address") or vals.get("locations[0].address") or ""))[:500]


def coerce_value(path: str, value):
    if value is None or value == "":
        return None
    if path.endswith(MONEY_SUFFIXES):
        v = parse_amount(value)
        if v is None:
            raise SubmissionError("Enter an amount, for example 12,50,00,000 or 12.5 crore.")
        return v
    if path.endswith(INT_SUFFIXES):
        v = parse_int(value)
        if v is None:
            raise SubmissionError("Enter a whole number.")
        return v
    return str(value).strip()[:1000]


def _assert_editable(sub: Submission, p: Principal) -> None:
    if not p.can_see_region(sub.region):
        raise SubmissionError("Submission is outside your region.")
    if sub.status in ("quoted", "declined", "duplicate", "closed"):
        raise SubmissionError(f"Submission is {sub.status}; fields can no longer be edited.")


def edit_field(db: Session, p: Principal, sub: Submission, field_id: uuid.UUID, value, reason: str) -> ExtractedField:
    _assert_editable(sub, p)
    f = db.get(ExtractedField, field_id)
    if f is None or f.submission_id != sub.id:
        raise SubmissionError("Field not found.")
    new = coerce_value(f.path, value)
    before = f.value
    if f.status == "conflict":
        f.conflict_value = None
        f.status = "ok"
    f.value, f.edited, f.reviewed = new, True, True
    if sub.review_started_at is None:
        sub.review_started_at = utcnow()
    db.add(FieldEdit(field_id=f.id, submission_id=sub.id, path=f.path, before=before, after=new, user_id=p.user_id,
                     reason=reason[:1000], kind="edit"))
    if sub.status in ("rated", "ready_for_rating"):
        sub.status = "in_review"
    revalidate(db, sub)
    audit.record(db, action="field.edited", entity_type="submission", entity_id=sub.id, actor_id=p.user_id,
                 actor_type="human", region=sub.region,
                 data={"path": f.path, "before": before, "after": new, "reason": reason,
                       "source_ref": f.source_ref, "confidence": f.confidence})
    db.commit()
    return f


def accept_field(db: Session, p: Principal, sub: Submission, field_id: uuid.UUID) -> ExtractedField:
    _assert_editable(sub, p)
    f = db.get(ExtractedField, field_id)
    if f is None or f.submission_id != sub.id:
        raise SubmissionError("Field not found.")
    if f.status == "conflict":
        raise SubmissionError("Resolve the update conflict before accepting.")
    f.reviewed = True
    if sub.review_started_at is None:
        sub.review_started_at = utcnow()
    db.add(FieldEdit(field_id=f.id, submission_id=sub.id, path=f.path, before=f.value, after=f.value,
                     user_id=p.user_id, kind="accept"))
    db.commit()
    return f


def resolve_conflict(db: Session, p: Principal, sub: Submission, field_id: uuid.UUID, keep: str) -> ExtractedField:
    """keep = 'mine' (retain the human correction) or 'incoming' (take the broker's updated value)."""
    _assert_editable(sub, p)
    f = db.get(ExtractedField, field_id)
    if f is None or f.submission_id != sub.id or f.status != "conflict":
        raise SubmissionError("No conflict on this field.")
    before = f.value
    if keep == "incoming":
        f.value = f.source_value = f.conflict_value
    f.conflict_value, f.status, f.reviewed = None, "ok", True
    db.add(FieldEdit(field_id=f.id, submission_id=sub.id, path=f.path, before=before, after=f.value,
                     user_id=p.user_id, kind="conflict_resolve", reason=f"kept {keep}"))
    revalidate(db, sub)
    if not db.scalar(select(func.count()).select_from(ExtractedField).where(
            ExtractedField.submission_id == sub.id, ExtractedField.status == "conflict")):
        sub.has_pending_update = False
    audit.record(db, action="field.conflict_resolved", entity_type="submission", entity_id=sub.id,
                 actor_id=p.user_id, actor_type="human", region=sub.region, data={"path": f.path, "kept": keep})
    db.commit()
    return f


def mark_ready(db: Session, p: Principal, sub: Submission) -> Submission:
    _assert_editable(sub, p)
    if sub.status not in ("in_review", "needs_info", "info_requested"):
        raise SubmissionError(f"Cannot mark ready from status {sub.status}.")
    fields = fields_of(db, sub.id)
    conflicts = [f.path for f in fields.values() if f.status == "conflict"]
    if conflicts:
        raise SubmissionError("Resolve update conflicts first: " + ", ".join(conflicts[:5]))
    blocking = [f.label for f in fields.values() if f.critical and f.status == "invalid"]
    if blocking:
        raise SubmissionError("Fix invalid critical fields first: " + ", ".join(blocking[:5]))
    unreviewed = [f.label for f in fields.values() if f.critical and f.status == "low_confidence" and not f.reviewed]
    if unreviewed:
        raise SubmissionError("Review low-confidence critical fields first: " + ", ".join(unreviewed[:5]))
    now = utcnow()
    sub.status, sub.ready_at = "ready_for_rating", now
    start = aware(sub.review_started_at) or now
    sub.keyed_seconds = int((now - start).total_seconds())  # type: ignore[operator]
    sub.has_pending_update = False
    audit.record(db, action="submission.ready", entity_type="submission", entity_id=sub.id, actor_id=p.user_id,
                 actor_type="human", region=sub.region, data={"review_seconds": sub.keyed_seconds})
    db.commit()
    return sub


# ------------------------------------------------------------------ mid-flight updates

def section_of(path: str) -> str:
    if path.startswith(("locations[", "sov.")):
        return "sov"
    if path.startswith("loss_history["):
        return "loss"
    return "proposal"


def apply_update(db: Session, sub: Submission, em: Email, res: ext.ExtractionResult,
                 changed_sections: set[str]) -> SubmissionVersion:
    """Field-level diff. Unchanged source values keep prior human corrections; changed values on
    human-edited fields become conflicts; nothing reviewed is silently overwritten."""
    existing = fields_of(db, sub.id)
    version_no = sub.current_version + 1
    diff: list[dict] = []
    for path, c in res.fields.items():
        if section_of(path) not in changed_sections:
            continue
        f = existing.get(path)
        if f is None:
            db.add(ExtractedField(submission_id=sub.id, version_no=version_no, path=path, label=_label(path),
                                  value=c.value, source_value=c.value, confidence=c.confidence,
                                  source_ref=c.source_ref, method=c.method, critical=c.critical,
                                  prompt_version=c.prompt_version, model_version=c.model_version))
            diff.append({"path": path, "label": _label(path), "before": None, "after": c.value, "change": "added"})
        elif f.source_value == c.value:
            if f.edited:
                diff.append({"path": path, "label": f.label, "before": f.value, "after": f.value,
                             "change": "kept_human_edit"})
            f.source_ref = c.source_ref
        elif f.edited:
            f.status, f.conflict_value = "conflict", c.value
            diff.append({"path": path, "label": f.label, "before": f.value, "after": c.value, "change": "conflict",
                         "source_before": f.source_value})
        else:
            diff.append({"path": path, "label": f.label, "before": f.value, "after": c.value, "change": "changed"})
            f.value = f.source_value = c.value
            f.confidence, f.source_ref, f.method, f.version_no, f.reviewed = (c.confidence, c.source_ref, c.method,
                                                                               version_no, False)
    for path, f in existing.items():
        if section_of(path) in changed_sections and path not in res.fields and f.method != "human":
            if f.edited:
                f.status, f.conflict_value = "conflict", None
                diff.append({"path": path, "label": f.label, "before": f.value, "after": None, "change": "conflict"})
            else:
                diff.append({"path": path, "label": f.label, "before": f.value, "after": None, "change": "removed"})
                db.execute(delete(FieldEdit).where(FieldEdit.field_id == f.id))
                db.delete(f)
    db.flush()
    v = SubmissionVersion(submission_id=sub.id, version_no=version_no, source_email_id=em.id, diff=diff,
                          snapshot={"sections": sorted(changed_sections)})
    db.add(v)
    sub.current_version = version_no
    sub.has_pending_update = True
    if sub.status in ("ready_for_rating", "rated"):
        sub.status = "in_review"
    revalidate(db, sub)
    audit.record(db, action="submission.updated_schedule", entity_type="submission", entity_id=sub.id,
                 region=sub.region, data={"version": version_no, "changes": len(diff),
                                          "conflicts": sum(1 for d in diff if d["change"] == "conflict")})
    return v


# ------------------------------------------------------------------ declines / info requests

def current_triage(db: Session, sub_id: uuid.UUID) -> TriageResult | None:
    return db.scalar(select(TriageResult).where(TriageResult.submission_id == sub_id,
                                                TriageResult.is_current.is_(True)))


def confirm_decline(db: Session, adapters: Adapters, p: Principal, sub: Submission, body: str | None,
                    reason: str) -> Decision:
    """One-click human confirmation. In-appetite risks can never reach this without a human override."""
    if not p.has("underwriter", "senior_underwriter"):
        raise SubmissionError("Only underwriters can send declines.")
    if not p.can_see_region(sub.region):
        raise SubmissionError("Submission is outside your region.")
    if sub.status in ("declined", "quoted", "duplicate"):
        raise SubmissionError(f"Submission is already {sub.status}.")
    tr = current_triage(db, sub.id)
    draft = body or (tr.decline_draft if tr else None)
    if not draft:
        raise SubmissionError("No decline text.")
    if not reason and (tr is None or tr.outcome != "out_of_appetite"):
        raise SubmissionError("A reason is required to decline a submission that was not out of appetite.")
    subject = draft.split("\n", 1)[0].replace("Subject: ", "") if draft.startswith("Subject:") else \
        f"Northstar General - {sub.reference}"
    text = draft.split("\n\n", 1)[1] if draft.startswith("Subject:") and "\n\n" in draft else draft
    em = db.get(Email, sub.email_id)
    mid = adapters.mailbox.send(sub.region, em.from_addr if em else "", subject, text,  # type: ignore[attr-defined]
                                em.message_id if em else None)
    if tr:
        tr.confirmed_by, tr.confirmed_at = p.user_id, utcnow()
    d = Decision(submission_id=sub.id, action="decline", user_id=p.user_id, reason=reason or "out_of_appetite",
                 message_sent=text)
    db.add(d)
    sub.status, sub.decided_at = "declined", utcnow()
    broker = db.get(Broker, sub.broker_id) if sub.broker_id else None
    if broker:
        adapters.crm.log_activity(broker.code, "submission_declined", {"reference": sub.reference})  # type: ignore[attr-defined]
    audit.record(db, action="decision.decline", entity_type="submission", entity_id=sub.id, actor_id=p.user_id,
                 actor_type="human", region=sub.region,
                 data={"reason": reason, "rules": [f["rule_id"] for f in (tr.fired_rules if tr else [])],
                       "message_id": mid, "turnaround_hours": round(
                           (utcnow() - aware(sub.received_at)).total_seconds() / 3600, 2)})  # type: ignore[operator]
    db.commit()
    return d


def override_triage(db: Session, p: Principal, sub: Submission, outcome: str, reason: str) -> TriageResult:
    if not p.has("underwriter", "senior_underwriter"):
        raise SubmissionError("Only underwriters can override triage.")
    if outcome not in ("in_appetite", "refer_risk_engineering", "out_of_appetite"):
        raise SubmissionError("Invalid outcome.")
    if len(reason.strip()) < 10:
        raise SubmissionError("Give a reason of at least 10 characters.")
    tr = current_triage(db, sub.id)
    if tr is None:
        raise SubmissionError("Submission has not been triaged.")
    tr.override_outcome, tr.override_reason = outcome, reason
    sub.triage_outcome = outcome
    if outcome == "out_of_appetite":
        sub.status = "decline_pending"
        if not tr.decline_draft:
            tr.decline_draft = (f"Subject: Northstar General - unable to quote - {sub.reference}\n\nDear Partner,\n\n"
                                f"We are unable to offer terms for {sub.insured_name}: {reason}\n\nKind regards,\n"
                                "Northstar General Insurance")
    elif sub.status == "decline_pending":
        sub.status = "received"  # resumes extraction for an overridden decline
    audit.record(db, action="triage.override", entity_type="submission", entity_id=sub.id, actor_id=p.user_id,
                 actor_type="human", region=sub.region, data={"from": tr.outcome, "to": outcome, "reason": reason})
    db.commit()
    return tr


def request_info(db: Session, adapters: Adapters, p: Principal, sub: Submission, message: str) -> Decision:
    if not p.has("underwriter", "senior_underwriter", "data_entry"):
        raise SubmissionError("Not permitted.")
    em = db.get(Email, sub.email_id)
    adapters.mailbox.send(sub.region, em.from_addr if em else "",  # type: ignore[attr-defined]
                          f"Information required - {sub.reference}", message, em.message_id if em else None)
    d = Decision(submission_id=sub.id, action="request_info", user_id=p.user_id, reason="information requested",
                 message_sent=message)
    db.add(d)
    sub.status = "info_requested"
    audit.record(db, action="decision.request_info", entity_type="submission", entity_id=sub.id,
                 actor_id=p.user_id, actor_type="human", region=sub.region, data={"chars": len(message)})
    db.commit()
    return d
