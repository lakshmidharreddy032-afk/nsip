"""Email classification: deterministic rules first (cheap, explainable), small model only if ambiguous."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import GatewayError
from app.ai.tasks import AITasks
from app.models import Email, Submission, SubmissionVersion

NOISE = re.compile(r"(out of office|automatic reply|auto-reply|undeliverable|newsletter|unsubscribe|webinar)", re.I)
UPDATE = re.compile(r"(revised|updated|amended|corrected)\s+(sov|schedule|values|proposal)", re.I)
SUBMISSION = re.compile(r"(sum insured|proposal|schedule of values|\bsov\b|request(ing)? (a )?quote|premises)", re.I)
QUERY = re.compile(r"(status|any update|chasing|follow(ing)? up|reminder|query)", re.I)
SOV_NAME = re.compile(r"(sov|schedule|values|location)", re.I)


def find_thread_submission(db: Session, em: Email) -> Submission | None:
    ids = [x for x in ([em.in_reply_to] if em.in_reply_to else []) + list(em.references or []) if x]
    if not ids:
        return None
    parents = list(db.scalars(select(Email.id).where(Email.message_id.in_(ids))))
    if not parents:
        return None
    sub = db.scalar(select(Submission).where(Submission.email_id.in_(parents)))
    if sub:
        return sub
    v = db.scalar(select(SubmissionVersion).where(SubmissionVersion.source_email_id.in_(parents)))
    return db.get(Submission, v.submission_id) if v else None


def classify(db: Session, em: Email, ai: AITasks | None) -> tuple[str, str, Submission | None]:
    """Returns (category, method, thread_submission)."""
    text = f"{em.subject}\n{em.sanitized_text}"
    names = [a.filename for a in em.attachments]
    parent = find_thread_submission(db, em)
    if NOISE.search(text[:600]):
        return "noise", "rules", None
    if parent is not None:
        if UPDATE.search(text) or any(SOV_NAME.search(n) for n in names):
            return "updated_schedule", "rules", parent
        return "query", "rules", parent
    if SUBMISSION.search(text) or any(SOV_NAME.search(n) for n in names):
        return "new_submission", "rules", None
    if QUERY.search(text) and not names:
        return "query", "rules", None
    if ai is None:
        return "noise", "rules", None
    try:
        out, _ = ai.classify_email(text, names)
    except GatewayError:
        return "unclassified", "fallback", None
    category = out.category
    if category == "updated_schedule":  # no thread to update: treat as a new submission for review
        category = "new_submission"
    return category, "llm", None
