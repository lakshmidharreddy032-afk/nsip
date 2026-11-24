"""Human-only quote issuance (constraints 1-4).

A quote can only be created by `issue_quote`, which requires:
  * a `HumanActor` (constructible only from an authenticated HTTP request), with MFA;
  * an explicit confirmation flag set by the underwriter;
  * a current rating run from a filed source (premium never comes from anywhere else);
  * a passing authority check re-validated against the database;
  * a cleared referral and a non-duplicate, non-declined submission.
Nothing under app/ai imports this module (enforced by tests/architecture).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.policy_admin import PolicyAdminQuote
from app.adapters.registry import Adapters, get_adapters
from app.core.config import get_settings
from app.core.security import HumanActor
from app.domain.audit import service as audit
from app.domain.authority import service as authority
from app.domain.rating.service import FILED_SOURCES, is_current
from app.domain.submissions import service as subs
from app.models import (
    Broker,
    Decision,
    ExtractedField,
    FieldEdit,
    Quote,
    RatingRun,
    Referral,
    Submission,
    TriageResult,
    utcnow,
)


class QuoteError(Exception):
    def __init__(self, message: str, authority_check: dict | None = None):
        super().__init__(message)
        self.authority_check = authority_check


def _evidence(db: Session, sub: Submission, run: RatingRun) -> dict:
    from app.models import Attachment, Email, SubmissionVersion

    email_ids = [sub.email_id] + list(db.scalars(select(SubmissionVersion.source_email_id)
                                                 .where(SubmissionVersion.submission_id == sub.id)))
    docs = [{"attachment_id": str(a.id), "filename": a.filename, "sha256": a.sha256,
             "document_store_path": a.document_store_path}
            for a in db.scalars(select(Attachment).where(Attachment.email_id.in_(email_ids)))]
    emails = [{"email_id": str(e.id), "message_id": e.message_id, "sha256": e.sha256}
              for e in db.scalars(select(Email).where(Email.id.in_(email_ids)))]
    fields = [{"path": f.path, "value": f.value, "source_value": f.source_value, "confidence": f.confidence,
               "source_ref": f.source_ref, "method": f.method, "model_version": f.model_version,
               "prompt_version": f.prompt_version}
              for f in db.scalars(select(ExtractedField).where(ExtractedField.submission_id == sub.id))]
    edits = [{"path": e.path, "before": e.before, "after": e.after, "user_id": str(e.user_id), "reason": e.reason,
              "kind": e.kind, "at": e.created_at.isoformat()}
             for e in db.scalars(select(FieldEdit).where(FieldEdit.submission_id == sub.id))]
    triage = db.scalar(select(TriageResult).where(TriageResult.submission_id == sub.id,
                                                  TriageResult.is_current.is_(True)))
    referral = db.scalar(select(Referral).where(Referral.submission_id == sub.id))
    return {
        "source_emails": emails, "source_documents": docs, "extracted_fields": fields, "human_edits": edits,
        "rating": {"run_id": str(run.id), "source": run.source, "version": run.source_version,
                   "filing_ref": run.filing_ref, "workbook_hash": run.workbook_hash, "inputs_hash": run.inputs_hash,
                   "inputs": run.inputs, "outputs": run.outputs},
        "triage": {"outcome": triage.outcome, "rule_version": triage.rule_version,
                   "rules": [f["rule_id"] for f in triage.fired_rules],
                   "override": triage.override_outcome} if triage else None,
        "referral": {"status": referral.status, "recommendation": referral.recommendation,
                     "findings": referral.findings} if referral else None,
    }


def issue_quote(db: Session, actor: HumanActor, submission_id: uuid.UUID, rating_run_id: uuid.UUID,
                confirmed: bool, adapters: Adapters | None = None) -> Quote:
    if not isinstance(actor, HumanActor):
        raise QuoteError("Quotes can only be issued by an authenticated underwriter.")
    if confirmed is not True:
        raise QuoteError("Underwriter confirmation is required to issue a quote.")
    adapters = adapters or get_adapters()
    p = actor.principal
    sub = db.get(Submission, submission_id)
    if sub is None or sub.deleted_at is not None:
        raise QuoteError("Submission not found.")
    if not p.can_see_region(sub.region):
        raise QuoteError("Submission is outside your region.")
    if sub.status != "rated":
        raise QuoteError(f"Submission must be rated before quoting (status: {sub.status}).")
    if sub.duplicate_of_id:
        raise QuoteError("Duplicate submissions cannot be quoted.")
    if (sub.triage_outcome == "out_of_appetite"):
        raise QuoteError("Out-of-appetite submissions cannot be quoted.")
    if sub.referral_status == "open":
        raise QuoteError("Risk-engineering referral is still open.")
    if db.scalar(select(Quote).where(Quote.submission_id == sub.id, Quote.status == "issued")):
        raise QuoteError("A quote has already been issued for this submission.")
    run = db.get(RatingRun, rating_run_id)
    if run is None or run.submission_id != sub.id or run.status != "ok":
        raise QuoteError("Rating run not found for this submission.")
    if run.source not in FILED_SOURCES:
        raise QuoteError("Premium must come from a filed rating source.")
    if not is_current(db, sub, run):
        raise QuoteError("Submission data changed after rating. Re-run rating before quoting.")
    total_si = int(run.inputs["sum_insured"])
    check = authority.check(db, p, line=sub.line, sum_insured=total_si, premium=run.premium, region=sub.region)
    if not check.allowed:
        db.add(Decision(submission_id=sub.id, action="refer", user_id=p.user_id,
                        reason="authority: " + "; ".join(check.reasons), authority_check=check.to_dict()))
        audit.record(db, action="quote.blocked_authority", entity_type="submission", entity_id=sub.id,
                     actor_id=p.user_id, actor_type="human", region=sub.region, data=check.to_dict())
        db.commit()
        raise QuoteError("Outside your authority; referral required.", check.to_dict())
    vals = subs.current_values(db, sub.id)
    broker = db.get(Broker, sub.broker_id) if sub.broker_id else None
    locations = []
    from app.domain.extraction.service import location_indices

    for i in location_indices(vals):
        locations.append({"address": vals.get(f"locations[{i}].address"), "pincode": vals.get(f"locations[{i}].pincode"),
                          "occupancy_code": run.inputs.get("occupancy_code"),
                          "sum_insured": vals.get(f"locations[{i}].sov.total") or 0})
    pa_req = PolicyAdminQuote(submission_ref=sub.reference, insured_name=sub.insured_name,
                              broker_code=broker.code if broker else "DIRECT", line=sub.line, sum_insured=total_si,
                              premium=Decimal(run.premium), rate_source=run.source, rate_version=run.source_version,
                              inception_date=str(vals.get("cover.inception_date") or "") or None,
                              underwriter_email=p.email, locations=locations)
    pa = adapters.policy_admin.create_quote(pa_req, idempotency_key=f"{sub.id}:{run.id}")  # type: ignore[attr-defined]
    evidence = _evidence(db, sub, run)
    fast_lane = Decimal(run.premium) < get_settings().small_risk_premium_inr
    seal = hashlib.sha256(json.dumps({"evidence": evidence, "authority": check.to_dict(),
                                      "policy_admin_ref": pa.quote_ref}, sort_keys=True, default=str).encode()).hexdigest()
    q = Quote(submission_id=sub.id, rating_run_id=run.id, premium=run.premium, issued_by=p.user_id,
              authority_snapshot=check.to_dict(), evidence=evidence, policy_admin_ref=pa.quote_ref,
              fast_lane=fast_lane, audit_seal_hash=seal)
    db.add(q)
    db.add(Decision(submission_id=sub.id, action="quote", user_id=p.user_id, reason="quoted within authority",
                    authority_check=check.to_dict()))
    sub.status, sub.decided_at = "quoted", utcnow()
    db.flush()
    audit.record(db, action="quote.issued", entity_type="quote", entity_id=q.id, actor_id=p.user_id,
                 actor_type="human", region=sub.region,
                 data={"submission": str(sub.id), "reference": sub.reference, "premium": str(q.premium),
                       "rate_source": run.source, "rate_version": run.source_version,
                       "authority_limit": check.limit, "policy_admin_ref": pa.quote_ref, "seal": seal,
                       "fast_lane": fast_lane, "request_id": actor.request_id})
    if broker:
        adapters.crm.log_activity(broker.code, "quote_issued", {"reference": sub.reference})  # type: ignore[attr-defined]
    db.commit()
    return q
