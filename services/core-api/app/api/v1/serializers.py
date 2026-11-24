from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Attachment,
    Broker,
    Decision,
    DuplicateLink,
    Email,
    ExtractedField,
    Quote,
    RatingRun,
    Referral,
    Submission,
    SubmissionVersion,
    TriageResult,
    aware,
    utcnow,
)


def money(v) -> str | None:
    return None if v is None else str(v)


def summary(s: Submission, broker: Broker | None = None) -> dict:
    due = aware(s.sla_due_at)
    return {
        "id": str(s.id), "reference": s.reference, "region": s.region, "status": s.status, "priority": s.priority,
        "line": s.line, "insured_name": s.insured_name, "broker": broker.name if broker else None,
        "broker_id": str(s.broker_id) if s.broker_id else None, "channel": s.channel,
        "occupancy_code": s.occupancy_code, "declared_sum_insured": s.declared_sum_insured,
        "total_sum_insured": s.total_sum_insured, "triage_outcome": s.triage_outcome,
        "referral_status": s.referral_status, "duplicate_of_id": str(s.duplicate_of_id) if s.duplicate_of_id else None,
        "injection_flagged": s.injection_flagged, "sov_reconciled": s.sov_reconciled,
        "has_pending_update": s.has_pending_update, "received_at": aware(s.received_at).isoformat(),  # type: ignore[union-attr]
        "sla_due_at": due.isoformat() if due else None,
        "sla_seconds_left": int((due - utcnow()).total_seconds()) if due else None,
        "current_version": s.current_version,
    }


def field_out(f: ExtractedField) -> dict:
    return {"id": str(f.id), "path": f.path, "label": f.label, "value": f.value, "source_value": f.source_value,
            "confidence": round(f.confidence, 3), "source_ref": f.source_ref, "method": f.method,
            "model_version": f.model_version, "prompt_version": f.prompt_version,
            "validation_errors": f.validation_errors, "status": f.status, "reviewed": f.reviewed, "edited": f.edited,
            "critical": f.critical, "conflict_value": f.conflict_value, "version_no": f.version_no}


def triage_out(t: TriageResult | None) -> dict | None:
    if t is None:
        return None
    return {"id": str(t.id), "outcome": t.outcome, "fired_rules": t.fired_rules, "rule_version": t.rule_version,
            "features": t.features, "llm_signals": t.llm_signals, "rationale": t.rationale,
            "decline_draft": t.decline_draft, "stage": t.stage, "confirmed_at": t.confirmed_at,
            "override_outcome": t.override_outcome, "override_reason": t.override_reason,
            "created_at": t.created_at.isoformat()}


def rating_out(r: RatingRun) -> dict:
    return {"id": str(r.id), "source": r.source, "source_version": r.source_version, "filing_ref": r.filing_ref,
            "workbook_hash": r.workbook_hash, "inputs_hash": r.inputs_hash, "inputs": r.inputs, "outputs": r.outputs,
            "premium": money(r.premium), "created_at": r.created_at.isoformat(), "run_by": str(r.run_by)}


def referral_out(r: Referral, sub: Submission | None = None) -> dict:
    due = aware(r.sla_due_at)
    out: dict[str, object] = {"id": str(r.id), "submission_id": str(r.submission_id), "kind": r.kind, "reason": r.reason,
           "rule_ids": r.rule_ids, "status": r.status, "region": r.region, "sla_due_at": due.isoformat() if due else None,
           "sla_seconds_left": int((due - utcnow()).total_seconds()) if due else None,
           "assigned_to": str(r.assigned_to) if r.assigned_to else None, "findings": r.findings,
           "recommendation": r.recommendation, "conditions": r.conditions,
           "completed_at": r.completed_at.isoformat() if r.completed_at else None}
    if sub:
        out["submission"] = {"reference": sub.reference, "insured_name": sub.insured_name,
                             "total_sum_insured": sub.total_sum_insured, "occupancy_code": sub.occupancy_code}
    return out


