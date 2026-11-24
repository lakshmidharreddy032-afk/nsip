"""Pipeline orchestration (spec section 4). Each stage is deterministic code; the AI layer only returns
validated data. Gateway outages route the submission to the manual queue instead of failing.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.data import centroid, geohash
from app.adapters.registry import Adapters, get_adapters
from app.ai.guards import injection
from app.ai.tasks import AITasks
from app.core.events import broadcaster
from app.core.logging import get_logger
from app.domain.appetite import service as appetite
from app.domain.audit import service as audit
from app.domain.clearance import service as clearance
from app.domain.extraction import service as ext
from app.domain.extraction.documents import ParsedDocument, needs_ocr, parse, parse_text
from app.domain.submissions import classification, enrichment, ingestion
from app.domain.submissions import service as subs
from app.models import Attachment, Broker, Email, Submission

log = get_logger("pipeline")
OCR_COST_PER_PAGE_INR = 0.4
STOP_STATUSES = ("duplicate", "clearance_review", "decline_pending", "declined")


def _parse_attachments(adapters: Adapters, em: Email, include_ocr: bool) -> list[ParsedDocument]:
    docs = []
    for att in em.attachments:
        if att.av_status != "clean" or not att.object_key:
            continue
        data = adapters.object_store.get(att.object_key)  # type: ignore[attr-defined]
        if needs_ocr(att.filename, data) and not include_ocr:
            continue
        try:
            doc = parse(data, str(att.id), att.filename, adapters.ocr)
        except Exception as e:  # noqa: BLE001 - corrupt broker files must not stop the pipeline
            log.warning("parse_failed", attachment=str(att.id), error=type(e).__name__)
            continue
        if doc:
            docs.append(doc)
    return docs


def _flag_injection(db: Session, em: Email, docs: list[ParsedDocument]) -> None:
    flags = list(em.injection_flags or [])
    for d in docs:
        for f in injection.detect(d.text(), d.filename):
            flags.append(f.to_dict())
        for t in d.tables:
            cells = " ".join(str(c.value) for row in t.rows for c in row if isinstance(c.value, str))
            for f in injection.detect(cells, d.filename):
                flags.append(f.to_dict())
    uniq = {(f["pattern"], f["location"]): f for f in flags}
    em.injection_flags = list(uniq.values())


def _store_documents(db: Session, adapters: Adapters, sub: Submission, em: Email) -> None:
    for seq, att in enumerate(em.attachments, start=1):
        if att.av_status == "clean" and att.object_key and not att.document_store_path:
            from app.adapters.storage import document_path

            path = document_path(sub.region, sub.reference, seq, att.sha256, att.filename, sub.received_at)
            att.document_store_path = adapters.document_store.store(  # type: ignore[attr-defined]
                path, adapters.object_store.get(att.object_key))  # type: ignore[attr-defined]


def _set_identity(sub: Submission, res: ext.ExtractionResult, features: dict) -> None:
    vals = res.values()
    from app.domain.extraction.normalise import normalise_address, normalise_name

    sub.insured_name = str(vals.get("insured.name") or "")[:300]
    sub.insured_name_norm = normalise_name(sub.insured_name)
    sub.primary_pincode = (str(vals.get("risk.pincode")) if vals.get("risk.pincode") else None)
    sub.primary_address_norm = normalise_address(str(vals.get("risk.address") or ""))[:500]
    sub.occupancy_code = features.get("occupancy_code")
    si = features.get("sum_insured")
    sub.declared_sum_insured = si
    sub.line = "package" if isinstance(si, int) and si <= 10_00_00_000 else "property"
    sub.priority = "high" if isinstance(si, int) and si >= 50_00_00_000 else "normal"
    if sub.primary_pincode and centroid(sub.primary_pincode):
        lat, lon = centroid(sub.primary_pincode)  # type: ignore[misc]
        sub.block_geohash = geohash(lat, lon, 6)


def process_email(db: Session, email_id: uuid.UUID, adapters: Adapters | None = None,
                  ai: AITasks | None = None, use_ai: bool = True) -> Submission | None:
    adapters = adapters or get_adapters()
    ai = ai if ai is not None else (AITasks(db) if use_ai else None)
    em = db.get(Email, email_id)
    if em is None or em.status != "received":
        return None
    cheap_docs = _parse_attachments(adapters, em, include_ocr=False)
    _flag_injection(db, em, cheap_docs)
    category, method, parent = classification.classify(db, em, ai)
    em.classification, em.classification_method = category, method
    if category == "updated_schedule" and parent is not None:
        em.status = "processed"
        process_update(db, parent, em, adapters, ai)
        db.commit()
        return parent
    if category not in ("new_submission", "unclassified"):
        em.status = "processed"
        audit.record(db, action=f"email.{category}", entity_type="email", entity_id=em.id, region=em.region,
                     data={"method": method, "thread_submission": str(parent.id) if parent else None})
        db.commit()
        return None
    sub = subs.create_submission(db, em)
    em.status = "processed"
    try:
        body_doc = parse_text(f"{em.subject}\n{em.sanitized_text}", "body", "email body")
        docs = [body_doc] + cheap_docs
        res = ext.key_facts(docs, ai, sub.id, body_doc.text())
        ingestion.register_pii(db, body_doc.text(), "submission text", submission_id=sub.id)
        features = ext.build_features(res.values(), sub.region)
        _set_identity(sub, res, features)
        subs.upsert_candidates(db, sub, res, 1)
        _store_documents(db, adapters, sub, em)
        db.flush()
        # Clearance before extraction
        clearance.run(db, sub)
        if sub.status in STOP_STATUSES:
            subs.revalidate(db, sub)
            db.commit()
            _publish(sub)
            return sub
        continue_pipeline(db, sub, adapters, ai, res=res, docs=docs, features=features)
    except Exception as e:  # noqa: BLE001 - never lose a submission; route to manual queue
        log.error("pipeline_failed", submission=str(sub.id), error=type(e).__name__, detail=str(e)[:300])
        db.rollback()
        sub = db.get(Submission, sub.id) or sub
        if sub in db:
            sub.status, sub.pipeline_error = "manual_review", f"{type(e).__name__}: {str(e)[:500]}"
            audit.record(db, action="pipeline.manual_fallback", entity_type="submission", entity_id=sub.id,
                         region=sub.region, data={"error": type(e).__name__})
            db.commit()
        return sub
    db.commit()
    _publish(sub)
    return sub


def continue_pipeline(db: Session, sub: Submission, adapters: Adapters, ai: AITasks | None,
                      res: ext.ExtractionResult | None = None, docs: list[ParsedDocument] | None = None,
                      features: dict | None = None) -> Submission:
    """Triage -> extraction -> enrichment -> post-extraction triage -> workbench."""
    em = db.get(Email, sub.email_id)
    assert em is not None
    body_doc = parse_text(f"{em.subject}\n{em.sanitized_text}", "body", "email body")
    if docs is None:
        docs = [body_doc] + _parse_attachments(adapters, em, include_ocr=False)
    if res is None:
        res = ext.key_facts(docs, ai, sub.id, body_doc.text())
    features = features or ext.build_features(res.values(), sub.region)
    existing = subs.current_triage(db, sub.id)
    overridden = existing is not None and existing.override_outcome is not None
    tr = existing if overridden and existing is not None else appetite.triage(db, sub, features, body_doc.text(), ai, stage="initial")
    if tr.outcome == "out_of_appetite" and not tr.override_outcome:
        subs.revalidate(db, sub)
        db.flush()
        return sub  # fast-track: declined at triage, no expensive extraction or enrichment
    ocr_docs = [d for d in _parse_attachments(adapters, em, include_ocr=True) if d.ocr_engine]
    _flag_injection(db, em, ocr_docs)
    sub.injection_flagged = bool(em.injection_flags)
    broker = db.get(Broker, sub.broker_id) if sub.broker_id else None
    res = ext.full_extraction(db, docs + ocr_docs, ai, sub.id, broker.name if broker else em.from_addr, res)
    if res.ocr_pages:
        from app.models import ThirdPartyCall

        db.add(ThirdPartyCall(provider="ocr", submission_id=sub.id, request_key=f"{res.ocr_pages} pages",
                              cost_inr=OCR_COST_PER_PAGE_INR * res.ocr_pages))
    subs.upsert_candidates(db, sub, res, sub.current_version)
    subs.revalidate(db, sub)
    enrichment.enrich(db, adapters, sub)
    post = ext.build_features(subs.current_values(db, sub.id), sub.region)
    if _material_change(features, post) and not overridden:
        tr2 = appetite.triage(db, sub, post, body_doc.text(), None, stage="post_extraction")
        if tr2.outcome == "out_of_appetite":
            return sub
    sub.status = "needs_info" if sub.triage_outcome == "needs_info" else "in_review"
    db.flush()
    return sub


def _material_change(a: dict, b: dict) -> bool:
    keys = ("occupancy_code", "construction", "cat_zone", "year_built", "claims_count_3y")
    if any(a.get(k) != b.get(k) and b.get(k) is not None for k in keys):
        return True
    si_a, si_b = a.get("sum_insured"), b.get("sum_insured")
    return bool(si_a and si_b and abs(si_a - si_b) > 0.05 * si_a)


def resume_after_clearance(db: Session, sub: Submission, adapters: Adapters | None = None,
                           ai: AITasks | None = None) -> Submission:
    adapters = adapters or get_adapters()
    ai = ai if ai is not None else AITasks(db)
    continue_pipeline(db, sub, adapters, ai)
    db.commit()
    _publish(sub)
    return sub


def process_update(db: Session, sub: Submission, em: Email, adapters: Adapters, ai: AITasks | None) -> None:
    known = {a.sha256 for a in db.scalars(select(Attachment).join(Email, Attachment.email_id == Email.id)
                                          .where(Email.id != em.id, Email.id.in_(_submission_email_ids(db, sub))))}
    new_atts = [a for a in em.attachments if a.sha256 not in known]
    docs_all = _parse_attachments(adapters, em, include_ocr=True)
    docs = [d for d in docs_all if any(str(a.id) == d.attachment_id for a in new_atts)]
    _flag_injection(db, em, docs)
    if em.injection_flags:
        sub.injection_flagged = True
    body_doc = parse_text(f"{em.subject}\n{em.sanitized_text}", "body", "email body")
    res = ext.key_facts([body_doc] + docs, None, sub.id, body_doc.text())
    broker = db.get(Broker, sub.broker_id) if sub.broker_id else None
    sections = {"proposal"} if any(p for p in res.fields if subs.section_of(p) == "proposal") else set()
    if docs:
        res = ext.full_extraction(db, docs, ai, sub.id, broker.name if broker else em.from_addr, res)
        if res.sov_layouts:
            sections.add("sov")
        if any(p.startswith("loss_history[") for p in res.fields):
            sections.add("loss")
    if not sections:
        audit.record(db, action="submission.update_no_change", entity_type="submission", entity_id=sub.id,
                     region=sub.region, data={"email": str(em.id)})
        return
    if "sov" not in sections:
        res.fields = {p: c for p, c in res.fields.items() if not p.startswith(("locations[", "sov."))}
    subs.apply_update(db, sub, em, res, sections)
    _store_documents(db, adapters, sub, em)
    post = ext.build_features(subs.current_values(db, sub.id), sub.region)
    tr = subs.current_triage(db, sub.id)
    if tr is None or _material_change(tr.features, post):
        appetite.triage(db, sub, post, body_doc.text(), None, stage="post_extraction")
    db.flush()
    _publish(sub)


def _submission_email_ids(db: Session, sub: Submission) -> list[uuid.UUID]:
    from app.models import SubmissionVersion

    ids = [sub.email_id] + list(db.scalars(select(SubmissionVersion.source_email_id)
                                           .where(SubmissionVersion.submission_id == sub.id)))
    return ids


def _publish(sub: Submission) -> None:
    broadcaster.publish("submission.updated", {"id": str(sub.id), "reference": sub.reference, "status": sub.status,
                                               "region": sub.region})


def poll_mailboxes(db: Session, adapters: Adapters | None = None, regions: list[str] | None = None,
                   use_ai: bool = True) -> dict:
    """Fetch new mail per region (email-first) plus the legacy portal (secondary channel)."""
    from app.core.config import get_settings
    from app.domain.analytics.flags import region_enabled

    adapters = adapters or get_adapters()
    stats = {"fetched": 0, "ingested": 0, "duplicates_skipped": 0, "processed": 0, "errors": 0}
    for region in regions or get_settings().regions:
        if not region_enabled(db, region):
            continue
        for source in (adapters.mailbox, adapters.portal):
            for raw in source.fetch(region):  # type: ignore[attr-defined]
                stats["fetched"] += 1
                em = ingestion.ingest(db, adapters, raw)
                db.commit()
                source.mark_processed(raw)  # type: ignore[attr-defined]
                if em is None:
                    stats["duplicates_skipped"] += 1
                    continue
                stats["ingested"] += 1
                try:
                    process_email(db, em.id, adapters, use_ai=use_ai)
                    stats["processed"] += 1
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1
    return stats
