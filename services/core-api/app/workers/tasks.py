"""Celery workers for ingestion, OCR and extraction. Horizontal scaling via queue-depth autoscaling (KEDA).

Queues: `ingest` (mailbox polling), `pipeline` (classification -> extraction), `maintenance` (retention).
In dev/test (`NSIP_TASKS_EAGER=true`) the same functions run inline.
"""
from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.core.db import SessionLocal

try:
    from celery import Celery
except ImportError:  # pragma: no cover
    Celery = None  # type: ignore[assignment,misc]

settings = get_settings()
celery_app = None
if Celery is not None:
    celery_app = Celery("nsip", broker=settings.redis_url or "memory://", backend=None)
    celery_app.conf.update(
        task_always_eager=settings.tasks_eager, task_acks_late=True, worker_prefetch_multiplier=1,
        task_routes={"nsip.poll_mailboxes": {"queue": "ingest"}, "nsip.process_email": {"queue": "pipeline"},
                     "nsip.retention": {"queue": "maintenance"}},
        beat_schedule={
            "poll-mailboxes": {"task": "nsip.poll_mailboxes", "schedule": 60.0},
            "retention-nightly": {"task": "nsip.retention", "schedule": 24 * 3600.0},
        },
    )

    @celery_app.task(name="nsip.poll_mailboxes", autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
    def poll_mailboxes_task() -> dict:
        from app.domain.submissions.pipeline import poll_mailboxes

        with SessionLocal() as db:
            return poll_mailboxes(db)

    @celery_app.task(name="nsip.process_email", autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=3)
    def process_email_task(email_id: str) -> str | None:
        from app.domain.submissions.pipeline import process_email

        with SessionLocal() as db:
            sub = process_email(db, uuid.UUID(email_id))
            return str(sub.id) if sub else None

    @celery_app.task(name="nsip.retention")
    def retention_task() -> dict:
        from app.adapters.registry import get_adapters
        from app.domain.privacy.service import run_retention

        with SessionLocal() as db:
            return run_retention(db, get_adapters())