def detail(db: Session, s: Submission) -> dict:
    broker = db.get(Broker, s.broker_id) if s.broker_id else None
    em = db.get(Email, s.email_id)
    email_ids = [s.email_id] + list(db.scalars(select(SubmissionVersion.source_email_id)
                                               .where(SubmissionVersion.submission_id == s.id)))
    emails = list(db.scalars(select(Email).where(Email.id.in_(email_ids)).order_by(Email.received_at)))
    atts = list(db.scalars(select(Attachment).where(Attachment.email_id.in_(email_ids))))
    fields = list(db.scalars(select(ExtractedField).where(ExtractedField.submission_id == s.id)
                             .order_by(ExtractedField.path)))
    triage = db.scalar(select(TriageResult).where(TriageResult.submission_id == s.id, TriageResult.is_current.is_(True)))
    links = list(db.scalars(select(DuplicateLink).where(DuplicateLink.submission_id == s.id)))
    versions = list(db.scalars(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id)
                               .order_by(SubmissionVersion.version_no)))
    ratings = list(db.scalars(select(RatingRun).where(RatingRun.submission_id == s.id)
                              .order_by(RatingRun.created_at.desc())))
    referral = db.scalar(select(Referral).where(Referral.submission_id == s.id).order_by(Referral.created_at.desc()))
    quote = db.scalar(select(Quote).where(Quote.submission_id == s.id))
    decisions = list(db.scalars(select(Decision).where(Decision.submission_id == s.id).order_by(Decision.created_at)))
    flags = []
    for e in emails:
        flags.extend(e.injection_flags or [])
    return {
        **summary(s, broker),
        "email": {"id": str(em.id), "from": em.from_addr, "subject": em.subject, "body": em.sanitized_text,
                  "message_id": em.message_id} if em else None,
        "emails": [{"id": str(e.id), "subject": e.subject, "from": e.from_addr, "received_at": aware(e.received_at).isoformat(),  # type: ignore[union-attr]
                    "classification": e.classification, "body": e.sanitized_text} for e in emails],
        "attachments": [{"id": str(a.id), "email_id": str(a.email_id), "filename": a.filename,
                         "content_type": a.content_type, "size": a.size, "sha256": a.sha256, "av_status": a.av_status,
                         "macro_stripped": a.macro_stripped, "document_store_path": a.document_store_path}
                        for a in atts],
        "fields": [field_out(f) for f in fields],
        "triage": triage_out(triage),
        "duplicates": [{"id": str(link.id), "candidate_id": str(link.candidate_id), "score": link.score,
                        "components": link.components, "band": link.band, "status": link.status,
                        "first_arrived_id": str(link.first_arrived_id),
                        "broker_of_record_id": str(link.broker_of_record_id) if link.broker_of_record_id else None,
                        "bor_rule": link.bor_rule} for link in links],
        "injection_flags": flags,
        "versions": [{"version_no": v.version_no, "created_at": v.created_at.isoformat(), "diff": v.diff,
                      "source_email_id": str(v.source_email_id)} for v in versions],
        "rating_runs": [rating_out(r) for r in ratings],
        "referral": referral_out(referral) if referral else None,
        "quote": {"id": str(quote.id), "premium": money(quote.premium), "policy_admin_ref": quote.policy_admin_ref,
                  "fast_lane": quote.fast_lane, "status": quote.status, "audit_seal_hash": quote.audit_seal_hash,
                  "authority_snapshot": quote.authority_snapshot, "issued_by": str(quote.issued_by),
                  "created_at": quote.created_at.isoformat()} if quote else None,
        "decisions": [{"action": d.action, "reason": d.reason, "user_id": str(d.user_id),
                       "created_at": d.created_at.isoformat(), "authority_check": d.authority_check}
                      for d in decisions],
        "pipeline_error": s.pipeline_error, "consent": s.consent,
    }
