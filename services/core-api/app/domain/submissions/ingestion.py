"""Ingestion and sanitisation: store originals immutably (SHA-256), strip active content, isolate text,
scan attachments, strip macros, register personal data (DPDP) and flag injection attempts.
"""
from __future__ import annotations

import hashlib
import html
import re
from datetime import timedelta
from email import message_from_bytes, policy
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.mailbox import RawMessage
from app.adapters.registry import Adapters
from app.adapters.scanning import strip_macros
from app.ai.guards import injection, pii
from app.core.config import get_settings
from app.domain.audit import service as audit
from app.models import Attachment, Broker, Email, PiiRegistry, utcnow


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "iframe", "object", "embed", "noscript", "head", "svg", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    p = _TextExtractor()
    p.feed(markup)
    return html.unescape("".join(p.parts))


def sanitise_text(text: str) -> str:
    text = injection.normalise(text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def register_pii(db: Session, text: str, location: str, email_id=None, submission_id=None) -> int:
    days = get_settings().pii_retention_days
    n = 0
    for hit in pii.detect(text):
        db.add(PiiRegistry(email_id=email_id, submission_id=submission_id, pii_type=hit.pii_type, location=location,
                           masked_value=hit.masked, value_hash=hit.value_hash,
                           retention_until=utcnow() + timedelta(days=days)))
        n += 1
    return n


def ingest(db: Session, adapters: Adapters, raw: RawMessage) -> Email | None:
    """Idempotent on Message-ID. Returns None when the message was already ingested."""
    s = get_settings()
    msg = message_from_bytes(raw.raw, policy=policy.default)
    sha = hashlib.sha256(raw.raw).hexdigest()
    message_id = (msg.get("Message-ID") or f"<{sha}@no-message-id>").strip()
    if db.scalar(select(Email.id).where(Email.message_id == message_id)):
        return None
    try:
        received = parsedate_to_datetime(str(msg.get("Date"))) if msg.get("Date") else utcnow()
    except (TypeError, ValueError):
        received = utcnow()
    raw_key = adapters.object_store.put(f"raw/{raw.region}/{received:%Y/%m}/{sha}.eml", raw.raw)  # type: ignore[attr-defined]
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        content = body_part.get_content()
        body = html_to_text(content) if body_part.get_content_type() == "text/html" else content
    from_addr = parseaddr(msg.get("From", ""))[1].lower()
    domain = from_addr.split("@")[-1] if "@" in from_addr else ""
    broker = db.scalar(select(Broker).where(Broker.email_domain == domain)) if domain else None
    refs = [r for r in (msg.get("References") or "").split() if r]
    subject = sanitise_text(str(msg.get("Subject", "")))[:1000]
    text = sanitise_text(body)
    em = Email(message_id=message_id, mailbox=raw.mailbox, region=raw.region, channel=raw.channel,
               from_addr=from_addr, subject=subject, received_at=received, in_reply_to=msg.get("In-Reply-To"),
               references=refs, raw_object_key=raw_key, sha256=sha, sanitized_text=text,
               broker_id=broker.id if broker else None)
    db.add(em)
    db.flush()
    flags = [f.to_dict() for f in injection.detect(subject + "\n" + text, "email body")]
    for part in msg.iter_attachments():
        filename = part.get_filename() or "attachment.bin"
        data = cast(bytes, part.get_payload(decode=True) or b"")
        att_sha = hashlib.sha256(data).hexdigest()
        att = Attachment(email_id=em.id, filename=filename[:500], content_type=part.get_content_type(),
                         size=len(data), object_key="", sha256=att_sha)
        if len(data) > s.max_attachment_bytes:
            att.av_status = "rejected_size"
            db.add(att)
            continue
        att.av_status = adapters.antivirus.scan(data)  # type: ignore[attr-defined]
        if att.av_status != "clean":
            att.object_key = adapters.object_store.put(f"quarantine/{att_sha}", data)  # type: ignore[attr-defined]
            db.add(att)
            continue
        data, stripped = strip_macros(filename, data)
        att.macro_stripped = stripped
        att.object_key = adapters.object_store.put(f"att/{att_sha}/{filename[-80:]}", data)  # type: ignore[attr-defined]
        db.add(att)
    em.injection_flags = flags
    register_pii(db, text, "email body", email_id=em.id)
    audit.record(db, action="email.ingested", entity_type="email", entity_id=em.id, region=raw.region,
                 data={"message_id": message_id, "sha256": sha, "channel": raw.channel,
                       "attachments": len(list(msg.iter_attachments())), "injection_flags": len(flags)})
    db.flush()
    return em
